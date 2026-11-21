"""Authenticated follow-up and rights routes with closed request contracts."""

from collections.abc import Callable

from care_link_contracts import validate_contract
from care_link_domain import ManualError
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from .lifecycle_ports import LifecycleGateway, Record
from .planning_routes import Authenticate


def page(request: Request, contract: str) -> Record:
    """Reject duplicates, noncanonical limits and unknown query fields."""
    data: Record = {}
    for key, value in request.query_params.multi_items():
        if key in data or key not in {"limit", "cursor"}:
            raise ManualError("manual.invalid_query", 400)
        if key == "limit":
            if (
                len(value) > 2
                or not value.isascii()
                or not value.isdecimal()
                or str(int(value)) != value
            ):
                raise ManualError("manual.invalid_query", 400)
            data[key] = int(value)
        else:
            data[key] = value
    validate_contract(contract, data)
    return data


def attach_lifecycle_routes(app: FastAPI, gateway: LifecycleGateway, actor: Authenticate) -> None:
    from .manual_app import body, identifier, response

    def command(
        path: str,
        parameter: str | None,
        contract: str,
        output: str,
        method: Callable[..., Record],
    ) -> None:
        async def handle(request: Request) -> JSONResponse:
            current = await actor(request, mutation=True)
            if request.query_params:
                raise ManualError("manual.invalid_query", 400)
            data = await body(request, contract)
            key = identifier(request.headers.get("idempotency-key", ""))
            target = (identifier(request.path_params[parameter]),) if parameter else ()
            return response(output, await run_in_threadpool(method, current, key, data, *target))

        app.add_api_route(path, handle, methods=["POST"])

    for path, parameter, contract, output, method in (
        (
            "/v1/sessions/{session_id}/post-crisis",
            "session_id",
            "PostCrisisRecord",
            "PostCrisisView",
            gateway.post_crisis_record,
        ),
        (
            "/v1/sessions/{session_id}/follow-ups",
            "session_id",
            "FollowUpCreate",
            "FollowUpView",
            gateway.followup_create,
        ),
        (
            "/v1/follow-ups/{followup_id}/anchor",
            "followup_id",
            "FollowUpBindAnchor",
            "FollowUpView",
            gateway.followup_bind_anchor,
        ),
        (
            "/v1/follow-ups/{followup_id}/cancel",
            "followup_id",
            "RevisionCommand",
            "FollowUpView",
            gateway.followup_cancel,
        ),
        (
            "/v1/sessions/{session_id}/outcomes",
            "session_id",
            "OutcomeCreate",
            "CommandResult",
            gateway.outcome_append,
        ),
        ("/v1/holds", None, "HoldCommand", "CommandResult", gateway.hold_create),
        (
            "/v1/holds/{hold_id}/release",
            "hold_id",
            "RevisionCommand",
            "CommandResult",
            gateway.hold_release,
        ),
        ("/v1/rights", None, "RightsCreate", "RightsView", gateway.rights_create),
    ):
        command(path, parameter, contract, output, method)

    def query(
        path: str,
        parameter: str | None,
        output: str,
        method: Callable[..., Record],
        query_contract: str | None = None,
    ) -> None:
        async def handle(request: Request) -> JSONResponse:
            # Download consumes a one-use authorization. GET still uses the
            # authenticated channel and current field filtering at the gateway.
            current = await actor(request)
            if query_contract is None and request.query_params:
                raise ManualError("manual.invalid_query", 400)
            data = page(request, query_contract) if query_contract else {}
            target = (identifier(request.path_params[parameter]),) if parameter else ()
            return response(output, await run_in_threadpool(method, current, *target, **data))

        app.add_api_route(path, handle, methods=["GET"])

    query("/v1/follow-ups/{followup_id}", "followup_id", "FollowUpView", gateway.followup_read)
    query(
        "/v1/sessions/{session_id}/outcomes",
        "session_id",
        "OutcomePage",
        gateway.outcomes_read,
        "PageQuery",
    )
    query("/v1/inbox", None, "InboxPage", gateway.participant_inbox, "InboxQuery")
    query("/v1/inbox/{message_id}", "message_id", "InboxMessageView", gateway.inbox_message_read)
    query("/v1/rights/{rights_id}", "rights_id", "RightsView", gateway.rights_read)
    query("/v1/rights/{rights_id}/download", "rights_id", "ExportView", gateway.export_download)
