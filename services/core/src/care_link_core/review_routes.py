"""Browser review transport: public context, authorized recovery and page leases."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Protocol, cast

from care_link_domain import Actor, ManualError
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, StreamingResponse

from .manual_channels import ManualChannels
from .review_channels import ReviewViews
from .review_context import ReviewContexts

Record = dict[str, object]


class ReviewGateway(Protocol):
    def review_workspace(self, actor: Actor, session_id: str | None) -> Record: ...
    def review_intent_cancel(
        self, actor: Actor, key: str, data: Record, session_id: str
    ) -> Record: ...

    def review_draft_save(
        self, actor: Actor, key: str, data: Record, session_id: str
    ) -> Record: ...
    def review_intent_prepare(
        self, actor: Actor, key: str, data: Record, session_id: str
    ) -> Record: ...


def add_review_routes(
    app: FastAPI,
    gateway: ReviewGateway,
    channels: ManualChannels,
    views: ReviewViews,
    current_actor: Callable[..., Awaitable[Actor]],
    contexts: ReviewContexts | None,
) -> None:
    from .manual_app import HEADERS, body, identifier, response

    async def context(request: Request) -> JSONResponse:
        value = (
            contexts.context(request.headers.get("host", "")) if contexts else {"enabled": False}
        )
        return JSONResponse(value, headers=HEADERS)

    async def register(request: Request) -> JSONResponse:
        actor = await current_actor(request, mutation=True, require_view=False)
        await body(request, "Empty")
        return JSONResponse(views.register(actor), headers=HEADERS)

    async def claim(request: Request) -> JSONResponse:
        actor = await current_actor(request, mutation=True, require_view=False)
        value = await body(request, "RevisionCommand")
        return JSONResponse(
            views.claim(
                actor,
                request.headers.get("x-review-view", ""),
                cast(str, value["expected_revision"]),
            ),
            headers=HEADERS,
        )

    async def inspect(request: Request) -> JSONResponse:
        actor = await current_actor(request)
        return JSONResponse(
            views.inspect(actor, request.headers.get("x-review-view", "")), headers=HEADERS
        )

    async def workspace(request: Request) -> JSONResponse:
        actor = await current_actor(request)
        if not actor.review_run_id:
            raise ManualError("manual.review_context_required")
        if set(request.query_params) - {"session_id"}:
            raise ManualError("manual.invalid_query", 400)
        raw = request.query_params.get("session_id")
        selected = identifier(raw) if raw else None
        return response(
            "ReviewWorkspace", await run_in_threadpool(gateway.review_workspace, actor, selected)
        )

    async def stream(request: Request) -> StreamingResponse:
        actor = await current_actor(request)
        handle = request.headers.get("x-review-view", "")
        views.require(actor, handle)

        async def events() -> AsyncIterator[str]:
            with channels.open(actor) as connected:
                try:
                    while not await request.is_disconnected():
                        fresh = await current_actor(request)
                        views.require(fresh, handle)
                        if fresh.transport_generation != connected.transport_generation:
                            break
                        channels.heartbeat(fresh)
                        # Presence is transport readiness, never a human ACK.
                        yield "event: ready\ndata: {}\n\n"
                        await asyncio.sleep(2)
                except ManualError:
                    yield "event: lost\ndata: {}\n\n"

        return StreamingResponse(
            events(), media_type="text/event-stream", headers={**HEADERS, "X-Accel-Buffering": "no"}
        )

    for path, contract, output, method in (
        ("draft", "ReviewDraftSave", "ReviewDraftView", gateway.review_draft_save),
        ("intent", "ReviewIntentPrepare", "ReviewIntentView", gateway.review_intent_prepare),
        ("intent/cancel", "ReviewIntentCancel", "ReviewIntentView", gateway.review_intent_cancel),
    ):

        def route(
            input_name: str, output_name: str, action: Callable[[Actor, str, Record, str], Record]
        ) -> Callable[[Request], Awaitable[JSONResponse]]:
            async def handler(request: Request) -> JSONResponse:
                actor = await current_actor(request, mutation=True)
                payload = await body(request, input_name)
                return response(
                    output_name,
                    await run_in_threadpool(
                        action,
                        actor,
                        identifier(request.headers.get("idempotency-key", "")),
                        payload,
                        identifier(request.path_params["session_id"]),
                    ),
                )

            return handler

        app.add_api_route(
            "/v1/review/sessions/{session_id}/" + path,
            route(contract, output, method),
            methods=["POST"],
        )
    app.add_api_route("/v1/review/context", context, methods=["GET"])
    app.add_api_route("/v1/review/view", register, methods=["POST"])
    app.add_api_route("/v1/review/view", inspect, methods=["GET"])
    app.add_api_route("/v1/review/view/claim", claim, methods=["POST"])
    app.add_api_route("/v1/review/workspace", workspace, methods=["GET"])
    app.add_api_route("/v1/review/events", stream, methods=["GET"])
