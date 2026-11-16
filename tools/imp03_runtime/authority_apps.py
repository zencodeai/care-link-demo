"""Protected fixed policy and host-journal endpoints, without browser routes."""

import base64
import json
from collections.abc import Callable
from uuid import UUID

from care_link_contracts import ContractError, validate_contract
from care_link_domain import ManualError
from care_link_policy_input import OpaPolicy
from care_link_recovery_control import FileJournal
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from .config import Record, record, unique
from .remote import canonical

Verifier = Callable[[Request, str], bool]


def base_app() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    async def failure(_request: Request, error: Exception) -> JSONResponse:
        status = error.status if isinstance(error, ManualError) else 422
        return JSONResponse(
            {"state": "dependency_unavailable" if status >= 500 else "denied"},
            status_code=status,
            headers={"Cache-Control": "no-store"},
        )

    app.add_exception_handler(ManualError, failure)
    app.add_exception_handler(ContractError, failure)
    return app


async def body(request: Request) -> Record:
    if (
        request.query_params
        or request.headers.get("content-encoding") is not None
        or not request.headers.get("content-type", "").startswith("application/json")
    ):
        raise ManualError("manual.invalid_request", 415)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 65536:
            raise ManualError("manual.body_too_large", 413)
    try:
        return record(json.loads(raw, object_pairs_hook=unique))
    except (ValueError, TypeError) as error:
        raise ManualError("manual.invalid_request", 400) from error


def policy_app(policy: OpaPolicy, verify: Verifier) -> FastAPI:
    app = base_app()

    async def evaluate(request: Request) -> JSONResponse:
        if not (verify(request, "core") or verify(request, "data")):
            raise ManualError("manual.workload_denied")
        value = await body(request)
        validate_contract("PolicyInput", value)
        decision = await run_in_threadpool(policy.evaluate, value)
        return JSONResponse(decision, headers={"Cache-Control": "no-store"})

    app.add_api_route("/internal/v1/policy/evaluate", evaluate, methods=["POST"])
    return app


def journal_app(journal: FileJournal, key: Ed25519PrivateKey, verify: Verifier) -> FastAPI:
    app = base_app()

    async def call(request: Request) -> JSONResponse:
        if not verify(request, "data"):
            raise ManualError("manual.workload_denied")
        value = await body(request)
        try:
            if (
                set(value) != {"nonce", "command"}
                or str(UUID(str(value["nonce"]))) != value["nonce"]
            ):
                raise ValueError("Invalid challenge")
            if request.url.path.endswith("/head"):
                if value["command"] is not None:
                    raise ValueError("Head has no command")
                state = await run_in_threadpool(journal.head)
            else:
                state = await run_in_threadpool(journal.append, record(value["command"]))
        except ValueError as error:
            raise ManualError("manual.invalid_request", 400) from error
        unsigned: Record = {
            "nonce": value["nonce"],
            "state": {
                "journal_id": state.journal_id,
                "generation": str(state.generation),
                "tip": str(state.tip),
                "tip_digest": state.tip_digest,
                "restriction_barrier": str(state.restriction_barrier),
                "serving_generation": str(state.serving_generation),
                "observed_at": state.observed_at.isoformat().replace("+00:00", "Z"),
            },
        }
        signature = base64.urlsafe_b64encode(key.sign(canonical(unsigned))).rstrip(b"=").decode()
        return JSONResponse(
            {**unsigned, "signature": signature}, headers={"Cache-Control": "no-store"}
        )

    app.add_api_route("/internal/v1/journal/head", call, methods=["POST"])
    app.add_api_route("/internal/v1/journal/append", call, methods=["POST"])
    return app
