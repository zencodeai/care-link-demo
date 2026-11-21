"""Fixed HTTPS signed adapters for follow-up and own-data rights."""

from uuid import uuid4

from care_link_domain import Actor

from .manual_http import HttpManualGateway, Record


class HttpLifecycleGateway(HttpManualGateway):
    def followup_create(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        return self._result(
            actor, "followup_create", key, data, {"session_id": session_id}, "FollowUpView"
        )

    def followup_read(self, actor: Actor, followup_id: str) -> Record:
        return self._result(
            actor, "followup_read", str(uuid4()), {}, {"followup_id": followup_id}, "FollowUpView"
        )

    def followup_cancel(self, actor: Actor, key: str, data: Record, followup_id: str) -> Record:
        return self._result(
            actor, "followup_cancel", key, data, {"followup_id": followup_id}, "FollowUpView"
        )

    def outcome_append(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        return self._result(
            actor, "outcome_append", key, data, {"session_id": session_id}, "CommandResult"
        )

    def outcomes_read(
        self, actor: Actor, session_id: str, *, limit: int = 50, cursor: str | None = None
    ) -> Record:
        return self._result(
            actor,
            "outcomes_read",
            str(uuid4()),
            {"limit": limit, **({"cursor": cursor} if cursor is not None else {})},
            {"session_id": session_id},
            "OutcomePage",
        )

    def hold_create(self, actor: Actor, key: str, data: Record) -> Record:
        return self._result(actor, "hold_create", key, data, {}, "CommandResult")

    def rights_create(self, actor: Actor, key: str, data: Record) -> Record:
        return self._result(actor, "rights_create", key, data, {}, "RightsView")

    def hold_release(self, actor: Actor, key: str, data: Record, hold_id: str) -> Record:
        return self._result(actor, "hold_release", key, data, {"hold_id": hold_id}, "CommandResult")

    def rights_read(self, actor: Actor, rights_id: str) -> Record:
        return self._result(
            actor, "rights_read", str(uuid4()), {}, {"rights_id": rights_id}, "RightsView"
        )

    def export_download(self, actor: Actor, rights_id: str) -> Record:
        return self._result(
            actor, "export_download", str(uuid4()), {}, {"rights_id": rights_id}, "ExportView"
        )

    def post_crisis_record(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        return self._result(
            actor, "post_crisis_record", key, data, {"session_id": session_id}, "PostCrisisView"
        )

    def participant_inbox(
        self, actor: Actor, *, limit: int = 50, cursor: str | None = None
    ) -> Record:
        return self._result(
            actor,
            "participant_inbox",
            str(uuid4()),
            {"limit": limit, **({"cursor": cursor} if cursor is not None else {})},
            {},
            "InboxPage",
        )

    def followup_bind_anchor(
        self, actor: Actor, key: str, data: Record, followup_id: str
    ) -> Record:
        return self._result(
            actor, "followup_bind_anchor", key, data, {"followup_id": followup_id}, "FollowUpView"
        )

    def inbox_message_read(self, actor: Actor, message_id: str) -> Record:
        return self._result(
            actor,
            "inbox_message_read",
            str(uuid4()),
            {},
            {"message_id": message_id},
            "InboxMessageView",
        )
