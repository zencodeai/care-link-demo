"""Real TLS PostgreSQL sender/receiver, race, crash and actor-scope qualification."""

import base64
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from uuid import uuid4

import psycopg
import pytest
from care_link_data import AESGCMContentCipher
from care_link_data.values import digest, stamp
from care_link_domain import ManualError
from care_link_policy_input import OpaPolicy
from care_link_simulators import ReceiverService
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from services.data.tests.test_directory import admit
from services.data.tests.test_manual import connected
from services.data.tests.test_plans_consent import plans_harness as base_plans_harness

referral_harness = base_plans_harness

ROOT = Path(__file__).resolve().parents[3]


def build_case(referral_harness, receiver_database):
    h, proofs = referral_harness
    admin, runtime = receiver_database
    with psycopg.connect(admin) as connection:
        connection.execute("TRUNCATE receiver.copy,receiver.package,receiver.decision")
    session = connected(h)
    for field in ["needs", "preferences"]:
        h.service.session_assertions(
            h.participant,
            str(uuid4()),
            {
                "expected_revision": session["revision"],
                "subject_id": session["subject_id"],
                "field": field,
                "value": {"kind": "text", "text": "Fictional " + field},
                "supersedes_id": None,
                "effective_at": stamp(datetime.now(UTC)),
            },
            session["id"],
        )
        session = h.service.session_read(h.worker, session["id"])
    data, directory = admit(h)
    service_id = data["service_id"]
    h.service.simulator_services = frozenset({service_id})
    receiver_actor = replace(h.worker, account_id=str(uuid4()), role="receiver")
    receiver = ReceiverService(
        runtime,
        AESGCMContentCipher(b"r" * 32),
        h.authority,
        actor_services={receiver_actor.account_id: service_id},
        services=frozenset({service_id}),
    )
    h.service.receiver = receiver
    sources = h.service.referral_sources(h.worker, session["id"])
    body = {
        "expected_revision": session["revision"],
        "subject_id": session["subject_id"],
        "recipient_service_id": service_id,
        "directory_revision": directory["revision"],
        "purpose": "referral",
        "selected": [entry["selected"] for entry in sources["items"]],
    }
    draft = h.service.referral_draft(h.worker, str(uuid4()), body, session["id"])
    proof = str(uuid4())
    proofs[proof] = (
        h.participant.account_id,
        session["subject_id"],
        session["id"],
        "referral",
        "self",
    )
    now = datetime.now(UTC)
    consent = h.service.consent_grant(
        h.participant,
        str(uuid4()),
        {
            "expected_revision": session["revision"],
            "subject_id": session["subject_id"],
            "session_id": session["id"],
            "purpose": "referral",
            "basis": "self",
            "authority_proof_id": proof,
            "recipient": {
                "kind": "service",
                "service_id": service_id,
                "directory_revision": directory["revision"],
            },
            "fields": ["needs", "preferences"],
            "effective_at": stamp(now - timedelta(seconds=1)),
            "expires_at": stamp(now + timedelta(seconds=120)),
        },
    )
    context = h.service.referral_context(h.worker, draft["id"])
    review_body = {
        "expected_revision": draft["revision"],
        "draft_id": draft["id"],
        "exact_digest": draft["digest"],
        "source_vector": context["versions"],
        "decision": "accept",
        "edited_text": None,
        "expires_at": stamp(now + timedelta(seconds=90)),
    }
    review = h.service.referral_review(h.worker, str(uuid4()), review_body, draft["id"])
    draft = h.service.referral_read(h.worker, draft["id"])
    enqueue = {
        "expected_revision": draft["revision"],
        "consent_id": consent["id"],
        "review_id": review["id"],
        "exact_payload_digest": draft["digest"],
        "generation": draft["generation"],
    }
    return h, receiver, receiver_actor, session, draft, consent, review, enqueue, body, review_body


@pytest.fixture
def referral_case(referral_harness, receiver_database):
    return build_case(referral_harness, receiver_database)


