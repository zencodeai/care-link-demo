"""Explicit process roots; credentials stay with their independently owned role."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING, cast

import httpx
from care_link_core.manual_app import create_manual_app
from care_link_core.manual_channels import ManualChannels
from care_link_core.manual_envelopes import SignedEnvelopeFactory
from care_link_core.manual_identity import HttpManualIdentity
from care_link_core.manual_security import CookieSecurity
from care_link_core.planning_http import HttpPlanningGateway
from care_link_domain import ManualError
from care_link_policy_input import DelegationVerifier, OpaPolicy
from care_link_recovery_control import FileJournal
from care_link_workload_trust import SOCKET_PEER_SCOPE_KEY, SocketPeer
from fastapi import Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from tools.imp02_application.browser import add_auth_proxy, add_client, secure_surface
from tools.imp02_application.config import private_key, public_key
from tools.imp02_application.mesh import MeshTransport, explicit_credentials_only
from tools.imp02_application.tls import PinnedAddressTransport

from .authority_apps import body, journal_app, policy_app
from .config import Record, integer, record, text, workload
from .remote import HttpChannels, HttpJournal, HttpPolicy

if TYPE_CHECKING:
    from care_link_identity import IdentityService, RetentionService


class Composition:
    def __init__(self, config: Record) -> None:
        self.config = config
        self.role = text(config, "role")
        self.verify = workload(config, self.role)
        self.clients: list[httpx.Client] = []
        self.retention: RetentionService | None = None
        self.maintenance_state = "not_started"
        self.app = self._compose()

    def remote(self, destination: str) -> tuple[httpx.Client, str]:
        target = record(record(self.config["outbound"])[destination])
        origin = text(target, "origin")
        client = httpx.Client(
            transport=MeshTransport(Path(text(target, "socket")), origin),
            cookies=explicit_credentials_only(),
            trust_env=False,
        )
        self.clients.append(client)
        return client, origin

    def identity(self) -> HttpManualIdentity:
        client, origin = self.remote("identity")
        return HttpManualIdentity(
            client, origin, public_key(text(self.config, "identity_public_key"))
        )

    def _compose(self) -> ASGIApp:
        cfg = self.config
        if self.role == "core":
            identity = self.identity()
            data_client, data_origin = self.remote("data")
            policy = HttpPolicy(*self.remote("pdp"))
            envelopes = SignedEnvelopeFactory(
                data_client,
                data_origin,
                identity,
                policy,
                private_key(text(cfg, "core_signing_key")),
            )
            channels = ManualChannels()
            from care_link_core.review_channels import ReviewViews

            self.review_channels = channels
            self.review_views = ReviewViews(channels)
            from care_link_core.plans_review_context import PlansReviewContexts
            from care_link_core.review_context import ReviewContexts

            from .review_browser import add_review_auth_proxy, review_origin_guard

            interactive_review = cfg.get("interactive_review_enabled", False)
            if type(interactive_review) is not bool or (
                interactive_review and not cfg.get("review_contexts_file")
            ):
                raise ValueError("Explicit review registry and boolean feature switch required")
            contexts = (
                (PlansReviewContexts if interactive_review else ReviewContexts)(
                    Path(text(cfg, "review_contexts_file")), text(cfg, "review_legacy_origin")
                )
                if cfg.get("review_contexts_file")
                else None
            )
            gateway = HttpPlanningGateway(data_client, data_origin, envelopes)
            app = create_manual_app(
                gateway,
                CookieSecurity(identity),
                channels,
                review_contexts=contexts,
                review_views=self.review_views,
                plans_review_contexts=contexts
                if isinstance(contexts, PlansReviewContexts)
                else None,
                planning=gateway,
            )

            async def current(request: Request) -> JSONResponse:
                if not self.verify(request, "data"):
                    raise ManualError("manual.workload_denied")
                value = await body(request)
                if set(value) != {"account_id", "browser_session_digest", "transport_generation"}:
                    raise ManualError("manual.invalid_request", 422)
                account, digest, generation = (
                    value["account_id"],
                    value["browser_session_digest"],
                    value["transport_generation"],
                )
                if (
                    not isinstance(account, str)
                    or not isinstance(digest, str)
                    or type(generation) is not int
                ):
                    raise ManualError("manual.invalid_request", 422)
                return JSONResponse(
                    {"current": channels.current(account, digest, generation)},
                    headers={"Cache-Control": "no-store"},
                )

            app.add_api_route("/internal/v1/channels/current", current, methods=["POST"])
            if contexts:
                add_review_auth_proxy(app, identity.client, identity.origin, contexts)
            else:
                add_auth_proxy(app, identity.client, identity.origin, "main")
            # The reviewed IMP-02 proxy route table predates continuation recovery.
            forward = next(
                route.endpoint
                for route in app.routes
                if isinstance(route, Route) and route.path == "/v1/auth/step-up"
            )
            app.add_api_route("/v1/auth/continuation-recovery", forward, methods=["POST"])
            from care_link_core import create_app as developer_app

            app.router.routes.extend(
                route
                for route in developer_app().routes
                if getattr(route, "path", "") == "/dev/health"
            )
            directory = Path(text(cfg, "web_directory"))
            review_entries: frozenset[str] = (
                frozenset({"/plans-review", "/plans-review/"})
                if interactive_review
                else frozenset()
            )
            if interactive_review:

                async def plans_review_entry() -> FileResponse:
                    return FileResponse(directory / "index.html")

                for entry in sorted(review_entries):
                    app.add_api_route(
                        entry, plans_review_entry, methods=["GET"], include_in_schema=False
                    )
            add_client(app, directory)
            surface = secure_surface(app, public_client_paths=review_entries)
            return review_origin_guard(surface, contexts) if contexts else surface
        if self.role == "data":
            from care_link_data import AESGCMContentCipher, ManualService, PostgresStore
            from care_link_data.app import SignedGatewaySecurity
            from care_link_data.app import create_app as data_app
            from care_link_data.directory_admission import VerifiedDirectoryAdmission

            identity = self.identity()
            store_factory = None
            if os.environ.get("CARE_LINK_IMP03_COMMIT_ACK_FAULT") == "cont1":
                from tools.imp03_shared.commit_fault import connection_factory

                store_factory = connection_factory(Path(text(cfg, "content_key")).parent)
            if cfg.get("directory_artifacts"):
                raise ValueError("Unsigned directory admission configuration is forbidden")
            admissions = cast(list[Record], cfg.get("directory_signed_admissions", []))
            pins = record(cfg.get("directory_trusted_keys", {}))
            directory_admission = VerifiedDirectoryAdmission(
                admissions, {key: public_key(str(path)) for key, path in pins.items()}
            )
            service = ManualService(
                PostgresStore(text(cfg, "store_dsn"), connection_factory=store_factory),
                identity,
                HttpPolicy(*self.remote("pdp")),
                HttpJournal(*self.remote("journal"), public_key(text(cfg, "journal_public_key"))),
                AESGCMContentCipher(Path(text(cfg, "content_key")).read_bytes()),
                channel=HttpChannels(*self.remote("core")),
                disclosure_templates=cast(dict[str, Record], cfg["disclosures"]),
                cursor_key=Path(text(cfg, "cursor_key")).read_bytes(),
                directory_admission=directory_admission,
            )
            delegation = DelegationVerifier(
                public_key(text(cfg, "core_public_key")),
                public_key(text(cfg, "identity_public_key")),
                identity.resolve,
            )
            return data_app(service, SignedGatewaySecurity(delegation, self.verify))
        if self.role == "identity":
            from care_link_identity import RetentionService
            from care_link_identity import create_app as identity_app
            from care_link_identity.manual_runtime import create_manual_identity_app

            service = identity_service(cfg, self.clients)
            interactive_review = cfg.get("interactive_review_enabled", False)
            if type(interactive_review) is not bool or (
                interactive_review and not cfg.get("review_contexts_file")
            ):
                raise ValueError("Explicit review registry and boolean feature switch required")
            self.retention = RetentionService(
                service.store, service.custody, None, clock=service.clock
            )
            if cfg.get("review_contexts_file"):
                from .review_identity import create_review_identity_surface

                return create_review_identity_surface(
                    service,
                    Path(text(cfg, "review_contexts_file")),
                    self.verify,
                    provider_configs_file=Path(text(cfg, "review_provider_configs_file"))
                    if cfg.get("review_provider_configs_file")
                    else None,
                    interactive_review_enabled=interactive_review,
                )
            browser = identity_app(service, ui_return_url=service.origin + "/")
            internal = create_manual_identity_app(service, self.verify)

            async def identity_surface(scope: Scope, receive: Receive, send: Send) -> None:
                path = scope.get("path", "")
                if path.startswith("/bff/main/"):
                    request = Request(scope, receive)
                    if not self.verify(request, "core"):
                        await JSONResponse({"state": "workload_denied"}, status_code=403)(
                            scope, receive, send
                        )
                        return
                    local = dict(scope)
                    local["path"] = path.removeprefix("/bff/main")
                    local["raw_path"] = local["path"].encode()
                    await browser(cast(Scope, local), receive, send)
                else:
                    await internal(scope, receive, send)

            return identity_surface
        if self.role == "pdp":
            manifest = record(cfg["policy"])
            policy = OpaPolicy(
                Path(text(cfg, "executable")),
                text(cfg, "executable_digest"),
                Path(text(manifest, "source")).read_bytes(),
                text(manifest, "signature"),
                public_key(text(manifest, "public_key")),
            )
            return policy_app(policy, self.verify)
        if self.role == "journal":
            key = private_key(text(cfg, "signing_key"))
            journal = FileJournal(
                Path(text(cfg, "journal_directory")),
                key,
                text(cfg, "signing_key_id"),
                expected_journal_id=text(cfg, "journal_id"),
            )
            return journal_app(journal, key, self.verify)
        raise ValueError("Unknown role")

    async def maintain(self, stop: asyncio.Event) -> None:
        import psycopg
        from care_link_identity import IdentityError

        while not stop.is_set():
            try:
                if self.retention is not None:
                    await run_in_threadpool(self.retention.expire_credentials)
                self.maintenance_state = "current"
            except (IdentityError, psycopg.Error, OSError):
                self.maintenance_state = "unavailable"
            try:
                await asyncio.wait_for(stop.wait(), timeout=5)
            except TimeoutError:
                pass

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            stop = asyncio.Event()
            maintenance = asyncio.create_task(self.maintain(stop)) if self.retention else None
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    stop.set()
                    if maintenance is not None:
                        await maintenance
                    for client in self.clients:
                        client.close()
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        capsule = scope.get(SOCKET_PEER_SCOPE_KEY)
        if not isinstance(capsule, SocketPeer) or capsule.uid != integer(self.config, "proxy_uid"):
            await JSONResponse({"state": "socket_custody_denied"}, status_code=403)(
                scope, receive, send
            )
            return
        await self.app(scope, receive, send)


def identity_service(config: Record, clients: list[httpx.Client]) -> IdentityService:
    from care_link_identity import (
        Custody,
        IdentityService,
        OIDCConfig,
        OIDCProvider,
        ReceiptSigner,
    )
    from care_link_identity import PostgresStore as IdentityStore

    oidc = OIDCConfig(**cast(dict[str, str], config["oidc"]))
    origin = str(httpx.URL(oidc.issuer).copy_with(path="/"))
    client = httpx.Client(
        transport=PinnedAddressTransport(
            origin, text(config, "provider_address"), text(config, "provider_ca")
        ),
        trust_env=False,
    )
    clients.append(client)
    return IdentityService(
        IdentityStore(text(config, "store_dsn")),
        OIDCProvider(oidc, client),
        Custody(Path(text(config, "custody_key")).read_bytes()),
        ReceiptSigner(private_key(text(config, "signing_key")), text(config, "signing_key_id")),
        oidc.issuer,
        text(config, "main_origin"),
    )
