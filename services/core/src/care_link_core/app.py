"""Composition root for the isolated developer transport."""

from typing import Literal
from uuid import uuid4

from care_link_contracts import ContractError, ErrorEnvelope, parse_contract, validate_contract
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse, Response

from .capabilities import developer_capability

BODY_LIMIT = 64 * 1024


def _error(
    status: int,
    code: Literal["INVALID_REQUEST", "CAPABILITY_DISABLED", "NOT_FOUND"],
    message_key: str,
) -> JSONResponse:
    envelope: ErrorEnvelope = {
        "code": code,
        "request_id": str(uuid4()),
        "retryable": False,
        "message_key": message_key,
        "operation_id": None,
        "retry_after_ms": None,
    }
    validate_contract("Error", envelope)
    return JSONResponse(envelope, status_code=status, headers={"Cache-Control": "no-store"})


def create_app() -> FastAPI:
    """Construct only local developer endpoints; no credentials or stores."""
    app = FastAPI(title="CARE-Link developer API", docs_url=None, redoc_url=None, openapi_url=None)

    async def health() -> JSONResponse:
        return JSONResponse(developer_capability(), headers={"Cache-Control": "no-store"})

    async def validate(name: str, request: Request) -> Response:
        media_type = request.headers.get("content-type", "").lower().replace(" ", "")
        if media_type not in {"application/json", "application/json;charset=utf-8"}:
            return _error(415, "INVALID_REQUEST", "developer.json_required")
        if request.headers.get("content-encoding") is not None:
            return _error(415, "INVALID_REQUEST", "developer.compression_unavailable")
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > BODY_LIMIT:
                return _error(413, "INVALID_REQUEST", "developer.body_too_large")
            body.extend(chunk)
        try:
            parse_contract(name, body.decode("utf-8", errors="strict"))
        except UnicodeError:
            return _error(400, "INVALID_REQUEST", "developer.malformed_json")
        except ContractError as error:
            if error.kind == "unknown_contract":
                return _error(404, "NOT_FOUND", "developer.contract_unavailable")
            status = 400 if error.kind == "malformed" else 422
            return _error(status, "INVALID_REQUEST", "developer.invalid_contract")
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

    async def unavailable() -> JSONResponse:
        return _error(503, "CAPABILITY_DISABLED", "developer.business_unavailable")

    app.add_api_route("/dev/health", health, methods=["GET"])
    app.add_api_route("/dev/contracts/{name}", validate, methods=["POST"])
    methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE", "CONNECT"]
    app.add_api_route("/v1", unavailable, methods=methods)
    app.add_api_route("/v1/{path:path}", unavailable, methods=methods)
    return app
