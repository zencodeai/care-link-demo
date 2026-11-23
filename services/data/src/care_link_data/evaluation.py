"""Guarded metadata for deterministic replay of admitted synthetic scenarios."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal, Protocol, TypedDict
from uuid import uuid4

from care_link_contracts import validate_contract
from care_link_domain import Actor, ManualError

from .engine import Engine
from .store import Record, Transaction, instant, text
from .values import Outcome, object_value


class ReplayCreate(TypedDict):
    scenario_id: str
    input_manifest_digest: str
    recorded_outputs_digest: str
    bundle_digest: str


@dataclass(frozen=True)
class ReplayResult:
    state: Literal["completed", "failed"]
    evidence_digest: str | None


class ReplayEvaluator(Protocol):
    def authorize(self, actor: Actor, request: ReplayCreate) -> None:
        """Check current explicit scenario custody and exact admitted input pins."""
        ...

    def evaluate(self, request: ReplayCreate) -> ReplayResult:
        """Re-execute bounded offline rules against pinned inputs and observations."""
        ...


def replay_request(data: Record) -> ReplayCreate:
    return {
        "scenario_id": text(data, "scenario_id"),
        "input_manifest_digest": text(data, "input_manifest_digest"),
        "recorded_outputs_digest": text(data, "recorded_outputs_digest"),
        "bundle_digest": text(data, "bundle_digest"),
    }


def evaluation_view(row: Record) -> Record:
    return {
        "id": text(row, "id"),
        "state": text(row, "state"),
        "evidence_digest": row["evidence_digest"],
        "clinical_claim": False,
    }


def evaluation_row(service: Engine, tx: Transaction, evaluation_id: str) -> Record:
    row = tx.get("evaluation", evaluation_id)
    if row is None or instant(row, "expires_at") <= service.clock():
        raise ManualError("evaluation.not_found", 404)
    return row


def evaluation_policy(
    service: Engine, tx: Transaction, actor: Actor, action: str, data: Record, request: Record
) -> None:
    """Build exact authority facts for the separately admitted replay corpus."""
    facts = object_value(request["authority_facts"])
    evaluator = service.replay_evaluator
    admitted = False
    if facts["resource_owned_or_assigned"] and evaluator is not None:
        try:
            source = (
                data
                if action == "replay_create"
                else evaluation_row(service, tx, text(data, "evaluation_id"))
            )
            target = replay_request(source)
            validate_contract("ReplayCreate", target)
            evaluator.authorize(actor, target.copy())
        except ManualError as error:
            if error.status >= 500:
                raise
        else:
            admitted = True
            request["artifact_digests"] = sorted(
                {
                    target["input_manifest_digest"],
                    target["recorded_outputs_digest"],
                    target["bundle_digest"],
                }
            )
            if action == "evaluation_read":
                object_value(request["versions"])["resource"] = "1"
    facts["resource_owned_or_assigned"] = admitted
    facts["field_scope_allowed"] = admitted
    facts["source_current"] = admitted
    facts["artifact_admitted"] = admitted


def check_evaluation_output(
    service: Engine, tx: Transaction, actor: Actor, result: Record, snapshot: Record
) -> None:
    """Recheck custody and authority before releasing an audited result."""
    row = evaluation_row(service, tx, text(result, "id"))
    evaluator = service.replay_evaluator
    if evaluator is None:
        raise ManualError("evaluation.disabled", 503)
    current = service.current_actor(actor)
    if not service.channel.current(
        current.account_id, current.browser_session_digest, current.transport_generation
    ):
        raise ManualError("evaluation.channel_changed", 409)
    evaluator.authorize(current, replay_request(row))
    service.assert_journal_current(snapshot)


class Evaluation(Engine):
    def replay_create(self, actor: Actor, key: str, data: Record) -> Record:
        evaluator = self.replay_evaluator
        if evaluator is None:
            raise ManualError("evaluation.disabled", 503)
        validate_contract("ReplayCreate", data)
        target = replay_request(data)
        result: ReplayResult | None = None

        def prepare() -> None:
            nonlocal result
            evaluator.authorize(actor, target.copy())
            result = evaluator.evaluate(target.copy())

        def apply(
            tx: Transaction,
            current: Actor,
            _data: Record,
            _session: Record | None,
            _guard: Record | None,
        ) -> Outcome:
            if result is None:
                raise ManualError("evaluation.offline_result_unavailable", 503)
            resource_id = str(uuid4())
            created_at = self.clock()
            row: Record = {
                "id": resource_id,
                "principal_id": current.account_id,
                **target,
                "state": result.state,
                "evidence_digest": result.evidence_digest,
                "created_at": created_at,
                "expires_at": created_at + timedelta(days=7),
            }
            if result.state not in {"completed", "failed"} or (
                result.state == "completed" and result.evidence_digest is None
            ):
                raise ManualError("evaluation.invalid_offline_result", 503)
            view = evaluation_view(row)
            validate_contract("EvaluationView", view)
            tx.put("evaluation", row)
            return Outcome("EvaluationView", view, resource_id=resource_id)

        def replay(
            tx: Transaction,
            _actor: Actor,
            _data: Record,
            _session: Record | None,
            _guard: Record | None,
        ) -> Outcome:
            operation = tx.get("operation", key)
            if operation is None:
                raise ManualError("evaluation.not_found", 404)
            row = evaluation_row(self, tx, text(operation, "resource_id"))
            if replay_request(row) != target:
                raise ManualError("evaluation.corrupt_binding", 503)
            return Outcome("EvaluationView", evaluation_view(row))

        return self._run(
            actor,
            "replay_create",
            key,
            dict(target),
            None,
            apply,
            contract="ReplayCreate",
            replay=replay,
            prepare_effect=prepare,
        )

    def evaluation_read(self, actor: Actor, evaluation_id: str) -> Record:
        if self.replay_evaluator is None:
            raise ManualError("evaluation.disabled", 503)

        def read(
            tx: Transaction,
            _actor: Actor,
            _data: Record,
            _session: Record | None,
            _guard: Record | None,
        ) -> Outcome:
            return Outcome(
                "EvaluationView", evaluation_view(evaluation_row(self, tx, evaluation_id))
            )

        return self._run(
            actor,
            "evaluation_read",
            None,
            {"evaluation_id": evaluation_id},
            None,
            read,
            contract="Path_evaluation_read",
        )
