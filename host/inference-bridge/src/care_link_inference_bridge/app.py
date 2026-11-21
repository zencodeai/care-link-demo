"""Authenticated bridge transport. Public listeners fail closed without verifier."""

from collections.abc import Callable
from datetime import datetime
from typing import Protocol, cast

from fastapi import FastAPI, Request, Response

from .tokenization import TokenizerPort


class ModelPort(Protocol):
    def complete(self, payload: dict[str, object], deadline: datetime) -> bytes: ...


def create_app(
    bridge: ModelPort,
    verify: Callable[[Request, str], bool],
    *,
    counter: TokenizerPort | None = None,
) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    async def execute(request: Request) -> Response:
        if not verify(request, "inference"):
            return Response(status_code=403)
        # Parse bounded duplicate-free JSON; the envelope is server-to-server.
        raw = await request.body()
        if len(raw) > 262144:
            return Response(status_code=413)
        import json

        def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate key")
                result[key] = value
            return result

        try:
            value: object = json.loads(raw, object_pairs_hook=unique)
            if not isinstance(value, dict) or set(cast(dict[str, object], value)) != {
                "payload",
                "deadline",
            }:
                raise ValueError("invalid bridge envelope")
            if not isinstance(value["deadline"], str) or not value["deadline"].endswith("Z"):
                raise ValueError("UTC deadline required")
            deadline = datetime.fromisoformat(value["deadline"].replace("Z", "+00:00"))
            if not isinstance(value["payload"], dict):
                raise ValueError("invalid payload")
            # Run blocking fixed transport outside the ASGI event loop.
            from starlette.concurrency import run_in_threadpool

            result = await run_in_threadpool(
                bridge.complete, cast(dict[str, object], value["payload"]), deadline
            )
            return Response(result, media_type="application/json")
        except (ValueError, RecursionError):
            return Response(status_code=400)
        except (TimeoutError, OSError):
            return Response(status_code=503)

    import threading

    tokenizer_slots = threading.BoundedSemaphore(2)

    async def tokenize(request: Request) -> Response:
        if not verify(request, "inference"):
            return Response(status_code=403)
        if counter is None:
            return Response(status_code=503)
        tokenizer = counter
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > 262144:
                return Response(status_code=413)
            raw.extend(chunk)
        import json

        def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
            value: dict[str, object] = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError("duplicate key")
                value[key] = item
            return value

        from .tokenization import TokenizationDenied, closed_messages, content_digest

        try:
            value = cast(dict[str, object], json.loads(raw, object_pairs_hook=unique))
            if set(value) != {"messages", "content_digest"}:
                raise ValueError("closed tokenize request required")
            messages = closed_messages(value["messages"])
            if value["content_digest"] != content_digest(messages):
                raise ValueError("tokenize content binding mismatch")
        except (ValueError, TypeError, RecursionError):
            return Response(status_code=400)
        if not tokenizer_slots.acquire(blocking=False):
            return Response(status_code=503)

        def count() -> bytes:
            from dataclasses import asdict

            try:
                result = tokenizer.count(messages)
                return json.dumps(asdict(result), sort_keys=True, separators=(",", ":")).encode()
            finally:
                # A timed-out request does not free a still-running tokenizer.
                tokenizer_slots.release()

        from asyncio import wait_for

        from starlette.concurrency import run_in_threadpool

        try:
            result = await wait_for(run_in_threadpool(count), timeout=10)
            return Response(
                result, media_type="application/json", headers={"Cache-Control": "no-store"}
            )
        except (TokenizationDenied, TimeoutError, OSError):
            return Response(status_code=503)

    app.add_api_route("/internal/v1/inference/tokenize", tokenize, methods=["POST"])
    app.add_api_route("/internal/v1/inference/execute", execute, methods=["POST"])
    return app
