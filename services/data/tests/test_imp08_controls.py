"""Real PostgreSQL control transitions; all identities/receipts are synthetic fixtures."""

import base64
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from care_link_data import PostgresStore
from care_link_data.governance.classification import change_class, required_authorities
from care_link_data.values import canonical, stamp
from care_link_domain import ManualError
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from psycopg.types.json import Jsonb


def key():
    return str(uuid4())


def provision_human(h, actor, authorities=("technical", "operations"), human_id=None):
    with psycopg.connect(h.database.admin) as connection:
        existing = connection.execute(
            "SELECT 1 FROM control.principal_guard WHERE principal_id=%s", (actor.account_id,)
        ).fetchone()
    if not existing:
        PostgresStore(h.database.admin).provision_principal(actor)
    with psycopg.connect(h.database.admin) as connection:
        previous = connection.execute(
            "SELECT human_id FROM governance.human_registry WHERE account_id=%s",
            (actor.account_id,),
        ).fetchone()
        connection.execute(
            "INSERT INTO governance.human_registry VALUES(%s,%s,%s,true,%s) "
            "ON CONFLICT(account_id) DO UPDATE SET human_id=excluded.human_id,"
            "authority_classes=excluded.authority_classes,active=true,"
            "identity_revision=excluded.identity_revision",
            (
                actor.account_id,
                human_id or (str(previous[0]) if previous else key()),
                list(authorities),
                actor.identity_revision,
            ),
        )
    return actor


def gov_actor(h, role="governance", authorities=("technical",), human_id=None):
    actor = replace(h.operator, account_id=key(), role=role, auth_time=datetime.now(UTC))
    return provision_human(h, actor, authorities, human_id)


def signed_candidate(
    h,
    mode="normal",
    domains=("technical",),
    kind="policy",
    paths=("apps/web/src/example.tsx",),
    payload=None,
):
    payload = payload or ("synthetic artifact " + key()).encode()
    digest = hashlib.sha256(payload).hexdigest()
    private = Ed25519PrivateKey.generate()
    evidence = hashlib.sha256(b"synthetic CI evidence").hexdigest()
    data = {
        "kind": kind,
        "version": "fixture-v1",
        "digest": digest,
        "source_revision": "83406f94014ca3cc71f870b3b8c771841c6e83f9",
        "content_class": "stub",
        "population": "synthetic",
        "evidence_digests": [evidence],
        "governed_domains": list(domains),
    }
    manifest = {
        "changed_paths": list(paths),
        "compatible_serving_generation": "1",
        "mode": mode,
        "rollback_trigger": "synthetic unauthorized effect or readiness loss",
        "required_evidence": [evidence],
    }
    signature = private.sign(canonical({"metadata": data, "manifest": manifest}).encode())
    data["signature"] = base64.b64encode(signature).decode()
    signer = key()
    with psycopg.connect(h.database.admin) as connection:
        connection.execute(
            "INSERT INTO governance.signer VALUES(%s,%s,true)",
            (signer, base64.b64encode(private.public_key().public_bytes_raw()).decode()),
        )
        connection.execute(
            "INSERT INTO governance.candidate VALUES(%s,%s,%s,%s,%s)",
            (digest, Jsonb(data), Jsonb(manifest), base64.b64encode(payload).decode(), signer),
        )
    return data


def register(h, mode="normal", **kwargs):
    provision_human(h, h.operator)
    data = signed_candidate(h, mode, **kwargs)
    result = h.service.artifact_register(h.operator, key(), data)
    assert result["state"] == "review_pending"
    return data


def review_all(h, data):
    paths = h.read("SELECT manifest FROM governance.candidate WHERE digest=%s", (data["digest"],))[
        0
    ][0]["changed_paths"]
    floor = change_class(data["kind"], data["governed_domains"], paths)
    for authority in required_authorities(floor, data["governed_domains"]):
        reviewer = gov_actor(
            h, "security" if authority == "security" else "governance", (authority,)
        )
        h.service.artifact_review(
            reviewer,
            key(),
            {
                "artifact_digest": data["digest"],
                "change_class": floor,
                "authority_class": authority,
                "decision": "accept",
                "evidence_digest": data["evidence_digests"][0],
                "expires_at": stamp(datetime.now(UTC) + timedelta(hours=1)),
            },
        )


