"""Isolated receiver HTTP boundary. No unauthenticated or permissive composition."""

from collections.abc import Callable
from typing import cast
from uuid import UUID, uuid4

from care_link_contracts import ContractError, parse_contract, validate_contract
from care_link_domain import ManualError
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from .receiver import ReceiverService, Record
from .security import ReceiverIdentity


def create_app(
    service: ReceiverService, identity: ReceiverIdentity, workload: Callable[[Request, str], bool]
) -> FastAPI:
    app = FastAPI(
        title="CARE-Link isolated synthetic receiver",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    async def failure(_request: Request, error: Exception) -> JSONResponse:
        status = error.status if isinstance(error, ManualError) else 422
        result: Record = {
            "code": "DEPENDENCY_UNAVAILABLE" if status >= 500 else "NOT_AUTHORIZED",
            "request_id": str(uuid4()),
            "retryable": status >= 500,
            "message_key": error.code
            if isinstance(error, ManualError)
            else "receiver.invalid_request",
            "operation_id": None,
            "retry_after_ms": None,
        }
        return JSONResponse(result, status_code=status, headers={"Cache-Control": "no-store"})

    app.add_exception_handler(ManualError, failure)
    app.add_exception_handler(ContractError, failure)

    async def body(request: Request, schema: str, expected: str) -> Record:
        if not workload(request, expected):
            raise ManualError("receiver.workload_denied")
        if request.query_params or request.headers.get("content-encoding") is not None:
            raise ManualError("receiver.invalid_request", 400)
        if request.headers.get("content-type", "").lower().replace(" ", "") not in {
            "application/json",
            "application/json;charset=utf-8",
        }:
            raise ManualError("receiver.json_required", 415)
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > 65536:
                raise ManualError("receiver.body_too_large", 413)
            data.extend(chunk)
        try:
            return cast(Record, parse_contract(schema, data.decode("utf-8", errors="strict")))
        except UnicodeError as error:
            raise ManualError("receiver.invalid_json", 400) from error

    def output(schema: str, result: Record) -> JSONResponse:
        validate_contract(schema, result)
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    async def send(request: Request) -> JSONResponse:
        data = await body(request, "ReceiverSend", "data")
        try:
            result = await run_in_threadpool(
                service.send, cast(str, data["service_id"]), cast(Record, data["package"])
            )
        except (TimeoutError, ConnectionError) as error:
            raise ManualError("receiver.result_unknown", 503) from error
        return output("ReceiptView", result)

    async def lookup(request: Request) -> JSONResponse:
        data = await body(request, "SimulatorLookup", "data")
        return output(
            "ReceiptView",
            await run_in_threadpool(
                service.lookup,
                cast(str, data["service_id"]),
                cast(str, data["dispatch_id"]),
                cast(str, data["payload_digest"]),
            ),
        )

    def human(action: str, schema: str) -> None:
        async def handle(request: Request) -> JSONResponse:
            envelope = await body(request, "ReceiverEnvelope", "core")
            key = request.headers.get("idempotency-key", "")
            try:
                if str(UUID(key)) != key:
                    raise ValueError("noncanonical key")
            except ValueError as error:
                raise ManualError("receiver.invalid_operation", 400) from error
            actor = await run_in_threadpool(identity.verify, envelope, action, key)
            args, paths = (
                cast(Record, envelope["arguments"]),
                cast(Record, envelope["path_arguments"]),
            )
            if action == "receiver_inbox":
                result = await run_in_threadpool(service.receiver_inbox, actor, args)
            elif action == "receiver_decide":
                result = await run_in_threadpool(service.receiver_decide, actor, key, args)
            elif action == "receiver_detail":
                result = await run_in_threadpool(
                    service.receiver_detail, actor, cast(str, paths["dispatch_id"])
                )
            else:
                result = await run_in_threadpool(
                    service.receiver_package, actor, cast(str, paths["dispatch_id"])
                )
            return output(schema, result)

        app.add_api_route("/internal/v1/receiver/" + action, handle, methods=["POST"])

    app.add_api_route("/internal/v1/receiver/send", send, methods=["POST"])
    app.add_api_route("/internal/v1/receiver/lookup", lookup, methods=["POST"])
    for action, schema in (
        ("receiver_inbox", "ReceiverPackagePage"),
        ("receiver_package", "ReferralPayload"),
        ("receiver_detail", "ReceiverDetail"),
        ("receiver_decide", "ReceiptView"),
    ):
        human(action, schema)
    return app
