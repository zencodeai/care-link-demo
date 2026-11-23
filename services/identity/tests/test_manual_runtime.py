"""Remote identity wire tests; explicit provider/store fixtures, not live IdP claims."""

import copy
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from care_link_identity import stepup
from care_link_identity.manual import start_recovery
from care_link_identity.manual_runtime import PREFIX, create_manual_identity_app
from conftest import signed_in
from fastapi.testclient import TestClient


def setup(identity):
    service = identity[0]
    raw = signed_in(service)
    calls = []

    def verifier(request, role):
        calls.append((request.url.path, role))
        return request.headers.get("x-test-peer") == role

    client = TestClient(create_manual_identity_app(service, verifier))
    return client, raw, calls


def post(client, name, data, peer="core"):
    return client.post(PREFIX + name, json=data, headers={"x-test-peer": peer})


def evidence(client, raw):
    response = post(
        client,
        "evidence",
        {
            "raw_session": raw,
            "transport_generation": "17",
            "action": "session_read",
            "request_digest": "a" * 64,
            "nonce": str(uuid4()),
            "resource_id": str(uuid4()),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_authenticate_and_csrf_use_current_provider(identity):
    client, raw, calls = setup(identity)
    response = post(client, "authenticate", {"raw_session": raw})
    assert response.status_code == 200
    assert identity[2].active_checks == 1
    csrf = identity[0].current(raw)["csrf"]
    assert (
        post(
            client, "csrf", {"raw_session": raw, "origin": "https://app.test", "supplied": csrf}
        ).status_code
        == 200
    )
    assert (
        post(
            client, "csrf", {"raw_session": raw, "origin": "https://other.test", "supplied": csrf}
        ).status_code
        == 403
    )
    assert calls[0] == (PREFIX + "authenticate", "core")
    identity[2].is_active = False
    assert post(client, "authenticate", {"raw_session": raw}).status_code == 503


def test_workload_role_cannot_cross_identity_route(identity):
    client, raw, _calls = setup(identity)
    assert post(client, "authenticate", {"raw_session": raw}, "data").status_code == 403
    assert post(client, "current", {"credential_ref": raw}, "core").status_code == 403


def test_evidence_resolves_to_private_short_lived_reference_and_current_provider(identity):
    client, raw, _calls = setup(identity)
    value = evidence(client, raw)
    response = post(client, "resolve", {"evidence": value}, "data")
    assert response.status_code == 200
    actor = response.json()
    assert actor["credential_ref"] == value["id"] != raw
    assert actor["transport_generation"] == "17"
    assert actor["request_deadline"] == value["expires_at"]
    assert raw not in response.text
    stored = identity[1].get("proof", value["id"])
    assert stored["credential"] != raw
    assert raw not in str(stored)
    current = post(client, "current", {"credential_ref": value["id"]}, "data")
    assert current.status_code == 200
    assert current.json()["request_deadline"] == actor["request_deadline"]
    identity[2].is_active = False
    assert post(client, "current", {"credential_ref": value["id"]}, "data").status_code == 503


@pytest.mark.parametrize("change", ["revision", "resource", "signature"])
def test_mutated_evidence_cannot_resolve(identity, change):
    client, raw, _calls = setup(identity)
    value = copy.deepcopy(evidence(client, raw))
    if change == "revision":
        value["identity_revision"] = "2"
    elif change == "resource":
        value["resource_id"] = str(uuid4())
    else:
        value["signature"] = "a" * 86
    assert post(client, "resolve", {"evidence": value}, "data").status_code == 403


def test_request_reference_cannot_extend_deadline_or_survive_revision(identity):
    client, raw, _calls = setup(identity)
    value = evidence(client, raw)
    identity[3].advance(1)
    assert post(client, "current", {"credential_ref": value["id"]}, "data").status_code == 403
    value = evidence(client, raw)
    # Simulate a durable account revision change after receipt creation.
    with identity[1].transaction() as tx:
        for key, account in tx.items("account"):
            account["revision"] = "2"
            tx.put("account", key, account)
    assert post(client, "resolve", {"evidence": value}, "data").status_code in {401, 403}


def test_provider_delay_past_original_evidence_expiry_denies(identity):
    client, raw, _calls = setup(identity)
    value = evidence(client, raw)
    identity[2].on_active = lambda: identity[3].advance(1)
    assert post(client, "resolve", {"evidence": value}, "data").status_code == 403


def test_duplicate_or_extra_fields_never_reach_provider(identity):
    client, raw, _calls = setup(identity)
    checks = identity[2].active_checks
    response = client.post(
        PREFIX + "authenticate",
        content='{"raw_session":"one","raw_session":"two"}',
        headers={"content-type": "application/json", "x-test-peer": "core"},
    )
    assert response.status_code == 422
    assert (
        post(client, "authenticate", {"raw_session": raw, "role": "supervisor"}).status_code == 422
    )
    assert identity[2].active_checks == checks


def test_remote_recovery_consumes_exact_fresh_ceremony_once(identity):
    client, raw, _calls = setup(identity)
    service = identity[0]
    sid, fid = str(uuid4()), str(uuid4())
    ceremony = start_recovery(
        service,
        raw,
        "test-binding",
        {"session_id": sid, "family_id": fid, "expected_revision": "1"},
    )
    state = parse_qs(urlsplit(ceremony["authorization_url"]).query)["state"][0]
    _view, replacement, proof_id = service.callback(state, "fresh-code", "test-binding")
    stepup.confirm(
        service,
        replacement,
        {
            "ceremony_id": ceremony["ceremony_id"],
            "proof_intent_id": proof_id,
            "expected_revision": "1",
        },
    )
    value = evidence(client, replacement)
    data = {
        "credential_ref": value["id"],
        "ceremony_id": ceremony["ceremony_id"],
        "session_id": sid,
        "family_id": fid,
    }
    assert post(client, "recovery", {**data, "family_id": str(uuid4())}, "data").status_code == 403
    assert post(client, "recovery", data, "data").status_code == 200
    assert post(client, "recovery", data, "data").status_code == 403


def test_training_identity_has_separate_short_lived_proof_custody(identity):
    service, store, provider, clock, _key = identity
    with store.transaction() as tx:
        for key, account in tx.items("account"):
            account["roles"] = [*account["roles"], "trainer"]
            tx.put("account", key, account)
    trainer = signed_in(service, "trainer")
    denied = TestClient(
        create_manual_identity_app(
            service, lambda request, peer: request.headers.get("x-test-peer") == peer
        )
    )
    enabled = TestClient(
        create_manual_identity_app(
            service,
            lambda request, peer: request.headers.get("x-test-peer") == peer,
            training_enabled=True,
            receiver_enabled=True,
        )
    )
    body = {
        "raw_session": trainer,
        "transport_generation": "1",
        "action": "scenario_read",
        "request_digest": "f" * 64,
        "nonce": str(uuid4()),
        "resource_id": str(uuid4()),
    }
    assert post(denied, "evidence", body).status_code == 403
    issued = post(enabled, "evidence", body)
    assert issued.status_code == 200, issued.text
    proof = issued.json()
    assert store.get("proof", proof["id"])["audience"] == "care-link-training"
    assert post(enabled, "resolve", {"evidence": proof}, "data").status_code == 403
    assert post(enabled, "resolve", {"evidence": proof}, "receiver").status_code == 403
    assert (
        post(enabled, "resolve", {"evidence": evidence(enabled, trainer)}, "training").status_code
        == 403
    )
    assert post(enabled, "resolve", {"evidence": proof}, "training").status_code == 200
    assert post(enabled, "current", {"credential_ref": proof["id"]}, "training").status_code == 200
    assert post(enabled, "rights-proof", {}, "training").status_code == 403
    provider.is_active = False
    assert post(enabled, "current", {"credential_ref": proof["id"]}, "training").status_code == 503
    provider.is_active = True
    clock.advance(1)
    assert post(enabled, "current", {"credential_ref": proof["id"]}, "training").status_code == 403
