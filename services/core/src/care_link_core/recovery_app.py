"""Private recovery origin independent of application generation admission."""

from uuid import uuid4

from care_link_contracts import ContractError, validate_contract
from care_link_domain import Actor, ManualError
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from .manual_app import HEADERS
from .manual_ports import BrowserSecurity
from .recovery_routes import RecoveryGateway, attach_recovery_routes


def create_recovery_app(gateway: RecoveryGateway, security: BrowserSecurity) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    async def actor(
        request: Request, *, mutation: bool = False, require_view: bool = True
    ) -> Actor:
        current = await run_in_threadpool(security.authenticate, request)
        if mutation:
            await run_in_threadpool(security.csrf, request, current)
        return current

    async def failed(_request: Request, error: Exception) -> JSONResponse:
        status = error.status if isinstance(error, ManualError) else 422
        if isinstance(error, ContractError) and error.kind == "malformed":
            status = 400
        value: dict[str, object] = {
            "code": "AUTHORITY_UNAVAILABLE"
            if status >= 500
            else "NOT_AUTHORIZED"
            if status in {401, 403}
            else "NOT_FOUND"
            if status == 404
            else "INVALID_REQUEST",
            "request_id": str(uuid4()),
            "retryable": status >= 500,
            "message_key": error.code
            if isinstance(error, ManualError)
            else "recovery.invalid_request",
            "operation_id": None,
            "retry_after_ms": None,
        }
        validate_contract("Error", value)
        return JSONResponse(value, status_code=status, headers=HEADERS)

    app.add_exception_handler(ManualError, failed)
    app.add_exception_handler(ContractError, failed)
    attach_recovery_routes(app, gateway, actor)
    return app
