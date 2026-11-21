"""Thin authenticated optional-assistance actor routes."""

from collections.abc import Callable

from care_link_domain import Actor, ManualError
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from ..planning_routes import Authenticate
from .ports import AssistanceGateway, Record


def attach_assistance_routes(
    app: FastAPI,
    gateway: AssistanceGateway,
    authenticate: Authenticate,
    availability: Callable[[Actor], Record] | None = None,
) -> None:
    from ..manual_app import body, identifier, response

    async def knowledge(request: Request) -> JSONResponse:
        actor = await authenticate(request, mutation=True)
        if request.query_params:
            raise ManualError("manual.invalid_query", 400)
        data = await body(request, "KnowledgeQuery")
        value = await run_in_threadpool(gateway.knowledge, actor, data)
        return response("KnowledgeResults", value)

    app.add_api_route("/v1/assistance/knowledge", knowledge, methods=["POST"])

    async def status(request: Request) -> JSONResponse:
        actor = await authenticate(request)
        if request.query_params:
            raise ManualError("manual.invalid_query", 400)
        value: Record = (
            (await run_in_threadpool(availability, actor))
            if availability
            else {"available": False, "functions": [], "reason": "assistance.function_disabled"}
        )
        return response("AssistanceStatus", value)

    async def create(request: Request) -> JSONResponse:
        actor = await authenticate(request, mutation=True)
        if request.query_params:
            raise ManualError("manual.invalid_query", 400)
        data = await body(request, "TaskCreate")
        key = identifier(request.headers.get("idempotency-key", ""))
        return response("TaskView", await run_in_threadpool(gateway.task_create, actor, key, data))

    app.add_api_route("/v1/assistance", status, methods=["GET"])
    app.add_api_route("/v1/tasks", create, methods=["POST"])

    def query(
        path: str, parameter: str, contract: str, method: Callable[[Actor, str], Record]
    ) -> None:
        async def handle(request: Request) -> JSONResponse:
            actor = await authenticate(request)
            if request.query_params:
                raise ManualError("manual.invalid_query", 400)
            target = identifier(request.path_params[parameter])
            return response(contract, await run_in_threadpool(method, actor, target))

        app.add_api_route(path, handle, methods=["GET"])

    for path, parameter, contract, method in (
        ("/v1/tasks/{task_id}", "task_id", "TaskView", gateway.task_read),
        ("/v1/tasks/{task_id}/context", "task_id", "AssistanceTaskContext", gateway.task_context),
        ("/v1/drafts/{draft_id}", "draft_id", "DraftView", gateway.draft_read),
        (
            "/v1/drafts/{draft_id}/context",
            "draft_id",
            "AssistanceDraftContext",
            gateway.draft_context,
        ),
    ):
        query(path, parameter, contract, method)

    def command(
        path: str,
        parameter: str,
        contract: str,
        output: str,
        method: Callable[[Actor, str, Record, str], Record],
    ) -> None:
        async def handle(request: Request) -> JSONResponse:
            actor = await authenticate(request, mutation=True)
            if request.query_params:
                raise ManualError("manual.invalid_query", 400)
            data = await body(request, contract)
            key = identifier(request.headers.get("idempotency-key", ""))
            target = identifier(request.path_params[parameter])
            return response(output, await run_in_threadpool(method, actor, key, data, target))

        app.add_api_route(path, handle, methods=["POST"])

    for path, parameter, contract, output, method in (
        (
            "/v1/tasks/{task_id}/cancel",
            "task_id",
            "RevisionCommand",
            "TaskView",
            gateway.task_cancel,
        ),
        ("/v1/tasks/{task_id}/revise", "task_id", "TaskCreate", "TaskView", gateway.task_revise),
        (
            "/v1/drafts/{draft_id}/review",
            "draft_id",
            "ReviewCommand",
            "ReviewView",
            gateway.draft_review,
        ),
    ):
        command(path, parameter, contract, output, method)
