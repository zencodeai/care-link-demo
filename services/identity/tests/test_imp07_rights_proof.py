"""Real identity ceremony rules using only the explicit synthetic provider fixture."""

from dataclasses import replace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from care_link_domain import ManualError
from care_link_identity import IdentityError, stepup
from care_link_identity.crypto import digest
from care_link_identity.manual import ManualIdentityAuthority
from care_link_identity.manual_runtime import PREFIX, create_manual_identity_app
from conftest import signed_in
from fastapi.testclient import TestClient


def callback(service, ceremony):
    state = parse_qs(urlsplit(ceremony["authorization_url"]).query)["state"][0]
    _view, raw, proof = service.callback(state, "fresh-synthetic-code", "test-binding")
    assert raw is not None and proof is not None
    return raw, {
        "ceremony_id": ceremony["ceremony_id"],
        "proof_intent_id": proof,
        "expected_revision": "1",
    }


def begin(identity, kind="export"):
    service = identity[0]
    raw = signed_in(service)
    request = {"purpose": kind, "resource_id": str(uuid4()), "expected_revision": "1"}
    ceremony = stepup.start(service, raw, "test-binding", request)
    raw, confirmation = callback(service, ceremony)
    assert stepup.confirm(service, raw, confirmation)["state"] == "cooling_off"
    return raw, request, ceremony


def verified(identity, kind="export"):
    raw, request, ceremony = begin(identity, kind)
    identity[3].advance(301)
    ceremony = stepup.start(identity[0], raw, "test-binding", request)
    raw, confirmation = callback(identity[0], ceremony)
    assert stepup.confirm(identity[0], raw, confirmation)["state"] == "verified"
    authority = ManualIdentityAuthority(identity[0])
    return authority, authority.authenticate(raw), ceremony["ceremony_id"], request["resource_id"]


@pytest.mark.parametrize("kind", ["export", "delete"])
def test_exact_second_proof_and_scope_required(identity, kind):
    authority, actor, proof, subject = verified(identity, kind)
    authority.rights_proof(actor, proof, subject, kind)
    # This is a current evidence read. Gateway uniqueness and download consumption
    # remain in the data transaction, rather than consuming authority on preflight.
    authority.rights_proof(actor, proof, subject, kind)
    with pytest.raises(ManualError, match="rights_proof_required"):
        authority.rights_proof(actor, proof, str(uuid4()), kind)
    with pytest.raises(ManualError, match="rights_proof_required"):
        authority.rights_proof(actor, proof, subject, "delete" if kind == "export" else "export")
    if kind == "export":
        authority.rights_download_proof(actor, proof, subject)
    else:
        with pytest.raises(ManualError, match="rights_proof_required"):
            authority.rights_download_proof(actor, proof, subject)


def test_one_mfa_and_cooling_clock_do_not_authorize_rights(identity):
    raw, request, ceremony = begin(identity)
    authority = ManualIdentityAuthority(identity[0])
    for seconds in (0, 301):
        identity[3].advance(seconds)
        actor = authority.authenticate(raw)
        with pytest.raises(ManualError, match="rights_proof_required"):
            authority.rights_proof(actor, ceremony["ceremony_id"], request["resource_id"], "export")


def test_second_authentication_before_cooling_and_replayed_confirmation_rejected(identity):
    raw, request, ceremony = begin(identity)
    # Another tab can start a new ceremony but cannot skip this one's cooling.
    second_tab = stepup.start(identity[0], raw, "test-binding", request)
    assert second_tab["ceremony_id"] != ceremony["ceremony_id"]
    identity[3].advance(301)
    resumed = stepup.start(identity[0], raw, "test-binding", request)
    assert resumed["ceremony_id"] == ceremony["ceremony_id"]
    raw, confirmation = callback(identity[0], resumed)
    with identity[1].transaction() as tx:
        reference = tx.get("intent", confirmation["proof_intent_id"])
        proof = tx.get("intent", reference["state_hash"])
        proof["proof_auth_time"] = ceremony["not_before"]
        # The original start response precedes the cooling timestamp.
        tx.put("intent", reference["state_hash"], proof)
    with pytest.raises(IdentityError):
        stepup.confirm(identity[0], raw, confirmation)


