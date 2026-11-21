"""Real data coordinator plus Core broker; inference is an explicit synthetic double."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from care_link_core.assistance_broker import InferenceBroker, ReleasedFunction
from care_link_core.assistance_broker.actors import ActorTasks
from care_link_core.assistance_broker.broker import canonical
from care_link_domain import ManualError

from services.data.tests.test_assistance import case, review_body


class InferenceDouble:
    def __init__(self):
        self.requests = []
        self.unsupported = False
        self.unknown = False

    def infer(self, request):
        self.requests.append(request)
        state = json.loads(
            next(i["text"] for i in request["items"] if i["label"] == "structured_state")
        )
        sources = [i for i in request["items"] if i["label"] == "untrusted_report"]
        proposal = {
            "task_id": request["task_id"],
            "step_id": request["step_id"],
            "fence": request["fence"],
            "expected_task_revision": state["task"]["revision"],
            "sources": [i["source"] for i in sources],
            "candidate_text": "Guarantees connection." if self.unsupported else sources[0]["text"],
            "next": None,
            "completion_claim": True,
        }
        return {
            "job_id": request["job_id"],
            "state": "compute_unknown" if self.unknown else "completed",
            "proposal": None if self.unknown else proposal,
            "input_tokens": 100,
            "output_tokens": 50,
            "model_digest": request["model_digest"],
            "safe_reason": "provider_stop_unverified" if self.unknown else None,
        }


def chain(h):
    coordinator, command, peer = case(h)
    task = coordinator.task_create(h.worker, str(uuid4()), command)
    actors = ActorTasks()
    actors.bind(h.worker, task)
    inference = InferenceDouble()
    instruction = "Quote only attributed fictional source text; produce an unsent summary."
    source = {
        "kind": "template",
        "id": str(uuid4()),
        "revision": "1",
        "digest": hashlib.sha256(instruction.encode()).hexdigest(),
        "observed_at": "2026-11-20T00:00:00Z",
        "verification": "verified",
    }
    item = {
        "source": source,
        "label": "approved_instruction",
        "text": instruction,
        "critical": True,
    }
    bundle = ReleasedFunction(
        "worker_summary",
        "a" * 64,
        hashlib.sha256(canonical([item]).encode()).hexdigest(),
        source,
        instruction,
    )
    broker = InferenceBroker(
        coordinator,
        inference,
        actor_for_task=actors.resolve,
        release=lambda _: bundle,
    )
    lease = broker.lease(
        task["id"],
        {
            "expected_revision": task["revision"],
            "step_id": str(uuid4()),
            "fence": "0",
        },
        peer,
    )
    request = {
        "task_id": task["id"],
        "step_id": lease["step_id"],
        "fence": lease["fence"],
        "expected_task_revision": task["revision"],
    }
    return coordinator, inference, broker, task, request, peer


def test_server_context_and_gateway_proposal_custody_then_human_reject(harness):
    coordinator, inference, broker, task, request, peer = chain(harness)
    result = broker.infer(request, peer)
    items = inference.requests[0]["items"]
    assert [i["label"] for i in items[:2]] == ["approved_instruction", "structured_state"]
    assert all(i["label"] == "untrusted_report" for i in items[2:])
    forged = {**result["proposal"], "candidate_text": "A model grants service consent."}
    with pytest.raises(ManualError, match="gateway_proposal_required"):
        broker.propose(forged, peer)
    current = broker.propose(result["proposal"], peer)
    assert current["state"] == "awaiting_human"
    context = coordinator.task_context(harness.worker, task["id"])
    draft = coordinator.draft_read(harness.worker, context["draft_id"])
    coordinator.draft_review(
        harness.worker, str(uuid4()), review_body(draft, "reject"), draft["id"]
    )
    assert harness.read("SELECT count(*) FROM referral.dispatch")[0][0] == 0
    assert harness.service.session_read(harness.worker, task["scope"]["session_id"])["id"]
    with pytest.raises(ManualError, match="gateway_proposal_required"):
        broker.propose(result["proposal"], peer)


def test_valid_citation_cannot_admit_unsupported_claims(harness):
    _coordinator, inference, broker, _task, request, peer = chain(harness)
    inference.unsupported = True
    with pytest.raises(ManualError, match="unsupported_proposal"):
        broker.infer(request, peer)
    assert harness.read("SELECT count(*) FROM assistance.draft")[0][0] == 0


def test_unknown_compute_and_wrong_peer_never_enter_proposal_custody(harness):
    _coordinator, inference, broker, task, request, peer = chain(harness)
    inference.unknown = True
    assert broker.infer(request, peer)["state"] == "compute_unknown"
    with pytest.raises(ManualError, match="runtime_required"):
        broker.infer(request, replace(peer, workload_id="spiffe://care-link.demo/demo/core"))
    assert harness.read("SELECT count(*) FROM assistance.draft")[0][0] == 0
    assert harness.service.session_read(harness.worker, task["scope"]["session_id"])["id"]


def test_actor_capability_expires_and_restart_cannot_recreate_it(harness):
    coordinator, command, _peer = case(harness)
    task = coordinator.task_create(harness.worker, str(uuid4()), command)
    now = datetime.now(UTC)
    actors = ActorTasks(clock=lambda: now)
    actors.bind(harness.worker, task)
    now += timedelta(seconds=61)
    with pytest.raises(ManualError, match="resumption_required"):
        actors.resolve(task["id"])
    with pytest.raises(ManualError, match="resumption_required"):
        ActorTasks().resolve(task["id"])
    assert coordinator.task_read(harness.worker, task["id"])["steps_used"] == 0
