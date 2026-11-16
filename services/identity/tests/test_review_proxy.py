"""Exact mTLS BFF origin headers are derived from the registered authority."""

import json
from uuid import uuid4

import httpx
from care_link_core.review_context import ReviewContexts
from fastapi import FastAPI
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from tools.imp03_runtime.review_browser import add_review_auth_proxy, review_origin_guard
from tools.imp03_runtime.review_identity import load_contexts


def contexts(tmp_path):
    path = tmp_path / "contexts.json"
    path.write_text(
        json.dumps(
            {
                "https://worker.test": {
                    "run_id": str(uuid4()),
                    "slot_id": "worker1",
                    "account_id": str(uuid4()),
                    "provider_subject": "issued-subject",
                    "role": "worker",
                    "state": "active",
                },
            }
        )
    )
    return ReviewContexts(path, "https://legacy.test")


def test_proxy_ignores_spoofed_origin_and_peer_headers(tmp_path):
    registry, captured = contexts(tmp_path), []

    def upstream(request):
        captured.append(request)
        return httpx.Response(
            200,
            json={"ok": True},
            headers={
                "Set-Cookie": "__Host-example=value; Secure; HttpOnly; Path=/",
                "X-Internal-Secret": "hidden",
            },
        )

    remote = httpx.Client(transport=httpx.MockTransport(upstream))
    app = FastAPI()
    add_review_auth_proxy(app, remote, "https://identity.internal", registry)
    client = TestClient(app, base_url="https://worker.test")
    response = client.get(
        "/v1/auth/session",
        headers={
            "X-Care-Link-Browser-Origin": "https://supervisor.test",
            "X-Forwarded-Host": "supervisor.test",
            "X-Verified-Peer": "supervisor",
        },
    )
    assert response.status_code == 200
    assert captured[0].headers["x-care-link-browser-origin"] == "https://worker.test"
    assert captured[0].headers["cookie"] == ""
    assert "x-forwarded-host" not in captured[0].headers
    assert "x-verified-peer" not in captured[0].headers
    assert str(captured[0].url) == "https://identity.internal/bff/main/v1/auth/session"
    assert response.headers.get("set-cookie")
    assert "x-internal-secret" not in response.headers


def test_unknown_host_and_unknown_auth_route_never_reach_identity(tmp_path):
    registry, captured = contexts(tmp_path), []
    remote = httpx.Client(
        transport=httpx.MockTransport(lambda r: captured.append(r) or httpx.Response(200))
    )
    app = FastAPI()
    add_review_auth_proxy(app, remote, "https://identity.internal", registry)
    client = TestClient(app, base_url="https://forged.test")
    assert client.get("/v1/auth/session").status_code == 403
    assert client.get("/v1/auth/arbitrary").status_code == 404
    assert not captured


def test_legacy_origin_still_gets_explicit_context_and_no_cookie_jar_fallback(tmp_path):
    registry, captured = contexts(tmp_path), []
    remote = httpx.Client(
        transport=httpx.MockTransport(lambda r: captured.append(r) or httpx.Response(200))
    )
    remote.cookies.set(
        "__Host-care-link-session", "another-actors-cookie", domain="identity.internal"
    )
    app = FastAPI()
    add_review_auth_proxy(app, remote, "https://identity.internal", registry)
    client = TestClient(app, base_url="https://legacy.test")
    assert client.get("/v1/auth/csrf").status_code == 200
    assert captured[0].headers["cookie"] == ""
    assert captured[0].headers["x-care-link-browser-origin"] == "https://legacy.test"


def test_root_guard_covers_assets_and_missing_registry(tmp_path):
    registry = contexts(tmp_path)
    app = FastAPI()

    @app.get("/")
    async def index():
        return JSONResponse({"page": "public"})

    client = TestClient(review_origin_guard(app, registry), base_url="https://forged.test")
    assert client.get("/").status_code == 403
    registry.path.unlink()
    assert client.get("/", headers={"host": "worker.test"}).status_code == 503


def test_identity_loader_consumes_exact_same_registry_shape(tmp_path):
    registry = contexts(tmp_path)
    values = load_contexts(registry.path)
    assert values["https://worker.test"].slot_id == "worker1"
