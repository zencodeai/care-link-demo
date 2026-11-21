"""Real PostgreSQL lifecycle invariants with separately scoped authority doubles."""

import base64
import hashlib
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from care_link_data import LifecycleJobs, apply_review_migration
from care_link_data.assistance.service import AssistanceService
from care_link_data.duties import DutyCommands
from care_link_data.lifecycle.graph import graph_blockers
from care_link_data.values import canonical, digest, stamp
from care_link_domain import DutyActor, DutyScope, ManualError
from care_link_policy_input import OpaPolicy
from care_link_policy_input.duties import DutyDefinition, SignedDutyDefinition, SignedDutyRegistry
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from services.data.tests.test_referrals import referral_case as fixture_referral_case
from services.data.tests.test_referrals import referral_harness as fixture_referral_harness
from services.data.tests.test_referrals import send
from services.data.tests.test_review_recovery import acknowledge, prepare_intake, save_intake

referral_case = fixture_referral_case
referral_harness = fixture_referral_harness


def duty(h, action, operation, payload, scope, *, bound=100):
    now = datetime.now(UTC)
    signing = Ed25519PrivateKey.generate()
    workload = "spiffe://care-link.demo/demo/jobs"
    definition = DutyDefinition(
        key(),
        workload,
        (action,),
        (scope.purpose,),
        ("expired_copy", "due_followup"),
        bound,
        key(),
        now + timedelta(minutes=5),
    )
    artifact = SignedDutyDefinition(definition, key(), 1, "synthetic-test-receipt", "")
    artifact = replace(
        artifact,
        signature=base64.urlsafe_b64encode(signing.sign(canonical(artifact.unsigned()).encode()))
        .rstrip(b"=")
        .decode(),
    )
    registry = SignedDutyRegistry(
        (artifact,),
        signer_keys={artifact.key_id: signing.public_key()},
        evidence_keys={workload: signing.public_key()},
        admitted_digests=frozenset({artifact.digest}),
        approval_receipts={definition.approval_receipt_id: artifact.digest},
        workload_check=lambda peer, credential: 1
        if peer == workload and credential == workload
        else 0,
    )
    actor = DutyActor(
        artifact.actor_id,
        workload,
        definition.duty_id,
        key(),
        artifact.digest,
        scope,
        action,
        DutyCommands.binding(action, operation, payload),
        key(),
        now,
        now + timedelta(seconds=1),
        "",
        1,
        1,
        workload,
        request_deadline=now + timedelta(seconds=1),
    )
    actor = replace(
        actor,
        signature=base64.urlsafe_b64encode(
            signing.sign(
                canonical({k: v for k, v in actor.evidence().items() if k != "signature"}).encode()
            )
        )
        .rstrip(b"=")
        .decode(),
    )
    return DutyCommands(h.service, registry), actor


def key():
    return str(uuid4())


@pytest.fixture
def life(harness, monkeypatch):
    h = harness
    h.participant = replace(h.participant, mfa=True)

    def proof(actor, ceremony, subject, kind):
        if not actor.mfa or kind not in {"export", "delete"}:
            raise ManualError("test.rights_proof_required")

    monkeypatch.setattr(h.authority, "rights_proof", proof, raising=False)
    monkeypatch.setattr(
        h.authority,
        "rights_download_proof",
        lambda a, c, s: proof(a, c, s, "export"),
        raising=False,
    )
    monkeypatch.setattr(h.authority, "consent_proof", lambda *args: None, raising=False)
    return h


def grant(h, session):
    current = h.service.session_read(h.participant, session["id"])
    return h.service.consent_grant(
        h.participant,
        key(),
        {
            "subject_id": session["subject_id"],
            "session_id": session["id"],
            "expected_revision": current["revision"],
            "purpose": "follow_up",
            "basis": "self",
            "authority_proof_id": key(),
            "recipient": {"kind": "account", "account_id": h.participant.account_id},
            "fields": ["summary"],
            "effective_at": stamp(datetime.now(UTC) - timedelta(seconds=1)),
            "expires_at": stamp(datetime.now(UTC) + timedelta(days=4)),
        },
    )


def followup(h, session, contact, pending=False):
    current = h.service.session_read(h.participant, session["id"])
    base = {
        "expected_revision": current["revision"],
        "subject_id": session["subject_id"],
        "recipient_account_id": h.participant.account_id,
        "contact_grant_id": contact["id"],
    }
    if pending:
        return h.service.followup_create(
            h.participant, key(), {**base, "kind": "pending_anchor"}, session["id"]
        )
    event = h.read(
        "SELECT event_id FROM durable.event WHERE session_id=%s ORDER BY sequence LIMIT 1",
        (session["id"],),
    )[0][0]
    anchor = h.service.post_crisis_record(
        h.participant,
        key(),
        {
            "expected_revision": current["revision"],
            "occurred_at": stamp(datetime.now(UTC)),
            "source_event_id": str(event),
        },
        session["id"],
    )
    current = h.service.session_read(h.participant, session["id"])
    base["expected_revision"] = current["revision"]
    return h.service.followup_create(
        h.participant,
        key(),
        {
            **base,
            "kind": "scheduled",
            "post_crisis_event_id": anchor["id"],
            "due_at": stamp(datetime.now(UTC) + timedelta(hours=25)),
        },
        session["id"],
    )


