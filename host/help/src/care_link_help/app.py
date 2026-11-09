"""Thin help transport. Composition requires a separate current help-origin BFF."""

import secrets
from dataclasses import dataclass
from typing import cast
from uuid import UUID, uuid4

from care_link_contracts import ContractError, parse_contract
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from .model import Action, BrowserSessions, HelpError, Wire
from .service import HelpService


@dataclass(frozen=True)
class HelpConfig:
    origin: str
    cookie_name: str = "__Host-care_link_help"
    static_url: str = "/static/"

    def __post_init__(self) -> None:
        from urllib.parse import urlsplit

        parsed = urlsplit(self.origin)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError("help requires an exact private HTTPS origin")
        if not self.cookie_name.startswith("__Host-"):
            raise ValueError("help requires host-only secure cookie naming")


def create_app(
    config: HelpConfig, service: HelpService | None = None, sessions: BrowserSessions | None = None
) -> FastAPI:
    """Unconfigured instances expose unavailable status and no private effects."""
    app = FastAPI(title="CARE-Link private help", docs_url=None, redoc_url=None, openapi_url=None)

    async def security_headers(request: Request, call_next: RequestResponseEndpoint) -> Response:
        return await _secure_response(request, call_next)

    async def operation(
        request: Request, action: Action, help_id: str | None = None, prepare: bool = False
    ) -> JSONResponse:
        try:
            if service is None or sessions is None:
                raise HelpError("help.identity_unavailable", 503)
            verified_sessions = sessions
            cookie = request.cookies.get(config.cookie_name)
            if not cookie:
                raise HelpError("help.login_required", 401)
            context = await run_in_threadpool(sessions.context, cookie)
            if action != "status":
                if (
                    request.headers.get("origin") != config.origin
                    or not secrets.compare_digest(
                        request.headers.get("x-csrf-token", ""), context.csrf_token
                    )
                    or not context.csrf_token
                ):
                    raise HelpError("help.csrf_denied")
                key = request.headers.get("idempotency-key", "")
                if not prepare and str(UUID(key)) != key:
                    raise HelpError("help.invalid_request", 400)
                if request.headers.get("content-encoding") is not None:
                    raise HelpError("help.invalid_request", 415)
                content_type = request.headers.get("content-type", "").lower().replace(" ", "")
                if content_type not in {"application/json", "application/json;charset=utf-8"}:
                    raise HelpError("help.json_required", 415)
                body_bytes = bytearray()
                async for chunk in request.stream():
                    if len(body_bytes) + len(chunk) > 65536:
                        raise HelpError("help.body_too_large", 413)
                    body_bytes.extend(chunk)
                body = cast(
                    Wire,
                    parse_contract(
                        "HelpCreate" if action == "create" else "RevisionCommand",
                        body_bytes.decode("utf-8"),
                    ),
                )
            else:
                if request.query_params:
                    raise HelpError("help.invalid_request", 400)
                key, body = str(uuid4()), {}
            if help_id is not None and str(UUID(help_id)) != help_id:
                raise HelpError("help.invalid_request", 400)
            if prepare:
                result = await run_in_threadpool(
                    service.prepare_create,
                    body,
                    context,
                    lambda: verified_sessions.proof(cookie, config.origin),
                )
                return JSONResponse(result)
            proof = await run_in_threadpool(sessions.proof, cookie, config.origin)
            result = await run_in_threadpool(
                service.execute,
                action=action,
                operation_id=key,
                help_id=help_id,
                body=body,
                context=context,
                proof_ref=proof,
            )
            return JSONResponse(result)
        except HelpError as error:
            return JSONResponse(
                {"message_key": error.code, "static_url": config.static_url},
                status_code=error.status,
            )
        except (ContractError, ValueError, UnicodeError):
            return JSONResponse({"message_key": "help.invalid_request"}, status_code=400)

    async def create(request: Request) -> JSONResponse:
        return await operation(request, "create")

    async def create_intent(request: Request) -> JSONResponse:
        return await operation(request, "create", prepare=True)

    async def status(request: Request, help_id: str) -> JSONResponse:
        return await operation(request, "status", help_id)

    async def accept(request: Request, help_id: str) -> JSONResponse:
        return await operation(request, "accept", help_id)

    async def cancel(request: Request, help_id: str) -> JSONResponse:
        return await operation(request, "cancel", help_id)

    async def health() -> JSONResponse:
        return JSONResponse(
            {
                "alive": True,
                "participant_admission": False,
                "private_help": "configured_unqualified" if service and sessions else "unavailable",
            }
        )

    app.middleware("http")(security_headers)
    app.add_api_route("/help/v1/requests", create, methods=["POST"])
    app.add_api_route("/help/v1/create-intent", create_intent, methods=["POST"])
    app.add_api_route("/help/v1/requests/{help_id}", status, methods=["GET"])
    app.add_api_route("/help/v1/requests/{help_id}/accept", accept, methods=["POST"])
    app.add_api_route("/help/v1/requests/{help_id}/cancel", cancel, methods=["POST"])
    app.add_api_route("/help/health", health, methods=["GET"])
    return app


async def _secure_response(request: Request, call_next: RequestResponseEndpoint) -> Response:
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
