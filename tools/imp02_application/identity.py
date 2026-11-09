"""Identity-only provider and database custody with explicit BFF origin contexts."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import httpx
import psycopg
from care_link_identity import (
    Custody,
    IdentityError,
    IdentityService,
    KeycloakCleanup,
    KeycloakServiceCredentials,
    OIDCConfig,
    OIDCProvider,
    PostgresStore,
    ReceiptSigner,
    RetentionService,
    SessionRetentionAuthority,
    SignalReceiver,
    WorkloadBindings,
    WorkloadSignals,
    create_app,
)
from care_link_workload_trust import BackendVerifier, PeerRule, UnixFenceClient
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from .config import private_key, public_key, text
from .tls import PinnedAddressTransport

AUTH_ROUTES = (
    ("GET", "/v1/auth/csrf"),
    ("POST", "/v1/auth/login"),
    ("GET", "/v1/auth/callback"),
    ("GET", "/v1/auth/session"),
    ("POST", "/v1/auth/logout"),
    ("POST", "/v1/auth/step-up"),
    ("POST", "/v1/auth/step-up/confirm"),
    ("GET", "/v1/auth/step-up/proof"),
)
HELP_ROUTES: frozenset[tuple[str, str]] = frozenset(
    ("POST", "/internal/v1/identity/" + name)
    for name in ("help-authorize", "help-browser-context", "help-browser-proof")
)


class IdentityApplication:
    def __init__(self, config: dict[str, object]) -> None:
        import os

        fence = UnixFenceClient(Path(text(config, "fence_socket")), 21000)
        rules = tuple(
            PeerRule(
                "spiffe://care-link.demo/lab/" + role,
                frozenset((method, "/bff/" + role + path) for method, path in AUTH_ROUTES)
                | (HELP_ROUTES if role == "help" else frozenset[tuple[str, str]]()),
            )
            for role in ("main", "help")
        )
        rules += (
            PeerRule(
                "spiffe://care-link.demo/lab/identity_provider",
                frozenset({("POST", "/internal/v1/identity/signals")}),
            ),
        )
        self.verifier = BackendVerifier(
            21002,
            rules,
            fence,
            backend_uid=os.geteuid(),
            local_spiffe_id="spiffe://care-link.demo/lab/identity",
        )
        store = PostgresStore(text(config, "store_dsn"))
        custody = Custody(Path(text(config, "custody_key")).read_bytes().strip())
        signer = ReceiptSigner(
            private_key(text(config, "signing_key")), text(config, "signing_key_id")
        )
        self.signals = SignalReceiver(
            store,
            text(config, "signal_issuer"),
            "care-link-identity",
            public_key(text(config, "signal_public_key")),
            text(cast(dict[str, object], config["oidc_main"]), "issuer"),
            lambda: datetime.now(UTC),
            WorkloadSignals(
                store,
                WorkloadBindings(
                    text(config, "signal_issuer"), cast(dict[str, str], config["workload_subjects"])
                ),
                fence,
            ),
        )
        self.services: dict[str, IdentityService] = {}
        self.apps: dict[str, FastAPI] = {}
        self.clients: list[httpx.Client] = []
        for role in ("main", "help"):
            raw = cast(dict[str, str], config["oidc_" + role])
            oidc = OIDCConfig(**raw)
            client = httpx.Client(
                transport=PinnedAddressTransport(
                    "https://id.localhost:20443",
                    text(config, "provider_address"),
                    text(config, "ca_file"),
                ),
                trust_env=False,
            )
            self.clients.append(client)
            service = IdentityService(
                store,
                OIDCProvider(oidc, client),
                custody,
                signer,
                oidc.issuer,
                text(config, role + "_origin"),
            )
            self.services[role] = service
            self.apps[role] = create_app(
                service,
                workload_verifier=self.verifier,
                signals=self.signals,
                session_cookie="__Host-care_link_help"
                if role == "help"
                else "__Host-care-link-session",
                ui_return_url=service.origin + "/",
            )

        origin = "https://id.localhost:20443"
        lifecycle = KeycloakServiceCredentials(
            text(cast(dict[str, object], config["oidc_main"]), "token_endpoint"),
            origin,
            text(config, "lifecycle_client_id"),
            text(config, "lifecycle_client_secret"),
            self.clients[0],
        )
        self.retention = RetentionService(
            store,
            custody,
            SessionRetentionAuthority(self.services["main"], text(config, "owner_account_id")),
            KeycloakCleanup(
                origin + "/admin/realms/care-link-imp02/users", origin, lifecycle, self.clients[0]
            ),
        )
        self.credential_maintenance_state = "not_started"

    async def maintain_credentials(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await run_in_threadpool(self.retention.expire_credentials)
                self.credential_maintenance_state = "current"
            except (psycopg.Error, IdentityError, OSError):
                self.credential_maintenance_state = "unavailable"
            try:
                await asyncio.wait_for(stop.wait(), timeout=5)
            except TimeoutError:
                pass

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            stop = asyncio.Event()
            maintenance = asyncio.create_task(self.maintain_credentials(stop))
            try:
                await self.apps["main"](scope, receive, send)
            finally:
                stop.set()
                await maintenance
                for client in self.clients:
                    client.close()
            return
        path = scope.get("path", "")
        request = Request(scope, receive)
        if path.startswith("/internal/"):
            await self.apps["help"](scope, receive, send)
            return
        for role in ("main", "help"):
            prefix = "/bff/" + role
            if path.startswith(prefix + "/") and self.verifier(request, role):
                local = dict(scope)
                local["path"] = path.removeprefix(prefix)
                local["raw_path"] = local["path"].encode()
                await self.apps[role](cast(Scope, local), receive, send)
                return
        await JSONResponse({"state": "workload_denied"}, status_code=403)(scope, receive, send)