def execute(h, kind="session"):
    data = {"class": kind, "batch_limit": 100}
    operation = key()
    commands, actor = duty(h, "lifecycle_due", operation, data, DutyScope(None, None, "rights"))
    return LifecycleJobs(h.service, commands.authority).lifecycle_due(actor, operation, data)


def make_due(h, follow):
    # Explicit synthetic fixture times affect business schedules only. Identity,
    # consent, proof and security clocks continue using actual wall time.
    with psycopg.connect(h.database.admin) as db:
        db.execute(
            "UPDATE care.follow_up SET due_at=clock_timestamp()-interval '1 second' WHERE id=%s",
            (follow["id"],),
        )


def test_pending_anchor_cannot_deliver_and_cancel_has_no_inbox(life):
    h = life
    session = h.create()
    contact = grant(h, session)
    pending = followup(h, session, contact, True)
    assert pending["state"] == "anchor_pending" and pending["due_at"] is None
    cancelled = h.service.followup_cancel(
        h.participant, key(), {"expected_revision": pending["revision"]}, pending["id"]
    )
    assert cancelled["state"] == "cancelled"
    execute(h)
    assert h.read("SELECT count(*) FROM care.inbox_message") == [(0,)]


def test_opt_out_before_authorization_never_delivers(life):
    h = life
    session = h.create()
    contact = grant(h, session)
    f = followup(h, session, contact)
    make_due(h, f)
    h.service.consent_revoke(
        h.participant, key(), {"expected_revision": contact["revision"]}, contact["id"]
    )
    execute(h)
    assert h.service.followup_read(h.participant, f["id"])["state"] == "cancelled"
    assert h.service.participant_inbox(h.participant)["items"] == []


def test_delivery_one_stable_effect_after_unknown_and_ended_session(life):
    h = life
    session = h.create()
    contact = grant(h, session)
    f = followup(h, session, contact)
    make_due(h, f)
    execute(h)
    first = h.service.participant_inbox(h.participant)["items"]
    assert len(first) == 1
    with psycopg.connect(h.database.admin) as db:
        db.execute("UPDATE care.follow_up SET state='unknown' WHERE id=%s", (f["id"],))
    execute(h)
    assert h.read("SELECT count(*) FROM care.inbox_message") == [(1,)]
    assert h.service.followup_read(h.participant, f["id"])["state"] == "sent"
    current = h.service.session_read(h.participant, session["id"])
    h.service.session_end(
        h.participant,
        key(),
        {"expected_revision": current["revision"], "reason": "user_choice"},
        session["id"],
    )
    view = h.service.inbox_message_read(h.participant, first[0]["id"])
    assert view["read_at"] is not None
    with pytest.raises(ManualError):
        h.service.inbox_message_read(h.worker, first[0]["id"])


def rights(h, session, kind):
    revision = h.read(
        "SELECT authority_revision FROM core.subject_guard WHERE subject_id=%s",
        (session["subject_id"],),
    )[0][0]
    body = {
        "subject_id": session["subject_id"],
        "expected_revision": str(revision),
        "kind": kind,
        "ceremony_id": key(),
    }
    operation = key()
    return operation, body, h.service.rights_create(h.participant, operation, body)


def test_one_use_export_reauthorizes_and_never_deletes(life):
    h = life
    session = h.create()
    _op, _body, r = rights(h, session, "export")
    assert r["state"] == "completed"
    result = h.service.export_download(h.participant, r["id"])
    assert result["subject_id"] == session["subject_id"]
    assert h.service.session_read(h.participant, session["id"])["id"] == session["id"]
    with pytest.raises(ManualError):
        h.service.export_download(h.participant, r["id"])


def test_delete_restricts_content_replays_and_retains_backup_pending(life):
    h = life
    session = h.create()
    operation, body, r = rights(h, session, "delete")
    assert r["state"] == "eligible"
    with pytest.raises(ManualError):
        h.service.session_read(h.participant, session["id"])
    assert h.service.rights_create(h.participant, operation, body)["id"] == r["id"]
    execute(h, "person")
    progress = h.service.rights_read(h.participant, r["id"])
    assert progress["state"] == "backup_pending"
    assert "physical_erasure_not_proven" in progress["exceptions"]
    assert h.journal.records[-1]["restriction"]["kind"] == "subject_delete"