@pytest.fixture
def opa_referral_case(referral_harness, receiver_database):
    executable = os.environ.get("CARE_LINK_OPA_BINARY")
    if not executable:
        pytest.skip("Pinned real OPA executable explicitly required")
    h, _proofs = referral_harness
    key = Ed25519PrivateKey.generate()
    source = (ROOT / "config/demo/imp05/policy/manual.rego").read_bytes()
    binary = Path(executable)
    with binary.open("rb") as stream:
        binary_digest = hashlib.file_digest(stream, "sha256").hexdigest()
    policy = OpaPolicy(
        binary, binary_digest, source, base64.b64encode(key.sign(source)).decode(), key.public_key()
    )
    with psycopg.connect(h.database.admin) as connection:
        connection.execute("UPDATE control.guard SET bundle_digest=%s", (policy.bundle_digest,))
    h.service.policy = policy
    return build_case(referral_harness, receiver_database)


def dispatch(case):
    h, _receiver, _actor, _session, draft, _consent, _review, enqueue, *_ = case
    return h.service.referral_dispatch(h.worker, str(uuid4()), enqueue, draft["id"])


def send(case, pending=None):
    h = case[0]
    pending = pending or dispatch(case)
    return h.service.dispatcher_send(
        h.worker, str(uuid4()), {"expected_revision": pending["revision"]}, pending["dispatch_id"]
    )


def reconcile(case, current):
    h = case[0]
    return h.service.dispatch_reconcile(
        h.worker, str(uuid4()), {"expected_revision": current["revision"]}, current["dispatch_id"]
    )


def test_pending_is_unsent_review_and_payload_are_immutable(referral_case):
    h, receiver, actor, session, draft, *_ = referral_case
    pending = dispatch(referral_case)
    assert pending["state"] == "pending" and pending["attempt_count"] == 0
    assert receiver.receiver_inbox(actor, {})["dispatch_ids"] == []
    assert h.read("SELECT count(*) FROM referral.authorization") == [(0,)]
    with psycopg.connect(h.database.runtime) as connection:
        connection.execute("SELECT set_config('care_link.session',%s,true)", (session["id"],))
        with pytest.raises(psycopg.Error, match="immutable"):
            connection.execute(
                "UPDATE referral.generation SET payload_digest=repeat('f',64) WHERE id=%s",
                (draft["id"],),
            )
    assert (
        h.service.session_read(h.participant, session["id"])["service_phase"] == "human_controlled"
    )
    assert "Fictional" not in str(h.read("SELECT payload_ciphertext FROM referral.generation"))


@pytest.mark.parametrize(
    "decision,fields,status",
    [
        ("partial", ["needs"], "partial"),
        ("reject", [], "rejected"),
        ("clarify", [], "reconciliation_needed"),
        ("accept", ["needs", "preferences"], "accepted"),
    ],
)
def test_receiver_owns_outcome_and_support_stays_active(referral_case, decision, fields, status):
    h, receiver, actor, session, draft, *_ = referral_case
    current = send(referral_case)
    assert current["state"] == "received"
    assert receiver.receiver_inbox(actor, {})["dispatch_ids"] == [current["dispatch_id"]]
    detail = receiver.receiver_detail(actor, current["dispatch_id"])
    receiver.receiver_decide(
        actor,
        str(uuid4()),
        {
            "expected_revision": detail["revision"],
            "dispatch_id": current["dispatch_id"],
            "payload_digest": draft["digest"],
            "decision": decision,
            "accepted_fields": fields,
            "reason": "accepted" if decision == "accept" else "capacity",
        },
    )
    current = reconcile(referral_case, current)
    assert current["state"] == status
    assert h.service.receipt_read(h.worker, current["dispatch_id"])["accepted_fields"] == fields
    assert (
        h.service.session_read(h.participant, session["id"])["service_phase"] == "human_controlled"
    )
    assert h.read("SELECT count(*) FROM referral.attempt") == [(1,)]
    assert h.read("SELECT count(*) FROM referral.observation") == [(2,)]


def test_dropped_reply_reconciles_without_duplicate_or_new_authorization(referral_case):
    h, receiver, actor, *_ = referral_case
    receiver.scenario = "drop_after_store"
    current = send(referral_case)
    assert current["state"] == "unknown"
    assert len(receiver.receiver_inbox(actor, {})["dispatch_ids"]) == 1
    current = reconcile(referral_case, current)
    assert current["state"] == "received"
    assert current["attempt_count"] == 1
    assert h.read("SELECT count(*),count(consumed_at) FROM referral.authorization") == [(1, 1)]
    assert h.read("SELECT count(*) FROM referral.attempt") == [(1,)]


