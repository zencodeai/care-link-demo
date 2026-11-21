"""Broker-only network adapter; actor and runtime peer derive from verified delegation.

The authentication callback must verify the Core broker workload, signed task
binding and a fresh server-held initiating actor. Nothing in the request body is
an actor, role, capability token or trusted context. These routes are opt-in.
"""

from collections.abc import Awaitable, Callable
from typing import cast

from care_link_contracts import parse_contract, validate_contract
from care_link_domain import Actor, ManualError, WorkloadPeer
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from ..store import Record
from .review import AssistanceCoordinator

RuntimeAuthenticate = Callable[[Request, str, str], Awaitable[tuple[Actor, WorkloadPeer]]]


def attach_assistance_runtime_gateway(
    app: FastAPI, service: AssistanceCoordinator, authenticate: RuntimeAuthenticate
) -> None:
    """Expose only to the fixed Core workload with verified delegated task scope."""

    def add(operation: str, contract: str, output: str) -> None:
        async def handle(request: Request) -> JSONResponse:
            if request.query_params:
                raise ManualError("manual.invalid_query", 400)
            raw = await request.body()
            if len(raw) > 65536:
                raise ManualError("manual.invalid_body", 413)
            data = cast(Record, parse_contract(contract, raw.decode("utf-8")))
            tid = str(request.path_params.get("task_id") or data.get("task_id"))
            actor, peer = await authenticate(request, operation, tid)
            if operation == "step_lease":
                result = await run_in_threadpool(service.step_lease, actor, tid, data, peer)
            elif operation == "step_renew":
                result = await run_in_threadpool(service.step_renew, actor, tid, data, peer)
            elif operation == "tool_invoke":
                result = await run_in_threadpool(service.tool_invoke, actor, data, peer)
            elif operation == "reserve_proposal":
                result = await run_in_threadpool(service.reserve_proposal, actor, data, peer)
            else:
                reservation = request.headers.get("X-Assistance-Reservation", "")
                if not reservation:
                    raise ManualError("assistance.proposal_reservation", 409)
                result = await run_in_threadpool(
                    service.proposal_submit, actor, data, peer, reservation
                )
            if output:
                validate_contract(output, result)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})

        suffix = "/{task_id}" if operation in {"step_lease", "step_renew"} else ""
        app.add_api_route(
            "/internal/v1/data/assistance/" + operation + suffix, handle, methods=["POST"]
        )

    add("step_lease", "LeaseCommand", "LeaseView")
    add("step_renew", "LeaseCommand", "LeaseView")
    add("tool_invoke", "ToolInvoke", "Observation")
    add("reserve_proposal", "RuntimeInferenceRequest", "")
    add("proposal_submit", "Proposal", "DraftView")
