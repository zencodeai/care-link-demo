"""Protected manual BFF composition, opt-in with explicit authority/gateway ports."""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from care_link_contracts import ContractError, parse_contract, validate_contract
from care_link_domain import Actor, ManualError, WorkloadPeer
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, StreamingResponse

from .assistance import AssistanceGateway
from .assistance_broker import InferenceBroker
from .manual_channels import ManualChannels
from .manual_ports import BrowserSecurity, ManualGateway
from .planning_ports import PlanningGateway
from .plans_review_context import PlansReviewContexts
from .referral_ports import ReceiverGateway, ReferralGateway
from .review_channels import ReviewViews
from .review_context import ReviewContexts

Record = dict[str, object]
Mutation = Callable[[Actor, str, Record, str], Record]
GlobalMutation = Callable[[Actor, str, Record], Record]
HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff"}


def identifier(raw: str) -> str:
    try:
        if str(UUID(raw)) != raw:
            raise ValueError("noncanonical UUID")
    except ValueError as error:
        raise ManualError("manual.invalid_identifier", 400) from error
    return raw


async def body(request: Request, name: str) -> Record:
    if request.headers.get("content-encoding") is not None:
        raise ManualError("manual.compression_denied", 415)
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
        return cast(Record, parse_contract(name, raw.decode("utf-8", errors="strict")))
    except UnicodeError as error:
        raise ManualError("manual.invalid_json", 400) from error


def response(name: str, result: Record) -> JSONResponse:
    validate_contract(name, result)
    return JSONResponse(result, headers=HEADERS)


