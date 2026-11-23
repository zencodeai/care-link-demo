"""Bind the host Help workload to an origin-scoped protected Identity surface."""

from collections.abc import Callable
from dataclasses import fields
from typing import cast

import httpx
from care_link_identity import IdentityService, OIDCConfig, OIDCProvider, create_app
from fastapi import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from tools.imp02_application.tls import PinnedAddressTransport
from tools.imp03_runtime.config import Record, record, text
from tools.imp10_runtime.routes import HELP_AUTH_ROUTES, HELP_IDENTITY_ROUTES

HELP_BFF = "/bff/help"
HELP_COOKIE = "__Host-care_link_help"


def _help_service(config: Record, main: IdentityService) -> tuple[IdentityService, httpx.Client]:
    settings = record(config["help_identity"])
    if set(settings) != {"origin", "oidc"}:
        raise ValueError("Exact private Help origin and OIDC configuration required")
    origin = text(settings, "origin")
    browser = httpx.URL(origin)
    if (
        browser.scheme != "https"
        or not browser.host
        or browser.host.rstrip(".") == httpx.URL(main.origin).host.rstrip(".")
        or browser.userinfo
        or origin != str(browser).removesuffix("/")
        or browser.path != "/"
        or browser.query
        or browser.fragment
    ):
        raise ValueError("Distinct canonical private Help HTTPS origin required")
    raw = record(settings["oidc"])
    allowed = {field.name for field in fields(OIDCConfig)}
    if not allowed - {"access_token_type"} <= set(raw) <= allowed or not all(
        isinstance(value, str) and value for value in raw.values()
    ):
        raise ValueError("Exact private Help OIDC settings required")
    oidc = OIDCConfig(**cast(dict[str, str], raw))
    if (
        not isinstance(main.provider, OIDCProvider)
        or oidc.issuer != main.issuer
        or oidc.client_id == main.provider.config.client_id
        or oidc.client_secret == main.provider.config.client_secret
        or oidc.redirect_uri != origin + "/v1/auth/callback"
    ):
        raise ValueError("Private Help requires its own OIDC client at the admitted issuer")
    issuer_origin = str(httpx.URL(oidc.issuer).copy_with(path="/"))
    client = httpx.Client(
        transport=PinnedAddressTransport(
            issuer_origin, text(config, "provider_address"), text(config, "provider_ca")
        ),
        trust_env=False,
    )
    return (
        IdentityService(
            main.store,
            OIDCProvider(oidc, client),
            main.custody,
            main.signer,
            oidc.issuer,
            origin,
            clock=main.clock,
        ),
        client,
    )


def with_private_help(
    primary: ASGIApp,
    *,
    config: Record,
    main_service: IdentityService,
    clients: list[httpx.Client],
    verify: Callable[[Request, str], bool],
) -> ASGIApp:
    """Expose only the named Help routes through the current workload verifier."""
    if "help_identity" not in config:
        return primary
    service, client = _help_service(config, main_service)
    browser = create_app(
        service,
        workload_verifier=verify,
        session_cookie=HELP_COOKIE,
        ui_return_url=service.origin + "/",
    )
    clients.append(client)

    async def surface(scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not (
            path == HELP_BFF
            or path.startswith(HELP_BFF + "/")
            or path.startswith("/internal/v1/identity/help-")
        ):
            await primary(scope, receive, send)
            return
        pair = (scope["method"], path)
        if pair in HELP_IDENTITY_ROUTES:
            # The existing Identity handlers check the current Help workload.
            await browser(scope, receive, send)
            return
        if pair in HELP_AUTH_ROUTES and verify(Request(scope, receive), "help"):
            local = dict(scope)
            local["path"] = path.removeprefix(HELP_BFF)
            local["raw_path"] = local["path"].encode()
            await browser(cast(Scope, local), receive, send)
            return
        await JSONResponse(
            {"state": "workload_denied"}, status_code=403, headers={"Cache-Control": "no-store"}
        )(scope, receive, send)

    return surface