def test_hold_blocks_purge_release_reasserts_external_restriction(life):
    h = life
    session = h.create()
    governance = replace(h.operator, account_id=key(), role="governance")
    from care_link_data import PostgresStore

    PostgresStore(h.database.admin).provision_principal(governance)
    epoch = h.read("SELECT epoch FROM control.guard")[0][0]
    hold = h.service.hold_create(
        governance,
        key(),
        {
            "expected_revision": str(epoch),
            "scope": {
                "session_id": session["id"],
                "subject_id": session["subject_id"],
                "purpose": "rights",
                "fields": [],
                "recipient_id": None,
            },
            "reason": "rights_review",
            "authority_ref": key(),
            "expires_at": None,
        },
    )
    _o, _b, r = rights(h, session, "delete")
    execute(h, "person")
    assert h.service.rights_read(h.participant, r["id"])["state"] == "held"
    h.service.hold_release(
        governance, key(), {"expected_revision": hold["revision"]}, hold["resource_id"]
    )
    assert h.journal.records[-1]["restriction"]["expires_at"] is None
    execute(h, "person")
    assert h.service.rights_read(h.participant, r["id"])["state"] == "backup_pending"


def test_graph_unknown_anchor_and_cycle_block_unsafe_purge():
    now = datetime.now(UTC)

    def copy(key_):
        return {
            "copy_id": key_,
            "subject_id": "s",
            "state": "retained",
            "classification": "synthetic_content",
            "anchor_at": now - timedelta(days=8),
            "expires_at": now - timedelta(days=1),
        }

    graph = {"a": copy("a"), "b": copy("b")}
    assert set(graph_blockers(graph, [("a", "b"), ("b", "a")], now).values()) == {
        "cyclic_dependency"
    }
    assert graph_blockers(graph, [("a", "missing")], now)["a"] == "unknown_dependency"
    graph["a"]["anchor_at"] = None
    graph["a"]["expires_at"] = None
    assert graph_blockers(graph, [], now)["a"] == "anchor_pending"


def test_other_tab_cannot_reuse_bound_ceremony(life):
    h = life
    session = h.create()
    _operation, body, _request = rights(h, session, "export")
    with pytest.raises(ManualError, match="ceremony_already_bound") as error:
        h.service.rights_create(h.participant, key(), body)
    assert error.value.status == 409
    assert h.read("SELECT count(*) FROM rights.request") == [(1,)]


def test_signed_duty_bound_rejects_larger_batch(life):
    h = life
    data = {"class": "person", "batch_limit": 2}
    operation = key()
    commands, actor = duty(
        h, "lifecycle_due", operation, data, DutyScope(None, None, "rights"), bound=1
    )
    with pytest.raises(ManualError):
        LifecycleJobs(h.service, commands.authority).lifecycle_due(actor, operation, data)
    assert h.read("SELECT count(*) FROM durable.duty_operation") == [(0,)]


def test_historical_purged_inventory_does_not_starve_new_deletion(life):
    h = life
    old = h.create()
    with psycopg.connect(h.database.admin) as db:
        db.execute(
            "INSERT INTO lifecycle.copy (copy_id,subject_id,session_id,purpose,aggregate_type,"
            "aggregate_id,content_ref,classification,encryption_key_ref,anchor_kind,anchor_at,"
            "expires_at,state,created_at) SELECT gen_random_uuid(),%s,%s,'support','session',"
            "gen_random_uuid(),'old:'||n,'synthetic_content','synthetic-test-key',"
            "'last_parent_closed',clock_timestamp()-interval '8 days',"
            "clock_timestamp()-interval '1 day','purged',clock_timestamp() "
            "FROM generate_series(1,120) n",
            (old["subject_id"], old["id"]),
        )
    session = h.create()
    _o, _b, r = rights(h, session, "delete")
    execute(h, "person")
    assert h.service.rights_read(h.participant, r["id"])["state"] == "backup_pending"


def test_other_author_private_report_survives_own_deletion(life):
    h = life
    session = h.create()
    report = key()
    copy = key()
    with psycopg.connect(h.database.admin) as db:
        db.execute(
            "INSERT INTO core.assertion VALUES(%s,%s,%s,1,'needs',%s,%s,"
            "'unverified',NULL,clock_timestamp(),clock_timestamp())",
            (
                report,
                session["id"],
                session["subject_id"],
                h.service.cipher.encrypt('{"kind":"text","text":"private worker report"}'),
                h.worker.account_id,
            ),
        )
        db.execute(
            "INSERT INTO lifecycle.copy VALUES(%s,%s,%s,'support','assertion',%s,%s,"
            "'synthetic_content','synthetic-test-key','last_parent_closed',NULL,NULL,"
            "'anchor_pending',clock_timestamp())",
            (copy, session["subject_id"], session["id"], report, "assertion:" + report),
        )
    _o, _b, r = rights(h, session, "delete")
    execute(h, "person")
    progress = h.service.rights_read(h.participant, r["id"])
    assert progress["state"] == "reconciliation_needed"
    assert "other_author_private_content_retained" in progress["exceptions"]
    assert (
        h.service.cipher.decrypt(
            h.read("SELECT value_ciphertext FROM core.assertion WHERE id=%s", (report,))[0][0]
        )
        == '{"kind":"text","text":"private worker report"}'
    )


