"""Closed authenticated governance routes. Browser fields never grant authority."""

import re
from collections.abc import Callable
from typing import cast

from care_link_contracts import validate_contract
from care_link_domain import ManualError
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from .governance_bindings import ROUTES, GovernanceRoute
from .governance_ports import GovernanceGateway, Record
from .planning_routes import Authenticate


def audit_query(request: Request) -> Record:
    data: Record = {}
    for name, value in request.query_params.multi_items():
        if name in data:
            raise ManualError("manual.invalid_query", 400)
        if name == "limit":
            if not value.isascii() or not value.isdecimal() or len(value) > 2:
                raise ManualError("manual.invalid_query", 400)
            if str(int(value)) != value:
                raise ManualError("manual.invalid_query", 400)
            data[name] = int(value)
        else:
            data[name] = value
    validate_contract("AuditQuery", data)
    return data


def attach_governance_routes(app: FastAPI, gateway: GovernanceGateway, actor: Authenticate) -> None:
    from .manual_app import body, identifier, response

    def attach(route: GovernanceRoute) -> None:
        method = cast(Callable[..., Record], getattr(gateway, route.action))

        async def handle(request: Request) -> JSONResponse:
            mutation = route.method == "POST"
            current = await actor(request, mutation=mutation)
            target: list[str] = []
            if route.target == "artifact_digest":
                value = request.path_params[route.target]
                if re.fullmatch(r"[0-9a-f]{64}", value) is None:
                    raise ManualError("manual.invalid_identifier", 400)
                target = [value]
            elif route.target:
                target = [identifier(request.path_params[route.target])]
            if mutation:
                if request.query_params:
                    raise ManualError("manual.invalid_query", 400)
                if route.contract is None:
                    raise ValueError("Mutation route must declare its contract")
                data = await body(request, route.contract)
                key = identifier(request.headers.get("idempotency-key", ""))
                result = await run_in_threadpool(method, current, key, data, *target)
            elif route.contract is not None:
                result = await run_in_threadpool(method, current, *target, audit_query(request))
            else:
                if request.query_params:
                    raise ManualError("manual.invalid_query", 400)
                result = await run_in_threadpool(method, current, *target)
            return response(route.output, result)

        app.add_api_route(route.path, handle, methods=[route.method])

    for route in ROUTES:
        attach(route)
