"""Explicit recovery browser composition; authority remains in the host coordinator."""

from typing import Protocol

from care_link_domain import Actor, ManualError
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from .planning_routes import Authenticate

Record = dict[str, object]


class RecoveryGateway(Protocol):
    def execute(
        self,
        operation: str,
        actor: Actor,
        body: Record | None = None,
        resource_id: str | None = None,
        command_id: str | None = None,
    ) -> Record: ...


# The evidence reads are additive projections of the closed PromotionBinding.
ROUTES = (
    ("backup_capture", "/backups", "POST", "Empty", "BackupView", None),
    ("backup_read", "/backups/{backup_id}", "GET", None, "BackupView", "backup_id"),
    ("restore_create", "/targets", "POST", "RestoreCreate", "RestoreView", None),
    ("restore_read", "/targets/{target_id}", "GET", None, "RestoreView", "target_id"),
    (
        "restore_validate",
        "/targets/{target_id}/validate",
        "POST",
        "RevisionCommand",
        "RestoreView",
        "target_id",
    ),
    ("promotion_propose", "/promotions/propose", "POST", "PromotionPropose", "CommandResult", None),
    ("promotion_approve", "/promotions/approve", "POST", "PromotionApprove", "CommandResult", None),
    ("promotion_execute", "/promotions/execute", "POST", "PromotionExecute", "CommandResult", None),
    ("promotion_read", "/promotions/{proposal_id}", "GET", None, "PromotionView", "proposal_id"),
    (
        "evidence_target",
        "/targets/{target_id}/evidence",
        "GET",
        None,
        "PromotionBinding",
        "target_id",
    ),
    (
        "evidence_promotion",
        "/promotions/{proposal_id}/evidence",
        "GET",
        None,
        "PromotionBinding",
        "proposal_id",
    ),
)


def attach_recovery_routes(
    app: FastAPI, gateway: RecoveryGateway, authenticate: Authenticate
) -> None:
    from .manual_app import body, identifier, response

    def attach(
        operation: str,
        path: str,
        verb: str,
        contract: str | None,
        output: str,
        resource: str | None,
    ) -> None:
        async def handle(request: Request) -> JSONResponse:
            if request.query_params:
                raise ManualError("manual.invalid_query", 400)
            mutation = verb == "POST"
            actor = await authenticate(request, mutation=mutation)
            target = identifier(request.path_params[resource]) if resource else None
            data = await body(request, contract) if contract else None
            key = identifier(request.headers.get("idempotency-key", "")) if mutation else None
            result = await run_in_threadpool(gateway.execute, operation, actor, data, target, key)
            return response(output, result)

        app.add_api_route("/v1/recovery" + path, handle, methods=[verb])

    for route in ROUTES:
        attach(*route)