def instance(h, name="evaluator"):
    boot = key()
    actor_id = key()
    workload = "spiffe://care-link.demo/demo/enforcer"
    with psycopg.connect(h.database.admin) as connection:
        connection.execute(
            "INSERT INTO governance.instance "
            "(instance_id,boot_id,workload_id,actor_id,healthy,required) "
            "VALUES(%s,%s,%s,%s,true,true) "
            "ON CONFLICT(instance_id) DO UPDATE SET boot_id=excluded.boot_id,"
            "actor_id=excluded.actor_id,healthy=true,required=true,observed_at=clock_timestamp()",
            (name, boot, workload, actor_id),
        )
    return name, boot, actor_id, workload


def activation(h, data):
    names = [
        row[0]
        for row in h.read(
            "SELECT instance_id FROM governance.instance WHERE required ORDER BY instance_id"
        )
    ]
    epoch = h.read("SELECT epoch FROM control.guard WHERE key='demo'")[0][0]
    return h.service.activation_create(
        h.operator,
        key(),
        {
            "artifact_digest": data["digest"],
            "expected_epoch": str(epoch),
            "effective_at": stamp(datetime.now(UTC) - timedelta(seconds=1)),
            "required_instances": names,
        },
    )


def provision_ack(h, activation_view, name="evaluator"):
    boot = h.read("SELECT boot_id FROM governance.instance WHERE instance_id=%s", (name,))[0][0]
    with psycopg.connect(h.database.admin) as connection:
        connection.execute(
            "INSERT INTO governance.ack VALUES(%s,%s,%s,%s,%s,%s,'ready',now()) "
            "ON CONFLICT(activation_id,instance_id) DO UPDATE SET boot_id=excluded.boot_id",
            (
                key(),
                activation_view["id"],
                name,
                boot,
                int(activation_view["epoch"]),
                activation_view["bundle_digest"],
            ),
        )


@pytest.mark.parametrize(
    "domains,paths,expected",
    [
        (("technical",), ("apps/web/src/example.tsx",), "C1"),
        (("technical",), ("config/a",), "C2"),
        (("consent",), ("apps/web/src/example.tsx",), "C3"),
        (("technical",), ("unknown/path",), "C3"),
        (("technical",), ("services/data/consent.py",), "C3"),
        (("technical",), ("services/data/src/care_link_data/engine.py",), "C3"),
        (("technical",), ("services/unknown/security.py",), "C3"),
        (("technical",), ("services/unknown/ordinary.py",), "C3"),
        (("unrecognized",), ("apps/web/src/display.tsx",), "C3"),
        (("technical",), ("apps/web/src/prompt.tsx",), "C2"),
        (("technical",), ("apps/web/src/model.tsx",), "C2"),
    ],
)
def test_mechanical_class_floor(domains, paths, expected):
    assert change_class("directory", domains, paths) == expected


def test_signed_exact_registration_and_context(harness):
    h = harness
    data = register(h)
    context = h.service.artifact_context(h.operator, data["digest"])
    assert context["payload_digest"] == data["digest"]
    assert context["change_class"] == "C2"
    assert set(context["missing_authorities"]) == {"technical", "security", "operations"}
    review_all(h, data)
    assert h.service.artifact_context(h.operator, data["digest"])["missing_authorities"] == []


def test_same_human_second_account_cannot_review(harness):
    h = harness
    data = register(h)
    human = h.read(
        "SELECT human_id FROM governance.human_registry WHERE account_id=%s",
        (h.operator.account_id,),
    )[0][0]
    reviewer = gov_actor(h, human_id=human)
    with pytest.raises(ManualError, match="independent_human"):
        h.service.artifact_review(
            reviewer,
            key(),
            {
                "artifact_digest": data["digest"],
                "change_class": "C2",
                "authority_class": "technical",
                "decision": "accept",
                "evidence_digest": data["evidence_digests"][0],
                "expires_at": stamp(datetime.now(UTC) + timedelta(hours=1)),
            },
        )


def test_unknown_signer_denies_even_valid_hash(harness):
    h = harness
    provision_human(h, h.operator)
    data = signed_candidate(h)
    with psycopg.connect(h.database.admin) as connection:
        connection.execute("UPDATE governance.signer SET active=false")
    with pytest.raises(ManualError, match="provenance"):
        h.service.artifact_register(h.operator, key(), data)