@pytest.mark.parametrize("scenario", ["timeout_before_store", "unavailable"])
def test_unknown_and_unavailable_never_become_connected_or_blind_retry(referral_case, scenario):
    h, receiver, actor, *_ = referral_case
    receiver.scenario = scenario
    current = send(referral_case)
    assert current["state"] == "unknown"
    current = reconcile(referral_case, current)
    assert current["state"] == "reconciliation_needed"
    assert receiver.receiver_inbox(actor, {})["dispatch_ids"] == []
    current = h.service.dispatcher_send(
        h.worker, str(uuid4()), {"expected_revision": current["revision"]}, current["dispatch_id"]
    )
    assert current["attempt_count"] == 1


@pytest.mark.parametrize("change", ["revoke", "policy", "assignment", "source", "directory"])
def test_pre_authorization_material_change_prevents_send(referral_case, monkeypatch, change):
    h, receiver, actor, session, _draft, consent, *_ = referral_case
    pending = dispatch(referral_case)
    ready, resume = Event(), Event()
    original = h.policy.evaluate

    def evaluate(request):
        result = original(request)
        if request["action"] == "dispatch_authorize":
            ready.set()
            assert resume.wait(5)
        return result

    monkeypatch.setattr(h.policy, "evaluate", evaluate)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(send, referral_case, pending)
        assert ready.wait(5)
        try:
            if change == "revoke":
                h.service.consent_revoke(
                    h.participant,
                    str(uuid4()),
                    {"expected_revision": consent["revision"]},
                    consent["id"],
                )
            else:
                with psycopg.connect(h.database.admin) as connection:
                    if change == "policy":
                        connection.execute("UPDATE control.guard SET epoch=epoch+1")
                    elif change == "assignment":
                        connection.execute(
                            "UPDATE workforce.assignment SET revision=revision+1 "
                            "WHERE session_id=%s",
                            (session["id"],),
                        )
                    elif change == "source":
                        connection.execute(
                            "UPDATE core.session SET revision=revision+1 WHERE id=%s",
                            (session["id"],),
                        )
                    else:
                        connection.execute("UPDATE knowledge.service_guard SET suspended=true")
        finally:
            resume.set()
        with pytest.raises(ManualError):
            future.result(5)
    assert receiver.receiver_inbox(actor, {})["dispatch_ids"] == []
    assert h.read("SELECT count(*) FROM referral.authorization") == [(0,)]


def test_after_consumption_revocation_records_actual_received_bytes(referral_case, monkeypatch):
    h, receiver, _actor, _session, _draft, consent, *_ = referral_case
    original = receiver.send

    def send_and_revoke(service_id, package):
        # No sender DB lock remains here: journalled revocation commits synchronously.
        h.service.consent_revoke(
            h.participant, str(uuid4()), {"expected_revision": consent["revision"]}, consent["id"]
        )
        return original(service_id, package)

    monkeypatch.setattr(receiver, "send", send_and_revoke)
    current = send(referral_case)
    assert current["state"] == "received"
    assert h.read("SELECT count(*) FROM referral.authorization WHERE consumed_at IS NOT NULL") == [
        (1,)
    ]


def test_crash_after_consumption_without_send_is_reconciliation_only(referral_case):
    h = referral_case[0]
    pending = dispatch(referral_case)
    h.service._authorize(h.worker, pending["dispatch_id"], pending["revision"])
    h.service._consume(h.worker, pending["dispatch_id"])
    current = h.service.dispatch_read(h.worker, pending["dispatch_id"])
    assert current["state"] == "attempted"
    current = h.service.dispatcher_send(
        h.worker, str(uuid4()), {"expected_revision": current["revision"]}, current["dispatch_id"]
    )
    assert current["state"] == "reconciliation_needed" and current["attempt_count"] == 1


