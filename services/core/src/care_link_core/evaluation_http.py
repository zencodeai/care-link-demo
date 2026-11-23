"""Fixed signed adapter for the Data-owned synthetic replay ledger."""

from uuid import uuid4

from care_link_domain import Actor

from .manual_http import HttpManualGateway, Record


class HttpEvaluationGateway(HttpManualGateway):
    def replay_create(self, actor: Actor, key: str, data: Record) -> Record:
        return self._result(actor, "replay_create", key, data, {}, "EvaluationView")

    def evaluation_read(self, actor: Actor, evaluation_id: str) -> Record:
        return self._result(
            actor,
            "evaluation_read",
            str(uuid4()),
            {},
            {"evaluation_id": evaluation_id},
            "EvaluationView",
        )
