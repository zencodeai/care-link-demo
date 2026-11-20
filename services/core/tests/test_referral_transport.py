"""Direct actor transport rejects forged scope, ambiguous requests and CSRF."""

import json
from pathlib import Path
from unittest.mock import create_autospec
from uuid import uuid4

import pytest
from care_link_core.manual_app import create_manual_app
from care_link_core.manual_channels import ManualChannels
from care_link_core.manual_ports import ManualGateway
from care_link_core.referral_ports import ReceiverGateway, ReferralGateway
from fastapi.testclient import TestClient
from test_manual_transport import Security

ROOT = Path(__file__).resolve().parents[3]


def example(name):
    fixtures = json.loads((ROOT / "doc/LLD/contracts/fixtures.json").read_text())
    entries = fixtures if isinstance(fixtures, list) else fixtures["fixtures"]
    return next(row["value"] for row in entries if row["id"] == "shape-" + name)


@pytest.fixture
def surface():
    gateway = create_autospec(ReferralGateway, instance=True)
    receiver = create_autospec(ReceiverGateway, instance=True)
    security = Security()
    client = TestClient(
        create_manual_app(
            create_autospec(ManualGateway, instance=True),
            security,
            ManualChannels(),
            referrals=gateway,
            receiver=receiver,
        ),
        base_url="https://app.test",
    )
    return client, gateway, receiver


def test_referral_requires_current_auth_csrf_canonical_key_and_strict_body(surface):
    client, gateway, _ = surface
    sid = str(uuid4())
    data = example("ReferralDraftCreate")
    path = f"/v1/sessions/{sid}/referrals"
    headers = {
        "Origin": "https://app.test",
        "X-CSRF-Token": "csrf",
        "Idempotency-Key": str(uuid4()),
    }
    assert (
        client.post(path, json=data, headers={**headers, "Authorization": "denied"}).status_code
        == 401
    )
    assert client.post(path, json=data).status_code == 403
    assert (
        client.post(path, json=data, headers={**headers, "Idempotency-Key": "invalid"}).status_code
        == 400
    )
    assert client.post(path, json={**data, "authorized": True}, headers=headers).status_code == 422
    assert client.post(path + "?role=worker", json=data, headers=headers).status_code == 400
    gateway.referral_draft.assert_not_called()
    gateway.referral_draft.return_value = example("ReferralView")
    result = client.post(path, json=data, headers=headers)
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert gateway.referral_draft.call_args.args[3] == sid


def test_receiver_decision_uses_independent_port_and_exact_target(surface):
    client, gateway, receiver = surface
    data = example("ReceiverDecision")
    headers = {
        "Origin": "https://app.test",
        "X-CSRF-Token": "csrf",
        "Idempotency-Key": str(uuid4()),
    }
    mismatch = client.post(f"/v1/receiver/packages/{uuid4()}/decision", json=data, headers=headers)
    assert mismatch.status_code == 422
    receiver.receiver_decide.assert_not_called()
    receiver.receiver_decide.return_value = example("ReceiptView")
    result = client.post(
        f"/v1/receiver/packages/{data['dispatch_id']}/decision", json=data, headers=headers
    )
    assert result.status_code == 200
    receiver.receiver_decide.assert_called_once()
    gateway.referral_dispatch.assert_not_called()


@pytest.mark.parametrize(
    "query", ["limit=01", "limit=51", "limit=1&limit=2", "service_id=x", "cursor="]
)
def test_receiver_inbox_rejects_ambiguous_or_unbounded_scope(surface, query):
    client, _, receiver = surface
    assert client.get("/v1/receiver/inbox?" + query).status_code in {400, 422}
    receiver.receiver_inbox.assert_not_called()


def test_pending_send_is_explicit_and_unknown_is_preserved(surface):
    client, gateway, _ = surface
    dispatch = example("DispatchView")
    dispatch["state"] = "unknown"
    gateway.dispatcher_send.return_value = dispatch
    headers = {
        "Origin": "https://app.test",
        "X-CSRF-Token": "csrf",
        "Idempotency-Key": str(uuid4()),
    }
    result = client.post(
        f"/v1/dispatches/{dispatch['dispatch_id']}/send",
        json={"expected_revision": "1"},
        headers=headers,
    )
    assert result.status_code == 200
    assert result.json()["state"] == "unknown"
    gateway.referral_dispatch.assert_not_called()
