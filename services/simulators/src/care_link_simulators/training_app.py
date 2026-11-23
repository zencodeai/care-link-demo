"""Dedicated workload and signed trainer boundary for scenario operations."""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

from care_link_contracts import ContractError, parse_contract, validate_contract
from care_link_domain import Actor, ManualError
from care_link_domain import training_digest as digest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from .receiver import Record
from .security import verify_signature
from .training import TrainingService

HEADERS = {"Cache-Control": "no-store"}
COMMANDS = {
    "scenario_create": ("ScenarioCreate", "CommandResult"),
    "scenario_stop": ("RevisionCommand", "CommandResult"),
    "scenario_read": ("Empty", "ScenarioView"),
}


class TrainingIdentity:
    def __init__(
        self,
        core_key: Ed25519PublicKey,
        identity_key: Ed25519PublicKey,
        resolve: Callable[[Record], Actor],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.core_key, self.identity_key, self.resolve, self.clock = (
            core_key,
            identity_key,
            resolve,
            clock,
        )

    def verify(self, envelope: Record, action: str, key: str) -> tuple[Actor, Record, str | None]:
        validate_contract("TrainingEnvelope", envelope)
        try:
            evidence = cast(Record, envelope["evidence"])
            paths = cast(Record, envelope["path_arguments"])
            args = cast(Record, envelope["arguments"])
            verify_signature(self.core_key, envelope)
            verify_signature(self.identity_key, evidence)
            now = self.clock()
            expires = datetime.fromisoformat(cast(str, envelope["expires_at"]))
            proof_expires = datetime.fromisoformat(cast(str, evidence["expires_at"]))
            verified = datetime.fromisoformat(cast(str, evidence["verified_at"]))
            schema, _ = COMMANDS[action]
            validate_contract(schema, args)
            if action == "scenario_create":
                validate_contract("Empty", paths)
            elif set(paths) != {"scenario_id"}:
                raise ValueError("Invalid training target")
            target = cast(str | None, paths.get("scenario_id"))
            if target is not None:
                validate_contract("Id", target)
            if (
                envelope["action"] != action
                or envelope["operation_id"] != key
                or evidence["action"] != action
                or evidence["request_digest"]
                != digest({"arguments": args, "path_arguments": paths})
                or evidence["resource_id"] != target
                or evidence["kind"] != "human_identity"
                or evidence["role"] != "trainer"
                or not now - timedelta(seconds=1)
                <= verified
                <= now
                < expires
                <= proof_expires
                <= now + timedelta(seconds=1)
            ):
                raise ValueError("Trainer binding mismatch")
            current = self.resolve(evidence)
            if (
                current.account_id != evidence["principal_id"]
                or current.role != "trainer"
                or str(current.identity_revision) != evidence["identity_revision"]
                or str(current.role_revision) != evidence["role_revision"]
                or current.identity_evidence_id != evidence["id"]
                or not current.mfa
                or self.clock() >= min(current.expires_at, expires)
            ):
                raise ValueError("Trainer identity changed")
            deadline = min(current.request_deadline or expires, expires)
            return replace(current, request_deadline=deadline), args, target
        except (InvalidSignature, KeyError, TypeError, ValueError) as error:
            raise ManualError("training.delegation_denied") from error


def create_training_app(
    service: TrainingService,
    identity: TrainingIdentity,
    workload: Callable[[Request, str], bool],
) -> FastAPI:
    app = FastAPI(
        title="CARE-Link isolated synthetic training",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    async def failure(_request: Request, error: Exception) -> JSONResponse:
        status = error.status if isinstance(error, ManualError) else 422
        message = error.code if isinstance(error, ManualError) else "training.invalid_request"
        code = {
            "manual.revision_conflict": "REVISION_CONFLICT",
            "manual.idempotency_conflict": "IDEMPOTENCY_CONFLICT",
        }.get(message)
        value = {
            "code": code or ("DEPENDENCY_UNAVAILABLE" if status >= 500 else "NOT_AUTHORIZED"),
            "request_id": str(uuid4()),
            "retryable": status >= 500,
            "message_key": message,
            "operation_id": None,
            "retry_after_ms": None,
        }
        validate_contract("Error", value)
        return JSONResponse(value, status_code=status, headers=HEADERS)

    app.add_exception_handler(ManualError, failure)
    app.add_exception_handler(ContractError, failure)

    def attach(action: str, output: str) -> None:
        async def handler(request: Request) -> JSONResponse:
            if not workload(request, "core"):
                raise ManualError("training.workload_denied")
            if request.query_params or request.headers.get("content-encoding") is not None:
                raise ManualError("training.invalid_request", 400)
            if request.headers.get("content-type", "").lower().replace(" ", "") not in {
                "application/json",
                "application/json;charset=utf-8",
            }:
                raise ManualError("training.json_required", 415)
            raw = bytearray()
            async for chunk in request.stream():
                if len(raw) + len(chunk) > 65536:
                    raise ManualError("training.body_too_large", 413)
                raw.extend(chunk)
            key = request.headers.get("idempotency-key", "")
            validate_contract("Id", key)
            try:
                envelope = cast(Record, parse_contract("TrainingEnvelope", raw.decode("utf-8")))
            except UnicodeError as error:
                raise ManualError("training.invalid_json", 400) from error
            actor, args, target = await run_in_threadpool(identity.verify, envelope, action, key)
            if action == "scenario_create":
                result = await run_in_threadpool(service.scenario_create, actor, key, args)
            elif target is None:
                raise ManualError("training.invalid_request", 400)
            elif action == "scenario_stop":
                result = await run_in_threadpool(service.scenario_stop, actor, key, target, args)
            else:
                result = await run_in_threadpool(service.scenario_read, actor, target)
            validate_contract(output, result)
            return JSONResponse(result, headers=HEADERS)

        app.add_api_route("/internal/v1/training/" + action, handler, methods=["POST"])

    for action, (_, output) in COMMANDS.items():
        attach(action, output)
    return app
