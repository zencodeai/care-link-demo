"""Named signed-delegation lifecycle gateway endpoints."""

from collections.abc import Awaitable, Callable
from typing import cast

from care_link_contracts import validate_contract
from care_link_domain import Actor
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from ..store import Record

Envelope = Callable[[Request, str], Awaitable[tuple[Actor, str, Record, Record]]]


def attach_lifecycle_gateway(app: FastAPI, service: object, envelope: Envelope) -> None:
    # The explicit table is transport dispatch only, never an executable caller-supplied name.
    def command(name: str, output: str, target: str | None = None) -> None:
        method = cast(Callable[..., Record], getattr(service, name))

        async def handle(request: Request) -> JSONResponse:
            actor, key, args, paths = await envelope(request, name)
            result = await run_in_threadpool(
                method, actor, key, args, *([cast(str, paths[target])] if target else [])
            )
            validate_contract(output, result)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})

        app.add_api_route("/internal/v1/data/" + name, handle, methods=["POST"])

    for name, output, target in (
        ("post_crisis_record", "PostCrisisView", "session_id"),
        ("followup_create", "FollowUpView", "session_id"),
        ("followup_bind_anchor", "FollowUpView", "followup_id"),
        ("followup_cancel", "FollowUpView", "followup_id"),
        ("outcome_append", "CommandResult", "session_id"),
        ("rights_create", "RightsView", None),
        ("hold_create", "CommandResult", None),
        ("hold_release", "CommandResult", "hold_id"),
    ):
        command(name, output, target)

    def query(name: str, output: str, target: str | None = None, page: bool = False) -> None:
        method = cast(Callable[..., Record], getattr(service, name))

        async def handle(request: Request) -> JSONResponse:
            actor, _key, args, paths = await envelope(request, name)
            kwargs = {"limit": args.get("limit", 50), "cursor": args.get("cursor")} if page else {}
            result = await run_in_threadpool(
                method, actor, *([cast(str, paths[target])] if target else []), **kwargs
            )
            validate_contract(output, result)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})

        app.add_api_route("/internal/v1/data/" + name, handle, methods=["POST"])

    for name, output, target, page in (
        ("followup_read", "FollowUpView", "followup_id", False),
        ("participant_inbox", "InboxPage", None, True),
        ("inbox_message_read", "InboxMessageView", "message_id", False),
        ("outcomes_read", "OutcomePage", "session_id", True),
        ("rights_read", "RightsView", "rights_id", False),
        ("export_download", "ExportView", "rights_id", False),
    ):
        query(name, output, target, page)