def test_stale_received_observation_cannot_erase_receiver_decision(referral_case):
    h, receiver, actor, _session, draft, *_ = referral_case
    current = send(referral_case)
    old = h.service.receipt_read(h.worker, current["dispatch_id"])
    receiver.receiver_decide(
        actor,
        str(uuid4()),
        {
            "expected_revision": "1",
            "dispatch_id": current["dispatch_id"],
            "payload_digest": draft["digest"],
            "decision": "reject",
            "accepted_fields": [],
            "reason": "capacity",
        },
    )
    current = reconcile(referral_case, current)
    assert current["state"] == "rejected"
    current = h.service._observe(h.worker, current["dispatch_id"], old)
    assert current["state"] == "rejected"
    assert h.read("SELECT count(*) FROM referral.observation") == [(3,)]


def test_changed_key_payload_or_generation_cannot_duplicate_logical_effect(referral_case):
    h, _receiver, _actor, _session, draft, _consent, _review, enqueue, *_ = referral_case
    key = str(uuid4())
    pending = h.service.referral_dispatch(h.worker, key, enqueue, draft["id"])
    assert (
        h.service.referral_dispatch(h.worker, key, enqueue, draft["id"])["dispatch_id"]
        == pending["dispatch_id"]
    )
    with pytest.raises(ManualError, match="idempotency_conflict"):
        h.service.referral_dispatch(h.worker, key, {**enqueue, "generation": "2"}, draft["id"])
    with pytest.raises(ManualError, match="generation_already_dispatched|stale_revision"):
        h.service.referral_dispatch(h.worker, str(uuid4()), enqueue, draft["id"])
    assert h.read("SELECT count(*) FROM referral.dispatch") == [(1,)]


def test_receiver_other_actor_and_business_credentials_cannot_read_package(
    referral_case, receiver_database
):
    h, receiver, actor, *_ = referral_case
    current = send(referral_case)
    with pytest.raises(ManualError):
        receiver.receiver_package(replace(actor, account_id=str(uuid4())), current["dispatch_id"])
    with pytest.raises(ManualError):
        receiver.receiver_package(replace(actor, role="worker"), current["dispatch_id"])
    settings = conninfo_to_dict(receiver_database[1])
    business = conninfo_to_dict(h.database.runtime)
    with psycopg.connect(
        make_conninfo(**{**settings, "user": business["user"], "password": business["password"]})
    ) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT * FROM receiver.package")
    with psycopg.connect(
        make_conninfo(**{**business, "user": settings["user"], "password": settings["password"]})
    ) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT * FROM core.session")


def test_receiver_changed_digest_is_rejected_under_existing_dispatch(referral_case):
    h, receiver, _actor, _session, draft, *_ = referral_case
    pending = dispatch(referral_case)
    h.service._authorize(h.worker, pending["dispatch_id"], pending["revision"])
    package = h.service._consume(h.worker, pending["dispatch_id"])
    receiver.send(draft["payload"]["recipient_service_id"], package)
    package = json.loads(json.dumps(package))
    package["payload"]["qualifications"].append("changed")
    package["payload_digest"] = digest(package["payload"])
    with pytest.raises(ManualError, match="digest_conflict"):
        receiver.send(draft["payload"]["recipient_service_id"], package)


def test_machine_target_or_review_free_text_cannot_become_dispatch(referral_case):
    h, _receiver, _actor, session, draft, _consent, _review, _enqueue, body, review_body = (
        referral_case
    )
    current = h.service.session_read(h.worker, session["id"])
    with pytest.raises(ManualError):
        h.service.referral_draft(
            h.worker,
            str(uuid4()),
            {
                **body,
                "expected_revision": current["revision"],
                "recipient_service_id": str(uuid4()),
            },
            session["id"],
        )
    with pytest.raises(ManualError, match="new_source_generation_required|stale_revision"):
        h.service.referral_review(
            h.worker,
            str(uuid4()),
            {**review_body, "decision": "edit", "edited_text": "hidden target"},
            draft["id"],
        )


def test_own_pid_can_read_exact_draft_for_consent(referral_case):
    h, _receiver, _actor, _session, draft, *_ = referral_case
    assert h.service.referral_read(h.participant, draft["id"])["payload"] == draft["payload"]
    with pytest.raises(ManualError):
        h.service.referral_read(replace(h.participant, account_id=str(uuid4())), draft["id"])