def test_export_final_proof_failure_rolls_back_consumption(life, monkeypatch):
    h = life
    session = h.create()
    _o, _b, r = rights(h, session, "export")
    calls = []

    def proof(actor, ceremony, subject):
        calls.append(ceremony)
        if len(calls) > 1:
            raise ManualError("test.final_proof_expired")

    monkeypatch.setattr(h.authority, "rights_download_proof", proof)
    with pytest.raises(ManualError, match="final_proof_expired"):
        h.service.export_download(h.participant, r["id"])
    assert h.read(
        "SELECT downloaded_at IS NULL,export_ciphertext IS NOT NULL "
        "FROM rights.request WHERE id=%s",
        (r["id"],),
    ) == [(True, True)]


def test_external_restriction_during_job_audit_rolls_back_delivery(life, monkeypatch):
    h = life
    session = h.create()
    contact = grant(h, session)
    f = followup(h, session, contact)
    make_due(h, f)
    data = {"class": "session", "batch_limit": 100}
    operation = key()
    commands, actor = duty(h, "lifecycle_due", operation, data, DutyScope(None, None, "rights"))
    jobs = LifecycleJobs(h.service, commands.authority)
    original = jobs._audit

    def audit(*args, **kwargs):
        original(*args, **kwargs)
        h.journal.state = replace(
            h.journal.state, restriction_barrier=h.journal.state.restriction_barrier + 1
        )

    monkeypatch.setattr(jobs, "_audit", audit)
    with pytest.raises(ManualError, match="journal_barrier"):
        jobs.lifecycle_due(actor, operation, data)
    assert h.read("SELECT count(*) FROM care.inbox_message") == [(0,)]
    assert h.read("SELECT state FROM care.follow_up WHERE id=%s", (f["id"],)) == [("scheduled",)]
    assert h.read("SELECT count(*) FROM durable.duty_operation") == [(0,)]


def test_real_opa_scheduled_pending_bind_and_signed_jobs(life):
    binary = os.environ.get("CARE_LINK_OPA_BINARY")
    if not binary:
        pytest.skip("explicit pinned OPA required")
    h = life
    session = h.create()
    contact = grant(h, session)
    source = (
        Path(__file__).resolve().parents[3] / "config/demo/imp07/policy/manual.rego"
    ).read_bytes()
    signing = Ed25519PrivateKey.generate()
    policy = OpaPolicy(
        Path(binary),
        hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
        source,
        base64.b64encode(signing.sign(source)).decode(),
        signing.public_key(),
    )
    h.service.policy = policy
    with psycopg.connect(h.database.admin) as db:
        db.execute("UPDATE control.guard SET bundle_digest=%s", (policy.bundle_digest,))
    scheduled = followup(h, session, contact)
    assert scheduled["state"] == "scheduled"
    pending = followup(h, session, contact, True)
    event = h.read(
        "SELECT id,occurred_at FROM care.post_crisis_event WHERE session_id=%s", (session["id"],)
    )[0]
    bound = h.service.followup_bind_anchor(
        h.participant,
        key(),
        {
            "expected_revision": pending["revision"],
            "contact_grant_id": contact["id"],
            "post_crisis_event_id": str(event[0]),
            "due_at": stamp(event[1] + timedelta(hours=26)),
        },
        pending["id"],
    )
    assert bound["state"] == "scheduled"
    make_due(h, scheduled)
    execute(h)
    assert len(h.service.participant_inbox(h.participant)["items"]) == 1


