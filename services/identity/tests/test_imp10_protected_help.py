"""Verify the opt-in Help surface with real workload and receipt checks."""

import base64
import os
import secrets
from collections.abc import Iterator
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from care_link_help import (
    HelpConfig,
    HelpService,
    HttpAuthority,
    HttpBrowserSessions,
    SignedReceipts,
    Spool,
)
from care_link_help import create_app as help_app
from care_link_identity import (
    Custody,
    IdentityError,
    IdentityService,
    OIDCConfig,
    OIDCProvider,
    ReceiptSigner,
)
from care_link_workload_trust import SOCKET_PEER_SCOPE_KEY, BackendVerifier, PeerRule, SocketPeer
from care_link_workload_trust.fence import FenceState
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.types import ASGIApp, Receive, Scope, Send

from services.identity.tests.conftest import Clock, FakeProvider, MemoryStore, signed_in
from tools.imp10_runtime import protected_help
from tools.imp10_runtime.protected_help import HELP_COOKIE, with_private_help
from tools.imp10_runtime.routes import HELP_AUTH_ROUTES, HELP_IDENTITY_ROUTES

MAIN_ORIGIN = "https://main.test"
HELP_ORIGIN = "https://help.test"
IDENTITY_ORIGIN = "https://identity.test"
PROVIDER_ISSUER = "https://provider.test/realm"
HELP_PEER = "spiffe://care-link.demo/demo/help"
IDENTITY_PEER = "spiffe://care-link.demo/demo/identity"


class Fence:
    state = FenceState(0, frozenset({HELP_PEER, IDENTITY_PEER}), frozenset(), (), "")

    def read(self) -> FenceState:
        return self.state


def oidc(client: str, origin: str) -> OIDCConfig:
    return OIDCConfig(
        issuer=PROVIDER_ISSUER,
        client_id=client,
        client_secret=secrets.token_urlsafe(32),
        redirect_uri=origin + "/v1/auth/callback",
        authorization_endpoint=PROVIDER_ISSUER + "/authorize",
        token_endpoint=PROVIDER_ISSUER + "/token",
        jwks_uri=PROVIDER_ISSUER + "/jwks",
        introspection_endpoint=PROVIDER_ISSUER + "/introspect",
        revocation_endpoint=PROVIDER_ISSUER + "/revoke",
        resource_audience="identity-resource",
        mfa_acr="al2",
    )


