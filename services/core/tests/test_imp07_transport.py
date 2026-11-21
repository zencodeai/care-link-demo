"""Direct actor transport rejects forged scope, ambiguous requests and CSRF."""

import json
from pathlib import Path
from unittest.mock import create_autospec
from uuid import uuid4

import pytest
from care_link_core.manual_app import create_manual_app
from care_link_core.manual_channels import ManualChannels
from care_link_core.manual_ports import ManualGateway
from fastapi.testclient import TestClient
from test_manual_transport import Security

ROOT = Path(__file__).resolve().parents[3]


def example(name):
    fixtures = json.loads((ROOT / "doc/LLD/contracts/fixtures.json").read_text())
    entries = fixtures if isinstance(fixtures, list) else fixtures["fixtures"]
    return next(row["value"] for row in entries if row["id"] == "shape-" + name)


@pytest.fixture
def surface():
    from care_link_core.lifecycle_ports import LifecycleGateway

    gateway = create_autospec(LifecycleGateway, instance=True)
    security = Security()
    client = TestClient(
        create_manual_app(
            create_autospec(ManualGateway, instance=True),
            security,
            ManualChannels(),
            lifecycle=gateway,
        ),
        base_url="https://app.test",
    )
    return client, gateway


def test_rights_requires_auth_csrf_strict_body_and_operation_identity(surface):
    client, gateway = surface
    data = example("RightsCreate")
    headers = {
        "Origin": "https://app.test",
        "X-CSRF-Token": "csrf",
        "Idempotency-Key": str(uuid4()),
    }
    assert (
        client.post(
            "/v1/rights", json=data, headers={**headers, "Authorization": "denied"}
        ).status_code
        == 401
    )
    assert client.post("/v1/rights", json=data).status_code == 403
    assert (
        client.post(
            "/v1/rights", json=data, headers={**headers, "Idempotency-Key": "invalid"}
        ).status_code
        == 400
    )
    assert (
        client.post("/v1/rights", json={**data, "authorized": True}, headers=headers).status_code
        == 422
    )
    assert (
        client.post("/v1/rights?subject_id=forged", json=data, headers=headers).status_code == 400
    )
    gateway.rights_create.assert_not_called()
    gateway.rights_create.return_value = example("RightsView")
    reply = client.post("/v1/rights", json=data, headers=headers)
    assert reply.status_code == 200
    assert reply.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "query",
    [
        "limit=" + "9" * 5000,
        "limit=01",
        "limit=51",
        "limit=1&limit=2",
        "subject_id=x",
        "cursor=",
        "limit=+1",
        "limit=١",
    ],
)
def test_inbox_rejects_ambiguous_or_unbounded_query(surface, query):
    client, gateway = surface
    assert client.get("/v1/inbox?" + query).status_code in {400, 422}
    gateway.participant_inbox.assert_not_called()


def test_followup_cancel_preserves_inflight_status(surface):
    client, gateway = surface
    value = example("FollowUpView")
    value["state"] = "authorized"
    gateway.followup_cancel.return_value = value
    reply = client.post(
        f"/v1/follow-ups/{value['id']}/cancel",
        json={"expected_revision": "1"},
        headers={
            "Origin": "https://app.test",
            "X-CSRF-Token": "csrf",
            "Idempotency-Key": str(uuid4()),
        },
    )
    assert reply.status_code == 200
    assert reply.json()["state"] == "authorized"


def test_download_has_no_caller_supplied_permission_scope(surface):
    client, gateway = surface
    assert client.get(f"/v1/rights/{uuid4()}/download?authorized=true").status_code == 400
    gateway.export_download.assert_not_called()


def test_machine_lifecycle_cannot_be_called_through_human_bff(surface):
    client, _ = surface
    assert (
        client.post(
            "/internal/v1/lifecycle/due", json={"batch_limit": 100, "class": "session"}
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "action,contract,target,purpose",
    [
        ("followup_create", "FollowUpCreate", "session_id", "follow_up"),
        ("followup_bind_anchor", "FollowUpBindAnchor", "followup_id", "follow_up"),
        ("rights_create", "RightsCreate", None, "rights"),
        ("hold_create", "HoldCommand", None, "rights"),
    ],
)
def test_signed_metadata_and_final_target_cannot_be_substituted(action, contract, target, purpose):
    from test_manual_envelopes import fixture

    factory, current, verifier, _metadata, calls, *_rest = fixture()
    key = str(uuid4())
    data = example(contract)
    paths = {target: str(uuid4())} if target else {}
    envelope = factory.build(current, action, key, data, paths)
    metadata = json.loads(calls[0].content)
    assert metadata["planning"]["path_arguments"] == paths
    assert metadata["planning"]["arguments"] == data
    assert metadata["scope"]["purpose"] == purpose
    assert (
        verifier.verify(envelope, action, key, "/internal/v1/data/" + action).account_id
        == current.account_id
    )
    envelope["arguments"]["expected_revision"] = "99"
    from care_link_domain import ManualError

    with pytest.raises(ManualError, match="delegation_denied"):
        verifier.verify(envelope, action, key, "/internal/v1/data/" + action)