@pytest.mark.parametrize(("busy", "other_author"), [(False, False), (True, False), (False, True)])
def test_assistance_minimization_honors_compute_and_author_dependencies(life, busy, other_author):
    h = life
    session = h.create()
    task = key()
    owner = h.worker.account_id if other_author else h.participant.account_id
    with psycopg.connect(h.database.admin) as db:
        db.execute(
            "INSERT INTO assistance.task(id,principal_id,session_id,body) VALUES(%s,%s,%s,%s)",
            (
                task,
                owner,
                session["id"],
                Jsonb({"ciphertext": h.service.cipher.encrypt('{"private":"synthetic prompt"}')}),
            ),
        )
        db.execute(
            "INSERT INTO lifecycle.copy VALUES(%s,%s,%s,'support','assistance_task',%s,%s,"
            "'synthetic_content','synthetic-test-key','last_parent_closed',NULL,NULL,"
            "'anchor_pending',clock_timestamp())",
            (key(), session["subject_id"], session["id"], task, "assistance_task:" + task),
        )
        if busy:
            db.execute(
                "INSERT INTO assistance.inference_job "
                "(id,task_id,step_id,fence,revision,model_digest,"
                "prompt_digest,request_digest,state,deadline,slot_id,bridge_generation) "
                "VALUES(%s,%s,%s,1,1,%s,%s,%s,'compute_unknown',"
                "clock_timestamp()+interval '1 minute','local-1','synthetic')",
                (key(), task, key(), "a" * 64, "b" * 64, "c" * 64),
            )
    _o, _b, r = rights(h, session, "delete")
    execute(h, "person")
    progress = h.service.rights_read(h.participant, r["id"])
    body = h.read("SELECT body FROM assistance.task WHERE id=%s", (task,))[0][0]
    plaintext = h.service.cipher.decrypt(body["ciphertext"])
    if busy:
        assert "compute_reconciliation_required" in progress["exceptions"]
        assert "synthetic prompt" in plaintext
    elif other_author:
        assert "other_author_private_content_retained" in progress["exceptions"]
        assert "synthetic prompt" in plaintext
    else:
        assert progress["state"] == "backup_pending"
        assert plaintext == "{}"


def record_anchor(h, session):
    current = h.service.session_read(h.participant, session["id"])
    event = h.read(
        "SELECT event_id FROM durable.event WHERE session_id=%s ORDER BY sequence LIMIT 1",
        (session["id"],),
    )[0][0]
    return h.service.post_crisis_record(
        h.participant,
        key(),
        {
            "expected_revision": current["revision"],
            "occurred_at": stamp(datetime.now(UTC)),
            "source_event_id": str(event),
        },
        session["id"],
    )


@pytest.mark.parametrize(("hours", "allowed"), [(23, False), (24, True), (72, True), (73, False)])
def test_followup_exact_anchor_window(life, hours, allowed):
    h = life
    session = h.create()
    contact = grant(h, session)
    anchor = record_anchor(h, session)
    current = h.service.session_read(h.participant, session["id"])
    from care_link_data.values import dt

    body = {
        "expected_revision": current["revision"],
        "subject_id": session["subject_id"],
        "recipient_account_id": h.participant.account_id,
        "contact_grant_id": contact["id"],
        "kind": "scheduled",
        "post_crisis_event_id": anchor["id"],
        "due_at": stamp(dt(anchor["occurred_at"]) + timedelta(hours=hours)),
    }
    if allowed:
        assert (
            h.service.followup_create(h.participant, key(), body, session["id"])["state"]
            == "scheduled"
        )
    else:
        with pytest.raises(ManualError, match="followup_window"):
            h.service.followup_create(h.participant, key(), body, session["id"])


@pytest.mark.parametrize("wrong_grant", [False, True])
def test_foreign_session_anchor_or_contact_grant_never_authorizes(life, wrong_grant):
    h = life
    session = h.create()
    contact = grant(h, session)
    foreign = h.create()
    foreign_grant = grant(h, foreign)
    anchor = record_anchor(h, foreign)
    current = h.service.session_read(h.participant, session["id"])
    body = {
        "expected_revision": current["revision"],
        "subject_id": session["subject_id"],
        "recipient_account_id": h.participant.account_id,
        "contact_grant_id": foreign_grant["id"] if wrong_grant else contact["id"],
        "kind": "scheduled",
        "post_crisis_event_id": anchor["id"],
        "due_at": stamp(datetime.now(UTC) + timedelta(hours=25)),
    }
    with pytest.raises(ManualError):
        h.service.followup_create(h.participant, key(), body, session["id"])
    assert h.read("SELECT count(*) FROM care.follow_up") == [(0,)]


def test_unknown_absence_and_fence_before_fresh_inbox_authorization(life):
    h = life
    session = h.create()
    contact = grant(h, session)
    f = followup(h, session, contact)
    make_due(h, f)
    with psycopg.connect(h.database.admin) as db:
        db.execute("UPDATE care.follow_up SET state='unknown',fence=4 WHERE id=%s", (f["id"],))
    execute(h)
    assert h.read("SELECT state,fence FROM care.follow_up WHERE id=%s", (f["id"],)) == [("sent", 5)]
    assert h.read("SELECT count(*) FROM care.inbox_message") == [(1,)]


