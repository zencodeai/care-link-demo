"""Server context, admission pins and exact gateway-proposal custody.

Only an authenticated inference response can enter pending proposal custody.
Restart discards this custody, requiring a newly reserved attempt; the durable
coordinator counters and fences never reset with this process.
"""

import hashlib
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

from care_link_contracts import validate_contract
from care_link_domain import Actor, ManualError, WorkloadPeer

from .ports import Coordinator, InferencePort, Record


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def record(value: object) -> Record:
    if not isinstance(value, dict):
        raise ManualError("assistance.invalid_context", 503)
    return cast(Record, value)


@dataclass(frozen=True)
class ReleasedFunction:
    function: str
    model_digest: str
    prompt_digest: str
    instruction_source: Record
    instruction: str


@dataclass(frozen=True)
class Pending:
    proposal_digest: str
    reservation_id: str
    actor: Actor
    peer: WorkloadPeer
    expires_at: datetime


class InferenceBroker:
    def __init__(
        self,
        coordinator: Coordinator,
        inference: InferencePort,
        *,
        actor_for_task: Callable[[str], Actor],
        release: Callable[[str], ReleasedFunction],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        work: Callable[[], Record] | None = None,
    ) -> None:
        self.coordinator, self.inference = coordinator, inference
        self.actor_for_task, self.release, self.clock = actor_for_task, release, clock
        self.pending: dict[tuple[str, str, str], Pending] = {}
        self.lock = threading.Lock()
        self.work = work

    def claim_work(self, peer: WorkloadPeer) -> Record:
        if (
            peer.workload_id != "spiffe://care-link.demo/demo/runtime"
            or peer.certificate_expires_at <= self.clock()
        ):
            raise ManualError("assistance.runtime_required", 403)
        value: Record = (
            self.work() if self.work else {"task_id": None, "task_revision": None, "fence": None}
        )
        validate_contract("RuntimeWorkItem", value)
        return value

    def _actor(self, task_id: str, peer: WorkloadPeer) -> Actor:
        if (
            peer.workload_id != "spiffe://care-link.demo/demo/runtime"
            or peer.certificate_expires_at <= self.clock()
        ):
            raise ManualError("assistance.runtime_required", 403)
        # This resolver is composition-owned. No actor ID or authority is read
        # from runtime input, model output or tool text.
        return self.actor_for_task(task_id)

    def lease(
        self, task_id: str, data: Record, peer: WorkloadPeer, *, renew: bool = False
    ) -> Record:
        validate_contract("LeaseCommand", data)
        actor = self._actor(task_id, peer)
        method = self.coordinator.step_renew if renew else self.coordinator.step_lease
        result = method(actor, task_id, data, peer)
        validate_contract("LeaseView", result)
        return result

    def tool(self, data: Record, peer: WorkloadPeer) -> Record:
        validate_contract("ToolInvoke", data)
        actor = self._actor(cast(str, data["task_id"]), peer)
        result = self.coordinator.tool_invoke(actor, data, peer)
        validate_contract("Observation", result)
        return result

    def infer(self, data: Record, peer: WorkloadPeer) -> Record:
        validate_contract("RuntimeInferenceRequest", data)
        actor = self._actor(cast(str, data["task_id"]), peer)
        reserved = self.coordinator.reserve_proposal(actor, data, peer)
        task = record(reserved["task"])
        bundle = self.release(cast(str, task["function"]))
        if (
            bundle.function != task["function"]
            or bundle.instruction_source.get("digest")
            != hashlib.sha256(bundle.instruction.encode()).hexdigest()
            or bundle.instruction_source.get("verification") != "verified"
            or bundle.instruction_source.get("kind") not in {"template", "artifact"}
        ):
            raise ManualError("assistance.release_unverified", 503)
        sources = cast(list[Record], reserved["sources"])
        items: list[Record] = [
            {
                "source": bundle.instruction_source,
                "label": "approved_instruction",
                "text": bundle.instruction,
                "critical": True,
            },
            {
                "source": bundle.instruction_source,
                "label": "structured_state",
                "text": canonical({"task": task, "goal": reserved["goal"], "step": data}),
                "critical": True,
            },
            *[
                {
                    "source": item["ref"],
                    "label": "untrusted_report",
                    "text": item["text"],
                    "critical": True,
                }
                for item in sources
            ],
        ]
        instruction_digest = hashlib.sha256(canonical(items[:1]).encode()).hexdigest()
        if bundle.prompt_digest != instruction_digest:
            raise ManualError("assistance.release_unverified", 503)
        deadline = min(
            self.clock() + timedelta(seconds=30),
            datetime.fromisoformat(cast(str, task["deadline"])),
        )
        request: Record = {
            "job_id": str(uuid4()),
            "task_id": data["task_id"],
            "step_id": data["step_id"],
            "fence": data["fence"],
            "function": task["function"],
            "model_digest": bundle.model_digest,
            "prompt_digest": bundle.prompt_digest,
            "items": items,
            "budgets": task["budgets"],
            "deadline": deadline.isoformat().replace("+00:00", "Z"),
        }
        validate_contract("InferenceRequest", request)
        result = self.inference.infer(request)
        validate_contract("InferenceResult", result)
        if result["job_id"] != request["job_id"] or result["model_digest"] != bundle.model_digest:
            raise ManualError("assistance.inference_binding", 503)
        if result["state"] != "completed":
            if result["proposal"] is not None:
                raise ManualError("assistance.invalid_inference_result", 503)
            return result
        proposal = record(result["proposal"])
        if any(
            proposal[key] != data[key]
            for key in ("task_id", "step_id", "fence", "expected_task_revision")
        ):
            raise ManualError("assistance.inference_binding", 503)
        # Initial worker_summary admission is extractive. Source citation alone
        # cannot legitimize invented legal/service/care-success statements.
        text = cast(str, proposal["candidate_text"])
        cited = cast(list[Record], proposal["sources"])
        admitted = [record(source["ref"]) for source in sources]
        excerpts = {cast(str, source["text"]) for source in sources if source["ref"] in cited}
        cited_keys = [canonical(source) for source in cited]
        source_text = {canonical(source["ref"]): cast(str, source["text"]) for source in sources}
        exact_join = text == "\n".join(source_text.get(key, "") for key in cited_keys)
        # Preserve the existing whole-single-line excerpt behavior, and accept
        # exact full multiline excerpts in citation order. No snippet extraction
        # or model-added connective text is admitted by the multiline path.
        literal_lines = all(line in excerpts for line in text.splitlines() if line.strip())
        if (
            not cited
            or len(set(cited_keys)) != len(cited_keys)
            or any(source not in admitted for source in cited)
            or proposal["next"] is not None
            or not text.strip()
            or not (exact_join or literal_lines)
            or self.clock() >= deadline
        ):
            raise ManualError("assistance.unsupported_proposal", 409)
        key = (cast(str, data["task_id"]), cast(str, data["step_id"]), cast(str, data["fence"]))
        with self.lock:
            self.pending = {k: p for k, p in self.pending.items() if p.expires_at > self.clock()}
            self.pending[key] = Pending(
                hashlib.sha256(canonical(proposal).encode()).hexdigest(),
                cast(str, reserved["reservation_id"]),
                actor,
                peer,
                deadline,
            )
        return result

    def propose(self, data: Record, peer: WorkloadPeer) -> Record:
        validate_contract("Proposal", data)
        task_id = cast(str, data["task_id"])
        current = self._actor(task_id, peer)
        key = (task_id, cast(str, data["step_id"]), cast(str, data["fence"]))
        with self.lock:
            pending = self.pending.get(key)
            if (
                pending is None
                or pending.expires_at <= self.clock()
                or pending.peer != peer
                or pending.actor.account_id != current.account_id
                or pending.proposal_digest != hashlib.sha256(canonical(data).encode()).hexdigest()
            ):
                raise ManualError("assistance.gateway_proposal_required", 409)
            result = self.coordinator.proposal_submit(current, data, peer, pending.reservation_id)
            self.pending.pop(key, None)
        # Coordinator stores an unsent draft; runtime sees task status only.
        validate_contract("DraftView", result)
        actor = self.actor_for_task(task_id)
        task = self.coordinator.task_read(actor, task_id)
        validate_contract("TaskView", task)
        return task
