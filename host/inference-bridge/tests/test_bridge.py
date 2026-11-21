import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from care_link_inference_bridge import ENDPOINT, MODEL, LocalModelBridge, create_app
from fastapi.testclient import TestClient


def payload():
    return {
        "model": MODEL,
        "messages": [{"role": "user", "content": "synthetic"}],
        "temperature": 0,
        "stream": False,
        "max_tokens": 1024,
        "reasoning_effort": "none",
        "response_format": {"type": "json_schema", "json_schema": {}},
    }


def test_fixed_destination_headers_no_proxy_no_redirect():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "https://external.invalid/"})

    bridge = LocalModelBridge(transport=httpx.MockTransport(respond))
    with pytest.raises(OSError):
        bridge.complete(payload(), datetime.now(UTC) + timedelta(seconds=20))
    assert len(calls) == 1 and str(calls[0].url) == ENDPOINT
    assert "authorization" not in calls[0].headers
    bridge.close()


@pytest.mark.parametrize(
    "change",
    [
        {"url": "https://external.invalid"},
        {"model": "other"},
        {"tools": []},
        {"stream": True},
        {"max_tokens": 1025},
        {"temperature": 1},
        {"reasoning_effort": "high"},
    ],
)
def test_destination_model_tools_and_budget_cannot_be_overridden(change):
    bridge = LocalModelBridge(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    with pytest.raises(ValueError):
        bridge.complete({**payload(), **change}, datetime.now(UTC) + timedelta(seconds=20))
    bridge.close()


def test_absolute_deadline_and_response_byte_bounds():
    bridge = LocalModelBridge(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"a" * 65537))
    )
    with pytest.raises(OSError):
        bridge.complete(payload(), datetime.now(UTC) + timedelta(seconds=20))
    with pytest.raises(TimeoutError):
        bridge.complete(payload(), datetime.now(UTC) - timedelta(seconds=1))
    bridge.close()


def test_local_api_secret_is_supplied_only_by_bridge_composition():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={})

    credential = "synthetic-secret"
    bridge = LocalModelBridge(api_token=credential, transport=httpx.MockTransport(respond))
    bridge.complete(payload(), datetime.now(UTC) + timedelta(seconds=20))
    assert calls[0].headers["authorization"] == "Bearer synthetic-secret"
    assert "synthetic-secret" not in repr(bridge)
    bridge.close()


def test_bridge_requires_authenticated_inference_workload():
    bridge = LocalModelBridge(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={})))
    client = TestClient(create_app(bridge, lambda _request, _role: False))
    assert client.post("/internal/v1/inference/execute", json={}).status_code == 403
    client = TestClient(create_app(bridge, lambda _request, role: role == "inference"))
    body = {
        "payload": payload(),
        "deadline": (datetime.now(UTC) + timedelta(seconds=20)).isoformat().replace("+00:00", "Z"),
    }
    assert client.post("/internal/v1/inference/execute", json=body).status_code == 200
    assert (
        client.post(
            "/internal/v1/inference/execute",
            content=json.dumps(body).replace('"payload":', '"deadline":"x","payload":'),
        ).status_code
        == 400
    )
    bridge.close()


@pytest.mark.parametrize(
    ("anonymous_status", "credential_status", "expected_headers"),
    [(401, 200, [False, True]), (200, 200, [False]), (401, 401, [False, True])],
)
def test_auth_preflight_requires_server_enforcement_and_an_accepted_credential(
    anonymous_status, credential_status, expected_headers
):
    calls = []

    def respond(request):
        assert str(request.url) == "http://127.0.0.1:1234/api/v1/models"
        assert request.method == "GET" and request.content == b""
        authenticated = "authorization" in request.headers
        calls.append(authenticated)
        return httpx.Response(credential_status if authenticated else anonymous_status)

    credential = "synthetic-secret"
    bridge = LocalModelBridge(api_token=credential, transport=httpx.MockTransport(respond))
    try:
        if anonymous_status == 401 and credential_status == 200:
            bridge.require_authentication()
        else:
            with pytest.raises(OSError, match="authentication|credential"):
                bridge.require_authentication()
        assert calls == expected_headers
    finally:
        bridge.close()