@pytest.mark.parametrize("boundary", ["dispatch_authorize", "dispatch_consume"])
@pytest.mark.parametrize("expiry_kind", ["consent", "review"])
def test_consent_expires_during_final_audit_rolls_back_authorization_or_attempt(
    referral_case, monkeypatch, boundary, expiry_kind
):
    h, _receiver, actor, _session, _draft, consent, *_ = referral_case
    pending = dispatch(referral_case)
    if boundary == "dispatch_consume":
        h.service._authorize(h.worker, pending["dispatch_id"], pending["revision"])
    original_audit = h.service._audit
    original_clock = h.service.clock
    expires = datetime.fromisoformat(
        (consent if expiry_kind == "consent" else referral_case[6])["expires_at"].replace(
            "Z", "+00:00"
        )
    )

    def audit(*args, **kwargs):
        value = original_audit(*args, **kwargs)
        if args[2] == boundary:
            h.service.clock = lambda: expires
        return value

    monkeypatch.setattr(h.service, "_audit", audit)
    try:
        with pytest.raises(
            ManualError,
            match="exact_consent_required" if expiry_kind == "consent" else "review_stale",
        ):
            if boundary == "dispatch_authorize":
                h.service._authorize(h.worker, pending["dispatch_id"], pending["revision"])
            else:
                h.service._consume(h.worker, pending["dispatch_id"])
    finally:
        h.service.clock = original_clock
    assert h.read("SELECT count(*) FROM referral.attempt") == [(0,)]
    assert h.read("SELECT count(*) FROM referral.authorization WHERE consumed_at IS NOT NULL") == [
        (0,)
    ]
    assert referral_case[1].receiver_inbox(actor, {})["dispatch_ids"] == []


@pytest.mark.parametrize(
    "status,accepted",
    [
        ("accepted", []),
        ("partial", ["needs", "preferences"]),
        ("partial", []),
        ("received", ["needs"]),
    ],
)
def test_malformed_receiver_semantics_cannot_infer_acceptance(referral_case, status, accepted):
    h = referral_case[0]
    current = send(referral_case)
    receipt = h.service.receipt_read(h.worker, current["dispatch_id"])
    with pytest.raises(ManualError, match="receipt_fields_invalid"):
        h.service._observe(
            h.worker,
            current["dispatch_id"],
            {**receipt, "id": str(uuid4()), "status": status, "accepted_fields": accepted},
        )
    assert h.service.dispatch_read(h.worker, current["dispatch_id"])["state"] == "received"


def test_real_opa_full_referral_and_receiver_reconciliation(opa_referral_case):
    case = opa_referral_case
    h, receiver, actor, _session, draft, *_ = case
    current = send(case)
    assert current["state"] == "received"
    detail = receiver.receiver_detail(actor, current["dispatch_id"])
    receiver.receiver_decide(
        actor,
        str(uuid4()),
        {
            "expected_revision": detail["revision"],
            "dispatch_id": current["dispatch_id"],
            "payload_digest": draft["digest"],
            "decision": "partial",
            "accepted_fields": ["needs"],
            "reason": "capacity",
        },
    )
    assert reconcile(case, current)["state"] == "partial"
    assert h.read("SELECT count(*) FROM referral.attempt") == [(1,)]


@pytest.mark.parametrize("action", ["referral_sources", "referral_read"])
def test_plan_share_expiring_during_output_audit_releases_no_payload(
    referral_case, referral_harness, monkeypatch, action
):
    from services.data.tests.test_plans_consent import grant_body

    h, proofs = referral_harness
    session = h.service.session_read(h.participant, referral_case[3]["id"])
    plan = h.service.plan_create(
        h.participant,
        str(uuid4()),
        {"expected_revision": session["revision"], "subject_id": session["subject_id"]},
    )
    h.service.plan_field_append(
        h.participant,
        str(uuid4()),
        {
            "expected_revision": plan["revision"],
            "field": "plan.strategies",
            "value": {"kind": "text", "text": "Fictional private plan strategy"},
            "source": None,
            "safety_relevant": False,
        },
        plan["id"],
    )
    body = grant_body(h, proofs, session)
    expires = datetime.now(UTC) + timedelta(seconds=20)
    body["expires_at"] = stamp(expires)
    h.service.consent_grant(h.participant, str(uuid4()), body)
    sources = h.service.referral_sources(h.worker, session["id"])
    selected = [
        entry["selected"]
        for entry in sources["items"]
        if entry["selected"]["field"] == "plan.strategies"
    ]
    assert len(selected) == 1
    draft = None
    if action == "referral_read":
        current = h.service.session_read(h.worker, session["id"])
        draft = h.service.referral_draft(
            h.worker,
            str(uuid4()),
            {**referral_case[8], "expected_revision": current["revision"], "selected": selected},
            session["id"],
        )
    original_clock, original_audit = h.service.clock, h.service._audit

    def audit(*args, **kwargs):
        value = original_audit(*args, **kwargs)
        if args[2] == action:
            h.service.clock = lambda: expires
        return value

    monkeypatch.setattr(h.service, "_audit", audit)
    try:
        with pytest.raises(ManualError, match="field_scope_denied"):
            if action == "referral_sources":
                h.service.referral_sources(h.worker, session["id"])
            else:
                h.service.referral_read(h.worker, draft["id"])
    finally:
        h.service.clock = original_clock


