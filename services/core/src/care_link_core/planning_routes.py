"""Thin actor routes for plans, consent and informational directory options."""

from collections.abc import Callable
from typing import Protocol

from care_link_domain import Actor, ManualError
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from .planning_ports import PlanningGateway, Record


class Authenticate(Protocol):
    async def __call__(
        self, request: Request, *, mutation: bool = False, require_view: bool = True
    ) -> Actor: ...


def attach_planning_routes(app: FastAPI, gateway: PlanningGateway, actor: Authenticate) -> None:
    from .manual_app import body, identifier, response

    def global_command(
        path: str, contract: str, output: str, method: Callable[[Actor, str, Record], Record]
    ) -> None:
        async def handle(request: Request) -> JSONResponse:
            current = await actor(request, mutation=True)
            if request.query_params:
                raise ManualError("manual.invalid_query", 400)
            data = await body(request, contract)
            key = identifier(request.headers.get("idempotency-key", ""))
            result = await run_in_threadpool(method, current, key, data)
            return response(output, result)

        app.add_api_route(path, handle, methods=["POST"])

    for path, contract, output, method in (
        ("/v1/plans", "PlanCreate", "PlanView", gateway.plan_create),
        ("/v1/consents", "ConsentGrant", "ConsentView", gateway.consent_grant),
        ("/v1/directory/search", "DirectoryQuery", "DirectoryPage", gateway.directory_search),
        ("/v1/directory/ingest", "DirectoryIngest", "DirectoryView", gateway.directory_ingest),
    ):
        global_command(path, contract, output, method)

    def target_command(
        path: str,
        parameter: str,
        contract: str,
        output: str,
        method: Callable[[Actor, str, Record, str], Record],
    ) -> None:
        async def handle(request: Request) -> JSONResponse:
            current = await actor(request, mutation=True)
            if request.query_params:
                raise ManualError("manual.invalid_query", 400)
            target = identifier(request.path_params[parameter])
            data = await body(request, contract)
            key = identifier(request.headers.get("idempotency-key", ""))
            return response(output, await run_in_threadpool(method, current, key, data, target))

        app.add_api_route(path, handle, methods=["POST"])

    for path, parameter, contract, output, method in (
        (
            "/v1/plans/{plan_id}/fields",
            "plan_id",
            "PlanFieldCreate",
            "PlanView",
            gateway.plan_field_append,
        ),
        (
            "/v1/plans/{plan_id}/retire",
            "plan_id",
            "RevisionCommand",
            "PlanView",
            gateway.plan_retire,
        ),
        (
            "/v1/consents/{grant_id}/revoke",
            "grant_id",
            "RevisionCommand",
            "CommandResult",
            gateway.consent_revoke,
        ),
        (
            "/v1/directory/{service_id}/suspend",
            "service_id",
            "ReasonCommand",
            "CommandResult",
            gateway.directory_suspend,
        ),
    ):
        target_command(path, parameter, contract, output, method)

    def query(
        path: str, parameter: str, output: str, method: Callable[[Actor, str], Record]
    ) -> None:
        async def handle(request: Request) -> JSONResponse:
            current = await actor(request)
            if request.query_params:
                raise ManualError("manual.invalid_query", 400)
            target = identifier(request.path_params[parameter])
            return response(output, await run_in_threadpool(method, current, target))

        app.add_api_route(path, handle, methods=["GET"])

    query("/v1/plans/{plan_id}", "plan_id", "PlanView", gateway.plan_read)
    query(
        "/v1/sessions/{session_id}/own-reports",
        "session_id",
        "OwnReportPage",
        gateway.own_reports_read,
    )
    query("/v1/consents/{grant_id}", "grant_id", "ConsentView", gateway.consent_read)
    query("/v1/directory/{service_id}", "service_id", "DirectoryView", gateway.directory_read)
