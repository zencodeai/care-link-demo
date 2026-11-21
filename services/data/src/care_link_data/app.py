"""Named internal gateway transports; workload plus signed current identity required."""

from collections.abc import Callable
from typing import Protocol, cast
from uuid import UUID, uuid4

from care_link_contracts import ContractError, parse_contract, validate_contract
from care_link_domain import Actor, ManualError
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response

from .assistance import AssistanceCoordinator
from .control import ManualService

Record = dict[str, object]
Mutation = Callable[[Actor, str, Record, str], Record]
GlobalMutation = Callable[[Actor, str, Record], Record]


class GatewaySecurity(Protocol):
    def verify(self, request: Request, envelope: Record, action: str, key: str) -> Actor: ...


class SignedDelegationPort(Protocol):
    def verify(self, envelope: Record, action: str, key: str, path: str) -> Actor: ...


class SignedGatewaySecurity:
    def __init__(
        self, delegations: SignedDelegationPort, workload_verifier: Callable[[Request, str], bool]
    ) -> None:
        self.delegations, self.workload_verifier = delegations, workload_verifier

    def verify(self, request: Request, envelope: Record, action: str, key: str) -> Actor:
        if not self.workload_verifier(request, "core"):
            raise ManualError("manual.workload_denied")
        return self.delegations.verify(envelope, action, key, request.url.path)


