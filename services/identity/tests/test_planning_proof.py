"""Exact subject/action MFA proof with real identity use cases and provider fixture."""

from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from care_link_domain import ManualError
from care_link_identity import stepup
from care_link_identity.manual import ManualIdentityAuthority
from care_link_identity.manual_runtime import PREFIX, create_manual_identity_app
from conftest import signed_in
from fastapi.testclient import TestClient


def ceremony(identity, *, purpose="plan_edit", confirm=True):
    service = identity[0]
    raw = signed_in(service)
    subject = str(uuid4())
    proof = stepup.start(
        service,
        raw,
        "test-binding",
        {
            "purpose": purpose,
            "resource_id": subject,
            "expected_revision": "1",
        },
    )
    state = parse_qs(urlsplit(proof["authorization_url"]).query)["state"][0]
    _view, replacement, proof_intent = service.callback(state, "fresh-code", "test-binding")
    assert replacement is not None
    if confirm:
        stepup.confirm(
            service,
            replacement,
            {
                "ceremony_id": proof["ceremony_id"],
                "proof_intent_id": proof_intent,
                "expected_revision": "1",
            },
        )
    authority = ManualIdentityAuthority(service)
    return (
        authority,
        authority.authenticate(replacement),
        proof["ceremony_id"],
        subject,
        str(uuid4()),
    )


@pytest.mark.parametrize(
    "purpose,ceremony_purpose",
    [("plan", "plan_edit"), ("referral", "referral_consent"), ("follow_up", "follow_up_consent")],
)
def test_self_consent_uses_current_exact_subject_and_purpose(identity, purpose, ceremony_purpose):
    authority, actor, proof, subject, session = ceremony(identity, purpose=ceremony_purpose)
    authority.consent_proof(actor, proof, subject, session, purpose, "self")
    with pytest.raises(ManualError, match="consent_proof_required"):
        authority.consent_proof(actor, proof, str(uuid4()), session, purpose, "self")
    with pytest.raises(ManualError, match="consent_proof_required"):
        authority.consent_proof(actor, proof, subject, session, purpose, "explicit_demo_delegation")
    with pytest.raises(ManualError, match="consent_proof_required"):
        authority.consent_proof(
            actor, proof, subject, session, "referral" if purpose == "plan" else "plan", "self"
        )


def test_unconfirmed_and_stale_mfa_never_supply_consent_authority(identity):
    authority, actor, proof, subject, session = ceremony(identity, confirm=False)
    with pytest.raises(ManualError, match="consent_proof_required"):
        authority.consent_proof(actor, proof, subject, session, "plan", "self")
    authority, actor, proof, subject, session = ceremony(identity)
    identity[3].advance(301)
    with pytest.raises(ManualError, match="consent_proof_required"):
        authority.consent_proof(actor, proof, subject, session, "plan", "self")


def test_remote_consent_proof_requires_data_workload_and_short_lived_current_reference(identity):
    authority, actor, proof, subject, session = ceremony(identity)
    client = TestClient(
        create_manual_identity_app(
            identity[0], lambda request, peer: request.headers.get("x-test-peer") == peer
        )
    )
    response = client.post(
        PREFIX + "evidence",
        json={
            "raw_session": actor.credential_ref,
            "transport_generation": "1",
            "action": "consent_grant",
            "request_digest": "a" * 64,
            "nonce": str(uuid4()),
            "resource_id": session,
        },
        headers={"x-test-peer": "core"},
    )
    assert response.status_code == 200
    request = {
        "credential_ref": response.json()["id"],
        "proof_id": proof,
        "subject_id": subject,
        "session_id": session,
        "purpose": "plan",
        "basis": "self",
    }
    assert (
        client.post(
            PREFIX + "consent-proof", json=request, headers={"x-test-peer": "core"}
        ).status_code
        == 403
    )
    accepted = client.post(PREFIX + "consent-proof", json=request, headers={"x-test-peer": "data"})
    assert accepted.status_code == 200 and accepted.json() == {"verified": True}
    assert actor.credential_ref not in accepted.text
    identity[3].advance(1)
    assert (
        client.post(
            PREFIX + "consent-proof", json=request, headers={"x-test-peer": "data"}
        ).status_code
        == 403
    )
    del authority