@pytest.fixture
def protected_fixture(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple]:
    clock = Clock()
    provider = FakeProvider(clock)
    main_oidc, help_oidc = oidc("main", MAIN_ORIGIN), oidc("help", HELP_ORIGIN)
    introspected = []

    def introspect(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == help_oidc.introspection_endpoint
        authorization = base64.b64decode(request.headers["Authorization"].removeprefix("Basic "))
        assert authorization == f"{help_oidc.client_id}:{help_oidc.client_secret}".encode()
        introspected.append(help_oidc.client_id)
        return httpx.Response(200, json={"active": provider.is_active, "sub": provider.subject})

    monkeypatch.setattr(OIDCProvider, "exchange", lambda _self, *args: provider.exchange(*args))
    monkeypatch.setattr(
        protected_help, "PinnedAddressTransport", lambda *_: httpx.MockTransport(introspect)
    )

    def primary_provider(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("The Help path must never use the main browser's OIDC client")

    key = Ed25519PrivateKey.generate()
    with httpx.Client(transport=httpx.MockTransport(primary_provider)) as primary_client:
        main = IdentityService(
            MemoryStore(),
            OIDCProvider(main_oidc, primary_client),
            Custody(Fernet.generate_key()),
            ReceiptSigner(key, "synthetic-identity"),
            PROVIDER_ISSUER,
            MAIN_ORIGIN,
            clock,
        )
        main.provision(provider.subject, str(uuid4()), ["pid"])
        config = {
            "provider_address": "127.0.0.1",
            "provider_ca": "/unopened/synthetic-ca.pem",
            "help_identity": {"origin": HELP_ORIGIN, "oidc": asdict(help_oidc)},
        }
        fence, proxy_uid = Fence(), os.geteuid() + 1
        verify = BackendVerifier(
            proxy_uid,
            (PeerRule(HELP_PEER, HELP_AUTH_ROUTES | HELP_IDENTITY_ROUTES),),
            fence,
            backend_uid=os.geteuid(),
            local_spiffe_id=IDENTITY_PEER,
        )
        clients: list[httpx.Client] = []
        try:
            yield main, provider, key, config, fence, proxy_uid, verify, clients, introspected
        finally:
            for client in clients:
                client.close()


def trusted_socket(app: ASGIApp, proxy_uid: int) -> ASGIApp:
    async def fixture(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            scope[SOCKET_PEER_SCOPE_KEY] = SocketPeer(proxy_uid)
        await app(scope, receive, send)

    return fixture


def test_private_help_bound_to_workload_and_origin_and_fails_closed(
    protected_fixture: tuple, tmp_path: Path
) -> None:
    main, provider, key, config, fence, proxy_uid, verify, clients, introspected = protected_fixture
    primary = FastAPI()

    @primary.get("/bff/main/health")
    def main_health() -> dict[str, bool]:
        return {"primary": True}

    app = with_private_help(
        primary, config=config, main_service=main, clients=clients, verify=verify
    )
    assert len(clients) == 1
    headers = {
        "x-care-link-verified-spiffe": HELP_PEER,
        "x-care-link-fence-generation": "0",
        "x-care-link-certificate-expires-at": (datetime.now(UTC) + timedelta(minutes=2))
        .isoformat()
        .replace("+00:00", "Z"),
    }
    with TestClient(app, base_url=IDENTITY_ORIGIN) as untrusted:
        assert untrusted.get("/bff/help/v1/auth/csrf", headers=headers).status_code == 403
        assert (
            untrusted.post("/internal/v1/identity/help-authorize", headers=headers).status_code
            == 403
        )
    with TestClient(
        trusted_socket(app, proxy_uid), base_url=IDENTITY_ORIGIN, headers=headers
    ) as internal:
        assert internal.get("/bff/main/health").json() == {"primary": True}
        assert internal.get("/bff/help/v1/auth/unknown").status_code == 403
        assert internal.get("/internal/v1/identity/help-authorize").status_code == 403
        assert (
            internal.post(
                "/internal/v1/identity/help-browser-context", params={"extra": "1"}
            ).status_code
            == 403
        )
        csrf = internal.get("/bff/help/v1/auth/csrf").json()["csrf_token"]
        login = {"role": "pid", "return_route": "participant", "locale": "en-CA"}
        assert (
            internal.post(
                "/bff/help/v1/auth/login",
                json=login,
                headers={"Origin": MAIN_ORIGIN, "X-CSRF-Token": csrf},
            ).status_code
            == 403
        )
        started = internal.post(
            "/bff/help/v1/auth/login",
            json=login,
            headers={"Origin": HELP_ORIGIN, "X-CSRF-Token": csrf},
        )
        query = parse_qs(urlsplit(started.json()["authorization_url"]).query)
        assert query["client_id"] == ["help"]
        callback = internal.get(
            "/bff/help/v1/auth/callback", params={"state": query["state"][0], "code": "test-code"}
        )
        assert callback.status_code == 200
        raw = internal.cookies[HELP_COOKIE]
        with pytest.raises(IdentityError) as cross_origin:
            main.browser_context(raw)
        assert cross_origin.value.status == 401
        main_cookie = signed_in(main)
        context_route = "/internal/v1/identity/help-browser-context"
        assert (
            internal.post(
                context_route,
                headers={
                    "X-Help-Session": main_cookie,
                    "X-Help-Origin": HELP_ORIGIN,
                },
            ).status_code
            == 401
        )
        assert (
            internal.post(
                context_route,
                headers={
                    "X-Help-Session": raw,
                    "x-care-link-verified-spiffe": "spiffe://care-link.demo/demo/core",
                },
            ).status_code
            == 403
        )
        assert (
            internal.post(
                "/internal/v1/identity/help-browser-proof",
                headers={
                    "X-Help-Session": raw,
                    "X-Help-Origin": MAIN_ORIGIN,
                },
            ).status_code
            == 403
        )

        def relay(request: httpx.Request) -> httpx.Response:
            response = internal.request(
                request.method, request.url.path, headers=request.headers, content=request.content
            )
            return httpx.Response(response.status_code, content=response.content)

        tmp_path.chmod(0o700)
        with httpx.Client(transport=httpx.MockTransport(relay)) as client:
            sessions = HttpBrowserSessions(client, IDENTITY_ORIGIN, HELP_ORIGIN)
            clock = main.clock
            help_service = HelpService(
                Spool(tmp_path / "help.sqlite", clock=clock),
                HttpAuthority(client, IDENTITY_ORIGIN),
                SignedReceipts({"synthetic-identity": key.public_key()}, clock=clock),
                clock=clock,
            )
            browser_app = help_app(HelpConfig(HELP_ORIGIN), help_service, sessions)
            with TestClient(browser_app, base_url=HELP_ORIGIN) as browser:
                browser.cookies.set(HELP_COOKIE, raw)
                context = sessions.context(raw)
                browser_headers = {"Origin": HELP_ORIGIN, "X-CSRF-Token": context.csrf_token}
                body = {"locale": "en-CA", "jurisdiction": None}
                intent = browser.post("/help/v1/create-intent", headers=browser_headers, json=body)
                assert intent.status_code == 200
                result = browser.post(
                    "/help/v1/requests",
                    json=body,
                    headers=browser_headers | {"Idempotency-Key": intent.json()["operation_id"]},
                )
                assert result.status_code == 200 and result.json()["state"] == "recorded"
                assert not result.json()["connection_confirmed"]
                provider.is_active = False
                assert browser.get("/help/v1/requests/" + result.json()["id"]).status_code == 503
                assert len(introspected) >= 4
        fence.state = replace(fence.state, generation=1, denied=frozenset({HELP_PEER}))
        assert internal.get("/bff/help/v1/auth/session").status_code == 403
        assert internal.post(context_route, headers={"X-Help-Session": raw}).status_code == 403


def test_help_requires_explicit_isolated_identity_configuration(protected_fixture: tuple) -> None:
    main, _provider, _key, config, _fence, _proxy, verify, clients, _checks = protected_fixture
    primary = FastAPI()
    options = {"main_service": main, "clients": clients, "verify": verify}
    assert with_private_help(primary, config={}, **options) is primary
    settings = config["help_identity"]
    oidc_config = settings["oidc"]
    preconditions = [
        None,
        settings | {"origin": MAIN_ORIGIN, "oidc": oidc_config},
        settings | {"origin": "https://main.test:8443", "oidc": oidc_config},
        settings | {"oidc": oidc_config | {"issuer": "https://provider.test/other-realm"}},
        settings | {"oidc": oidc_config | {"client_id": "main"}},
        settings | {"oidc": oidc_config | {"client_secret": main.provider.config.client_secret}},
        settings | {"oidc": oidc_config | {"redirect_uri": MAIN_ORIGIN + "/v1/auth/callback"}},
    ]
    for setting in preconditions:
        with pytest.raises(ValueError):
            with_private_help(primary, config=config | {"help_identity": setting}, **options)
    assert clients == []
