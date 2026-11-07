"""The walking skeleton validates contracts without simulating service success."""

import pytest
from care_link_contracts import validate_contract
from care_link_core import create_app
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_health_is_closed_developer_capability_without_participant_admission(
    client: TestClient,
) -> None:
    response = client.get("/dev/health")
    assert response.status_code == 200
    validate_contract("DeveloperCapability", response.json())
    assert response.json()["participant_admission"] is False
    assert response.json()["business_operations"] == "unavailable"
    assert response.headers["cache-control"] == "no-store"


def test_contract_validation_is_only_a_no_content_check(client: TestClient) -> None:
    response = client.post("/dev/contracts/RevisionCommand", json={"expected_revision": "1"})
    assert response.status_code == 204
    assert response.content == b""


@pytest.mark.parametrize("method", ["GET", "POST", "PATCH", "DELETE", "PUT", "OPTIONS"])
@pytest.mark.parametrize("path", ["/v1", "/v1/sessions", "/v1/unknown/nested"])
def test_every_business_request_remains_explicitly_unavailable(
    client: TestClient, method: str, path: str
) -> None:
    response = client.request(method, path, json={"anything": "synthetic"})
    assert response.status_code == 503
    validate_contract("Error", response.json())
    assert response.json()["code"] == "CAPABILITY_DISABLED"
    assert response.json()["operation_id"] is None
    assert response.json()["retryable"] is False


@pytest.mark.parametrize(
    ("body", "status"),
    [
        (b'{"expected_revision":"9223372036854775808"}', 422),
        (b'{"expected_revision":"1","unknown":"secret-marker"}', 422),
        (b'{"expected_revision":"1","expected_revision":"2"}', 400),
        (b'{"expected_revision":NaN}', 400),
        (b'{"expected_revision":"\\ud800"}', 400),
        (b'{"expected_revision":"\xff"}', 400),
        (b"{", 400),
    ],
)
def test_invalid_input_returns_safe_closed_error(
    client: TestClient, body: bytes, status: int
) -> None:
    response = client.post(
        "/dev/contracts/RevisionCommand", content=body, headers={"content-type": "application/json"}
    )
    assert response.status_code == status
    validate_contract("Error", response.json())
    assert "secret-marker" not in response.text
    assert "expected_revision" not in response.text


def test_nested_key_is_rejected_by_developer_endpoint(client: TestClient) -> None:
    response = client.post(
        "/dev/contracts/SessionCreate",
        json={
            "tags": {"environment": "demo", "population": "synthetic", "authority": True},
            "participant_kind": "pid",
            "jurisdiction": None,
            "locale": "en-CA",
            "channel": "web",
            "persona_id": None,
            "fixture_id": None,
        },
    )
    assert response.status_code == 422


def test_streamed_body_cap_applies_without_trusting_content_length(client: TestClient) -> None:
    response = client.post(
        "/dev/contracts/RevisionCommand",
        content=iter([b" " * 32768, b" " * 32768, b" "]),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    validate_contract("Error", response.json())


def test_content_type_and_compression_are_explicitly_limited(client: TestClient) -> None:
    response = client.post("/dev/contracts/RevisionCommand", content=b"{}")
    assert response.status_code == 415
    response = client.post(
        "/dev/contracts/RevisionCommand",
        content=b"{}",
        headers={"content-type": "application/json", "content-encoding": "gzip"},
    )
    assert response.status_code == 415


def test_unknown_contract_has_no_execution_fallback(client: TestClient) -> None:
    response = client.post("/dev/contracts/ExecuteSql", json={})
    assert response.status_code == 404
    validate_contract("Error", response.json())
