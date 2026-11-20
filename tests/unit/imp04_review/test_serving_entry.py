"""Real composed entry routing/CSP with temporary assets and no remote I/O."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from starlette.testclient import TestClient

from tools.imp02_application.browser import secure_surface
from tools.imp03_runtime import compose

RUN = "10000000-0000-4000-8000-000000000001"
ACTOR = "20000000-0000-4000-8000-000000000001"
ORIGIN = f"https://r{UUID(RUN).hex}-pid.plans.localhost:30443"
LEGACY = "https://plans.localhost:30443"
INDEX = '<!doctype html><html><body><script src="/assets/app.js"></script></body></html>'


@pytest.fixture
def surface(tmp_path, monkeypatch):
    assets = tmp_path / "web"
    (assets / "assets").mkdir(parents=True)
    (assets / "index.html").write_text(INDEX)
    (assets / "assets/app.js").write_text("window.reviewFixture=true;")
    registry = tmp_path / "registry.json"
    now = datetime.now(UTC)
    registry.write_text(
        json.dumps(
            {
                ORIGIN: {
                    "mode": "plans",
                    "authentication_mode": "automatic_review",
                    "environment": "synthetic-review",
                    "run_id": RUN,
                    "slot_id": "pid",
                    "account_id": ACTOR,
                    "provider_subject": ACTOR,
                    "role": "pid",
                    "state": "active",
                    "started_at": now.isoformat().replace("+00:00", "Z"),
                    "expires_at": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                    "session_id": ACTOR,
                    "plan_id": None,
                    "recipient_id": None,
                }
            }
        )
    )

    def no_remote(request):
        raise AssertionError("Static entry must not call remote identity/data/PDP")

    client = httpx.Client(transport=httpx.MockTransport(no_remote))
    identity = SimpleNamespace(client=client, origin="https://identity.example")
    monkeypatch.setattr(compose.Composition, "identity", lambda self: identity)
    monkeypatch.setattr(
        compose.Composition,
        "remote",
        lambda self, destination: (client, f"https://{destination}.example"),
    )
    monkeypatch.setattr(compose, "workload", lambda config, role: lambda request, source: False)
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(compose, "private_key", lambda path: key)

    def build(enabled=True, *, registered=True):
        config = {
            "role": "core",
            "web_directory": str(assets),
            "core_signing_key": "unused-fixture-key",
            "interactive_review_enabled": enabled,
        }
        if registered:
            config.update(review_contexts_file=str(registry), review_legacy_origin=LEGACY)
        return compose.Composition(config).app

    yield build
    client.close()


@pytest.mark.parametrize("path", ["/plans-review", "/plans-review/"])
def test_gated_exact_deep_links_serve_html_with_working_public_csp(surface, path):
    with TestClient(surface(), base_url=ORIGIN, follow_redirects=False) as client:
        response = client.get(path)
        assert response.status_code == 200
        assert response.text == INDEX
        assert response.headers["content-type"].startswith("text/html")
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["x-content-type-options"] == "nosniff"
        policy = response.headers["content-security-policy"]
        for directive in (
            "script-src 'self'",
            "style-src 'self'",
            "connect-src 'self'",
            "frame-ancestors 'none'",
            "form-action 'self'",
        ):
            assert directive in policy
        assert client.get("/assets/app.js").text == "window.reviewFixture=true;"


@pytest.mark.parametrize("path", ["/assets/missing.js", "/v1/missing", "/plans-review/missing"])
def test_no_blanket_html_fallback_for_assets_api_or_child_paths(surface, path):
    with TestClient(surface(), base_url=ORIGIN, follow_redirects=False) as client:
        response = client.get(path)
        assert response.status_code == 404
        assert response.text != INDEX
        if path != "/assets/missing.js":
            assert "script-src" not in response.headers["content-security-policy"]


def test_entry_is_read_only_and_origin_guard_still_precedes_html(surface):
    with TestClient(surface(), base_url=ORIGIN, follow_redirects=False) as client:
        assert client.post("/plans-review").status_code == 405
        denied = client.get("/plans-review", headers={"host": "unregistered.plans.localhost:30443"})
        assert denied.status_code == 403
        assert denied.text != INDEX
        assert denied.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("registered", [True, False])
def test_disabled_review_preserves_root_and_does_not_add_entry(surface, registered):
    with TestClient(surface(False, registered=registered), base_url=ORIGIN) as client:
        assert client.get("/").text == INDEX
        for path in ("/plans-review", "/plans-review/"):
            response = client.get(path)
            assert response.status_code == 404
            assert "script-src" not in response.headers["content-security-policy"]
        assert client.get("/dev/health").status_code == 200


def test_secure_surface_default_does_not_expand_public_paths():
    app = FastAPI()
    with TestClient(secure_surface(app)) as client:
        for path in ("/plans-review", "/plans-review/"):
            assert "script-src" not in client.get(path).headers["content-security-policy"]