def test_immutable_payload_hash_is_verified(harness):
    h = harness
    provision_human(h, h.operator)
    data = signed_candidate(h)
    with psycopg.connect(h.database.admin) as connection:
        connection.execute(
            "UPDATE governance.candidate SET payload=%s WHERE digest=%s",
            (base64.b64encode(b"changed").decode(), data["digest"]),
        )
    with pytest.raises(ManualError, match="digest_invalid"):
        h.service.artifact_register(h.operator, key(), data)


def test_activation_denies_missing_review_and_old_boot(harness):
    h = harness
    data = register(h)
    instance(h)
    proposed = activation(h, data)
    provision_ack(h, proposed)
    with pytest.raises(ManualError, match="missing_current_reviews"):
        h.service.activation_commit(
            h.operator, key(), {"expected_revision": proposed["revision"]}, proposed["id"]
        )
    review_all(h, data)
    instance(h)  # a new boot invalidates exact old ACK
    with pytest.raises(ManualError, match="current_boot_ack"):
        h.service.activation_commit(
            h.operator, key(), {"expected_revision": proposed["revision"]}, proposed["id"]
        )
    provision_ack(h, proposed)
    result = h.service.activation_commit(
        h.operator, key(), {"expected_revision": proposed["revision"]}, proposed["id"]
    )
    assert result["state"] == "active"
    assert h.read("SELECT epoch,bundle_digest FROM control.guard")[0] == (
        int(proposed["epoch"]),
        data["digest"],
    )
    assert h.service.health_read(h.operator)["ready"] is True


def test_restrictive_fence_precedes_ack(harness):
    h = harness
    data = register(h, "restricted")
    instance(h)
    before = h.read("SELECT epoch FROM control.guard")[0][0]
    proposed = activation(h, data)
    assert proposed["missing_instances"] == ["evaluator"]
    assert h.read("SELECT epoch,mode FROM control.guard")[0] == (before + 1, "restricted")
    assert h.journal.records[-1]["restriction"]["kind"] == "kill"
    assert h.service.health_read(h.operator)["ready"] is False


def test_required_instance_omission_denied(harness):
    h = harness
    data = register(h)
    instance(h)
    instance(h, "second")
    with pytest.raises(ManualError, match="instances_mismatch"):
        h.service.activation_create(
            h.operator,
            key(),
            {
                "artifact_digest": data["digest"],
                "expected_epoch": "1",
                "effective_at": stamp(datetime.now(UTC)),
                "required_instances": ["evaluator"],
            },
        )


def test_expired_review_cannot_activate(harness):
    h = harness
    data = register(h)
    instance(h)
    review_all(h, data)
    proposed = activation(h, data)
    provision_ack(h, proposed)
    with psycopg.connect(h.database.admin) as connection:
        connection.execute("UPDATE governance.review SET expires_at=now()-interval '1 second'")
    with pytest.raises(ManualError, match="missing_current_reviews"):
        h.service.activation_commit(
            h.operator, key(), {"expected_revision": proposed["revision"]}, proposed["id"]
        )


def test_principal_containment_is_bounded_and_journalled(harness):
    h = harness
    provision_human(h, h.operator)
    initial_mode = h.read("SELECT mode FROM control.guard")[0][0]
    scope = {
        "session_id": None,
        "subject_id": None,
        "purpose": "security",
        "fields": [],
        "recipient_id": h.worker.account_id,
    }
    record = h.service.incident_create(
        h.operator,
        key(),
        {"kind": "security", "scope": scope, "severity": "critical", "evidence_refs": ["a" * 64]},
    )
    result = h.service.incident_transition(
        h.operator,
        key(),
        {
            "expected_revision": record["revision"],
            "target_state": "contained",
            "evidence_digest": "b" * 64,
            "recovery_approval_id": None,
        },
        record["id"],
    )
    assert result["state"] == "contained"
    assert (
        h.read(
            "SELECT revoked FROM control.principal_guard WHERE principal_id=%s",
            (h.worker.account_id,),
        )[0][0]
        is True
    )
    assert h.read("SELECT mode FROM control.guard")[0][0] == initial_mode
    assert h.journal.records[-1]["restriction"]["kind"] == "identity_revoke"