def test_ordinary_referral_eligible_payload_minimized_and_unknown_retained(referral_case):
    h, receiver, _actor, session, draft, *_ = referral_case
    source = h.read(
        "SELECT payload_ciphertext FROM referral.generation WHERE id=%s", (draft["id"],)
    )[0][0]
    current = h.service.session_read(h.participant, session["id"])
    h.service.session_end(
        h.participant,
        key(),
        {"expected_revision": current["revision"], "reason": "user_choice"},
        session["id"],
    )
    with psycopg.connect(h.database.admin) as db:
        closed = datetime.now(UTC) - timedelta(days=8)
        db.execute("UPDATE core.session SET closed_at=%s WHERE id=%s", (closed, session["id"]))
        db.execute(
            "UPDATE lifecycle.copy SET anchor_at=%s,expires_at=%s,state='retained' "
            "WHERE session_id=%s AND purpose='support'",
            (closed, closed + timedelta(days=7), session["id"]),
        )
    execute(h, "referral")
    erased, state = h.read(
        "SELECT payload_ciphertext,state FROM referral.generation WHERE id=%s", (draft["id"],)
    )[0]
    assert erased != source and h.service.cipher.decrypt(erased) == "{}" and state == "purged"


def test_unknown_referral_gets_no_terminal_anchor_or_payload_erasure(referral_case):
    h, receiver, _actor, session, draft, *_ = referral_case
    receiver.scenario = "drop_after_store"
    assert send(referral_case)["state"] == "unknown"
    source = h.read(
        "SELECT payload_ciphertext FROM referral.generation WHERE id=%s", (draft["id"],)
    )[0][0]
    current = h.service.session_read(h.participant, session["id"])
    h.service.session_end(
        h.participant,
        key(),
        {"expected_revision": current["revision"], "reason": "user_choice"},
        session["id"],
    )
    execute(h, "referral")
    assert h.read(
        "SELECT payload_ciphertext FROM referral.generation WHERE id=%s", (draft["id"],)
    ) == [(source,)]
    assert h.read(
        "SELECT state,anchor_at FROM lifecycle.copy WHERE aggregate_id=%s", (draft["id"],)
    ) == [("anchor_pending", None)]


def test_released_hold_history_cannot_exhaust_current_hold_bound(life):
    h = life
    session = h.create()
    scope = {
        "session_id": session["id"],
        "subject_id": session["subject_id"],
        "purpose": "rights",
        "fields": [],
        "recipient_id": None,
    }
    with psycopg.connect(h.database.admin) as db:
        db.execute(
            "INSERT INTO lifecycle.hold SELECT gen_random_uuid(),1,%s,'rights_review',"
            "gen_random_uuid(),%s,clock_timestamp()-interval '1 minute',NULL,clock_timestamp() "
            "FROM generate_series(1,120)",
            (Jsonb(scope), h.operator.account_id),
        )
    _o, _b, r = rights(h, session, "delete")
    execute(h, "person")
    assert h.service.rights_read(h.participant, r["id"])["state"] == "backup_pending"


def test_rotating_subject_scan_progresses_past_held_candidates(life):
    h = life
    sessions = sorted([h.create() for _ in range(3)], key=lambda row: row["subject_id"])
    for session in sessions[:-1]:
        scope = {
            "session_id": session["id"],
            "subject_id": session["subject_id"],
            "purpose": "rights",
            "fields": [],
            "recipient_id": None,
        }
        with psycopg.connect(h.database.admin) as db:
            db.execute(
                "INSERT INTO lifecycle.hold VALUES(%s,1,%s,'rights_review',%s,%s,"
                "clock_timestamp(),NULL,NULL)",
                (key(), Jsonb(scope), key(), h.operator.account_id),
            )
    requested = [rights(h, s, "delete")[2] for s in sessions]
    for _ in range(3):
        data = {"class": "person", "batch_limit": 1}
        operation = key()
        commands, actor = duty(h, "lifecycle_due", operation, data, DutyScope(None, None, "rights"))
        LifecycleJobs(h.service, commands.authority).lifecycle_due(actor, operation, data)
    assert h.service.rights_read(h.participant, requested[-1]["id"])["state"] == "backup_pending"
    assert all(
        h.service.rights_read(h.participant, r["id"])["state"] == "held" for r in requested[:-1]
    )


