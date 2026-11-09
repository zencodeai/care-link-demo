"""Restrictive signal ordering, signature and replay behavior."""

import base64
import hashlib
from uuid import uuid4

import pytest
from care_link_contracts import validate_contract
from care_link_identity import IdentityError, SignalReceiver
from care_link_identity.crypto import canonical
from care_link_identity.domain import stamp
from conftest import signed_in

pytestmark = pytest.mark.unit


def make_signal(identity, sequence="1", previous="0" * 64, jti=None):
    service, store, _provider, clock, key = identity
    account = next(value for (kind, _key), value in store.records.items() if kind == "account")
    event = {
        "issuer_id": "local-provider-signals",
        "audience": "care-link-identity",
        "jti": jti or str(uuid4()),
        "subject_id": account["account_id"],
        "event_type": "credential_revoked",
        "source_sequence": sequence,
        "previous_digest": previous,
        "event_at": stamp(clock()),
    }
    event["digest"] = hashlib.sha256(canonical(event)).hexdigest()
    event["signature"] = base64.urlsafe_b64encode(key.sign(canonical(event))).rstrip(b"=").decode()
    receiver = SignalReceiver(
        store,
        "local-provider-signals",
        "care-link-identity",
        key.public_key(),
        service.issuer,
        clock,
    )
    return receiver, event


def test_signed_revoke_durable_duplicate_and_no_regrant(identity):
    service, _store, _provider, _clock, _key = identity
    raw = signed_in(service)
    receiver, event = make_signal(identity)
    result = receiver.ingest(event)
    validate_contract("SignalAck", result)
    assert result["state"] == "applied"
    assert receiver.ingest(event)["state"] == "duplicate"
    with pytest.raises(IdentityError):
        service.current(raw)


def test_sequence_gap_blocks_account_without_advancing_ack(identity):
    service, _store, _provider, _clock, _key = identity
    raw = signed_in(service)
    receiver, event = make_signal(identity, sequence="3")
    result = receiver.ingest(event)
    assert result["state"] == "gap_blocked" and result["accepted_sequence"] == "0"
    with pytest.raises(IdentityError):
        service.current(raw)


def test_jti_reuse_with_other_signed_digest_quarantines(identity):
    receiver, first = make_signal(identity)
    assert receiver.ingest(first)["state"] == "applied"
    _receiver, other = make_signal(
        identity, sequence="2", previous=first["digest"], jti=first["jti"]
    )
    assert receiver.ingest(other)["state"] == "quarantined"


@pytest.mark.parametrize(
    "field,value",
    [("signature", "invalid"), ("digest", "f" * 64), ("issuer_id", "wrong"), ("audience", "wrong")],
)
def test_forged_signal_cannot_fence_or_ack(identity, field, value):
    receiver, event = make_signal(identity)
    event[field] = value
    with pytest.raises(IdentityError):
        receiver.ingest(event)


def test_expired_authenticated_signal_fences_pending_snapshot_recovery(identity):
    service, _store, _provider, clock, _key = identity
    raw = signed_in(service)
    receiver, event = make_signal(identity)
    clock.advance(61)
    assert receiver.ingest(event)["state"] == "gap_blocked"
    with pytest.raises(IdentityError):
        service.current(raw)


def test_unauthenticated_expired_signal_cannot_fence(identity):
    service, _store, _provider, clock, _key = identity
    raw = signed_in(service)
    receiver, event = make_signal(identity)
    event["signature"] = "invalid"
    clock.advance(61)
    with pytest.raises(IdentityError):
        receiver.ingest(event)
    assert service.current(raw)


def test_workload_compromise_cannot_mutate_coincident_account_uuid(identity):
    service, store, _provider, _clock, key = identity
    raw = signed_in(service)
    receiver, event = make_signal(identity)
    event["event_type"] = "workload_compromised"
    content = {k: v for k, v in event.items() if k not in {"digest", "signature"}}
    event["digest"] = hashlib.sha256(canonical(content)).hexdigest()
    event["signature"] = (
        base64.urlsafe_b64encode(
            key.sign(canonical({k: v for k, v in event.items() if k != "signature"}))
        )
        .rstrip(b"=")
        .decode()
    )
    before = dict(store.records)
    with pytest.raises(IdentityError):
        receiver.ingest(event)
    assert store.records == before
    assert service.current(raw)