def test_no_exception_to_fixed_exclusion(harness):
    h = harness
    provision_human(h, h.operator)
    governor = gov_actor(h)
    with pytest.raises(ManualError):
        h.service.exception_create(
            governor,
            key(),
            {
                "expected_revision": "1",
                "scope": {
                    "session_id": None,
                    "subject_id": None,
                    "purpose": "governance",
                    "fields": [],
                    "recipient_id": None,
                },
                "policy_rule_id": "no_police",
                "approver_receipt_id": key(),
                "expires_at": stamp(datetime.now(UTC) + timedelta(minutes=5)),
                "compensating_control_digest": "a" * 64,
            },
        )


def test_runtime_cannot_write_human_or_approval_custody(harness):
    h = harness
    with psycopg.connect(h.database.runtime) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "INSERT INTO governance.human_registry VALUES(%s,%s,ARRAY['security'],true,1)",
                (h.worker.account_id, key()),
            )


def signed_enforcer(h, proposed, *, boot=None, name="evaluator", actor_id=None):
    from care_link_data.governance.ack import EnforcerAcknowledgements
    from care_link_domain import DutyActor, DutyScope
    from care_link_policy_input.duties import (
        DutyDefinition,
        SignedDutyDefinition,
        SignedDutyRegistry,
    )

    operation = key()
    instance_row = h.read(
        "SELECT boot_id,actor_id,workload_id FROM governance.instance WHERE instance_id=%s", (name,)
    )[0]
    payload = {
        "activation_id": proposed["id"],
        "instance_id": name,
        "boot_id": boot or str(instance_row[0]),
        "epoch": proposed["epoch"],
        "bundle_digest": proposed["bundle_digest"],
        "status": "ready",
    }
    now = datetime.now(UTC)
    signing = Ed25519PrivateKey.generate()
    workload = instance_row[2]
    definition = DutyDefinition(
        key(),
        workload,
        ("activation_ack",),
        ("governance",),
        ("validated_security_event",),
        1,
        key(),
        now + timedelta(minutes=5),
    )
    artifact = SignedDutyDefinition(
        definition, actor_id or str(instance_row[1]), 1, "fixture-enforcer", ""
    )
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
        DutyScope(None, None, "governance"),
        "activation_ack",
        EnforcerAcknowledgements.binding("activation_ack", operation, payload),
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
    return EnforcerAcknowledgements(h.service, registry), actor, operation, payload


def test_signed_enforcer_ack_has_workload_audit_and_current_boot(harness):
    h = harness
    data = register(h)
    instance(h)
    review_all(h, data)
    proposed = activation(h, data)
    commands, actor, operation, payload = signed_enforcer(h, proposed)
    acknowledged = commands.activation_ack(actor, operation, payload)
    assert acknowledged["missing_instances"] == []
    assert acknowledged["state"] == "ready"
    assert h.read(
        "SELECT actor_context->'actor'->>'kind' FROM audit.event WHERE operation_id=%s",
        (operation,),
    ) == [("workload",)]
    assert commands.activation_ack(actor, operation, payload) == acknowledged
    assert h.read(
        "SELECT count(*) FROM control.principal_guard WHERE principal_id=%s", (actor.actor_id,)
    ) == [(0,)]


def test_signed_old_boot_and_wrong_registered_actor_denied(harness):
    h = harness
    data = register(h)
    instance(h)
    proposed = activation(h, data)
    for overrides in ({"boot": key()}, {"actor_id": key()}):
        commands, actor, operation, payload = signed_enforcer(h, proposed, **overrides)
        with pytest.raises(ManualError, match="exact_current_boot"):
            commands.activation_ack(actor, operation, payload)
    assert h.read("SELECT count(*) FROM governance.ack") == [(0,)]


def test_rollback_is_new_epoch_and_requires_fresh_receipts(harness):
    h = harness
    first = register(h)
    instance(h)
    review_all(h, first)
    one = activation(h, first)
    provision_ack(h, one)
    h.service.activation_commit(
        h.operator, key(), {"expected_revision": one["revision"]}, one["id"]
    )
    second = register(h, "ai_disabled")
    review_all(h, second)
    two = activation(h, second)
    provision_ack(h, two)
    h.service.activation_commit(
        h.operator, key(), {"expected_revision": two["revision"]}, two["id"]
    )
    rollback = activation(h, first)
    provision_ack(h, rollback)
    with pytest.raises(ManualError, match="fresh_reviews"):
        h.service.activation_commit(
            h.operator, key(), {"expected_revision": rollback["revision"]}, rollback["id"]
        )
    review_all(h, first)
    rolled = h.service.activation_commit(
        h.operator, key(), {"expected_revision": rollback["revision"]}, rollback["id"]
    )
    assert int(rolled["epoch"]) > int(two["epoch"])
    assert h.read("SELECT restriction_barrier FROM control.guard")[0][0] > 0
    assert h.read("SELECT serving_generation FROM control.guard") == [(1,)]


