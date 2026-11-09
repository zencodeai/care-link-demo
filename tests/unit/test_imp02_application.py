"""Composition boundary checks; network/provider behavior is qualified separately."""

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tools.imp02_application.browser import add_auth_proxy
from tools.imp02_application.mesh import MeshTransport, explicit_credentials_only


@pytest.mark.unit
def test_bff_forwards_only_protocol_routes_and_separates_authority_headers() -> None:
    seen: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            headers=[("set-cookie", "session=one; Secure"), ("set-cookie", "binding=two; Secure")],
            json={"csrf_token": "metadata"},
        )

    with httpx.Client(transport=httpx.MockTransport(upstream)) as channel:
        app = FastAPI()
        add_auth_proxy(app, channel, "https://identity.mesh.local:8443", "help")
        with TestClient(app) as browser:
            response = browser.get(
                "/v1/auth/csrf",
                headers={
                    "cookie": "own=opaque",
                    "x-help-session": "forged",
                    "x-care-link-verified-spiffe": "forged",
                    "x-forwarded-client-cert": "forged",
                },
            )
            assert response.status_code == 200
            assert len(response.headers.get_list("set-cookie")) == 2
            assert str(seen[0].url) == "https://identity.mesh.local:8443/bff/help/v1/auth/csrf"
            assert seen[0].headers["cookie"] == "own=opaque"
            assert not {
                "x-help-session",
                "x-care-link-verified-spiffe",
                "x-forwarded-client-cert",
            } & set(seen[0].headers)
            assert browser.post("/internal/v1/identity/help-authorize", json={}).status_code == 404
            assert len(seen) == 1


@pytest.mark.unit
def test_mesh_client_rejects_different_authority_before_socket_access(tmp_path: Path) -> None:
    with httpx.Client(
        transport=MeshTransport(tmp_path / "not-present.sock", "https://identity.mesh.local:8443")
    ) as client:
        with pytest.raises(ValueError, match="Unconfigured mesh authority"):
            client.get("https://attacker.invalid/internal/v1/identity/help-authorize")


@pytest.mark.unit
def test_shared_bff_never_supplies_another_browsers_cookie() -> None:
    seen: list[str] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("cookie", ""))
        return httpx.Response(200, headers={"set-cookie": "session=upstream; Path=/; Secure"})

    with httpx.Client(transport=httpx.MockTransport(upstream)) as channel:
        # Exercise defense even with an injected/pre-populated shared client.
        channel.cookies.set("session", "another-browser", domain="identity.mesh.local")
        app = FastAPI()
        add_auth_proxy(app, channel, "https://identity.mesh.local:8443", "help")
        with TestClient(app) as first:
            first.get("/v1/auth/csrf", headers={"cookie": "session=first-browser"})
        with TestClient(app) as second:
            second.get("/v1/auth/csrf")
        assert seen == ["session=first-browser", ""]


@pytest.mark.unit
def test_mesh_client_does_not_retain_upstream_browser_cookies() -> None:
    seen: list[str] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("cookie", ""))
        return httpx.Response(200, headers={"set-cookie": "session=upstream; Path=/; Secure"})

    with httpx.Client(
        transport=httpx.MockTransport(upstream), cookies=explicit_credentials_only()
    ) as client:
        client.get("https://identity.mesh.local:8443/", headers={"cookie": "session=explicit"})
        client.get("https://identity.mesh.local:8443/")
        assert list(client.cookies.items()) == []
        assert seen == ["session=explicit", ""]


@pytest.mark.unit
def test_help_client_route_and_api_have_separate_content_policies(tmp_path: Path) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from tools.imp02_application.__main__ import compose

    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text('<html><script src="/assets/client.js"></script></html>')
    (web / "assets").mkdir()
    (web / "assets/client.js").write_text("void 0")
    custody = tmp_path / "spool"
    custody.mkdir(mode=0o700)
    key = tmp_path / "identity.pub"
    key.write_bytes(
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    app = compose(
        "help",
        {
            "identity_origin": "https://identity.mesh.local:8443",
            "origin": "https://help.localhost:19443",
            "outbound_socket": str(tmp_path / "not-present.sock"),
            "spool": str(custody / "help.sqlite"),
            "signing_key_id": "test-public-key",
            "signing_public_key": str(key),
            "static_origin": "https://static.localhost:21443",
            "web_directory": str(web),
        },
    )
    with TestClient(app) as client:
        ui = client.get("/private-help")
        assert ui.status_code == 200 and "client.js" in ui.text
        assert "script-src 'self'" in ui.headers["content-security-policy"]
        assert client.get("/assets/client.js").status_code == 200
        api = client.get("/help/health")
        assert api.status_code == 200
        assert (
            api.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
        )
        denied = client.post("/help/v1/requests", json={})
        assert denied.status_code == 401