def create_manual_app(
    gateway: ManualGateway,
    security: BrowserSecurity,
    channels: ManualChannels,
    *,
    review_contexts: ReviewContexts | None = None,
    plans_review_contexts: PlansReviewContexts | None = None,
    review_views: ReviewViews | None = None,
    planning: PlanningGateway | None = None,
    referrals: ReferralGateway | None = None,
    receiver: ReceiverGateway | None = None,
    assistance: AssistanceGateway | None = None,
    assistance_availability: Callable[[Actor], Record] | None = None,
    assistance_broker: InferenceBroker | None = None,
    runtime_verify: Callable[[Request], WorkloadPeer] | None = None,
) -> FastAPI:
    """No permissive defaults; existing developer application stays separate."""
    app = FastAPI(title="CARE-Link manual BFF", docs_url=None, redoc_url=None, openapi_url=None)

    async def error_response(_request: Request, error: Exception) -> JSONResponse:
        status = error.status if isinstance(error, ManualError) else 422
        key = error.code if isinstance(error, ManualError) else "manual.invalid_request"
        if isinstance(error, ContractError) and error.kind == "malformed":
            status = 400
        suffix = key.removeprefix("manual.")
        codes = {
            "commit_unknown": "COMMIT_UNKNOWN",
            "idempotency_conflict": "IDEMPOTENCY_CONFLICT",
            "replacement_unavailable": "REPLACEMENT_UNAVAILABLE",
            "revision_conflict": "REVISION_CONFLICT",
            "context_stale": "CONTEXT_STALE",
            "policy_unavailable": "POLICY_UNAVAILABLE",
            "policy_denied": "NOT_AUTHORIZED",
            "audit_unavailable": "AUDIT_UNAVAILABLE",
            "deadline_exceeded": "DEADLINE_EXCEEDED",
            "cursor_expired": "CURSOR_EXPIRED",
            "token_expired": "TOKEN_EXPIRED",
            "token_used": "TOKEN_USED",
        }
        default_code = (
            "AUTHORITY_UNAVAILABLE"
            if status >= 500
            else (
                "UNAUTHENTICATED"
                if status == 401
                else "NOT_AUTHORIZED"
                if status == 403
                else "NOT_FOUND"
                if status == 404
                else "INVALID_REQUEST"
            )
        )
        raw_key = _request.headers.get("idempotency-key", "")
        try:
            operation_key: str | None = identifier(raw_key) if raw_key else None
        except ManualError:
            operation_key = None
        value: Record = {
            "code": codes.get(suffix, default_code),
            "request_id": str(uuid4()),
            "retryable": status >= 500,
            "message_key": key,
            "operation_id": operation_key,
            "retry_after_ms": None,
        }
        return response_error(value, status)

    def response_error(value: Record, status: int) -> JSONResponse:
        validate_contract("Error", value)
        return JSONResponse(value, status_code=status, headers=HEADERS)

    app.add_exception_handler(ManualError, error_response)
    app.add_exception_handler(ContractError, error_response)

    if plans_review_contexts is not None and plans_review_contexts is not review_contexts:
        raise ValueError("Plans review must share the exact authenticated origin registry")
    if review_views is not None and review_views.channels is not channels:
        raise ValueError("Review view custody must use the exact serving channels")
    views = review_views if review_views is not None else ReviewViews(channels)

    async def actor(
        request: Request, *, mutation: bool = False, require_view: bool = True
    ) -> Actor:
        deadline = datetime.now(UTC) + timedelta(seconds=1)
        current = channels.bind(await run_in_threadpool(security.authenticate, request))
        if review_contexts is not None:
            context = review_contexts.context(request.headers.get("host", ""))
            if context.get("enabled") and (
                current.review_run_id != context["run_id"]
                or current.review_slot_id != context["slot_id"]
                or current.review_origin != context["origin"]
                or current.account_id != context["account_id"]
                or current.role != context["role"]
            ):
                raise ManualError("manual.review_context_mismatch")
        if current.request_deadline is not None:
            deadline = min(deadline, current.request_deadline)
        if deadline <= datetime.now(UTC):
            raise ManualError("manual.deadline_exceeded", 503)
        current = replace(current, request_deadline=deadline)
        if mutation:
            await run_in_threadpool(security.csrf, request, current)
            if current.review_run_id and require_view:
                views.require(current, request.headers.get("x-review-view", ""))
        return current

    if (assistance_broker is None) != (runtime_verify is None):
        raise ValueError("Broker routes require exact runtime workload verification")
    if assistance_broker is not None and runtime_verify is not None:
        from .assistance_broker import attach_broker_routes

        attach_broker_routes(app, assistance_broker, runtime_verify)

    if assistance is not None:
        from .assistance import attach_assistance_routes

        attach_assistance_routes(app, assistance, actor, availability=assistance_availability)

    if planning is not None:
        from .planning_routes import attach_planning_routes

        attach_planning_routes(app, planning, actor)

    if receiver is not None and referrals is None:
        raise ValueError("Receiver routes require explicit referral composition")
    if referrals is not None:
        from .referral_routes import attach_referral_routes

        attach_referral_routes(app, referrals, actor, receiver)

    def mutation_route(name: str, output: str, method: Mutation) -> Callable[[Request], object]:
        async def handle(request: Request) -> JSONResponse:
            current = await actor(request, mutation=True)
            data = await body(request, name)
            key = identifier(request.headers.get("idempotency-key", ""))
            session_id = identifier(request.path_params["session_id"])
            if request.query_params:
                raise ManualError("manual.invalid_query", 400)
            result = await run_in_threadpool(method, current, key, data, session_id)
            if output == "ContinuationIssued" and result.get("state") == "replacement_unavailable":
                raise ManualError("manual.replacement_unavailable", 409)
            return response(output, result)

        return handle

    routes: tuple[tuple[str, str, str, Mutation], ...] = (
        ("continuations", "RevisionCommand", "ContinuationIssued", gateway.continuation_issue),
        ("disclosure", "DisclosureAck", "CommandResult", gateway.session_disclosure),
        ("turns", "TurnSubmit", "AssessmentView", gateway.session_turns),
        ("assertions", "AssertionCreate", "AssertionView", gateway.session_assertions),
        ("choices", "ChoiceCommand", "CommandResult", gateway.session_choices),
        ("human-request", "HumanRequest", "QueueView", gateway.session_human_request),
        ("end", "ReasonCommand", "CommandResult", gateway.session_end),
        ("messages", "MessageSubmit", "MessageView", gateway.message_send),
        ("workforce/reserve", "AssignmentCommand", "AssignmentView", gateway.workforce_reserve),
        ("workforce/accept", "RevisionCommand", "AssignmentView", gateway.workforce_accept),
        (
            "workforce/prepare-transfer",
            "RevisionCommand",
            "TransferPreparation",
            gateway.workforce_prepare_transfer,
        ),
        (
            "workforce/confirm-transfer",
            "TransferConfirm",
            "SessionView",
            gateway.workforce_confirm_transfer,
        ),
        (
            "workforce/transfer-failed",
            "ReasonCommand",
            "QueueView",
            gateway.workforce_transfer_failed,
        ),
        ("workforce/observe", "ObserveCommand", "CommandResult", gateway.workforce_observe),
        ("workforce/takeover", "AssignmentCommand", "SessionView", gateway.workforce_takeover),
        ("workforce/channel-acks", "ChannelAckSubmit", "ChannelAckView", gateway.channel_ack),
    )
    for path, contract, output, method in routes:
        app.add_api_route(
            "/v1/sessions/{session_id}/" + path,
            mutation_route(contract, output, method),
            methods=["POST"],
        )

    def global_route(name: str, output: str, method: GlobalMutation) -> Callable[[Request], object]:
        async def handle(request: Request) -> JSONResponse:
            current = await actor(request, mutation=True)
            data = await body(request, name)
            key = identifier(request.headers.get("idempotency-key", ""))
            if request.query_params:
                raise ManualError("manual.invalid_query", 400)
            result = await run_in_threadpool(method, current, key, data)
            if output == "ContinuationIssued" and result.get("state") == "replacement_unavailable":
                raise ManualError("manual.replacement_unavailable", 409)
            return response(output, result)

        return handle

    for path, contract, output, method in (
        ("/v1/sessions", "SessionCreate", "SessionView", gateway.session_create),
        (
            "/v1/continuations/rotate",
            "ContinuationRotate",
            "ContinuationIssued",
            gateway.continuation_rotate,
        ),
        (
            "/v1/continuations/recover",
            "ContinuationRecover",
            "ContinuationIssued",
            gateway.continuation_recover,
        ),
        ("/v1/operating-state", "ControlChange", "CommandResult", gateway.control_change),
    ):
        app.add_api_route(path, global_route(contract, output, method), methods=["POST"])

    async def read_session(request: Request) -> JSONResponse:
        current = await actor(request)
        if request.query_params:
            raise ManualError("manual.invalid_query", 400)
        return response(
            "SessionView",
            await run_in_threadpool(
                gateway.session_read, current, identifier(request.path_params["session_id"])
            ),
        )

    async def challenge(request: Request) -> JSONResponse:
        current = await actor(request)
        if current.review_run_id:
            views.require(current, request.headers.get("x-review-view", ""))
        if request.query_params:
            raise ManualError("manual.invalid_query", 400)
        return response(
            "ChannelChallengeView",
            await run_in_threadpool(
                gateway.channel_challenge_read,
                current,
                identifier(request.path_params["session_id"]),
            ),
        )

    def page_query(request: Request) -> tuple[int, str | None]:
        pairs = list(request.query_params.multi_items())
        query = dict(pairs)
        if len(pairs) != len(query) or not set(query) <= {"limit", "cursor"}:
            raise ManualError("manual.invalid_query", 400)
        raw = query.get("limit", "50")
        if (
            not raw.isascii()
            or not raw.isdecimal()
            or len(raw) > 2
            or str(int(raw)) != raw
            or not 1 <= int(raw) <= 50
        ):
            raise ManualError("manual.invalid_query", 400)
        cursor = query.get("cursor")
        if cursor is not None and not 1 <= len(cursor) <= 1024:
            raise ManualError("manual.invalid_query", 400)
        return int(raw), cursor

    async def queue(request: Request) -> JSONResponse:
        current = await actor(request)
        limit, cursor = page_query(request)
        return response(
            "QueuePage",
            await run_in_threadpool(gateway.queue_list, current, limit=limit, cursor=cursor),
        )

    async def messages(request: Request) -> JSONResponse:
        current = await actor(request)
        limit, cursor = page_query(request)
        return response(
            "MessagePage",
            await run_in_threadpool(
                gateway.messages_read,
                current,
                identifier(request.path_params["session_id"]),
                limit=limit,
                cursor=cursor,
            ),
        )

    async def operation(request: Request) -> JSONResponse:
        current = await actor(request)
        if request.query_params:
            raise ManualError("manual.invalid_query", 400)
        return response(
            "OperationStatus",
            await run_in_threadpool(
                gateway.operation_status, current, identifier(request.path_params["operation_id"])
            ),
        )

    async def events(request: Request) -> StreamingResponse:
        initial = await actor(request)
        if initial.review_run_id:
            raise ManualError("manual.review_global_stream_required", 409)
        session_id = identifier(request.path_params["session_id"])
        if request.query_params:
            raise ManualError("manual.invalid_query", 400)
        raw_sequence = request.headers.get("last-event-id", "0")
        if (
            not raw_sequence.isdecimal()
            or len(raw_sequence) > 19
            or str(int(raw_sequence)) != raw_sequence
            or int(raw_sequence) > 9223372036854775807
        ):
            raise ManualError("manual.invalid_sequence", 400)
        # Check current scope/audit before sending the streaming response headers.
        await run_in_threadpool(gateway.session_read, initial, session_id)

        async def stream() -> AsyncIterator[str]:
            position = int(raw_sequence)
            with channels.open(initial) as connected:
                try:
                    while not await request.is_disconnected():
                        current = await actor(request)
                        if (
                            current.account_id,
                            current.browser_session_digest,
                            current.transport_generation,
                        ) != (
                            initial.account_id,
                            initial.browser_session_digest,
                            connected.transport_generation,
                        ):
                            break
                        channels.heartbeat(current)
                        refs = await run_in_threadpool(
                            gateway.session_events, current, session_id, position
                        )
                        if refs:
                            # One fresh gateway disclosure per emitted event. Never
                            # replay the rest of a previously authorized private batch.
                            event = refs[0]
                            validate_contract("EventView", event)
                            sequence = int(cast(str, event["sequence"]))
                            if event["type"] == "resync_required" or sequence <= position:
                                yield "event: resync_required\ndata: {}\n\n"
                                break
                            position = sequence
                            encoded = json.dumps(event, separators=(",", ":"))
                            yield f"id: {position}\nevent: {event['type']}\ndata: {encoded}\n\n"
                        else:
                            yield ": heartbeat\n\n"
                            await asyncio.sleep(1)
                except (ManualError, ContractError):
                    yield "event: resync_required\ndata: {}\n\n"

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={**HEADERS, "X-Accel-Buffering": "no"}
        )

    app.add_api_route("/v1/sessions/{session_id}", read_session, methods=["GET"])
    app.add_api_route("/v1/sessions/{session_id}/messages", messages, methods=["GET"])
    app.add_api_route("/v1/sessions/{session_id}/events", events, methods=["GET"])
    app.add_api_route("/v1/sessions/{session_id}/workforce/challenge", challenge, methods=["GET"])
    app.add_api_route("/v1/workforce/queue", queue, methods=["GET"])
    app.add_api_route("/v1/operations/{operation_id}", operation, methods=["GET"])
    from .review_routes import ReviewGateway, add_review_routes

    if review_contexts is not None:
        add_review_routes(
            app, cast(ReviewGateway, gateway), channels, views, actor, review_contexts
        )
    from .plans_review_routes import WorkspaceGateway, attach_plans_review_routes

    attach_plans_review_routes(app, cast(WorkspaceGateway, gateway), actor, plans_review_contexts)
    return app
