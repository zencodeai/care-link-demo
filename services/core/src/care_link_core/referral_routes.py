"""Thin authenticated referral and separately scoped receiver actor handlers."""

from collections.abc import Callable

from care_link_contracts import validate_contract
from care_link_domain import Actor, ManualError
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from .planning_routes import Authenticate
from .referral_ports import ReceiverGateway, Record, ReferralGateway


def attach_referral_routes(
    app: FastAPI,
    gateway: ReferralGateway,
    authenticate: Authenticate,
    receiver: ReceiverGateway | None = None,
) -> None:
    from .manual_app import body, identifier, response

    def command(
        path: str,
        parameter: str,
        contract: str,
        output: str,
        method: Callable[[Actor, str, Record, str], Record],
    ) -> None:
        async def handle(request: Request) -> JSONResponse:
            actor = await authenticate(request, mutation=True)
            if request.query_params:
                raise ManualError("manual.invalid_query", 400)
            data = await body(request, contract)
            key = identifier(request.headers.get("idempotency-key", ""))
            target = identifier(request.path_params[parameter])
            return response(output, await run_in_threadpool(method, actor, key, data, target))

        app.add_api_route(path, handle, methods=["POST"])

    for path, parameter, contract, output, method in (
        (
            "/v1/sessions/{session_id}/referrals",
            "session_id",
            "ReferralDraftCreate",
            "ReferralView",
            gateway.referral_draft,
        ),
        (
            "/v1/referrals/{referral_id}/review",
            "referral_id",
            "ReviewCommand",
            "ReviewView",
            gateway.referral_review,
        ),
        (
            "/v1/referrals/{referral_id}/dispatch",
            "referral_id",
            "DispatchRequest",
            "DispatchView",
            gateway.referral_dispatch,
        ),
        (
            "/v1/dispatches/{dispatch_id}/send",
            "dispatch_id",
            "RevisionCommand",
            "DispatchView",
            gateway.dispatcher_send,
        ),
        (
            "/v1/dispatches/{dispatch_id}/reconcile",
            "dispatch_id",
            "RevisionCommand",
            "DispatchView",
            gateway.dispatch_reconcile,
        ),
    ):
        command(path, parameter, contract, output, method)

    def query(
        path: str, parameter: str, output: str, method: Callable[[Actor, str], Record]
    ) -> None:
        async def handle(request: Request) -> JSONResponse:
            actor = await authenticate(request)
            if request.query_params:
                raise ManualError("manual.invalid_query", 400)
            return response(
                output,
                await run_in_threadpool(method, actor, identifier(request.path_params[parameter])),
            )

        app.add_api_route(path, handle, methods=["GET"])

    for path, parameter, output, method in (
        (
            "/v1/sessions/{session_id}/referral-sources",
            "session_id",
            "ReferralSourcePage",
            gateway.referral_sources,
        ),
        ("/v1/referrals/{referral_id}", "referral_id", "ReferralView", gateway.referral_read),
        (
            "/v1/referrals/{referral_id}/context",
            "referral_id",
            "ReferralContext",
            gateway.referral_context,
        ),
        ("/v1/dispatches/{dispatch_id}", "dispatch_id", "DispatchView", gateway.dispatch_read),
        (
            "/v1/dispatches/{dispatch_id}/receipt",
            "dispatch_id",
            "ReceiptView",
            gateway.receipt_read,
        ),
    ):
        query(path, parameter, output, method)

    if receiver is None:
        return
    query(
        "/v1/receiver/packages/{dispatch_id}",
        "dispatch_id",
        "ReferralPayload",
        receiver.receiver_package,
    )
    query(
        "/v1/receiver/packages/{dispatch_id}/detail",
        "dispatch_id",
        "ReceiverDetail",
        receiver.receiver_detail,
    )

    async def inbox(request: Request) -> JSONResponse:
        actor = await authenticate(request)
        pairs = list(request.query_params.multi_items())
        params = dict(pairs)
        if len(pairs) != len(params) or not set(params) <= {"limit", "cursor"}:
            raise ManualError("manual.invalid_query", 400)
        raw = params.get("limit", "50")
        if not raw.isascii() or not raw.isdecimal() or len(raw) > 2 or str(int(raw)) != raw:
            raise ManualError("manual.invalid_query", 400)
        data: Record = {"limit": int(raw)}
        if "cursor" in params:
            data["cursor"] = params["cursor"]
        validate_contract("ReceiverPackageQuery", data)
        return response(
            "ReceiverPackagePage", await run_in_threadpool(receiver.receiver_inbox, actor, data)
        )

    async def decide(request: Request) -> JSONResponse:
        actor = await authenticate(request, mutation=True)
        if request.query_params:
            raise ManualError("manual.invalid_query", 400)
        data = await body(request, "ReceiverDecision")
        if data["dispatch_id"] != identifier(request.path_params["dispatch_id"]):
            raise ManualError("manual.target_mismatch", 422)
        key = identifier(request.headers.get("idempotency-key", ""))
        return response(
            "ReceiptView", await run_in_threadpool(receiver.receiver_decide, actor, key, data)
        )

    app.add_api_route("/v1/receiver/inbox", inbox, methods=["GET"])
    app.add_api_route("/v1/receiver/packages/{dispatch_id}/decision", decide, methods=["POST"])