def test_invalid_post_send_receipt_is_durable_unknown_then_reconciles(referral_case, monkeypatch):
    h, receiver, _actor, *_ = referral_case
    original = receiver.send

    def forged_reply(service_id, package):
        receipt = original(service_id, package)
        return {**receipt, "status": "accepted", "accepted_fields": []}

    monkeypatch.setattr(receiver, "send", forged_reply)
    current = send(referral_case)
    assert current["state"] == "unknown"
    assert h.read("SELECT safe_reason FROM referral.observation") == [("invalid_receipt",)]
    assert reconcile(referral_case, current)["state"] == "received"


def test_unknown_copy_never_inherits_session_only_cleanup(referral_case, receiver_database):
    h, receiver, actor, session, *_ = referral_case
    receiver.scenario = "drop_after_store"
    current = send(referral_case)
    assert current["state"] == "unknown"
    session = h.service.session_read(h.participant, session["id"])
    h.service.session_end(
        h.participant,
        str(uuid4()),
        {"expected_revision": session["revision"], "reason": "user_choice"},
        session["id"],
    )
    assert h.read(
        "SELECT purpose,anchor_kind,state,expires_at FROM lifecycle.copy "
        "WHERE aggregate_type='referral'"
    ) == [("referral", "referral_terminal_parent", "anchor_pending", None)]
    with psycopg.connect(receiver_database[0]) as connection:
        assert connection.execute(
            "SELECT purpose,anchor_kind,retention_days,state,expires_at FROM receiver.copy"
        ).fetchall() == [("referral", "parent_and_delivery_terminal", 7, "anchor_pending", None)]
    assert receiver.receiver_inbox(actor, {})["dispatch_ids"] == [current["dispatch_id"]]


def test_receiver_authority_expiring_during_final_write_rolls_back(referral_case, monkeypatch):
    from contextlib import contextmanager

    _h, receiver, actor, _session, draft, *_ = referral_case
    current = send(referral_case)
    detail = receiver.receiver_detail(actor, current["dispatch_id"])
    deadline = datetime.now(UTC) + timedelta(seconds=2)
    actor = replace(actor, request_deadline=deadline)
    original_connection, original_clock = receiver.connection, receiver.clock

    @contextmanager
    def slow_final_write():
        with original_connection() as connection:

            class DelayedWrite:
                def execute(self, statement, parameters=()):
                    result = connection.execute(statement, parameters)
                    if statement.startswith("INSERT INTO receiver.decision"):
                        receiver.clock = lambda: deadline
                    return result

            yield DelayedWrite()

    monkeypatch.setattr(receiver, "connection", slow_final_write)
    try:
        with pytest.raises(ManualError, match="service_authority_required"):
            receiver.receiver_decide(
                actor,
                str(uuid4()),
                {
                    "expected_revision": detail["revision"],
                    "dispatch_id": current["dispatch_id"],
                    "payload_digest": draft["digest"],
                    "decision": "accept",
                    "accepted_fields": ["needs", "preferences"],
                    "reason": "accepted",
                },
            )
    finally:
        receiver.clock = original_clock
        monkeypatch.setattr(receiver, "connection", original_connection)
    observed = receiver.receiver_detail(actor, current["dispatch_id"])
    assert observed["revision"] == detail["revision"]
    assert observed["receipt"]["status"] == "received"