def test_malformed_copy_locator_cannot_erase_other_session_through_sql_definer(life):
    h = life
    one = h.create()
    two = h.create()
    report = key()
    copy = key()
    secret = h.service.cipher.encrypt('{"kind":"text","text":"foreign synthetic report"}')
    now = datetime.now(UTC)
    with psycopg.connect(h.database.admin) as db:
        db.execute(
            "INSERT INTO core.assertion VALUES(%s,%s,%s,1,'needs',%s,%s,'unverified',NULL,%s,%s)",
            (report, one["id"], one["subject_id"], secret, h.participant.account_id, now, now),
        )
        db.execute(
            "INSERT INTO lifecycle.copy VALUES(%s,%s,%s,'support','assertion',%s,%s,"
            "'synthetic_content','synthetic-test-key','last_parent_closed',%s,%s,'retained',%s)",
            (
                copy,
                two["subject_id"],
                two["id"],
                report,
                "malformed:" + copy,
                now - timedelta(days=8),
                now - timedelta(days=1),
                now,
            ),
        )
    with h.service.store.transaction(h.participant, two["id"]) as tx:
        assert (
            tx.connection.execute(
                "SELECT blocked_reason FROM lifecycle.copy_source(%s)", (copy,)
            ).fetchone()["blocked_reason"]
            == "source_inventory_review_required"
        )
    with pytest.raises(ManualError):
        with h.service.store.transaction(h.participant, two["id"]) as tx:
            tx.connection.execute(
                "SELECT lifecycle.purge_copy(%s,%s)", (copy, h.service.cipher.encrypt("{}"))
            )
    assert h.read("SELECT value_ciphertext FROM core.assertion WHERE id=%s", (report,)) == [
        (secret,)
    ]


def test_review_drafts_and_intents_are_inventoried_and_own_delete_minimized(life):
    h = life
    with psycopg.connect(h.database.admin, row_factory=dict_row) as db:
        apply_review_migration(db)
    session = h.create()
    acknowledge(h, session["id"])
    draft = save_intake(h, session["id"], "Synthetic unsent private recovery draft")
    intent = prepare_intake(h, session["id"], draft)
    copies = h.read(
        "SELECT aggregate_type,anchor_kind FROM lifecycle.copy "
        "WHERE aggregate_id IN (%s,%s) ORDER BY aggregate_type",
        (draft["id"], intent["operation_id"]),
    )
    assert copies == [("review_draft", "capture"), ("review_intent", "capture")]
    _o, _b, r = rights(h, session, "delete")
    execute(h, "person")
    assert h.service.rights_read(h.participant, r["id"])["state"] == "backup_pending"
    assert h.read("SELECT count(*) FROM core.review_draft") == [(0,)]
    assert h.read("SELECT count(*) FROM core.review_intent") == [(0,)]


def test_legacy_assistance_cache_erased_with_own_source_despite_retained_other_author(life):
    h = life
    session = h.create()
    task = key()
    operation = key()
    payload = {"synthetic": "request"}
    assertion = h.service.session_assertions(
        h.participant,
        key(),
        {
            "expected_revision": session["revision"],
            "subject_id": session["subject_id"],
            "field": "needs",
            "supersedes_id": None,
            "effective_at": stamp(datetime.now(UTC)),
            "value": {"kind": "text", "text": "Synthetic worker private retained report"},
        },
        session["id"],
    )
    with psycopg.connect(h.database.admin) as db:
        db.execute(
            "UPDATE core.assertion SET author_id=%s WHERE id=%s",
            (h.worker.account_id, assertion["id"]),
        )
        db.execute(
            "INSERT INTO assistance.task(id,principal_id,session_id,body) VALUES(%s,%s,%s,%s)",
            (
                task,
                h.participant.account_id,
                session["id"],
                Jsonb({"ciphertext": h.service.cipher.encrypt('{"private":"synthetic prompt"}')}),
            ),
        )
        db.execute(
            "INSERT INTO lifecycle.copy VALUES(%s,%s,%s,'support','assistance_task',%s,%s,"
            "'synthetic_content','synthetic-test-key','last_parent_closed',NULL,NULL,"
            "'anchor_pending',clock_timestamp())",
            (key(), session["subject_id"], session["id"], task, "assistance_task:" + task),
        )
        db.execute(
            "INSERT INTO assistance.operation VALUES(%s,%s,%s,'task_create',%s,%s,'task',%s)",
            (
                operation,
                h.participant.account_id,
                session["id"],
                digest({"target": session["id"], "data": payload}),
                session["id"],
                h.service.cipher.encrypt(
                    canonical({"id": task, "private": "synthetic cached result"})
                ),
            ),
        )
    _o, _b, r = rights(h, session, "delete")
    execute(h, "person")
    assert (
        "other_author_private_content_retained"
        in h.service.rights_read(h.participant, r["id"])["exceptions"]
    )
    cached = h.read(
        "SELECT response_ciphertext FROM assistance.operation WHERE id=%s", (operation,)
    )[0][0]
    assert h.service.cipher.decrypt(cached) == "{}"
    with h.service.store.transaction(h.participant, session["id"]) as tx:
        with pytest.raises(ManualError, match="source_content_expired"):
            AssistanceService(h.service).replay(
                tx, operation, "task_create", payload, session["id"]
            )


