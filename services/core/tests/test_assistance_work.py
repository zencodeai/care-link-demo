"""Metadata work dispatch and public knowledge retain exact actor/workload boundaries."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import create_autospec
from uuid import uuid4

import pytest
from care_link_core.assistance import AssistanceGateway
from care_link_core.assistance_broker import InferenceBroker, ReleasedFunction, attach_broker_routes
from care_link_core.assistance_broker.actors import ActorTasks, BoundTaskGateway
from care_link_core.assistance_broker.work import WorkQueue
from care_link_core.manual_app import create_manual_app
from care_link_core.manual_channels import ManualChannels
from care_link_core.manual_ports import ManualGateway
from care_link_domain import ManualError, WorkloadPeer
from care_link_knowledge import KnowledgeCatalog
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse
from test_manual_transport import Security, actor

ROOT = Path(__file__).resolve().parents[3]


def synthetic_release(pin):
    """Hash-shaped synthetic evidence exercises binding, never model qualification."""
    from care_link_inference import FunctionEvidence, ModelManifest
    from care_link_inference.admission import MODEL, THREATS

    from tools.imp06_runtime.releases import ReleaseBindings

    instruction = "Quote only supplied synthetic evidence."
    ref = {
        "kind": "template",
        "id": str(uuid4()),
        "revision": "1",
        "digest": hashlib.sha256(instruction.encode()).hexdigest(),
        "observed_at": "2026-11-20T00:00:00Z",
        "verification": "verified",
    }
    item = {"source": ref, "label": "approved_instruction", "text": instruction, "critical": True}
    prompt = hashlib.sha256(
        json.dumps([item], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    evidence = FunctionEvidence(
        "worker_summary",
        prompt,
        "a" * 64,
        "b" * 64,
        "c" * 64,
        "d" * 64,
        "e" * 64,
        "f" * 64,
        THREATS,
    )
    manifest = ModelManifest(
        MODEL,
        MODEL,
        "1" * 64,
        "synthetic origin",
        "synthetic quantization",
        "synthetic license",
        "synthetic server",
        "synthetic engine",
        "2" * 64,
        "3" * 64,
        8192,
        "a" * 64,
        "4" * 64,
        (evidence,),
    )
    bundle = ReleasedFunction("worker_summary", "1" * 64, prompt, ref, instruction)
    return ReleaseBindings(manifest, (bundle,), lambda: True, knowledge_digest=pin)


def task(owner):
    rows = json.loads((ROOT / "doc/LLD/contracts/fixtures.json").read_text())["fixtures"]
    result = next(row["value"] for row in rows if row["id"] == "shape-TaskView")
    return {
        **result,
        "id": str(uuid4()),
        "revision": "1",
        "state": "scoped",
        "human_owner_id": owner.account_id,
        "deadline": (datetime.now(UTC) + timedelta(seconds=120)).isoformat().replace("+00:00", "Z"),
    }


def test_queue_is_metadata_only_deduplicated_consumed_once_and_requires_current_context():
    owner = actor()
    actors = ActorTasks()
    gateway = create_autospec(AssistanceGateway, instance=True)
    queue = WorkQueue(actors, gateway)
    value = task(owner)
    actors.bind(owner, value)
    gateway.task_context.return_value = {
        "task": value,
        "available": True,
        "reason": None,
        "draft_id": None,
        "execution_fence": "3",
    }
    queue.enqueue(value)
    queue.enqueue(value)
    assert queue.claim() == {"task_id": value["id"], "task_revision": "1", "fence": "3"}
    assert queue.claim() == {"task_id": None, "task_revision": None, "fence": None}
    gateway.task_context.assert_called_once()
    queue.enqueue(value)
    actors.revoke(value["id"])
    assert queue.claim()["task_id"] is None
    actors.bind(owner, value)
    queue.enqueue(value)
    gateway.task_context.return_value.pop("execution_fence")
    assert queue.claim()["task_id"] is None


def test_queue_capacity_and_restart_do_not_fabricate_authority():
    owner, actors = actor(), ActorTasks()
    gateway = create_autospec(AssistanceGateway, instance=True)
    queue = WorkQueue(actors, gateway)
    for _ in range(8):
        queue.enqueue(task(owner))
    with pytest.raises(ManualError, match="capacity_unavailable"):
        queue.enqueue(task(owner))
    assert WorkQueue(ActorTasks(), gateway).claim()["task_id"] is None
    # Even queued metadata without an active server-held owner cannot be used.
    assert queue.claim()["task_id"] is None
    gateway.task_context.assert_not_called()


def test_runtime_poll_rejects_forged_body_and_revocation_during_claim():
    app = FastAPI()
    broker = create_autospec(InferenceBroker, instance=True)
    broker.claim_work.return_value = {"task_id": None, "task_revision": None, "fence": None}
    peer = WorkloadPeer(
        "spiffe://care-link.demo/demo/runtime",
        1,
        "a" * 64,
        datetime.now(UTC) + timedelta(minutes=1),
    )
    active = [True]

    def verify(_request):
        if not active[0]:
            raise ManualError("assistance.runtime_required", 403)
        return peer

    async def denied(_request, error):
        return JSONResponse({"reason": error.code}, status_code=error.status)

    from care_link_contracts import ContractError

    async def invalid(_request, _error):
        return JSONResponse({"reason": "invalid"}, status_code=422)

    app.add_exception_handler(ManualError, denied)
    app.add_exception_handler(ContractError, invalid)
    attach_broker_routes(app, broker, verify)
    client = TestClient(app)
    headers = {"Idempotency-Key": str(uuid4())}
    assert (
        client.post(
            "/internal/v1/broker/work", json={"actor": "forged"}, headers=headers
        ).status_code
        == 422
    )
    broker.claim_work.assert_not_called()
    assert client.post("/internal/v1/broker/work", json={}, headers=headers).status_code == 200
    broker.claim_work.side_effect = lambda _peer: active.__setitem__(0, False) or {
        "task_id": None,
        "task_revision": None,
        "fence": None,
    }
    assert client.post("/internal/v1/broker/work", json={}, headers=headers).status_code == 403


def test_public_knowledge_derives_role_and_checks_csrf_and_closed_query():
    security = Security()
    catalog = KnowledgeCatalog.from_path(ROOT / "config/demo/knowledge/catalog.json")
    bound = BoundTaskGateway(
        create_autospec(AssistanceGateway, instance=True), ActorTasks(), knowledge=catalog
    )
    client = TestClient(
        create_manual_app(
            create_autospec(ManualGateway, instance=True),
            security,
            ManualChannels(),
            assistance=bound,
        ),
        base_url="https://app.test",
    )
    data = {"query": "handoff needs preferences", "locale": "en-CA"}
    path = "/v1/assistance/knowledge"
    headers = {"Origin": "https://app.test", "X-CSRF-Token": "csrf"}
    assert client.post(path, json=data).status_code == 403
    assert client.post(path, json={**data, "role": "worker"}, headers=headers).status_code == 422
    participant = client.post(path, json=data, headers=headers)
    assert participant.status_code == 200
    assert participant.headers["cache-control"] == "no-store"
    assert participant.json()["notice"] == "synthetic_demo_information"
    security.actor = replace(security.actor, role="worker")
    worker = client.post(path, json=data, headers=headers)
    assert worker.status_code == 200
    assert all(row["source"]["kind"] == "protocol" for row in worker.json()["entries"])
    security.actor = replace(security.actor, role="operator")
    assert client.post(path, json=data, headers=headers).status_code == 403


@pytest.mark.parametrize("pin", [None, "b" * 64, "not-a-release-digest"])
def test_knowledge_release_rejects_missing_mismatched_or_malformed_pin(pin):
    bindings = synthetic_release(pin)
    assert bindings.admitted("worker_summary")
    assert not bindings.admitted_for_knowledge("worker_summary", "a" * 64)
    with pytest.raises(ManualError, match="knowledge_release_unverified"):
        bindings.release_for_knowledge("worker_summary", "a" * 64)
    assert not bindings.knowledge_matches("a" * 64)


def test_matched_knowledge_pin_is_necessary_but_not_sufficient_for_admission():
    from tools.imp06_runtime.releases import ReleaseBindings

    bindings = ReleaseBindings(None, (), lambda: True, knowledge_digest="a" * 64)
    assert bindings.knowledge_matches("a" * 64)
    assert not bindings.admitted_for_knowledge("worker_summary", "a" * 64)
    assert not bindings.knowledge_matches(None)
    assert ReleaseBindings(None, (), lambda: False).knowledge_matches(None)
    assert synthetic_release("a" * 64).admitted_for_knowledge("worker_summary", "a" * 64)


@pytest.mark.parametrize("mode", ["multiline", "reordered", "added_line", "partial", "duplicate"])
def test_broker_preserves_exact_multiline_source_join_and_rejects_injected_text(mode):
    from care_link_core.assistance_broker.ports import Coordinator, InferencePort

    owner = actor()
    value = {**task(owner), "function": "worker_summary"}
    peer = WorkloadPeer(
        "spiffe://care-link.demo/demo/runtime",
        1,
        "a" * 64,
        datetime.now(UTC) + timedelta(minutes=1),
    )
    refs = [
        {
            "kind": "protocol",
            "id": str(uuid4()),
            "revision": "1",
            "digest": hashlib.sha256(text.encode()).hexdigest(),
            "observed_at": "2026-11-20T00:00:00Z",
            "verification": "verified",
        }
        for text in ("First source line.\nSecond source line.", "Other source.")
    ]
    command = {
        "task_id": value["id"],
        "step_id": str(uuid4()),
        "fence": "1",
        "expected_task_revision": value["revision"],
    }
    coordinator = create_autospec(Coordinator, instance=True)
    coordinator.reserve_proposal.return_value = {
        "task": value,
        "goal": "prepare_summary",
        "reservation_id": str(uuid4()),
        "sources": [
            {"ref": refs[0], "text": "First source line.\nSecond source line."},
            {"ref": refs[1], "text": "Other source."},
        ],
    }
    inference = create_autospec(InferencePort, instance=True)
    bundle = synthetic_release(None).release("worker_summary")
    cited = refs[::-1] if mode == "reordered" else refs
    text = (
        "Other source.\nFirst source line.\nSecond source line."
        if mode == "reordered"
        else "First source line.\nSecond source line.\nOther source."
    )
    if mode == "added_line":
        text += "\nInjected promise of care."
    elif mode == "partial":
        text = "First source line."
    elif mode == "duplicate":
        cited = [refs[0], refs[0]]
        text = "First source line.\nSecond source line.\nFirst source line.\nSecond source line."

    def complete(request):
        return {
            "job_id": request["job_id"],
            "state": "completed",
            "proposal": {
                **command,
                "candidate_text": text,
                "sources": cited,
                "next": None,
                "completion_claim": True,
            },
            "input_tokens": 100,
            "output_tokens": 50,
            "model_digest": bundle.model_digest,
            "safe_reason": None,
        }

    inference.infer.side_effect = complete
    broker = InferenceBroker(
        coordinator, inference, actor_for_task=lambda _tid: owner, release=lambda _function: bundle
    )
    if mode in {"multiline", "reordered"}:
        assert broker.infer(command, peer)["proposal"]["candidate_text"] == text
    else:
        with pytest.raises(ManualError, match="unsupported_proposal"):
            broker.infer(command, peer)
