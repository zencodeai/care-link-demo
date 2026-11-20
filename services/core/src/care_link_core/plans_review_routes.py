"""Explicit interactive-review context and currently authorized recovery metadata."""

from collections.abc import Awaitable, Callable
from typing import Protocol, cast

from care_link_domain import Actor, ManualError
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

Record = dict[str, object]


class PlansReviewContextPort(Protocol):
    def context(self, host: str) -> Record: ...
    def selection(self, host: str, actor: Actor) -> Record: ...


class WorkspaceGateway(Protocol):
    def review_workspace(self, actor: Actor, session_id: str | None) -> Record: ...


def attach_plans_review_routes(
    app: FastAPI,
    gateway: WorkspaceGateway,
    authenticate: Callable[..., Awaitable[Actor]],
    contexts: PlansReviewContextPort | None,
) -> None:
    from .manual_app import response

    def selected_context(request: Request) -> Record:
        if request.query_params or len(request.headers.getlist("host")) != 1:
            raise ManualError("manual.invalid_review_context", 400)
        if contexts is None:
            return {"enabled": False}
        return contexts.context(request.headers["host"])

    async def context(request: Request) -> JSONResponse:
        return response("PlansReviewContext", selected_context(request))

    async def workspace(request: Request) -> JSONResponse:
        configured = selected_context(request)
        if contexts is None or configured.get("enabled") is not True:
            raise ManualError("manual.review_context_required", 404)
        if configured.get("run_state") != "active":
            raise ManualError("manual.review_closed", 403)
        actor = await authenticate(request)
        if (
            actor.review_run_id != configured.get("run_id")
            or actor.review_slot_id != configured.get("slot_id")
            or actor.review_origin != configured.get("origin")
            or actor.account_id != configured.get("account_id")
            or actor.role != configured.get("role")
        ):
            raise ManualError("manual.review_context_mismatch", 403)
        selection = contexts.selection(request.headers["host"], actor)
        session_id = selection.get("session_id")
        if not isinstance(session_id, str):
            raise ManualError("manual.review_not_ready", 503)
        value = await run_in_threadpool(gateway.review_workspace, actor, session_id)
        current = value.get("conversation")
        if (
            value.get("run_id") != configured["run_id"]
            or value.get("run_state") != "active"
            or not isinstance(current, dict)
            or cast(Record, current).get("id") != session_id
        ):
            raise ManualError("manual.review_context_mismatch", 403)
        # No projection or permission is reconstructed from the registry. The
        # gateway just reauthorized the conversation; plan/report/grant reads
        # retain their individual current-authority checks after recovery.
        return response(
            "PlansReviewWorkspace",
            {"workspace": value, "selection": selection, "expires_at": configured["expires_at"]},
        )

    app.add_api_route("/v1/plans-review/context", context, methods=["GET"])
    app.add_api_route("/v1/plans-review/workspace", workspace, methods=["GET"])
