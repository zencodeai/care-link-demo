"""Fixed signed gateway operations; no model credentials or business DB access."""

from uuid import uuid4

from care_link_domain import Actor, ManualError

from ..manual_http import HttpManualGateway
from .ports import Record


class HttpAssistanceGateway(HttpManualGateway):
    def knowledge(self, actor: Actor, data: Record) -> Record:
        # Patient-independent lookup has explicit Core catalog custody; it is
        # not an implicit unsigned data-gateway operation.
        raise ManualError("assistance.knowledge_unavailable", 503)

    def task_create(self, actor: Actor, key: str, data: Record) -> Record:
        return self._result(actor, "task_create", key, data, {}, "TaskView")

    def task_read(self, actor: Actor, task_id: str) -> Record:
        return self._result(actor, "task_read", str(uuid4()), {}, {"task_id": task_id}, "TaskView")

    def task_context(self, actor: Actor, task_id: str) -> Record:
        return self._result(
            actor,
            "assistance_task_context",
            str(uuid4()),
            {},
            {"task_id": task_id},
            "AssistanceTaskContext",
        )

    def task_cancel(self, actor: Actor, key: str, data: Record, task_id: str) -> Record:
        return self._result(actor, "task_cancel", key, data, {"task_id": task_id}, "TaskView")

    def task_revise(self, actor: Actor, key: str, data: Record, task_id: str) -> Record:
        return self._result(actor, "task_revise", key, data, {"task_id": task_id}, "TaskView")

    def draft_read(self, actor: Actor, draft_id: str) -> Record:
        return self._result(
            actor, "draft_read", str(uuid4()), {}, {"draft_id": draft_id}, "DraftView"
        )

    def draft_context(self, actor: Actor, draft_id: str) -> Record:
        return self._result(
            actor,
            "assistance_draft_context",
            str(uuid4()),
            {},
            {"draft_id": draft_id},
            "AssistanceDraftContext",
        )

    def draft_review(self, actor: Actor, key: str, data: Record, draft_id: str) -> Record:
        return self._result(actor, "draft_review", key, data, {"draft_id": draft_id}, "ReviewView")
