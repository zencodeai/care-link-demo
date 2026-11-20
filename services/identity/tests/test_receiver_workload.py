"""Receiver gets only independently resolved current identity, never grantor powers."""

from care_link_identity.manual_runtime import create_manual_identity_app
from fastapi.testclient import TestClient
from test_manual_runtime import evidence, post, setup


def test_receiver_identity_routes_are_explicitly_opted_in_and_minimized(identity):
    old, raw, _ = setup(identity)
    proof = evidence(old, raw)
    assert post(old, "resolve", {"evidence": proof}, "receiver").status_code == 403
    client = TestClient(
        create_manual_identity_app(
            identity[0],
            lambda request, peer: request.headers.get("x-test-peer") == peer,
            receiver_enabled=True,
        )
    )
    resolved = post(client, "resolve", {"evidence": proof}, "receiver")
    assert resolved.status_code == 200
    assert (
        post(
            client, "current", {"credential_ref": resolved.json()["credential_ref"]}, "receiver"
        ).status_code
        == 200
    )
    for name in ("recovery", "consent-proof", "authenticate", "evidence", "csrf"):
        assert post(client, name, {}, "receiver").status_code == 403
