"""Thin browser BFF forwarding and immutable built client delivery."""

from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

# Never forward incoming hop-by-hop, proxy identity or peer-certificate headers.
REQUEST_HEADERS = frozenset(
    {"accept", "content-type", "origin", "cookie", "x-csrf-token", "idempotency-key"}
)
RESPONSE_HEADERS = frozenset(
    {
        "content-type",
        "cache-control",
        "pragma",
        "location",
        "x-proof-intent-id",
        "x-ceremony-id",
        "referrer-policy",
        "content-security-policy",
        "x-content-type-options",
    }
)


def add_auth_proxy(app: FastAPI, client: httpx.Client, authority: str, role: str) -> None:
    if role not in {"main", "help"}:
        raise ValueError("Exact BFF context required")

    async def forward(request: Request) -> Response:
        from starlette.concurrency import run_in_threadpool

        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 65536:
                return JSONResponse({"state": "invalid_request"}, status_code=413)
        target = authority + "/bff/" + role + request.url.path
        if request.url.query:
            target += "?" + request.url.query
        headers = {
            key: value for key, value in request.headers.items() if key.lower() in REQUEST_HEADERS
        }
        # A shared upstream client must never fill an absent browser Cookie
        # header from another browser's response cookie jar.
        headers["cookie"] = request.headers.get("cookie", "")
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
            if key.decode().lower() in RESPONSE_HEADERS | {"set-cookie"}
        ]
        return response

    # Exact routes only; no generic proxy exposing identity internals.
    routes = {
        "/v1/auth/csrf": ["GET"],
        "/v1/auth/login": ["POST"],
        "/v1/auth/callback": ["GET"],
        "/v1/auth/session": ["GET"],
        "/v1/auth/logout": ["POST"],
        "/v1/auth/step-up": ["POST"],
        "/v1/auth/step-up/confirm": ["POST"],
        "/v1/auth/step-up/proof": ["GET"],
    }
    for path, methods in routes.items():
        app.add_api_route(path, forward, methods=methods)


def add_client(app: FastAPI, directory: Path, *, help_surface: bool = False) -> None:
    if not (directory / "index.html").is_file():
        raise ValueError("Built client bundle required")
    if help_surface:

        async def help_index() -> FileResponse:
            return FileResponse(directory / "index.html")

        app.add_api_route("/private-help", help_index, methods=["GET"])
    app.mount("/", StaticFiles(directory=directory, html=True))


def secure_surface(app: FastAPI, help_api: ASGIApp | None = None) -> ASGIApp:
    async def headers(request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        public_client = request.url.path in {"/", "/private-help"} or request.url.path.startswith(
            "/assets/"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
            "img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
            if public_client
            else "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    app.middleware("http")(headers)

    async def application(scope: Scope, receive: Receive, send: Send) -> None:
        if help_api is not None and scope["type"] == "http" and scope["path"].startswith("/help/"):
            await help_api(scope, receive, send)
            return
        await app(scope, receive, send)

    return application
