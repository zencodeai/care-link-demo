"""Named authenticated internal planning handlers; no browser authority inputs."""

from collections.abc import Awaitable, Callable
from typing import cast

from care_link_contracts import validate_contract
from care_link_domain import Actor
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from .control import ManualService
from .store import Record

Envelope = Callable[[Request, str], Awaitable[tuple[Actor, str, Record, Record]]]


def attach_planning_gateway(app: FastAPI, service: ManualService, envelope: Envelope) -> None:
    def command(name: str, output: str, method: Callable[[Actor, str, Record], Record]) -> None:
        async def handle(request: Request) -> JSONResponse:
            actor, key, arguments, _paths = await envelope(request, name)
            value = await run_in_threadpool(method, actor, key, arguments)
            validate_contract(output, value)
            return JSONResponse(value, headers={"Cache-Control": "no-store"})

        app.add_api_route("/internal/v1/data/" + name, handle, methods=["POST"])

    for name, output, method in (
        ("plan_create", "PlanView", service.plan_create),
        ("consent_grant", "ConsentView", service.consent_grant),
        ("directory_search", "DirectoryPage", service.directory_search),
        ("directory_ingest", "DirectoryView", service.directory_ingest),
    ):
        command(name, output, method)

    def target_command(
        name: str,
        parameter: str,
        output: str,
        method: Callable[[Actor, str, Record, str], Record],
    ) -> None:
        async def handle(request: Request) -> JSONResponse:
            actor, key, arguments, paths = await envelope(request, name)
            value = await run_in_threadpool(
                method, actor, key, arguments, cast(str, paths[parameter])
            )
            validate_contract(output, value)
            return JSONResponse(value, headers={"Cache-Control": "no-store"})

        app.add_api_route("/internal/v1/data/" + name, handle, methods=["POST"])

    for name, parameter, output, method in (
        ("plan_field_append", "plan_id", "PlanView", service.plan_field_append),
        ("plan_retire", "plan_id", "PlanView", service.plan_retire),
        ("consent_revoke", "grant_id", "CommandResult", service.consent_revoke),
        ("directory_suspend", "service_id", "CommandResult", service.directory_suspend),
    ):
        target_command(name, parameter, output, method)

    def query(
        name: str, parameter: str, output: str, method: Callable[[Actor, str], Record]
    ) -> None:
        async def handle(request: Request) -> JSONResponse:
            actor, _key, _arguments, paths = await envelope(request, name)
            value = await run_in_threadpool(method, actor, cast(str, paths[parameter]))
            validate_contract(output, value)
            return JSONResponse(value, headers={"Cache-Control": "no-store"})

        app.add_api_route("/internal/v1/data/" + name, handle, methods=["POST"])

    query("plan_read", "plan_id", "PlanView", service.plan_read)
    query("own_reports_read", "session_id", "OwnReportPage", service.own_reports_read)
    query("consent_read", "grant_id", "ConsentView", service.consent_read)
    query("directory_read", "service_id", "DirectoryView", service.directory_read)
