"""Synthetic cryptographic fixtures; these keys/receipts convey no human approval."""

import base64
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from care_link_domain import DutyActor, DutyScope, ManualError
from care_link_policy_input.duties import (
    DutyDefinition,
    SignedDutyDefinition,
    SignedDutyRegistry,
    canonical,
)
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

NOW = datetime(2026, 11, 9, tzinfo=UTC)


def fixture(
    action: str = "identity_revoke",
) -> tuple[SignedDutyRegistry, DutyActor, Ed25519PrivateKey]:
    key = Ed25519PrivateKey.generate()
    workload = (
        "spiffe://care-link.demo/demo/identity"
        if action == "identity_revoke"
        else "spiffe://care-link.demo/demo/jobs"
    )
    definition = DutyDefinition(
        str(uuid4()),
        workload,
        (action,),
        ("security" if action == "identity_revoke" else "support",),
        ("identity_signal" if action == "identity_revoke" else "expired_reservation",),
        1,
        str(uuid4()),
        NOW + timedelta(days=1),
    )
    artifact = SignedDutyDefinition(definition, str(uuid4()), 1, "fixture-only", "")
    artifact = replace(
        artifact,
        signature=base64.urlsafe_b64encode(key.sign(canonical(artifact.unsigned())))
        .rstrip(b"=")
        .decode(),
    )
    registry = SignedDutyRegistry(
        (artifact,),
        signer_keys={"fixture-only": key.public_key()},
        evidence_keys={workload: key.public_key()},
        admitted_digests=frozenset({artifact.digest}),
        approval_receipts={definition.approval_receipt_id: artifact.digest},
        workload_check=lambda peer, credential: 1
        if peer == workload and credential == workload
        else 0,
        clock=lambda: NOW,
    )
    scope = (
        DutyScope(None, None, "security")
        if action == "identity_revoke"
        else DutyScope(str(uuid4()), str(uuid4()), "support")
    )
    actor = DutyActor(
        artifact.actor_id,
        workload,
        definition.duty_id,
        str(uuid4()),
        artifact.digest,
        scope,
        action,
        "a" * 64,
        str(uuid4()),
        NOW,
        NOW + timedelta(seconds=1),
        "",
        1,
        1,
        workload,
        job_id=str(uuid4()) if action == "job_execute" else None,
        request_deadline=NOW + timedelta(seconds=1),
    )
    actor = sign_actor(actor, key)
    return registry, actor, key


def sign_actor(actor: DutyActor, key: Ed25519PrivateKey) -> DutyActor:
    evidence = {k: v for k, v in actor.evidence().items() if k != "signature"}
    return replace(
        actor,
        signature=base64.urlsafe_b64encode(key.sign(canonical(evidence))).rstrip(b"=").decode(),
    )


def test_empty_registry_and_missing_exact_receipt_deny() -> None:
    registry, actor, _ = fixture()
    with pytest.raises(ManualError, match="not_admitted"):
        SignedDutyRegistry().current(actor, actor.action, actor.request_digest, actor.scope)
    missing = SignedDutyRegistry(
        registry.definitions,
        signer_keys=registry.signer_keys,
        evidence_keys=registry.evidence_keys,
        admitted_digests=registry.admitted_digests,
        workload_check=registry.workload_check,
        clock=lambda: NOW,
    )
    with pytest.raises(ManualError, match="not_admitted"):
        missing.current(actor, actor.action, actor.request_digest, actor.scope)


@pytest.mark.parametrize("action", ["identity_revoke", "job_execute"])
def test_exact_signed_duty_and_current_workload_are_required(action: str) -> None:
    registry, actor, key = fixture(action)
    assert registry.current(actor, action, actor.request_digest, actor.scope) == actor
    for changed in [
        replace(actor, actor_id=str(uuid4())),
        replace(actor, workload_revision=2),
        replace(actor, duty_revision=2),
        replace(actor, originating_human_id=str(uuid4())),
        replace(actor, signature="invalid"),
    ]:
        with pytest.raises(ManualError):
            registry.current(
                sign_actor(changed, key) if changed.signature == actor.signature else changed,
                action,
                actor.request_digest,
                actor.scope,
            )
    with pytest.raises(ManualError):
        registry.current(actor, action, "b" * 64, actor.scope)


def test_slow_workload_recheck_cannot_reuse_expired_evidence() -> None:
    registry, actor, _ = fixture()
    clock = [NOW]

    def slow(_peer: str, _credential: str) -> int:
        clock[0] += timedelta(seconds=1)
        return 1

    registry.clock = lambda: clock[0]
    registry.workload_check = slow
    with pytest.raises(ManualError, match="expired"):
        registry.current(actor, actor.action, actor.request_digest, actor.scope)


def test_signed_delegation_rejects_wrong_route_peer_actor_and_body() -> None:
    registry, actor, key = fixture()
    operation = str(uuid4())
    outer: dict[str, object] = {
        "id": operation,
        "actor": actor.wire(),
        "evidence": actor.evidence(),
        "scope": actor.scope.wire(),
        "audience": "care-link-control",
        "method": "POST",
        "path": "/internal/v1/control/identity-revoke",
        "body_digest": "b" * 64,
        "nonce": actor.nonce,
        "expires_at": actor.expires_at.isoformat().replace("+00:00", "Z"),
    }
    outer["signature"] = base64.urlsafe_b64encode(key.sign(canonical(outer))).rstrip(b"=").decode()
    options = dict(
        peer=actor.workload_id,
        method="POST",
        path=str(outer["path"]),
        audience="care-link-control",
        body_digest="b" * 64,
        operation_id=operation,
        request_digest=actor.request_digest,
        credential_ref=actor.credential_ref,
    )
    resolved = registry.resolve(outer, **options)
    assert resolved.actor_id == actor.actor_id and resolved.wire()["kind"] == "workload"
    for field, value in [
        ("path", "/other"),
        ("peer", "spiffe://wrong"),
        ("body_digest", "c" * 64),
        ("operation_id", str(uuid4())),
    ]:
        with pytest.raises(ManualError):
            registry.resolve(outer, **{**options, field: value})
    assert (
        hashlib.sha256(canonical(registry.definitions[0].unsigned())).hexdigest()
        == actor.duty_artifact_digest
    )
