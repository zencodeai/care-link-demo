"""Independent public listener and separately composed authenticated admin listener."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast
from uuid import UUID

from care_link_contracts import ContractError, parse_contract, validate_contract
from fastapi import FastAPI, Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from .publication import Publication, PublicationStore, PublicationUnavailable, PublicText, unique
from .rendering import CONTENT_SECURITY_POLICY, page

HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
}


def create_app(store: PublicationStore | None = None, *, allow_owner_demo: bool = False) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def fallback(locale: str = "en-CA") -> Response:
        try:
            if store is None:
                raise PublicationUnavailable()
            publication = store.current()
            text = next(text for text in publication.texts if text.locale == locale)
            owner_demo = publication.review.profile == "owner_review_local_demo"
            if owner_demo and not allow_owner_demo:
                raise PublicationUnavailable("Owner-demo publication is not enabled")
            return HTMLResponse(page(text, owner_demo=owner_demo), headers=HEADERS)
        except (PublicationUnavailable, StopIteration):
            text = (
                "Reviewed fallback content is unavailable. Private help may also be unavailable. "
                "This engineering demo has no participant admission."
            )
            if locale == "fr-CA":
                text = (
                    "Le contenu de secours vérifié est indisponible. L’aide privée peut aussi "
                    "être indisponible. Cette démonstration n’admet aucun participant."
                )
            safe_locale = locale if locale in {"en-CA", "fr-CA"} else "en-CA"
            return HTMLResponse(
                page(PublicText(safe_locale, "CARE-Link", text)), status_code=503, headers=HEADERS
            )

    def manifest(locale: str = "en-CA") -> JSONResponse:
        try:
            if store is None:
                raise PublicationUnavailable()
            value = store.current().manifest(locale)
            validate_contract("StaticManifest", value)
            return JSONResponse(value, headers=HEADERS)
        except PublicationUnavailable:
            return JSONResponse(
                {"state": "reviewed_content_unavailable", "participant_admission": False},
                status_code=503,
                headers=HEADERS,
            )

    def owner_manifest(locale: str = "en-CA") -> JSONResponse:
        try:
            if store is None or not allow_owner_demo:
                raise PublicationUnavailable("Owner-demo publication is not enabled")
            return JSONResponse(store.current().owner_manifest(locale), headers=HEADERS)
        except PublicationUnavailable:
            return JSONResponse(
                {"state": "owner_reviewed_demo_unavailable", "participant_admission": False},
                status_code=503,
                headers=HEADERS,
            )

    app.add_api_route("/fallback", fallback, methods=["GET"])
    app.add_api_route("/demo-static/v1/manifest", owner_manifest, methods=["GET"])
    app.add_api_route("/static/v1/manifest", manifest, methods=["GET"])
    return app


@dataclass(frozen=True)
class Publisher:
    account_id: str
    role: str
    fresh_mfa: bool
    transport: str = "unverified"


class ResolvePublisher(Protocol):
    def __call__(self, request: Request) -> Publisher:
        """Fresh operator from a non-browser mutually authenticated admin channel.

        Resolve from the protected transport, never caller-supplied identity headers.
        Cookie sessions are not accepted by this admin listener.
        """
        ...


def create_admin_app(
    store: PublicationStore,
    resolve: ResolvePublisher,
    load_artifact: Callable[[str, str], Publication],
    *,
    allow_owner_demo: bool = False,
) -> FastAPI:
    """Bind separately; trusted loader resolves locally staged bytes and review receipt."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    async def publish_selected(request: Request, *, owner_demo: bool) -> JSONResponse:
        try:
            publisher = resolve(request)
            if (
                publisher.role != "operator"
                or not publisher.fresh_mfa
                or publisher.transport != "authenticated_admin_channel"
                or request.headers.get("cookie")
                or request.headers.get("origin")
            ):
                return JSONResponse({"state": "denied"}, status_code=403, headers=HEADERS)
            operation_id = request.headers.get("idempotency-key", "")
            try:
                if str(UUID(operation_id)) != operation_id:
                    raise ValueError()
            except ValueError:
                return JSONResponse(
                    {"state": "invalid_operation_key"}, status_code=400, headers=HEADERS
                )
            if request.headers.get("content-type") != "application/json" or request.headers.get(
                "content-encoding"
            ):
                return JSONResponse({"state": "invalid_request"}, status_code=415, headers=HEADERS)
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 65536:
                    return JSONResponse(
                        {"state": "invalid_request"}, status_code=413, headers=HEADERS
                    )
            if owner_demo:
                if not allow_owner_demo:
                    raise PublicationUnavailable("Owner-demo publication is not enabled")
                raw: object = json.loads(body.decode("utf-8"), object_pairs_hook=unique)
                if not isinstance(raw, dict):
                    raise PublicationUnavailable("Invalid owner-demo publication command")
                owner_request = cast(dict[str, object], raw)
                if set(owner_request) != {
                    "artifact_digest",
                    "owner_review_receipt_id",
                    "expected_current_digest",
                }:
                    raise PublicationUnavailable("Invalid owner-demo publication command")
                # Reuse the reviewed scalar shape constraints internally. The
                # separate wire route/receipt name never claims independent review.
                shape = {
                    "artifact_digest": owner_request["artifact_digest"],
                    "independent_review_receipt_id": owner_request["owner_review_receipt_id"],
                    "expected_current_digest": owner_request["expected_current_digest"],
                }
                validate_contract("StaticPublish", shape)
                value = cast(dict[str, str | None], shape)
            else:
                value = cast(dict[str, str | None], parse_contract("StaticPublish", body.decode()))
            publication = load_artifact(
                str(value["artifact_digest"]), str(value["independent_review_receipt_id"])
            )
            expected_profile = "owner_review_local_demo" if owner_demo else "independent"
            if (
                publication.review.profile != expected_profile
                or publication.artifact_digest != value["artifact_digest"]
                or publication.review.receipt_id != value["independent_review_receipt_id"]
            ):
                raise PublicationUnavailable()
            current = store.publish(
                publication, value["expected_current_digest"], publisher.account_id, operation_id
            )
            manifest = current.owner_manifest("en-CA") if owner_demo else current.manifest("en-CA")
            return JSONResponse(manifest, headers=HEADERS)
        except (PublicationUnavailable, ContractError, UnicodeError, json.JSONDecodeError):
            return JSONResponse({"state": "publication_rejected"}, status_code=409, headers=HEADERS)

    async def publish(request: Request) -> JSONResponse:
        return await publish_selected(request, owner_demo=False)

    async def publish_owner(request: Request) -> JSONResponse:
        return await publish_selected(request, owner_demo=True)

    app.add_api_route("/static-admin/v1/publications", publish, methods=["POST"])
    if allow_owner_demo:
        app.add_api_route("/demo-static-admin/v1/publications", publish_owner, methods=["POST"])
    return app
