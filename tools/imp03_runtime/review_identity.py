"""Optional exact actor-origin routing on the existing protected identity mesh."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

from care_link_identity.app import create_app
from care_link_identity.domain import IdentityError
from care_link_identity.manual_runtime import create_manual_identity_app
from care_link_identity.provider import OIDCProvider
from care_link_identity.review import ReviewIdentityRegistry
from care_link_identity.review_context import ReviewContext
from care_link_identity.review_providers import ReviewProviders
from care_link_identity.service import IdentityService
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import record, unique


def load_contexts(path: Path) -> dict[str, ReviewContext]:
    """Read an atomically published non-secret exact allowlist, never DNS authority."""
    source = record(json.loads(path.read_text(), object_pairs_hook=unique))
    result: dict[str, ReviewContext] = {}
    for origin, value in source.items():
        context = record(value)
        if set(context) != {"run_id", "slot_id", "account_id", "provider_subject", "role", "state"}:
            raise ValueError("Exact review identity context fields required")
        result[origin] = ReviewContext(origin=origin, **cast(dict[str, str], context))
    return result


def create_review_identity_surface(
    service: IdentityService,
    contexts_file: Path,
    workload_verifier: Callable[[Request, str], bool],
    *,
    provider_configs_file: Path | None = None,
) -> ASGIApp:
    """Only the authenticated core BFF supplies the originating browser context."""

    def contexts() -> dict[str, ReviewContext]:
        return load_contexts(contexts_file)

    if provider_configs_file is not None:
        if not isinstance(service.provider, OIDCProvider):
            raise ValueError("Configured OIDC provider required for private review catalog")
        providers = ReviewProviders(service.provider, contexts, provider_configs_file)
    else:
        providers = None
    registry = ReviewIdentityRegistry(service, contexts, providers)
    internal = create_manual_identity_app(
        service, workload_verifier, service_for_session=registry.session_service
    )
    legacy = create_app(service, ui_return_url=service.origin + "/")

    async def surface(scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if not path.startswith("/bff/main/"):
            await internal(scope, receive, send)
            return
        request = Request(scope, receive)
        if not workload_verifier(request, "core"):
            await JSONResponse({"state": "workload_denied"}, status_code=403)(scope, receive, send)
            return
        origin = request.headers.get("x-care-link-browser-origin")
        try:
            if origin == service.origin:
                browser = legacy
            elif origin:
                selected = registry.browser_service(origin)
                browser = create_app(selected, ui_return_url=selected.origin + "/")
            else:
                raise IdentityError("identity.review_origin_required")
        except (IdentityError, ValueError, OSError) as error:
            status = error.status if isinstance(error, IdentityError) else 503
            await JSONResponse(
                {
                    "state": "review_origin_denied"
                    if status < 500
                    else "review_registry_unavailable"
                },
                status_code=status,
                headers={"Cache-Control": "no-store"},
            )(scope, receive, send)
            return
        local = dict(scope)
        local["path"] = path.removeprefix("/bff/main")
        local["raw_path"] = local["path"].encode()
        await browser(cast(Scope, local), receive, send)

    return surface
