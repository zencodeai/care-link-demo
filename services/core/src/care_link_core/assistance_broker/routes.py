"""Verified workload routes. Runtime supplies task references, never actor context."""

from collections.abc import Callable
from typing import cast

from care_link_domain import WorkloadPeer
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from .broker import InferenceBroker


def attach_broker_routes(
    app: FastAPI,
    broker: InferenceBroker,
    verify: Callable[[Request], WorkloadPeer],
) -> None:
    from ..manual_app import body, identifier, response

    async def work(request: Request) -> JSONResponse:
        peer = await run_in_threadpool(verify, request)
        identifier(request.headers.get("idempotency-key", ""))
        from care_link_domain import ManualError

        if request.query_params:
            raise ManualError("manual.invalid_query", 400)
        await body(request, "RuntimeWorkRequest")
        result = await run_in_threadpool(broker.claim_work, peer)
        if await run_in_threadpool(verify, request) != peer:
            raise ManualError("assistance.runtime_changed", 403)
        return response("RuntimeWorkItem", result)

    app.add_api_route("/internal/v1/broker/work", work, methods=["POST"])

    async def lease(request: Request) -> JSONResponse:
        peer = await run_in_threadpool(verify, request)
        data = await body(request, "LeaseCommand")
        identifier(request.headers.get("idempotency-key", ""))
        task_id = identifier(request.path_params["task_id"])
        from care_link_domain import ManualError

        if request.query_params:
            raise ManualError("manual.invalid_query", 400)
        result = await run_in_threadpool(
            broker.lease, task_id, data, peer, renew=request.url.path.endswith("/renew")
        )
        if await run_in_threadpool(verify, request) != peer:
            raise ManualError("assistance.runtime_changed", 403)
        return response("LeaseView", result)

    for ending in ("lease", "renew"):
        app.add_api_route("/internal/v1/tasks/{task_id}/" + ending, lease, methods=["POST"])

    def operation(path: str, contract: str, output: str) -> None:
        async def handle(request: Request) -> JSONResponse:
            peer = await run_in_threadpool(verify, request)
            identifier(request.headers.get("idempotency-key", ""))
            from care_link_domain import ManualError

            if request.query_params:
                raise ManualError("manual.invalid_query", 400)
            data = await body(request, contract)
            method = (
                broker.infer
                if contract == "RuntimeInferenceRequest"
                else broker.propose
                if contract == "Proposal"
                else broker.tool
            )
            result = await run_in_threadpool(method, data, peer)
            # A long model call cannot retain the authority of a runtime that
            # has been fenced while its request was in flight.
            if await run_in_threadpool(verify, request) != peer:
                raise ManualError("assistance.runtime_changed", 403)
            return response(output, result)

        app.add_api_route(path, cast(Callable[..., object], handle), methods=["POST"])

    operation("/internal/v1/broker/inference", "RuntimeInferenceRequest", "InferenceResult")
    operation("/internal/v1/broker/proposals", "Proposal", "TaskView")
    operation("/internal/v1/broker/tools", "ToolInvoke", "Observation")
