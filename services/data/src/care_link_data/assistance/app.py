"""Named signed data-gateway routes for optional assistance."""

from collections.abc import Callable
from typing import cast

from care_link_contracts import validate_contract
from care_link_domain import Actor
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from ..planning_app import Envelope
from ..store import Record
from .review import AssistanceCoordinator


def attach_assistance_gateway(
    app: FastAPI, service: AssistanceCoordinator, envelope: Envelope
) -> None:
    async def create(request: Request) -> JSONResponse:
        actor, key, arguments, _paths = await envelope(request, "task_create")
        result = await run_in_threadpool(service.task_create, actor, key, arguments)
        validate_contract("TaskView", result)
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    app.add_api_route("/internal/v1/data/task_create", create, methods=["POST"])

    def query(
        name: str, parameter: str, output: str, method: Callable[[Actor, str], Record]
    ) -> None:
        async def handle(request: Request) -> JSONResponse:
            actor, _key, _args, paths = await envelope(request, name)
            result = await run_in_threadpool(method, actor, cast(str, paths[parameter]))
            validate_contract(output, result)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})

        app.add_api_route("/internal/v1/data/" + name, handle, methods=["POST"])

    for name, parameter, output, method in (
        ("task_read", "task_id", "TaskView", service.task_read),
        ("assistance_task_context", "task_id", "AssistanceTaskContext", service.task_context),
        ("draft_read", "draft_id", "DraftView", service.draft_read),
        ("assistance_draft_context", "draft_id", "AssistanceDraftContext", service.draft_context),
    ):
        query(name, parameter, output, method)

    def command(
        name: str, parameter: str, output: str, method: Callable[[Actor, str, Record, str], Record]
    ) -> None:
        async def handle(request: Request) -> JSONResponse:
            actor, key, args, paths = await envelope(request, name)
            result = await run_in_threadpool(method, actor, key, args, cast(str, paths[parameter]))
            validate_contract(output, result)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})

        app.add_api_route("/internal/v1/data/" + name, handle, methods=["POST"])

    for name, parameter, output, method in (
        ("task_cancel", "task_id", "TaskView", service.task_cancel),
        ("task_revise", "task_id", "TaskView", service.task_revise),
        ("draft_review", "draft_id", "ReviewView", service.draft_review),
    ):
        command(name, parameter, output, method)