def test_unknown_cancel_never_reauthorizes_after_durable_absence(life):
    h = life
    session = h.create()
    contact = grant(h, session)
    f = followup(h, session, contact)
    make_due(h, f)
    with psycopg.connect(h.database.admin) as db:
        db.execute("UPDATE care.follow_up SET state='unknown',fence=4 WHERE id=%s", (f["id"],))
    cancellation = h.service.followup_cancel(
        h.participant, key(), {"expected_revision": f["revision"]}, f["id"]
    )
    assert cancellation["state"] == "reconciliation_needed"
    execute(h)
    assert h.service.followup_read(h.participant, f["id"])["state"] == "cancelled"
    assert h.read("SELECT fence FROM care.follow_up WHERE id=%s", (f["id"],)) == [(5,)]
    assert h.read("SELECT count(*) FROM care.inbox_message") == [(0,)]


def test_explicit_historical_crisis_anchor_uses_its_own_window(life):
    h = life
    session = h.create()
    contact = grant(h, session)
    current = h.service.session_read(h.participant, session["id"])
    source = h.read(
        "SELECT event_id FROM durable.event WHERE session_id=%s ORDER BY sequence LIMIT 1",
        (session["id"],),
    )[0][0]
    occurred = datetime.now(UTC) - timedelta(hours=24)
    anchor = h.service.post_crisis_record(
        h.participant,
        key(),
        {
            "expected_revision": current["revision"],
            "occurred_at": stamp(occurred),
            "source_event_id": str(source),
        },
        session["id"],
    )
    current = h.service.session_read(h.participant, session["id"])
    follow = h.service.followup_create(
        h.participant,
        key(),
        {
            "kind": "scheduled",
            "expected_revision": current["revision"],
            "subject_id": session["subject_id"],
            "recipient_account_id": h.participant.account_id,
            "contact_grant_id": contact["id"],
            "post_crisis_event_id": anchor["id"],
            "due_at": stamp(occurred + timedelta(hours=25)),
        },
        session["id"],
    )
    assert follow["state"] == "scheduled"
    assert follow["due_at"] == stamp(occurred + timedelta(hours=25))


def test_message_copy_wrong_subject_cannot_borrow_other_person_deletion(life):
    h = life
    one = h.create()
    two = h.create()
    message = key()
    copy = key()
    secret = h.service.cipher.encrypt("Synthetic private message for first subject")
    with psycopg.connect(h.database.admin) as db:
        db.execute(
            "INSERT INTO core.message VALUES(%s,%s,1,%s,'participant',%s,1,clock_timestamp())",
            (message, one["id"], h.participant.account_id, secret),
        )
        db.execute(
            "INSERT INTO lifecycle.copy VALUES(%s,%s,%s,'support','message',%s,%s,"
            "'synthetic_content','synthetic-test-key','last_parent_closed',NULL,NULL,"
            "'anchor_pending',clock_timestamp())",
            (copy, two["subject_id"], one["id"], message, "wrong-subject:" + copy),
        )
    rights(h, two, "delete")
    with h.service.store.transaction(h.participant, one["id"]) as tx:
        assert (
            tx.connection.execute(
                "SELECT blocked_reason FROM lifecycle.copy_source(%s)", (copy,)
            ).fetchone()["blocked_reason"]
            == "source_inventory_review_required"
        )
    with pytest.raises(ManualError):
        with h.service.store.transaction(h.participant, one["id"]) as tx:
            tx.connection.execute(
                "SELECT lifecycle.purge_copy(%s,%s)", (copy, h.service.cipher.encrypt("{}"))
            )
    assert h.read("SELECT text_ciphertext FROM core.message WHERE id=%s", (message,)) == [(secret,)]


@pytest.mark.parametrize("action", ["participant_inbox", "inbox_message_read"])
@pytest.mark.parametrize("change", ["expiry", "subject"])
def test_inbox_final_audit_scope_change_discloses_no_content(life, monkeypatch, action, change):
    h = life
    session = h.create()
    contact = grant(h, session)
    f = followup(h, session, contact)
    make_due(h, f)
    execute(h)
    message = h.read("SELECT id FROM care.inbox_message")[0][0]
    original = h.service._audit

    def audit(tx, current, name, *args, **kwargs):
        result = original(tx, current, name, *args, **kwargs)
        if name == action:
            tx.scope(session["id"])
            if change == "expiry":
                tx.connection.execute(
                    "UPDATE care.inbox_message SET "
                    "expires_at=clock_timestamp()-interval '1 second' "
                    "WHERE id=%s",
                    (message,),
                )
            else:
                tx.connection.execute(
                    "UPDATE core.subject_guard SET delete_state='restricted' WHERE subject_id=%s",
                    (session["subject_id"],),
                )
        return result

    monkeypatch.setattr(h.service, "_audit", audit)
    with pytest.raises(ManualError, match="inbox_unavailable"):
        if action == "participant_inbox":
            h.service.participant_inbox(h.participant)
        else:
            h.service.inbox_message_read(h.participant, str(message))
    assert h.read("SELECT read_at FROM care.inbox_message WHERE id=%s", (message,)) == [(None,)]
