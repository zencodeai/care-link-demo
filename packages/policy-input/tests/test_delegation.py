"""Signature/binding tests with declared signing keys and current identity fixture."""

import base64
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from care_link_domain import Actor, ManualError
from care_link_policy_input import DelegationVerifier
from care_link_policy_input.opa import canonical
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def sample():
    now = datetime.now(UTC)
    actor = Actor(
        str(uuid4()),
        "pid",
        1,
        1,
        now,
        False,
        "a" * 64,
        7,
        "identity-proof-reference",
        now + timedelta(minutes=1),
        str(uuid4()),
    )
    core_key, identity_key = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    operation, nonce, sid = str(uuid4()), str(uuid4()), str(uuid4())
    args = {"expected_revision": "1", "reason": "user_requested"}
    paths = {"session_id": sid}
    digest = hashlib.sha256(canonical({"arguments": args, "path_arguments": paths})).hexdigest()

    def sign(key, value):
        return {
            **value,
            "signature": base64.urlsafe_b64encode(key.sign(canonical(value))).rstrip(b"=").decode(),
        }

    evidence = sign(
        identity_key,
        {
            "id": actor.identity_evidence_id,
            "principal_id": actor.account_id,
            "role": "pid",
            "identity_revision": "1",
            "role_revision": "1",
            "action": "session_human_request",
            "resource_id": sid,
            "request_digest": digest,
            "nonce": nonce,
            "verified_at": now.isoformat().replace("+00:00", "Z"),
            "expires_at": (now + timedelta(seconds=0.9)).isoformat().replace("+00:00", "Z"),
            "kind": "human_identity",
        },
    )
    delegation = sign(
        core_key,
        {
            "id": operation,
            "actor": {
                "kind": "human",
                "principal_id": actor.account_id,
                "workload_id": "spiffe://care-link.demo/demo/core",
                "role": "pid",
                "assurance": "AL1",
                "identity_evidence_id": actor.identity_evidence_id,
                "task_id": None,
                "job_id": None,
            },
            "evidence": evidence,
            "scope": {
                "session_id": sid,
                "subject_id": None,
                "purpose": "support",
                "fields": [],
                "recipient_id": None,
            },
            "audience": "care-link-data",
            "method": "POST",
            "path": "/internal/v1/data/session_human_request",
            "body_digest": digest,
            "nonce": nonce,
            "expires_at": evidence["expires_at"],
        },
    )
    verifier = DelegationVerifier(
        core_key.public_key(), identity_key.public_key(), lambda _: actor, clock=lambda: now
    )
    return (
        verifier,
        {"arguments": args, "path_arguments": paths, "delegation": delegation},
        operation,
        actor,
    )


def test_signed_request_resolves_current_identity_not_serialized_claims():
    verifier, envelope, key, actor = sample()
    verified = verifier.verify(
        envelope, "session_human_request", key, "/internal/v1/data/session_human_request"
    )
    assert verified.account_id == actor.account_id
    assert verified.request_deadline is not None
    verifier.current_identity = lambda _: replace(actor, identity_revision=2)
    with pytest.raises(ManualError):
        verifier.verify(
            envelope, "session_human_request", key, "/internal/v1/data/session_human_request"
        )


@pytest.mark.parametrize("change", ["payload", "path", "key", "scope", "signature", "expired"])
def test_changed_payload_target_scope_signature_or_expired_receipt_denies(change):
    verifier, envelope, key, actor = sample()
    path = "/internal/v1/data/session_human_request"
    if change == "payload":
        envelope["arguments"]["reason"] = "fixture_escalation"
    elif change == "path":
        path = "/internal/v1/data/session_end"
    elif change == "key":
        key = str(uuid4())
    elif change == "scope":
        envelope["delegation"]["scope"]["session_id"] = str(uuid4())
    elif change == "signature":
        envelope["delegation"]["signature"] = "a" * 86
    elif change == "expired":
        verifier.clock = lambda: datetime.now(UTC) + timedelta(seconds=2)
    with pytest.raises(ManualError):
        verifier.verify(envelope, "session_human_request", key, path)


def test_delayed_current_identity_cannot_extend_signed_request_deadline():
    verifier, envelope, key, actor = sample()
    original = verifier.clock()
    advanced = [original]
    verifier.clock = lambda: advanced[0]

    def slow_current(_evidence):
        advanced[0] += timedelta(seconds=2)
        return actor

    verifier.current_identity = slow_current
    with pytest.raises(ManualError, match="delegation_denied"):
        verifier.verify(
            envelope, "session_human_request", key, "/internal/v1/data/session_human_request"
        )