def test_review_expiry_during_audit_rolls_back_activation(harness, monkeypatch):
    h = harness
    data = register(h)
    instance(h)
    review_all(h, data)
    proposed = activation(h, data)
    provision_ack(h, proposed)
    now = datetime.now(UTC)
    with psycopg.connect(h.database.admin) as connection:
        connection.execute(
            "UPDATE governance.review SET expires_at=%s", (now + timedelta(seconds=2),)
        )
    original = h.service._audit

    def expire_after_audit(tx, actor, action, *args, **kwargs):
        result = original(tx, actor, action, *args, **kwargs)
        if action == "activation_commit":
            h.service.clock = lambda: now + timedelta(seconds=3)
        return result

    monkeypatch.setattr(h.service, "_audit", expire_after_audit)
    with pytest.raises(ManualError, match="missing_current_reviews"):
        h.service.activation_commit(
            h.operator, key(), {"expected_revision": proposed["revision"]}, proposed["id"]
        )
    assert h.read("SELECT bundle_digest FROM control.guard") == [("a" * 64,)]
    assert h.read("SELECT state FROM governance.activation WHERE id=%s", (proposed["id"],)) == [
        ("staged",)
    ]
    assert h.journal.records[-1]["kind"] == "relax_intent"  # intent alone cannot grant


def test_nonpolicy_artifact_cannot_replace_policy_evaluator(harness):
    h = harness
    data = register(h, "restricted", kind="model")
    instance(h)
    with pytest.raises(ManualError, match="non_policy_activation"):
        activation(h, data)
    assert h.read("SELECT mode,bundle_digest FROM control.guard") == [("ai_disabled", "a" * 64)]
    assert not h.journal.records


def test_arbitrary_independent_human_cannot_approve_exception(harness):
    from care_link_data.values import digest

    h = harness
    governor = gov_actor(h)
    worker = gov_actor(h, "worker", ())
    scope = {
        "session_id": None,
        "subject_id": None,
        "purpose": "governance",
        "fields": [],
        "recipient_id": None,
    }
    receipt = key()
    data = {
        "expected_revision": "1",
        "scope": scope,
        "policy_rule_id": "demo.review_frequency",
        "approver_receipt_id": receipt,
        "expires_at": stamp(datetime.now(UTC) + timedelta(minutes=5)),
        "compensating_control_digest": "b" * 64,
    }
    human = h.read(
        "SELECT human_id FROM governance.human_registry WHERE account_id=%s", (worker.account_id,)
    )[0][0]
    with psycopg.connect(h.database.admin) as connection:
        connection.execute(
            "INSERT INTO governance.exception_rule VALUES('demo.review_frequency',%s,%s,%s,true)",
            ("a" * 64, "b" * 64, Jsonb(scope)),
        )
        connection.execute(
            "INSERT INTO governance.approval "
            "VALUES(%s,'exception_create',%s,%s,%s,now()+interval '10 minutes',true,%s)",
            (
                receipt,
                digest({k: v for k, v in data.items() if k != "approver_receipt_id"}),
                worker.account_id,
                human,
                Jsonb(scope),
            ),
        )
    with pytest.raises(ManualError, match="approver_authority"):
        h.service.exception_create(governor, key(), data)
    assert h.read("SELECT count(*) FROM governance.exception") == [(0,)]


