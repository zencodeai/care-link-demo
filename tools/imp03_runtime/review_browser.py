"""Exact actor-origin auth forwarding; caller headers never select a workspace."""

import httpx
from care_link_core.review_context import ReviewContexts
from care_link_domain import ManualError
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from tools.imp02_application.browser import REQUEST_HEADERS, RESPONSE_HEADERS


def add_review_auth_proxy(
    app: FastAPI,
    client: httpx.Client,
    authority: str,
    contexts: ReviewContexts,
) -> None:
    async def forward(request: Request) -> Response:
        try:
            hosts = request.headers.getlist("host")
            if len(hosts) != 1:
                raise ManualError("manual.review_origin_denied")
            origin = contexts.origin(hosts[0])
        except (ManualError, OSError, ValueError) as error:
            status = error.status if isinstance(error, ManualError) else 503
            return JSONResponse(
                {
                    "state": "review_origin_denied"
                    if status < 500
                    else "review_registry_unavailable"
                },
                status_code=status,
                headers={"Cache-Control": "no-store"},
            )
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 65536:
                return JSONResponse({"state": "invalid_request"}, status_code=413)
        target = authority + "/bff/main" + request.url.path
        if request.url.query:
            target += "?" + request.url.query
        headers = {
            key: value for key, value in request.headers.items() if key.lower() in REQUEST_HEADERS
        }
        headers["cookie"] = request.headers.get("cookie", "")
        headers["x-care-link-browser-origin"] = origin
        try:
            upstream = await run_in_threadpool(
                client.request,
                request.method,
                target,
                headers=headers,
                content=bytes(raw),
                timeout=30,
                follow_redirects=False,
            )
        except httpx.HTTPError:
            return JSONResponse(
                {"state": "identity_unavailable"},
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )
        response = Response(upstream.content, status_code=upstream.status_code)
        response.raw_headers = [
            (key, value)
            for key, value in upstream.headers.raw
            if key.decode().lower()
            in RESPONSE_HEADERS
            | {"set-cookie", "x-care-link-authentication-mode", "x-care-link-review-expires-at"}
        ]
        return response

    for path, methods in {
        "/v1/auth/csrf": ["GET"],
        "/v1/auth/login": ["POST"],
        "/v1/auth/callback": ["GET"],
        "/v1/auth/session": ["GET"],
        "/v1/auth/logout": ["POST"],
        "/v1/auth/step-up": ["POST"],
        "/v1/auth/step-up/confirm": ["POST"],
        "/v1/auth/step-up/proof": ["GET"],
        "/v1/auth/continuation-recovery": ["POST"],
        "/v1/auth/review/login": ["POST"],
        "/v1/auth/review/verify": ["POST"],
    }.items():
        app.add_api_route(path, forward, methods=methods)


def review_origin_guard(app: ASGIApp, contexts: ReviewContexts) -> ASGIApp:
    """Reject unregistered authorities before serving either assets or APIs."""

    async def guarded(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path", "").startswith("/internal/"):
            await app(scope, receive, send)
            return
        request = Request(scope)
        try:
            hosts = request.headers.getlist("host")
            if len(hosts) != 1:
                raise ManualError("manual.review_origin_denied")
            contexts.origin(hosts[0])
        except (ManualError, OSError, ValueError) as error:
            status = error.status if isinstance(error, ManualError) else 503
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
        await app(scope, receive, send)

    return guarded