@pytest.mark.parametrize("alter", ["expired", "future", "factors", "revision", "actor", "first"])
def test_stale_or_malformed_al3_evidence_fails_closed(identity, alter):
    authority, actor, proof_id, subject = verified(identity)
    if alter == "expired":
        identity[3].advance(301)
    elif alter == "actor":
        actor = replace(actor, account_id=str(uuid4()))
    else:
        with identity[1].transaction() as tx:
            ceremony = tx.get("ceremony", proof_id)
            if alter == "future":
                ceremony["verified_auth_time"] = "2099-01-01T00:00:00Z"
            elif alter == "factors":
                ceremony["verified_factors"] = []
            elif alter == "revision":
                ceremony["expected_revision"] = "2"
            elif alter == "first":
                ceremony["verified_proof"] = ceremony["first_proof"]
            tx.put("ceremony", proof_id, ceremony)
    with pytest.raises(ManualError, match="rights_proof_required"):
        authority.rights_proof(actor, proof_id, subject, "export")


def test_unrelated_general_mfa_and_old_browser_session_do_not_prove_rights(identity):
    authority, actor, proof, subject = verified(identity)
    unrelated = authority.authenticate(signed_in(identity[0]))
    assert unrelated.mfa
    with pytest.raises(ManualError, match="rights_proof_required"):
        authority.rights_proof(unrelated, proof, subject, "export")
    with identity[1].transaction() as tx:
        session = tx.get("session", digest(actor.credential_ref))
        session["mfa"] = False
        tx.put("session", digest(actor.credential_ref), session)
    with pytest.raises(ManualError, match="rights_proof_required"):
        authority.rights_proof(actor, proof, subject, "export")


def test_remote_rights_proof_checks_data_workload_exact_fields_and_deadline(identity):
    _authority, actor, proof, subject = verified(identity)
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
            "action": "rights_create",
            "request_digest": "a" * 64,
            "nonce": str(uuid4()),
            "resource_id": subject,
        },
        headers={"x-test-peer": "core"},
    )
    assert response.status_code == 200
    request = {
        "credential_ref": response.json()["id"],
        "ceremony_id": proof,
        "subject_id": subject,
        "kind": "export",
    }
    assert (
        client.post(
            PREFIX + "rights-proof", json=request, headers={"x-test-peer": "core"}
        ).status_code
        == 403
    )
    for name in ("rights-proof", "rights-download-proof"):
        arguments = (
            request if name == "rights-proof" else {k: v for k, v in request.items() if k != "kind"}
        )
        result = client.post(PREFIX + name, json=arguments, headers={"x-test-peer": "data"})
        assert result.status_code == 200 and result.json() == {"verified": True}
        assert actor.credential_ref not in result.text
        assert (
            client.post(
                PREFIX + name, json={**arguments, "role": "pid"}, headers={"x-test-peer": "data"}
            ).status_code
            == 422
        )
    identity[3].advance(1)
    assert (
        client.post(
            PREFIX + "rights-proof", json=request, headers={"x-test-peer": "data"}
        ).status_code
        == 403
    )


def test_confirmed_second_proof_cannot_be_confirmed_again(identity):
    raw, request, ceremony = begin(identity)
    identity[3].advance(301)
    resumed = stepup.start(identity[0], raw, "test-binding", request)
    raw, confirmation = callback(identity[0], resumed)
    assert stepup.confirm(identity[0], raw, confirmation)["state"] == "verified"
    with pytest.raises(IdentityError):
        stepup.confirm(identity[0], raw, confirmation)
    assert ceremony["ceremony_id"] == resumed["ceremony_id"]


def test_provider_revocation_blocks_current_rights_evidence(identity):
    authority, actor, proof, subject = verified(identity)
    identity[2].is_active = False
    with pytest.raises(ManualError):
        authority.rights_proof(actor, proof, subject, "export")