def test_actual_pinned_opa_activation_and_current_evaluator(harness):
    import os
    from pathlib import Path

    from care_link_policy_input import OpaPolicy
    from care_link_policy_input.governed import GovernedPolicies

    binary = os.environ.get("CARE_LINK_OPA_BINARY")
    if not binary:
        pytest.skip("Explicit pinned OPA required for real activation evaluator proof")
    h = harness
    source = (
        Path(__file__).resolve().parents[3] / "config/demo/imp08/policy/manual.rego"
    ).read_bytes()
    candidate = source + b"\n# synthetic exact governance candidate\n"
    executable = Path(binary)
    executable_digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    signer = Ed25519PrivateKey.generate()

    def evaluator(content):
        return OpaPolicy(
            executable,
            executable_digest,
            content,
            base64.b64encode(signer.sign(content)).decode(),
            signer.public_key(),
        )

    old = evaluator(source)
    new = evaluator(candidate)
    h.service.policy = GovernedPolicies((old, new))
    with psycopg.connect(h.database.admin) as connection:
        connection.execute("UPDATE control.guard SET bundle_digest=%s", (old.bundle_digest,))
    data = register(h, payload=candidate, kind="policy")
    instance(h)
    review_all(h, data)
    proposed = activation(h, data)
    commands, actor, operation, payload = signed_enforcer(h, proposed)
    ready = commands.activation_ack(actor, operation, payload)
    committed = h.service.activation_commit(
        h.operator, key(), {"expected_revision": ready["revision"]}, proposed["id"]
    )
    assert committed["bundle_digest"] == new.bundle_digest
    assert h.service.health_read(h.operator)["ready"] is True
    assert h.journal.records[-1]["kind"] == "relax_intent"
    assert h.journal.records[-1]["relaxation_evidence_digest"] is not None
    # Real business requests select the new source and stay current.
    session = h.create()
    assert session["id"]
    instance(h)
    assert h.service.health_read(h.operator)["ready"] is False
    with pytest.raises(ManualError):
        h.create()
    commands, actor, operation, payload = signed_enforcer(h, committed)
    renewed = commands.activation_ack(actor, operation, payload)
    assert renewed["state"] == "active" and renewed["missing_instances"] == []
    assert h.create()["id"]


def test_signed_host_journal_records_restrictive_and_relaxation_receipts(harness, tmp_path):
    from care_link_recovery_control import FileJournal

    h = harness
    journal = FileJournal.provision(
        tmp_path / "governance-journal",
        Ed25519PrivateKey.generate(),
        "synthetic-control-key",
        journal_id=h.journal.head().journal_id,
    )
    h.service.journal = journal
    restricted = register(h, "restricted")
    instance(h)
    review_all(h, restricted)
    staged = activation(h, restricted)
    assert journal.head().restriction_barrier == 1
    commands, actor, operation, payload = signed_enforcer(h, staged)
    ready = commands.activation_ack(actor, operation, payload)
    h.service.activation_commit(
        h.operator, key(), {"expected_revision": ready["revision"]}, staged["id"]
    )
    assert journal.head().tip == 2 and journal.head().restriction_barrier == 1
    normal = register(h, "normal")
    review_all(h, normal)
    staged = activation(h, normal)
    commands, actor, operation, payload = signed_enforcer(h, staged)
    ready = commands.activation_ack(actor, operation, payload)
    h.service.activation_commit(
        h.operator, key(), {"expected_revision": ready["revision"]}, staged["id"]
    )
    final = journal.head()
    assert final.tip == 3 and final.restriction_barrier == 1
    assert h.read("SELECT mode,restriction_barrier FROM control.guard") == [("normal", 1)]
    reopened = FileJournal(
        journal.path, journal.private_key, journal.key_id, expected_journal_id=journal.journal_id
    )
    recovered = reopened.head()
    assert (recovered.tip, recovered.tip_digest, recovered.restriction_barrier) == (
        final.tip,
        final.tip_digest,
        final.restriction_barrier,
    )
    encoded = (journal.path / "records.jsonl").read_text()
    assert '"relaxation_evidence_digest":null' in encoded
    assert '"kind":"relax_intent"' in encoded


def test_new_required_instance_invalidates_current_activation(harness):
    h = harness
    data = register(h)
    instance(h)
    review_all(h, data)
    proposed = activation(h, data)
    provision_ack(h, proposed)
    committed = h.service.activation_commit(
        h.operator, key(), {"expected_revision": proposed["revision"]}, proposed["id"]
    )
    assert h.service.health_read(h.operator)["ready"] is True
    instance(h, "new-required")
    assert h.service.activation_read(h.operator, committed["id"])["missing_instances"] == [
        "new-required"
    ]
    assert h.service.health_read(h.operator)["ready"] is False
    with pytest.raises(ManualError):
        h.create()
