"""Pinned HTTPS adapter for named data operations; no SQL or user-selected target."""

from typing import Protocol, cast
from uuid import uuid4

import httpx
from care_link_contracts import ContractError, parse_contract, validate_contract
from care_link_domain import Actor, ManualError

Record = dict[str, object]

# These fixed transport keys distinguish exhausted budgets/current guard changes
# without reflecting arbitrary upstream strings or response contents to clients.
_SAFE_GATEWAY_ERRORS = {
    "manual.deadline": 503,
    "manual.deadline_exceeded": 503,
    "manual.stale_authority": 409,
    "manual.journal_barrier": 503,
}


class EnvelopeFactory(Protocol):
    def build(
        self, actor: Actor, action: str, key: str, arguments: Record, path_arguments: Record
    ) -> Record: ...


class HttpManualGateway:
    def __init__(self, client: httpx.Client, origin: str, envelopes: EnvelopeFactory) -> None:
        url = httpx.URL(origin)
        if (
            url.scheme != "https"
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
            or url.username
            or url.password
        ):
            raise ValueError("Data gateway must be a fixed HTTPS origin")
        self.client, self.origin, self.envelopes = client, origin.rstrip("/"), envelopes

    def _request(
        self,
        actor: Actor,
        action: str,
        key: str,
        args: Record,
        paths: Record,
        output: str,
        *,
        sequence: int | None = None,
    ) -> Record | None:
        if sequence is not None:
            args = {**args, "last_event_id": str(sequence)}
        envelope = self.envelopes.build(actor, action, key, args, paths)
        validate_contract("Gateway_" + action, envelope)
        headers = {"Idempotency-Key": key, "Content-Type": "application/json"}
        try:
            response = self.client.post(
                self.origin + "/internal/v1/data/" + action,
                json=envelope,
                headers=headers,
                timeout=1.0,
                follow_redirects=False,
            )
        except httpx.HTTPError as error:
            raise ManualError("manual.commit_unknown", 503) from error
        if response.status_code == 204 and action == "session_events":
            return None
        if len(response.content) > 65536 or not response.headers.get("content-type", "").startswith(
            "application/json"
        ):
            raise ManualError("manual.invalid_gateway_response", 503)
        if response.status_code != 200:
            try:
                payload = cast(Record, parse_contract("Error", response.text))
            except ContractError as error:
                raise ManualError("manual.invalid_gateway_response", 503) from error
            if actor.review_run_id and payload.get("message_key") == "manual.identity_changed":
                raise ManualError("manual.fresh_auth_required", 401)
            # Fixed safe machine keys only; no upstream transcript/body logging.
            mapping = {
                "COMMIT_UNKNOWN": "manual.commit_unknown",
                "IDEMPOTENCY_CONFLICT": "manual.idempotency_conflict",
                "REPLACEMENT_UNAVAILABLE": "manual.replacement_unavailable",
                "REVISION_CONFLICT": "manual.stale_revision",
            }
            failure_key = mapping.get(cast(str, payload["code"]))
            if failure_key is None:
                supplied = payload.get("message_key")
                failure_key = (
                    supplied
                    if isinstance(supplied, str)
                    and _SAFE_GATEWAY_ERRORS.get(supplied) == response.status_code
                    else "manual.gateway_denied"
                )
            raise ManualError(failure_key, response.status_code)
        return cast(Record, parse_contract(output, response.text))

    def _result(
        self, actor: Actor, action: str, key: str, args: Record, paths: Record, output: str
    ) -> Record:
        result = self._request(actor, action, key, args, paths, output)
        if result is None:
            raise ManualError("manual.invalid_gateway_response", 503)
        return result

    def session_create(self, actor: Actor, key: str, data: Record) -> Record:
        return self._result(actor, "session_create", key, data, {}, "SessionView")

    def session_read(self, actor: Actor, session_id: str) -> Record:
        return self._result(
            actor, "session_read", str(uuid4()), {}, {"session_id": session_id}, "SessionView"
        )

    def channel_challenge_read(self, actor: Actor, session_id: str) -> Record:
        return self._result(
            actor,
            "channel_challenge_read",
            str(uuid4()),
            {},
            {"session_id": session_id},
            "ChannelChallengeView",
        )

    def operation_status(self, actor: Actor, operation_id: str) -> Record:
        return self._result(
            actor,
            "operation_status",
            str(uuid4()),
            {},
            {"operation_id": operation_id},
            "OperationStatus",
        )

    def queue_list(self, actor: Actor, *, limit: int = 50, cursor: str | None = None) -> Record:
        return self._result(
            actor,
            "queue_list",
            str(uuid4()),
            {"limit": limit, **({"cursor": cursor} if cursor is not None else {})},
            {},
            "QueuePage",
        )

    def messages_read(
        self, actor: Actor, session_id: str, *, limit: int = 50, cursor: str | None = None
    ) -> Record:
        return self._result(
            actor,
            "messages_read",
            str(uuid4()),
            {"limit": limit, **({"cursor": cursor} if cursor is not None else {})},
            {"session_id": session_id},
            "MessagePage",
        )

    def session_events(self, actor: Actor, session_id: str, last_event_id: int = 0) -> list[Record]:
        result = self._request(
            actor,
            "session_events",
            str(uuid4()),
            {},
            {"session_id": session_id},
            "EventView",
            sequence=last_event_id,
        )
        return [] if result is None else [result]

    def session_disclosure(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        return self._result(
            actor, "session_disclosure", key, data, {"session_id": session_id}, "CommandResult"
        )

    def session_turns(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        return self._result(
            actor, "session_turns", key, data, {"session_id": session_id}, "AssessmentView"
        )

    def session_assertions(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        return self._result(
            actor, "session_assertions", key, data, {"session_id": session_id}, "AssertionView"
        )

    def session_choices(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        return self._result(
            actor, "session_choices", key, data, {"session_id": session_id}, "CommandResult"
        )

    def session_human_request(
        self, actor: Actor, key: str, data: Record, session_id: str
    ) -> Record:
        return self._result(
            actor, "session_human_request", key, data, {"session_id": session_id}, "QueueView"
        )

    def session_end(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        return self._result(
            actor, "session_end", key, data, {"session_id": session_id}, "CommandResult"
        )

    def message_send(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        return self._result(
            actor, "message_send", key, data, {"session_id": session_id}, "MessageView"
        )

    def workforce_reserve(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        return self._result(
            actor, "workforce_reserve", key, data, {"session_id": session_id}, "AssignmentView"
        )

    def workforce_accept(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        return self._result(
            actor, "workforce_accept", key, data, {"session_id": session_id}, "AssignmentView"
        )

    def workforce_prepare_transfer(
        self, actor: Actor, key: str, data: Record, session_id: str
    ) -> Record:
        return self._result(
            actor,
            "workforce_prepare_transfer",
            key,
            data,
            {"session_id": session_id},
            "TransferPreparation",
        )

    def workforce_confirm_transfer(
        self, actor: Actor, key: str, data: Record, session_id: str
    ) -> Record:
        return self._result(
            actor,
            "workforce_confirm_transfer",
            key,
            data,
            {"session_id": session_id},
            "SessionView",
        )

    def workforce_transfer_failed(
        self, actor: Actor, key: str, data: Record, session_id: str
    ) -> Record:
        return self._result(
            actor, "workforce_transfer_failed", key, data, {"session_id": session_id}, "QueueView"
        )

    def workforce_observe(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        return self._result(
            actor, "workforce_observe", key, data, {"session_id": session_id}, "CommandResult"
        )

    def workforce_takeover(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        return self._result(
            actor, "workforce_takeover", key, data, {"session_id": session_id}, "SessionView"
        )

    def channel_ack(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        return self._result(
            actor, "channel_ack", key, data, {"session_id": session_id}, "ChannelAckView"
        )

    def continuation_rotate(self, actor: Actor, key: str, data: Record) -> Record:
        return self._result(actor, "continuation_rotate", key, data, {}, "ContinuationIssued")

    def continuation_recover(self, actor: Actor, key: str, data: Record) -> Record:
        return self._result(actor, "continuation_recover", key, data, {}, "ContinuationIssued")

    def control_change(self, actor: Actor, key: str, data: Record) -> Record:
        return self._result(actor, "control_change", key, data, {}, "CommandResult")

    def continuation_issue(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        return self._result(
            actor, "continuation_issue", key, data, {"session_id": session_id}, "ContinuationIssued"
        )

    def review_workspace(self, actor: Actor, session_id: str | None) -> Record:
        return self._result(
            actor,
            "review_workspace",
            str(uuid4()),
            {"session_id": session_id},
            {},
            "ReviewWorkspace",
        )

    def review_draft_save(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        return self._result(
            actor, "review_draft_save", key, data, {"session_id": session_id}, "ReviewDraftView"
        )

    def review_intent_prepare(
        self, actor: Actor, key: str, data: Record, session_id: str
    ) -> Record:
        return self._result(
            actor,
            "review_intent_prepare",
            key,
            data,
            {"session_id": session_id},
            "ReviewIntentView",
        )

    def review_intent_cancel(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        return self._result(
            actor, "review_intent_cancel", key, data, {"session_id": session_id}, "ReviewIntentView"
        )
