"""Named gateway endpoints for reviewed referral effects."""

from collections.abc import Callable
from typing import cast

from care_link_domain import Actor
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from .control import ManualService
from .planning_app import Envelope
from .store import Record


def attach_referral_gateway(app: FastAPI, service: ManualService, envelope: Envelope) -> None:
    def command(
        name: str, parameter: str, output: str, method: Callable[[Actor, str, Record, str], Record]
    ) -> None:
        async def handle(request: Request) -> JSONResponse:
            from care_link_contracts import validate_contract

            actor, key, arguments, paths = await envelope(request, name)
            value = await run_in_threadpool(
                method, actor, key, arguments, cast(str, paths[parameter])
            )
            validate_contract(output, value)
            return JSONResponse(value, headers={"Cache-Control": "no-store"})

        app.add_api_route("/internal/v1/data/" + name, handle, methods=["POST"])

    for name, parameter, output, method in (
        ("referral_draft", "session_id", "ReferralView", service.referral_draft),
        ("referral_review", "referral_id", "ReviewView", service.referral_review),
        ("referral_dispatch", "referral_id", "DispatchView", service.referral_dispatch),
        ("dispatcher_send", "dispatch_id", "DispatchView", service.dispatcher_send),
        ("dispatch_reconcile", "dispatch_id", "DispatchView", service.dispatch_reconcile),
    ):
        command(name, parameter, output, method)

    def query(
        name: str, parameter: str, output: str, method: Callable[[Actor, str], Record]
    ) -> None:
        async def handle(request: Request) -> JSONResponse:
            from care_link_contracts import validate_contract

            actor, _key, _arguments, paths = await envelope(request, name)
            value = await run_in_threadpool(method, actor, cast(str, paths[parameter]))
            validate_contract(output, value)
            return JSONResponse(value, headers={"Cache-Control": "no-store"})

        app.add_api_route("/internal/v1/data/" + name, handle, methods=["POST"])

    for name, parameter, output, method in (
        ("referral_sources", "session_id", "ReferralSourcePage", service.referral_sources),
        ("referral_read", "referral_id", "ReferralView", service.referral_read),
        ("referral_context", "referral_id", "ReferralContext", service.referral_context),
        ("dispatch_read", "dispatch_id", "DispatchView", service.dispatch_read),
        ("receipt_read", "dispatch_id", "ReceiptView", service.receipt_read),
    ):
        query(name, parameter, output, method)
