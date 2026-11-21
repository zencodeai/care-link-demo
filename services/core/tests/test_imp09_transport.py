"""Recovery browser parsing and authority boundaries, without live promotion."""

import json
from pathlib import Path
from unittest.mock import create_autospec
from uuid import uuid4

import pytest
from care_link_core.recovery_app import create_recovery_app
from care_link_core.recovery_routes import ROUTES, RecoveryGateway
from fastapi.testclient import TestClient
from test_manual_transport import Security

ROOT = Path(__file__).resolve().parents[3]


def example(name):
    rows = json.loads((ROOT / "doc/LLD/contracts/fixtures.json").read_text())["fixtures"]
    return next(row["value"] for row in rows if row["id"] == "shape-" + name)


@pytest.fixture
def surface():
    gateway = create_autospec(RecoveryGateway, instance=True)
    return TestClient(
        create_recovery_app(gateway, Security()), base_url="https://app.test"
    ), gateway


@pytest.mark.parametrize("action,path,verb,contract,output,resource", ROUTES)
def test_recovery_closed_authenticated_transport(
    surface, action, path, verb, contract, output, resource
):
    client, gateway = surface
    path = "/v1/recovery" + path
    if resource:
        path = path.replace("{" + resource + "}", str(uuid4()))
    headers = {
        "Origin": "https://app.test",
        "X-CSRF-Token": "csrf",
        "Idempotency-Key": str(uuid4()),
    }
    gateway.execute.return_value = example(output)
    if verb == "POST":
        data = example(contract)
        assert client.post(path, json=data).status_code == 403
        assert (
            client.post(path, json={**data, "approved": True}, headers=headers).status_code == 422
        )
        assert client.post(
            path,
            content='{"expected_revision":"1","expected_revision":"1"}',
            headers={**headers, "Content-Type": "application/json"},
        ).status_code in {400, 422}
        gateway.execute.assert_not_called()
        response = client.post(path, json=data, headers=headers)
    else:
        response = client.get(path, headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert gateway.execute.call_args.args[0] == action
    count = gateway.execute.call_count
    assert client.request(verb, path + "?approved=true", headers=headers).status_code == 400
    assert gateway.execute.call_count == count


def test_recovery_never_exposes_manual_service_or_unauthenticated_health(surface):
    client, _ = surface
    assert client.get("/v1/workforce/queue").status_code == 404
    assert client.get("/docs").status_code == 404
    assert (
        client.get(
            "/v1/recovery/backups/" + str(uuid4()), headers={"Authorization": "denied"}
        ).status_code
        == 401
    )


def test_generation_fence_denies_browser_before_gateway_effect():
    from care_link_core.manual_app import create_manual_app
    from care_link_core.manual_channels import ManualChannels
    from care_link_core.manual_ports import ManualGateway
    from care_link_domain import ManualError

    gateway = create_autospec(ManualGateway, instance=True)

    def admission():
        raise ManualError("recovery.generation_fenced", 503)

    client = TestClient(
        create_manual_app(gateway, Security(), ManualChannels(), generation_admission=admission)
    )
    result = client.get("/v1/workforce/queue")
    assert result.status_code == 503
    gateway.queue_list.assert_not_called()


def test_help_import_requires_current_workload_not_browser_fields():
    from care_link_core.help_reconcile import HelpReconciler
    from care_link_core.manual_app import create_manual_app
    from care_link_core.manual_channels import ManualChannels
    from care_link_core.manual_ports import ManualGateway

    importer = create_autospec(HelpReconciler, instance=True)
    importer.reconcile.return_value = example("CommandResult")
    allowed = [False]
    client = TestClient(
        create_manual_app(
            create_autospec(ManualGateway, instance=True),
            Security(),
            ManualChannels(),
            help_reconciler=importer,
            help_verify=lambda request: allowed[0],
        )
    )
    data = example("HelpReconcile")
    headers = {"Idempotency-Key": str(uuid4())}
    assert client.post("/internal/v1/help/reconcile", json=data, headers=headers).status_code == 403
    importer.reconcile.assert_not_called()
    allowed[0] = True
    assert (
        client.post(
            "/internal/v1/help/reconcile", json={**data, "role": "help"}, headers=headers
        ).status_code
        == 422
    )
    assert client.post("/internal/v1/help/reconcile", json=data, headers=headers).status_code == 200
