"""Provider-derived MFA proof binds a single immutable recovery proposal."""

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from care_link_domain import ManualError
from care_link_identity import stepup
from care_link_identity.manual import ManualIdentityAuthority
from care_link_identity.promotion import consume_promotion_proof
from conftest import signed_in


def verified(identity):
    service, store, provider, clock, _ = identity
    with store.transaction() as tx:
        for key, row in tx.items("account"):
            row["roles"] = ["security"]
            tx.put("account", key, row)
    raw = signed_in(service, "security")
    proposal = str(uuid4())
    result = stepup.start(
        service,
        raw,
        "test-binding",
        {"purpose": "promotion", "resource_id": proposal, "expected_revision": "1"},
    )
    state = parse_qs(urlsplit(result["authorization_url"]).query)["state"][0]
    _, replacement, proof = service.callback(state, "fresh-code", "test-binding")
    assert replacement and proof
    stepup.confirm(
        service,
        replacement,
        {"ceremony_id": result["ceremony_id"], "proof_intent_id": proof, "expected_revision": "1"},
    )
    actor = ManualIdentityAuthority(service).authenticate(replacement)
    return actor, result["ceremony_id"], proposal, clock() + timedelta(seconds=120)


def test_promotion_binds_proposal_digest_and_expiry(identity):
    actor, ceremony, proposal, expiry = verified(identity)
    for wrong in [str(uuid4())]:
        with pytest.raises(ManualError):
            consume_promotion_proof(identity[0], actor, ceremony, wrong, "a" * 64, expiry)
    consume_promotion_proof(identity[0], actor, ceremony, proposal, "a" * 64, expiry)
    consume_promotion_proof(identity[0], actor, ceremony, proposal, "a" * 64, expiry)
    with pytest.raises(ManualError):
        consume_promotion_proof(identity[0], actor, ceremony, proposal, "b" * 64, expiry)
    with pytest.raises(ManualError):
        consume_promotion_proof(
            identity[0], actor, ceremony, proposal, "a" * 64, expiry + timedelta(seconds=1)
        )


def test_promotion_requires_current_provider_and_fresh_mfa(identity):
    actor, ceremony, proposal, expiry = verified(identity)
    identity[2].is_active = False
    with pytest.raises(ManualError):
        consume_promotion_proof(identity[0], actor, ceremony, proposal, "a" * 64, expiry)


def test_promotion_rejects_expiry_over_300_seconds(identity):
    actor, ceremony, proposal, _ = verified(identity)
    with pytest.raises(ManualError):
        consume_promotion_proof(
            identity[0], actor, ceremony, proposal, "a" * 64, identity[3]() + timedelta(seconds=301)
        )
