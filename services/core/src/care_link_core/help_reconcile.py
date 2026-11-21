"""Internal authenticated opaque-help reconciliation; never a browser endpoint."""

from collections.abc import Callable
from typing import Protocol

from care_link_domain import ManualError
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

Record = dict[str, object]


class HelpReconciler(Protocol):
    def reconcile(self, request: Record, command_id: str) -> Record: ...


def attach_help_reconcile(
    app: FastAPI, reconciler: HelpReconciler, verify_help_workload: Callable[[Request], bool]
) -> None:
    from .manual_app import body, identifier, response

    async def handle(request: Request) -> JSONResponse:
        # A body account/role or browser session cannot confer workload authority.
        if not verify_help_workload(request):
            raise ManualError("recovery.help_workload_denied")
        if request.query_params:
            raise ManualError("manual.invalid_query", 400)
        data = await body(request, "HelpReconcile")
        key = identifier(request.headers.get("idempotency-key", ""))
        result = await run_in_threadpool(reconciler.reconcile, data, key)
        return response("CommandResult", result)

    app.add_api_route("/internal/v1/help/reconcile", handle, methods=["POST"])
