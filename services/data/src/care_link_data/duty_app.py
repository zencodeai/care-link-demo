"""Canonical narrow machine-duty routes, separate from the human BFF perimeter."""

import hashlib
import re
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID, uuid4

from care_link_contracts import ContractError, parse_contract, validate_contract
from care_link_domain import DutyActor, ManualError, WorkloadPeer
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from .duties import DutyCommands
from .lifecycle.jobs import LifecycleJobs
from .values import canonical

Record = dict[str, object]


class DutyResolver(Protocol):
    def resolve(
        self,
        delegation: Record,
        *,
        peer: str,
        method: str,
        path: str,
        audience: str,
        body_digest: str,
        operation_id: str,
        request_digest: str,
        credential_ref: str,
    ) -> DutyActor: ...


class DutySecurity(Protocol):
    def verify(self, request: Request, data: Record, action: str, key: str) -> DutyActor: ...


class SignedDutySecurity:
    def __init__(
        self,
        resolver: DutyResolver,
        workload_verifier: Callable[[Request, str], WorkloadPeer | None],
    ) -> None:
        self.resolver, self.workload_verifier = resolver, workload_verifier

    def verify(self, request: Request, data: Record, action: str, key: str) -> DutyActor:
        peer = "identity" if action == "identity_revoke" else "jobs"
        admitted = self.workload_verifier(request, peer)
        expected = "spiffe://care-link.demo/demo/" + peer
        if (
            admitted is None
            or admitted.workload_id != expected
            or re.fullmatch(r"[0-9a-f]{64}", admitted.certificate_digest) is None
            or admitted.certificate_expires_at <= datetime.now(UTC)
        ):
            raise ManualError("manual.workload_denied")
        raw = request.headers.get("x-care-link-delegation", "")
        if len(raw.encode()) > 32768:
            raise ManualError("manual.delegation_too_large", 413)
        delegation = cast(Record, parse_contract("SignedDelegation", raw))
        actor = self.resolver.resolve(
            delegation,
            peer="spiffe://care-link.demo/demo/" + peer,
            method=request.method,
            path=request.url.path,
            audience="care-link-control" if action == "identity_revoke" else "care-link-core",
            body_digest=hashlib.sha256(canonical(data).encode()).hexdigest(),
            operation_id=key,
            request_digest=DutyCommands.binding(action, key, data),
            credential_ref=admitted.certificate_digest,
        )
        if actor.workload_revision != admitted.fence_generation:
            raise ManualError("manual.workload_fence_changed")
        deadlines = [actor.expires_at, admitted.certificate_expires_at]
        if actor.request_deadline is not None:
            deadlines.append(actor.request_deadline)
        deadline = min(deadlines)
        if deadline <= datetime.now(UTC):
            raise ManualError("manual.deadline_exceeded", 503)
        return replace(actor, request_deadline=deadline)


def create_duty_app(
    commands: DutyCommands, security: DutySecurity, *, lifecycle: LifecycleJobs | None = None
) -> FastAPI:
    app = FastAPI(
        title="CARE-Link registered workload duties",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    async def error_response(request: Request, error: Exception) -> JSONResponse:
        status = error.status if isinstance(error, ManualError) else 422
        key = error.code if isinstance(error, ManualError) else "manual.invalid_request"
        raw_key = request.headers.get("idempotency-key", "")
        try:
            operation_id = str(UUID(raw_key)) if str(UUID(raw_key)) == raw_key else None
        except ValueError:
            operation_id = None
        payload: Record = {
            "code": "COMMIT_UNKNOWN"
            if key == "manual.commit_unknown"
            else "CAPABILITY_DISABLED"
            if "not_admitted" in key or "disabled" in key
            else "AUTHORITY_UNAVAILABLE"
            if status >= 500
            else "NOT_AUTHORIZED"
            if status == 403
            else "INVALID_REQUEST",
            "request_id": str(uuid4()),
            "retryable": status >= 500,
            "message_key": key,
            "operation_id": operation_id,
            "retry_after_ms": None,
        }
        validate_contract("Error", payload)
        return JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})

    app.add_exception_handler(ManualError, error_response)
    app.add_exception_handler(ContractError, error_response)

    def route(
        action: str, contract: str, method: Callable[[DutyActor, str, Record], Record]
    ) -> Callable[[Request], object]:
        async def handle(request: Request) -> JSONResponse:
            if request.query_params or request.headers.get("content-encoding") is not None:
                raise ManualError("manual.invalid_request", 400)
            if request.headers.get("content-type", "").lower().replace(" ", "") not in {
                "application/json",
                "application/json;charset=utf-8",
            }:
                raise ManualError("manual.json_required", 415)
            raw = bytearray()
            async for chunk in request.stream():
                if len(raw) + len(chunk) > 65536:
                    raise ManualError("manual.body_too_large", 413)
                raw.extend(chunk)
            try:
                data = cast(Record, parse_contract(contract, raw.decode("utf-8", errors="strict")))
                key = request.headers.get("idempotency-key", "")
                if str(UUID(key)) != key:
                    raise ValueError("noncanonical operation key")
            except (UnicodeError, ValueError) as error:
                raise ManualError("manual.invalid_request", 400) from error
            actor = await run_in_threadpool(security.verify, request, data, action, key)
            result = await run_in_threadpool(method, actor, key, data)
            validate_contract("CommandResult", result)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})

        return handle

    app.add_api_route(
        "/internal/v1/control/identity-revoke",
        route("identity_revoke", "Signal", commands.identity_revoke),
        methods=["POST"],
    )
    app.add_api_route(
        "/internal/v1/jobs/execute",
        route("job_execute", "DueJob", commands.job_execute),
        methods=["POST"],
    )
    if lifecycle is not None:
        app.add_api_route(
            "/internal/v1/lifecycle/due",
            route("lifecycle_due", "LifecycleDueRequest", lifecycle.lifecycle_due),
            methods=["POST"],
        )
    return app
