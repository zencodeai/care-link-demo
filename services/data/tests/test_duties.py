"""Real PostgreSQL duty transitions; cryptographic receipts are test fixtures only."""

import base64
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from care_link_data.duties import DutyCommands, SignalSource
from care_link_data.values import canonical, digest, stamp
from care_link_domain import DutyActor, DutyScope, ManualError
from care_link_policy_input.duties import DutyDefinition, SignedDutyDefinition, SignedDutyRegistry
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from services.data.tests.conftest import Harness


def key() -> str:
    return str(uuid4())


def duty(
    h: Harness, action: str, operation: str, payload: dict[str, object], scope: DutyScope
) -> tuple[DutyCommands, DutyActor]:
    now = datetime.now(UTC)
    signing = Ed25519PrivateKey.generate()
    workload = (
        "spiffe://care-link.demo/demo/identity"
        if action == "identity_revoke"
        else "spiffe://care-link.demo/demo/jobs"
    )
    definition = DutyDefinition(
        key(),
        workload,
        (action,),
        (scope.purpose,),
        ("identity_signal" if action == "identity_revoke" else "expired_reservation",),
        1,
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
        job_id=str(payload["job_id"]) if action == "job_execute" else None,
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


def signal(
    principal: str, signer: Ed25519PrivateKey, *, sequence: int = 1, age: int = 0
) -> dict[str, object]:
    data: dict[str, object] = {
        "issuer_id": "fixture-source",
        "audience": "care-link-control",
        "jti": key(),
        "subject_id": principal,
        "event_type": "credential_revoked",
        "source_sequence": str(sequence),
        "previous_digest": "0" * 64,
        "event_at": stamp(datetime.now(UTC) - timedelta(seconds=age)),
    }
    data["digest"] = digest(data)
    data["signature"] = (
        base64.urlsafe_b64encode(signer.sign(canonical(data).encode())).rstrip(b"=").decode()
    )
    return data


def configure_signal(commands: DutyCommands, signer: Ed25519PrivateKey) -> DutyCommands:
    return DutyCommands(
        commands.service,
        commands.authority,
        signal_sources={"fixture-source": SignalSource("care-link-control", signer.public_key())},
    )


def test_signed_identity_duty_revokes_without_human_actor_or_principal_row(
    harness: Harness,
) -> None:
    h = harness
    signer = Ed25519PrivateKey.generate()
    payload = signal(h.participant.account_id, signer)
    operation = key()
    commands, actor = duty(
        h, "identity_revoke", operation, payload, DutyScope(None, None, "security")
    )
    commands = configure_signal(commands, signer)
    result = commands.identity_revoke(actor, operation, payload)
    assert result["state"] == "committed"
    assert h.read(
        "SELECT revoked,identity_revision FROM control.principal_guard WHERE principal_id=%s",
        (h.participant.account_id,),
    ) == [(True, 2)]
    assert h.read(
        "SELECT count(*) FROM control.principal_guard WHERE principal_id=%s", (actor.actor_id,)
    ) == [(0,)]
    assert h.read(
        "SELECT actor_context->'actor'->>'kind',actor_context->'actor'->>'workload_id' "
        "FROM audit.event WHERE operation_id=%s",
        (operation,),
    ) == [("workload", actor.workload_id)]
    assert len(h.journal.records) == 1
    assert commands.identity_revoke(actor, operation, payload) == result
    assert len(h.journal.records) == 1
    with pytest.raises(ManualError):
        h.create()


@pytest.mark.parametrize("kind", ["signature", "unmapped", "workload_kind"])
def test_invalid_signal_duty_has_no_restrictive_effect(harness: Harness, kind: str) -> None:
    h = harness
    signer = Ed25519PrivateKey.generate()
    payload = signal(key() if kind == "unmapped" else h.participant.account_id, signer)
    if kind == "signature":
        payload["signature"] = "invalid"
    if kind == "workload_kind":
        payload = {**payload, "event_type": "workload_compromised"}
    operation = key()
    commands, actor = duty(
        h, "identity_revoke", operation, payload, DutyScope(None, None, "security")
    )
    commands = configure_signal(commands, signer)
    with pytest.raises(ManualError):
        commands.identity_revoke(actor, operation, payload)
    assert h.read(
        "SELECT revoked FROM control.principal_guard WHERE principal_id=%s",
        (h.participant.account_id,),
    ) == [(False,)]
    assert not h.read("SELECT * FROM durable.duty_operation WHERE state='committed'")
    assert not h.journal.records


@pytest.mark.parametrize("sequence,age", [(2, 0), (1, 61)])
def test_signed_gap_or_stale_signal_quarantines_source_under_global_restriction(
    harness: Harness, sequence: int, age: int
) -> None:
    h = harness
    signer = Ed25519PrivateKey.generate()
    payload = signal(h.participant.account_id, signer, sequence=sequence, age=age)
    operation = key()
    commands, actor = duty(
        h, "identity_revoke", operation, payload, DutyScope(None, None, "security")
    )
    commands = configure_signal(commands, signer)
    commands.identity_revoke(actor, operation, payload)
    assert h.read("SELECT quarantined FROM control.signal_source") == [(True,)]
    assert h.read("SELECT mode FROM control.guard") == [("restricted",)]
    assert h.journal.records[0]["restriction"]["kind"] == "kill"


def reserved(h: Harness) -> dict[str, object]:
    session = h.create()
    queue = h.service.session_human_request(
        h.participant,
        key(),
        {"expected_revision": session["revision"], "reason": "user_requested"},
        str(session["id"]),
    )
    h.service.workforce_reserve(
        h.worker,
        key(),
        {"expected_revision": queue["revision"], "worker_id": h.worker.account_id},
        str(session["id"]),
    )
    job = h.read(
        "SELECT job_id,aggregate_id,expected_revision,fence,original_operation_id,"
        "deadline,session_id "
        "FROM durable.due_job"
    )[0]
    return {
        "job_id": str(job[0]),
        "kind": "reservation_expiry",
        "aggregate_id": str(job[1]),
        "expected_revision": str(job[2]),
        "fence": str(job[3]),
        "original_operation_id": str(job[4]),
        "deadline": stamp(job[5]),
        "session_id": str(job[6]),
    }


def test_persisted_expiry_job_requeues_once_without_resolving_support(harness: Harness) -> None:
    h = harness
    stored = reserved(h)
    sid = str(stored.pop("session_id"))
    with psycopg.connect(h.database.admin) as admin:
        admin.execute("UPDATE workforce.assignment SET expires_at=now()-interval '1 second'")
        admin.execute("UPDATE durable.due_job SET due_at=now()-interval '1 second'")
    subject = str(h.read("SELECT persona_id FROM core.session WHERE id=%s", (sid,))[0][0])
    operation = key()
    commands, actor = duty(h, "job_execute", operation, stored, DutyScope(sid, subject, "support"))
    result = commands.job_execute(actor, operation, stored)
    assert result["state"] == "committed"
    assert h.read("SELECT status FROM workforce.assignment") == [("expired",)]
    assert h.read("SELECT status FROM workforce.queue_entry") == [("pending",)]
    assert h.read("SELECT service_phase,unresolved FROM core.session") == [("queued", True)]
    assert h.read("SELECT state FROM durable.due_job") == [("completed",)]
    assert commands.job_execute(actor, operation, stored) == result
    assert h.read("SELECT count(*) FROM durable.duty_operation") == [(1,)]


def test_job_forgery_or_early_delivery_cannot_expire_assignment(harness: Harness) -> None:
    h = harness
    stored = reserved(h)
    sid = str(stored.pop("session_id"))
    subject = str(h.read("SELECT persona_id FROM core.session")[0][0])
    for payload in [stored, {**stored, "fence": "999"}, {**stored, "kind": "dispatch"}]:
        operation = key()
        commands, actor = duty(
            h, "job_execute", operation, payload, DutyScope(sid, subject, "support")
        )
        with pytest.raises(ManualError):
            commands.job_execute(actor, operation, payload)
    assert h.read("SELECT status FROM workforce.assignment") == [("reserved",)]
    assert not h.read("SELECT * FROM durable.duty_operation WHERE state='committed'")


def test_authenticated_pdp_denial_is_terminal_and_has_workload_canonical_audit(
    harness: Harness,
) -> None:
    h = harness
    stored = reserved(h)
    sid = str(stored.pop("session_id"))
    subject = str(h.read("SELECT persona_id FROM core.session")[0][0])
    with psycopg.connect(h.database.admin) as admin:
        admin.execute("UPDATE workforce.assignment SET expires_at=now()-interval '1 second'")
        admin.execute("UPDATE durable.due_job SET due_at=now()-interval '1 second'")
    operation = key()
    commands, actor = duty(h, "job_execute", operation, stored, DutyScope(sid, subject, "support"))
    evaluate = h.policy.evaluate

    def deny(request: dict[str, object]) -> dict[str, object]:
        decision = evaluate(request)
        decision["decision"] = "DENY"
        decision["reasons"] = ["NOT_AUTHORIZED"]
        return decision

    h.policy.evaluate = deny
    with pytest.raises(ManualError, match="policy_denied"):
        commands.job_execute(actor, operation, stored)
    assert h.read(
        "SELECT state FROM durable.duty_operation WHERE operation_id=%s", (operation,)
    ) == [("rejected",)]
    assert h.read(
        "SELECT decision,actor_context->'actor'->>'kind' FROM audit.event WHERE operation_id=%s",
        (operation,),
    ) == [("DENY", "workload")]
    h.policy.evaluate = evaluate
    result = commands.job_execute(actor, operation, stored)
    assert result["state"] == "rejected"
    assert h.read("SELECT status FROM workforce.assignment") == [("reserved",)]
    assert h.read("SELECT state FROM durable.due_job") == [("pending",)]


def test_authenticated_dependency_denial_can_retry_same_key_without_terminal_rejection(
    harness: Harness,
) -> None:
    h = harness
    signer = Ed25519PrivateKey.generate()
    payload = signal(h.participant.account_id, signer)
    operation = key()
    commands, actor = duty(
        h, "identity_revoke", operation, payload, DutyScope(None, None, "security")
    )
    commands = configure_signal(commands, signer)
    h.policy.fail = True
    with pytest.raises(ManualError, match="pdp_unavailable"):
        commands.identity_revoke(actor, operation, payload)
    assert not h.read("SELECT * FROM durable.duty_operation")
    assert h.read("SELECT decision FROM audit.event") == [("DENY",)]
    assert h.read(
        "SELECT revoked FROM control.principal_guard WHERE principal_id=%s",
        (h.participant.account_id,),
    ) == [(False,)]
    h.policy.fail = False
    assert commands.identity_revoke(actor, operation, payload)["state"] == "committed"


def test_authenticated_fenced_job_has_deny_audit_and_keeps_assignment(harness: Harness) -> None:
    h = harness
    stored = reserved(h)
    sid = str(stored.pop("session_id"))
    subject = str(h.read("SELECT persona_id FROM core.session")[0][0])
    with psycopg.connect(h.database.admin) as admin:
        admin.execute("UPDATE workforce.assignment SET expires_at=now()-interval '1 second'")
        admin.execute("UPDATE durable.due_job SET due_at=now()-interval '1 second'")
        admin.execute("UPDATE core.session_guard SET control_epoch=control_epoch+1")
    operation = key()
    commands, actor = duty(h, "job_execute", operation, stored, DutyScope(sid, subject, "support"))
    with pytest.raises(ManualError, match="job_fenced"):
        commands.job_execute(actor, operation, stored)
    assert h.read("SELECT decision FROM audit.event WHERE operation_id=%s", (operation,)) == [
        ("DENY",)
    ]
    assert h.read("SELECT status FROM workforce.assignment") == [("reserved",)]
    assert h.read("SELECT state FROM durable.due_job") == [("pending",)]


def test_unauthenticated_duty_never_gets_canonical_workload_actor_slot(harness: Harness) -> None:
    h = harness
    signer = Ed25519PrivateKey.generate()
    payload = signal(h.participant.account_id, signer)
    operation = key()
    commands, actor = duty(
        h, "identity_revoke", operation, payload, DutyScope(None, None, "security")
    )
    commands = configure_signal(commands, signer)
    with pytest.raises(ManualError):
        commands.identity_revoke(replace(actor, signature="invalid"), operation, payload)
    assert not h.read("SELECT * FROM audit.event")
    assert not h.read("SELECT * FROM durable.duty_operation")
