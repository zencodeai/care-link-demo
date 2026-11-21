"""Governance browser boundary rejects forged scope and ambiguous request identity."""

import json
from pathlib import Path
from unittest.mock import create_autospec
from uuid import uuid4

import pytest
from care_link_core.governance_ports import GovernanceGateway
from care_link_core.manual_app import create_manual_app
from care_link_core.manual_channels import ManualChannels
from care_link_core.manual_ports import ManualGateway
from fastapi.testclient import TestClient
from test_manual_transport import Security

ROOT = Path(__file__).resolve().parents[3]


def example(name):
    entries = json.loads((ROOT / "doc/LLD/contracts/fixtures.json").read_text())["fixtures"]
    return next(row["value"] for row in entries if row["id"] == "shape-" + name)


@pytest.fixture
def surface():
    gateway = create_autospec(GovernanceGateway, instance=True)
    app = create_manual_app(
        create_autospec(ManualGateway, instance=True),
        Security(),
        ManualChannels(),
        governance=gateway,
    )
    return TestClient(app, base_url="https://app.test"), gateway


def headers():
    return {
        "Origin": "https://app.test",
        "X-CSRF-Token": "csrf",
        "Idempotency-Key": str(uuid4()),
    }


@pytest.mark.parametrize(
    "path,action,contract,output",
    [
        ("/v1/artifacts", "artifact_register", "ArtifactRegister", "ArtifactView"),
        ("/v1/artifacts/reviews", "artifact_review", "ArtifactReview", "CommandResult"),
        ("/v1/activations", "activation_create", "ActivationCreate", "ActivationView"),
        ("/v1/access/grants", "scoped_access_grant", "ScopeGrantCreate", "CommandResult"),
        ("/v1/audit/search", "audit_query", "AuditQuery", "AuditPage"),
        ("/v1/metrics/query", "metrics_query", "MetricsQuery", "MetricsView"),
    ],
)
def test_governance_commands_require_auth_csrf_closed_schema_and_key(
    surface, path, action, contract, output
):
    client, gateway = surface
    method = getattr(gateway, action)
    data = example(contract)
    assert client.post(path, json=data).status_code == 403
    assert (
        client.post(path, json=data, headers={**headers(), "Authorization": "denied"}).status_code
        == 401
    )
    assert client.post(path, json={**data, "approved": True}, headers=headers()).status_code == 422
    assert client.post(path + "?authorized=true", json=data, headers=headers()).status_code == 400
    method.assert_not_called()
    method.return_value = example(output)
    result = client.post(path, json=data, headers=headers())
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "query", ["limit=01", "limit=1&limit=2", "authorized=true", "limit=" + "9" * 5000]
)
def test_evidence_download_rejects_ambiguous_query(surface, query):
    client, gateway = surface
    result = client.get(f"/v1/audit/exports/{uuid4()}?{query}")
    assert result.status_code in {400, 422}
    gateway.audit_export_read.assert_not_called()


def test_enforcer_ack_never_enters_human_bff(surface):
    client, _gateway = surface
    assert (
        client.post(
            "/internal/v1/control/ack", json=example("ActivationAck"), headers=headers()
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "action,contract,target,purpose",
    [
        ("artifact_register", "ArtifactRegister", None, "governance"),
        ("artifact_review", "ArtifactReview", None, "governance"),
        ("activation_commit", "RevisionCommand", "activation_id", "governance"),
        ("incident_transition", "IncidentTransition", "incident_id", "security"),
        ("audit_query", "AuditQuery", None, "audit"),
        ("metrics_query", "MetricsQuery", None, "audit"),
    ],
)
def test_signed_metadata_binds_exact_governance_query_and_target(action, contract, target, purpose):
    from care_link_domain import ManualError
    from test_manual_envelopes import fixture

    factory, actor, verifier, _metadata, calls, *_ = fixture()
    key, data = str(uuid4()), example(contract)
    paths = {target: str(uuid4())} if target else {}
    envelope = factory.build(actor, action, key, data, paths)
    metadata = json.loads(calls[0].content)
    assert metadata["planning"]["arguments"] == data
    assert metadata["planning"]["path_arguments"] == paths
    assert metadata["scope"]["purpose"] == purpose
    assert (
        verifier.verify(envelope, action, key, "/internal/v1/data/" + action).account_id
        == actor.account_id
    )
    envelope["arguments"]["approved"] = True
    with pytest.raises(ManualError, match="delegation_denied"):
        verifier.verify(envelope, action, key, "/internal/v1/data/" + action)


def test_review_context_digest_path_is_canonical(surface):
    client, gateway = surface
    assert client.get("/v1/artifacts/invalid/review-context").status_code == 400
    gateway.artifact_context.assert_not_called()
