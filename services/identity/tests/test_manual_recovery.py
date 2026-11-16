"""Identity recovery behavior with declared provider/store fixtures, not live IdP evidence."""

from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from care_link_domain import ManualError
from care_link_identity import stepup
from care_link_identity.manual import ManualIdentityAuthority, start_recovery
from conftest import signed_in


def ceremony(identity):
    service, _store, _provider, _clock, _key = identity
    raw = signed_in(service)
    session_id, family_id = str(uuid4()), str(uuid4())
    result = start_recovery(
        service,
        raw,
        "test-binding",
        {"session_id": session_id, "family_id": family_id, "expected_revision": "1"},
    )
    state = parse_qs(urlsplit(result["authorization_url"]).query)["state"][0]
    _view, replacement, proof_id = service.callback(state, "fresh-code", "test-binding")
    assert replacement and proof_id
    stepup.confirm(
        service,
        replacement,
        {
            "ceremony_id": result["ceremony_id"],
            "proof_intent_id": proof_id,
            "expected_revision": "1",
        },
    )
    authority = ManualIdentityAuthority(service)
    return (
        authority,
        authority.authenticate(replacement),
        result["ceremony_id"],
        session_id,
        family_id,
    )


def test_recovery_proof_binds_exact_family_and_is_consumed_once(identity):
    authority, actor, proof, session_id, family_id = ceremony(identity)
    with pytest.raises(ManualError):
        authority.recovery_proof(actor, proof, session_id, str(uuid4()))
    authority.recovery_proof(actor, proof, session_id, family_id)
    with pytest.raises(ManualError):
        authority.recovery_proof(actor, proof, session_id, family_id)


def test_recovery_rechecks_live_provider_before_consuming(identity):
    authority, actor, proof, session_id, family_id = ceremony(identity)
    identity[2].is_active = False
    with pytest.raises(ManualError):
        authority.recovery_proof(actor, proof, session_id, family_id)