def create_app(
    service: ManualService,
    security: GatewaySecurity,
    *,
    assistance: AssistanceCoordinator | None = None,
) -> FastAPI:
    app = FastAPI(title="CARE-Link data gateway", docs_url=None, redoc_url=None, openapi_url=None)

    async def error_response(_request: Request, error: Exception) -> JSONResponse:
        status = error.status if isinstance(error, ManualError) else 422
        key = error.code if isinstance(error, ManualError) else "manual.invalid_request"
        suffix = key.removeprefix("manual.")
        codes = {
            "commit_unknown": "COMMIT_UNKNOWN",
            "idempotency_conflict": "IDEMPOTENCY_CONFLICT",
            "replacement_unavailable": "REPLACEMENT_UNAVAILABLE",
            "stale_revision": "REVISION_CONFLICT",
        }
        value: Record = {
            "code": codes.get(
                suffix,
                "DEPENDENCY_UNAVAILABLE"
                if status >= 500
                else "NOT_AUTHORIZED"
                if status == 403
                else "INVALID_REQUEST",
            ),
            "request_id": str(uuid4()),
            "retryable": status >= 500,
            "message_key": key,
            "operation_id": None,
            "retry_after_ms": None,
        }
        validate_contract("Error", value)
        return JSONResponse(value, status_code=status, headers={"Cache-Control": "no-store"})

    app.add_exception_handler(ManualError, error_response)
    app.add_exception_handler(ContractError, error_response)

    async def envelope(request: Request, name: str) -> tuple[Actor, str, Record, Record]:
        if request.headers.get("content-encoding") is not None or request.headers.get(
            "content-type", ""
        ).lower().replace(" ", "") not in {"application/json", "application/json;charset=utf-8"}:
            raise ManualError("manual.json_required", 415)
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > 65536:
                raise ManualError("manual.body_too_large", 413)
            raw.extend(chunk)
        try:
            parsed = cast(
                Record, parse_contract("Gateway_" + name, raw.decode("utf-8", errors="strict"))
            )
            key = request.headers.get("idempotency-key", "")
            if str(UUID(key)) != key or request.query_params:
                raise ValueError("invalid operation key/query")
        except (UnicodeError, ValueError) as error:
            raise ManualError("manual.invalid_request", 400) from error
        current = await run_in_threadpool(security.verify, request, parsed, name, key)
        # Upstream permit is preliminary; the service builds its own fresh current
        # PolicyInput and final guard/audit checks before each protected effect.
        decision = cast(Record, parsed["decision"])
        if decision["decision"] != "PERMIT":
            raise ManualError("manual.policy_denied")
        return (
            current,
            key,
            cast(Record, parsed["arguments"]),
            cast(Record, parsed["path_arguments"]),
        )

    if assistance is not None:
        from .assistance.app import attach_assistance_gateway

        attach_assistance_gateway(app, assistance, envelope)

    from .governance_app import attach_governance_gateway

    attach_governance_gateway(app, service, envelope)

    from .lifecycle.app import attach_lifecycle_gateway

    attach_lifecycle_gateway(app, service, envelope)

    from .planning_app import attach_planning_gateway

    attach_planning_gateway(app, service, envelope)
    from .referral_app import attach_referral_gateway

    attach_referral_gateway(app, service, envelope)

    def mutation(name: str, output: str, method: Mutation) -> None:
        async def handler(request: Request) -> Response:
            actor, key, args, paths = await envelope(request, name)
            result = await run_in_threadpool(
                method, actor, key, args, cast(str, paths["session_id"])
            )
            if output == "ContinuationIssued" and result.get("state") == "replacement_unavailable":
                raise ManualError("manual.replacement_unavailable", 409)
            validate_contract(output, result)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})

        app.add_api_route("/internal/v1/data/" + name, handler, methods=["POST"])

    for name, output, method in (
        ("continuation_issue", "ContinuationIssued", service.continuation_issue),
        ("session_disclosure", "CommandResult", service.session_disclosure),
        ("session_turns", "AssessmentView", service.session_turns),
        ("session_assertions", "AssertionView", service.session_assertions),
        ("session_choices", "CommandResult", service.session_choices),
        ("session_human_request", "QueueView", service.session_human_request),
        ("session_end", "CommandResult", service.session_end),
        ("message_send", "MessageView", service.message_send),
        ("workforce_reserve", "AssignmentView", service.workforce_reserve),
        ("workforce_accept", "AssignmentView", service.workforce_accept),
        ("workforce_prepare_transfer", "TransferPreparation", service.workforce_prepare_transfer),
        ("workforce_confirm_transfer", "SessionView", service.workforce_confirm_transfer),
        ("workforce_transfer_failed", "QueueView", service.workforce_transfer_failed),
        ("workforce_observe", "CommandResult", service.workforce_observe),
        ("workforce_takeover", "SessionView", service.workforce_takeover),
        ("channel_ack", "ChannelAckView", service.channel_ack),
        ("review_draft_save", "ReviewDraftView", service.review_draft_save),
        ("review_intent_prepare", "ReviewIntentView", service.review_intent_prepare),
        ("review_intent_cancel", "ReviewIntentView", service.review_intent_cancel),
    ):
        mutation(name, output, method)

    def global_mutation(name: str, output: str, method: GlobalMutation) -> None:
        async def handler(request: Request) -> Response:
            actor, key, args, _paths = await envelope(request, name)
            result = await run_in_threadpool(method, actor, key, args)
            if output == "ContinuationIssued" and result.get("state") == "replacement_unavailable":
                raise ManualError("manual.replacement_unavailable", 409)
            validate_contract(output, result)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})

        app.add_api_route("/internal/v1/data/" + name, handler, methods=["POST"])

    for name, output, method in (
        ("session_create", "SessionView", service.session_create),
        ("continuation_rotate", "ContinuationIssued", service.continuation_rotate),
        ("continuation_recover", "ContinuationIssued", service.continuation_recover),
        ("control_change", "CommandResult", service.control_change),
    ):
        global_mutation(name, output, method)

    def query(name: str, output: str) -> None:
        async def handler(request: Request) -> Response:
            actor, _key, args, paths = await envelope(request, name)
            session_id = cast(str, paths.get("session_id", ""))
            if name == "review_workspace":
                result = await run_in_threadpool(
                    service.review_workspace, actor, cast(str | None, args.get("session_id"))
                )
            elif name == "queue_list":
                result = await run_in_threadpool(
                    service.queue_list,
                    actor,
                    limit=cast(int, args.get("limit", 50)),
                    cursor=cast(str | None, args.get("cursor")),
                )
            elif name == "messages_read":
                result = await run_in_threadpool(
                    service.messages_read,
                    actor,
                    session_id,
                    limit=cast(int, args.get("limit", 50)),
                    cursor=cast(str | None, args.get("cursor")),
                )
            elif name == "operation_status":
                result = await run_in_threadpool(
                    service.operation_status, actor, cast(str, paths["operation_id"])
                )
            elif name == "channel_challenge_read":
                result = await run_in_threadpool(service.channel_challenge_read, actor, session_id)
            elif name == "session_events":
                raw = cast(str, args["last_event_id"])
                if (
                    request.headers.get("last-event-id") not in {None, raw}
                    or not raw.isascii()
                    or not raw.isdecimal()
                    or len(raw) > 19
                    or str(int(raw)) != raw
                    or int(raw) > 9223372036854775807
                ):
                    raise ManualError("manual.invalid_sequence", 400)
                events = await run_in_threadpool(
                    service.session_events, actor, session_id, int(raw)
                )
                if not events:
                    return Response(status_code=204, headers={"Cache-Control": "no-store"})
                result = events[0]
            else:
                result = await run_in_threadpool(service.session_read, actor, session_id)
            validate_contract(output, result)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})

        app.add_api_route("/internal/v1/data/" + name, handler, methods=["POST"])

    for name, output in [
        ("review_workspace", "ReviewWorkspace"),
        ("queue_list", "QueuePage"),
        ("messages_read", "MessagePage"),
        ("operation_status", "OperationStatus"),
        ("channel_challenge_read", "ChannelChallengeView"),
        ("session_events", "EventView"),
        ("session_read", "SessionView"),
    ]:
        query(name, output)

    async def authority_metadata(request: Request) -> Response:
        if request.headers.get("content-encoding") is not None or request.headers.get(
            "content-type", ""
        ).lower().replace(" ", "") not in {"application/json", "application/json;charset=utf-8"}:
            raise ManualError("manual.json_required", 415)
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > 65536:
                raise ManualError("manual.body_too_large", 413)
            raw.extend(chunk)
        try:
            data = cast(
                Record, parse_contract("MetadataRequest", raw.decode("utf-8", errors="strict"))
            )
            key = request.headers.get("idempotency-key", "")
            if str(UUID(key)) != key or request.query_params:
                raise ValueError("invalid operation key/query")
        except (UnicodeError, ValueError) as error:
            raise ManualError("manual.invalid_request", 400) from error
        scope = cast(Record, data["scope"])
        # The signing codec is identical to named gateway envelopes: exact
        # arguments and path bindings, excluding recursive signature metadata.
        normalized: Record = {
            "delegation": data["delegation"],
            "arguments": {k: v for k, v in data.items() if k != "delegation"},
            "path_arguments": {"session_id": scope["session_id"]} if scope["session_id"] else {},
        }
        actor = await run_in_threadpool(
            security.verify, request, normalized, cast(str, data["action"]), key
        )
        result = await run_in_threadpool(service.authority_metadata, actor, data)
        validate_contract("MetadataResult", result)
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    app.add_api_route("/internal/v1/data/authority", authority_metadata, methods=["POST"])
    return app
