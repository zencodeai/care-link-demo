"""Real PostgreSQL shared-counter, authority, review and persistence behavior."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from care_link_contracts import validate_contract
from care_link_data.assistance import AssistanceCoordinator
from care_link_data.values import stamp
from care_link_domain import ManualError, WorkloadPeer

from services.data.tests.test_manual import connected


def case(h, runtime_current=lambda _peer: True):
    session = connected(h)
    h.service.session_assertions(
        h.participant,
        str(uuid4()),
        {
            "expected_revision": session["revision"],
            "subject_id": session["subject_id"],
            "field": "needs",
            "value": {"kind": "text", "text": "Fictional needs"},
            "supersedes_id": None,
            "effective_at": stamp(datetime.now(UTC)),
        },
        session["id"],
    )
    session = h.service.session_read(h.worker, session["id"])
    with psycopg.connect(h.database.admin) as tx:
        tx.execute("UPDATE control.guard SET mode='normal'")
    service = AssistanceCoordinator(
        h.service, admitted=lambda f: f == "worker_summary", runtime_current=runtime_current
    )
    data = {
        "expected_revision": session["revision"],
        "function": "worker_summary",
        "scope": {
            "session_id": session["id"],
            "subject_id": None,
            "purpose": "support",
            "fields": ["needs"],
            "recipient_id": None,
        },
        "goal": "prepare_summary",
        "inputs": [],
        "completion": "draft_ready",
        "binding": {"kind": "session", "session_id": session["id"]},
    }
    peer = WorkloadPeer(
        "spiffe://care-link.demo/demo/runtime", 1, "a" * 64, datetime.now(UTC) + timedelta(hours=1)
    )
    return service, data, peer


def lease(service, h, task, peer, fence="0"):
    return service.step_lease(
        h.worker,
        task["id"],
        {"expected_revision": task["revision"], "step_id": str(uuid4()), "fence": fence},
        peer,
    )


def request(task, claimed):
    return {
        "task_id": task["id"],
        "step_id": claimed["step_id"],
        "fence": claimed["fence"],
        "expected_task_revision": task["revision"],
    }


def draft(service, h, task, peer):
    claimed = lease(service, h, task, peer)
    reserved = service.reserve_proposal(h.worker, request(task, claimed), peer)
    proposal = {
        **request(task, claimed),
        "candidate_text": "Fictional needs",
        "sources": [s["ref"] for s in reserved["sources"]],
        "next": None,
        "completion_claim": True,
    }
    return service.proposal_submit(h.worker, proposal, peer, reserved["reservation_id"])


def review_body(draft, decision="accept", edited=None):
    return {
        "expected_revision": draft["revision"],
        "draft_id": draft["id"],
        "exact_digest": draft["payload_digest"],
        "source_vector": draft["source_vector"],
        "decision": decision,
        "edited_text": edited,
        "expires_at": stamp(datetime.now(UTC) + timedelta(seconds=60)),
    }


def test_disabled_functions_and_control_preserve_manual(harness):
    h = harness
    service, data, _peer = case(h)
    assert AssistanceCoordinator(h.service).availability(h.worker)["available"] is False
    with pytest.raises(ManualError, match="function_disabled"):
        AssistanceCoordinator(h.service).task_create(h.worker, str(uuid4()), data)
    with psycopg.connect(h.database.admin) as tx:
        tx.execute("UPDATE control.guard SET mode='ai_disabled'")
    with pytest.raises(ManualError, match="function_disabled"):
        service.task_create(h.worker, str(uuid4()), data)
    assert h.service.session_read(h.worker, data["binding"]["session_id"])["id"]


def test_create_replays_exact_identity_and_encrypts_content(harness):
    h = harness
    service, data, _peer = case(h)
    key = str(uuid4())
    task = service.task_create(h.worker, key, data)
    assert service.task_create(h.worker, key, data) == task
    assert task["scope"]["subject_id"] is not None
    assert data["scope"]["subject_id"] is None
    assert h.read("SELECT count(*) FROM assistance.task")[0][0] == 1
    body = h.read("SELECT body FROM assistance.task")[0][0]
    assert set(body) == {"ciphertext"}
    assert "Fictional" not in str(body)
    assert (
        h.read("SELECT count(*) FROM lifecycle.copy WHERE aggregate_type='assistance_task'")[0][0]
        == 1
    )
    changed = {
        **data,
        "inputs": [
            {
                "kind": "assertion",
                "id": str(uuid4()),
                "revision": "1",
                "digest": "a" * 64,
                "observed_at": stamp(datetime.now(UTC)),
                "verification": "unknown",
            }
        ],
    }
    with pytest.raises(ManualError, match="idempotency_conflict"):
        service.task_create(h.worker, key, changed)


def test_only_owner_and_exact_scope_can_read(harness):
    h = harness
    service, data, _peer = case(h)
    task = service.task_create(h.worker, str(uuid4()), data)
    with pytest.raises(ManualError, match="not_found"):
        service.task_read(h.participant, task["id"])
    with pytest.raises(ManualError, match="scope_unavailable"):
        service.task_create(
            h.worker,
            str(uuid4()),
            {**data, "scope": {**data["scope"], "fields": ["plan.contacts"]}},
        )
    with pytest.raises(ManualError, match="function_disabled"):
        service.task_create(h.participant, str(uuid4()), data)


def test_competing_claims_only_one_and_restart_keeps_counters(harness):
    h = harness
    service, data, peer = case(h)
    task = service.task_create(h.worker, str(uuid4()), data)

    def claim():
        try:
            return lease(service, h, task, peer)
        except ManualError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: claim(), range(2)))
    claimed = next(c for c in claims if c is not None)
    assert len([c for c in claims if c]) == 1
    rebuilt = AssistanceCoordinator(
        h.service, admitted=lambda f: f == "worker_summary", runtime_current=lambda _peer: True
    )
    assert rebuilt.task_read(h.worker, task["id"])["steps_used"] == 1
    for _ in range(2):
        rebuilt.reserve_proposal(h.worker, request(task, claimed), peer)
    with pytest.raises(ManualError, match="proposal_budget"):
        rebuilt.reserve_proposal(h.worker, request(task, claimed), peer)


def test_expired_lease_is_fenced_and_budget_not_reset(harness):
    h = harness
    service, data, peer = case(h)
    task = service.task_create(h.worker, str(uuid4()), data)
    claimed = lease(service, h, task, peer)
    sid = data["binding"]["session_id"]
    with service.transaction(h.worker, sid, "test_lease_expiry", {}) as (tx, actor, _v):
        stored = service.read(tx, "task", task["id"])
        stored["lease"]["expires_at"] = stamp(datetime.now(UTC) - timedelta(seconds=1))
        service.save(tx, "task", stored, actor.account_id, sid)
    new = lease(service, h, task, peer, fence=claimed["fence"])
    assert new["fence"] == "2"
    assert service.task_read(h.worker, task["id"])["steps_used"] == 2
    with pytest.raises(ManualError, match="stale_lease"):
        service.reserve_proposal(h.worker, request(task, claimed), peer)


def test_wrong_or_expired_workload_denied(harness):
    h = harness
    service, data, peer = case(h)
    task = service.task_create(h.worker, str(uuid4()), data)
    with pytest.raises(ManualError, match="runtime_required"):
        lease(service, h, task, replace(peer, workload_id="spiffe://care-link.demo/demo/core"))
    with pytest.raises(ManualError, match="runtime_required"):
        lease(service, h, task, replace(peer, certificate_expires_at=datetime.now(UTC)))


def test_tool_dedup_shared_budget_and_closed_scopes(harness):
    h = harness
    service, data, peer = case(h)
    task = service.task_create(h.worker, str(uuid4()), data)
    claimed = lease(service, h, task, peer)
    call = {
        **request(task, claimed),
        "invocation_id": str(uuid4()),
        "arguments": {
            "tool": "session_read",
            "session_id": data["binding"]["session_id"],
            "fields": ["needs"],
        },
    }
    observed = service.tool_invoke(h.worker, call, peer)
    validate_contract("Observation", observed)
    assert observed["taint"] == "untrusted"
    assert observed["result"]["kind"] == "success"
    assert service.tool_invoke(h.worker, call, peer) == observed
    assert service.task_read(h.worker, task["id"])["tools_used"] == 1
    for _ in range(2):
        denied = service.tool_invoke(
            h.worker,
            {
                **call,
                "invocation_id": str(uuid4()),
                "arguments": {**call["arguments"], "fields": ["plan.contacts"]},
            },
            peer,
        )
        assert denied["result"]["kind"] == "failure"
    with pytest.raises(ManualError, match="tool_budget"):
        service.tool_invoke(h.worker, {**call, "invocation_id": str(uuid4())}, peer)


def test_human_edit_requires_new_exact_review_and_never_sends(harness):
    h = harness
    service, data, peer = case(h)
    task = service.task_create(h.worker, str(uuid4()), data)
    proposed = draft(service, h, task, peer)
    assert service.task_read(h.worker, task["id"])["state"] == "awaiting_human"
    edited = service.draft_review(
        h.worker,
        str(uuid4()),
        review_body(proposed, "edit", "Edited fictional needs"),
        proposed["id"],
    )
    new = service.draft_read(h.worker, proposed["id"])
    assert new["state"] == "review_pending"
    assert edited["exact_digest"] != proposed["payload_digest"]
    assert new["text"] == "Edited fictional needs"
    with pytest.raises(ManualError, match="stale_review"):
        service.draft_review(h.worker, str(uuid4()), review_body(proposed), proposed["id"])
    key = str(uuid4())
    body = review_body(new)
    accepted = service.draft_review(h.worker, key, body, proposed["id"])
    assert service.draft_review(h.worker, key, body, proposed["id"]) == accepted
    assert service.draft_read(h.worker, proposed["id"])["state"] == "accepted"
    assert h.read("SELECT count(*) FROM referral.dispatch")[0][0] == 0
    assert (
        h.read("SELECT count(*) FROM lifecycle.copy WHERE aggregate_type='assistance_draft'")[0][0]
        == 1
    )


def test_cancel_replay_fences_output_and_stales_review(harness):
    h = harness
    service, data, peer = case(h)
    task = service.task_create(h.worker, str(uuid4()), data)
    proposed = draft(service, h, task, peer)
    key = str(uuid4())
    body = {"expected_revision": task["revision"]}
    cancelled = service.task_cancel(h.worker, key, body, task["id"])
    assert service.task_cancel(h.worker, key, body, task["id"]) == cancelled
    assert service.draft_context(h.worker, proposed["id"])["draft"]["state"] == "stale"
    with pytest.raises(ManualError, match="stale_review"):
        service.draft_review(h.worker, str(uuid4()), review_body(proposed), proposed["id"])


def test_changed_sources_block_review_and_revise_preserves_lifetime(harness):
    h = harness
    service, data, peer = case(h)
    task = service.task_create(h.worker, str(uuid4()), data)
    proposed = draft(service, h, task, peer)
    sid = data["binding"]["session_id"]
    session = h.service.session_read(h.worker, sid)
    h.service.session_assertions(
        h.participant,
        str(uuid4()),
        {
            "expected_revision": session["revision"],
            "subject_id": session["subject_id"],
            "field": "needs",
            "value": {"kind": "text", "text": "Changed needs"},
            "supersedes_id": None,
            "effective_at": stamp(datetime.now(UTC)),
        },
        sid,
    )
    with pytest.raises(ManualError, match="sources_changed"):
        service.draft_review(h.worker, str(uuid4()), review_body(proposed), proposed["id"])
    revised_data = {**data, "scope": task["scope"], "expected_revision": task["revision"]}
    key = str(uuid4())
    revised = service.task_revise(h.worker, key, revised_data, task["id"])
    assert service.task_revise(h.worker, key, revised_data, task["id"]) == revised
    assert revised["steps_used"] == 1
    assert revised["revision"] == "2"
    claimed = lease(service, h, revised, peer, fence="2")
    service.reserve_proposal(h.worker, request(revised, claimed), peer)
    with pytest.raises(ManualError, match="proposal_budget"):
        service.reserve_proposal(h.worker, request(revised, claimed), peer)


def test_revise_stales_old_draft_even_without_changed_sources(harness):
    h = harness
    service, data, peer = case(h)
    task = service.task_create(h.worker, str(uuid4()), data)
    proposed = draft(service, h, task, peer)
    revise_data = {**data, "scope": task["scope"], "expected_revision": task["revision"]}
    revised = service.task_revise(h.worker, str(uuid4()), revise_data, task["id"])
    assert service.draft_read(h.worker, proposed["id"])["state"] == "stale"
    assert service.draft_context(h.worker, proposed["id"])["draft"]["state"] == "stale"
    with pytest.raises(ManualError, match="stale_review"):
        service.draft_review(h.worker, str(uuid4()), review_body(proposed), proposed["id"])
    service.draft_review(h.worker, str(uuid4()), review_body(proposed, "reject"), proposed["id"])
    assert service.task_read(h.worker, task["id"]) == revised


def test_runtime_replacement_cannot_complete_old_lease(harness):
    h = harness
    service, data, peer = case(h)
    task = service.task_create(h.worker, str(uuid4()), data)
    claimed = lease(service, h, task, peer)
    for replacement in [
        replace(peer, fence_generation=2),
        replace(peer, certificate_digest="b" * 64),
    ]:
        with pytest.raises(ManualError, match="stale_lease"):
            service.reserve_proposal(h.worker, request(task, claimed), replacement)


def test_awaiting_human_requires_explicit_actor_revision(harness):
    h = harness
    service, data, peer = case(h)
    task = service.task_create(h.worker, str(uuid4()), data)
    draft(service, h, task, peer)
    with pytest.raises(ManualError, match="human_resumption_required"):
        lease(service, h, task, peer, fence="1")


@pytest.mark.parametrize(
    ("goal", "completion"),
    [("prepare_draft", "draft_ready"), ("check_progress", "receipt_observed")],
)
def test_function_goal_and_completion_are_closed(harness, goal, completion):
    h = harness
    service, data, _peer = case(h)
    with pytest.raises(ManualError, match="goal_unavailable"):
        service.task_create(
            h.worker, str(uuid4()), {**data, "goal": goal, "completion": completion}
        )
    task = service.task_create(h.worker, str(uuid4()), data)
    revised = {
        **data,
        "scope": task["scope"],
        "expected_revision": task["revision"],
        "goal": goal,
        "completion": completion,
    }
    with pytest.raises(ManualError, match="goal_unavailable"):
        service.task_revise(h.worker, str(uuid4()), revised, task["id"])


def test_human_review_outlives_compute_slice_only_with_current_authority(harness):
    h = harness
    service, data, peer = case(h)
    task = service.task_create(h.worker, str(uuid4()), data)
    proposed = draft(service, h, task, peer)
    sid = data["binding"]["session_id"]
    with service.transaction(h.worker, sid, "test_expire_compute", {}) as (tx, actor, _v):
        stored = service.read(tx, "task", task["id"])
        stored["deadline"] = stamp(datetime.now(UTC) - timedelta(seconds=1))
        service.save(tx, "task", stored, actor.account_id, sid)
    with pytest.raises(ManualError, match="task_terminal"):
        lease(service, h, task, peer, fence="1")
    result = service.draft_review(h.worker, str(uuid4()), review_body(proposed), proposed["id"])
    assert result["decision"] == "accept"


def test_server_actor_ceiling_fails_closed_after_restart_or_cancel(harness):
    h = harness
    service, data, peer = case(h)
    task = service.task_create(h.worker, str(uuid4()), data)
    actor = service.actor_for_task(task["id"])
    assert actor.account_id == h.worker.account_id
    assert actor.request_deadline <= datetime.now(UTC) + timedelta(seconds=1)
    rebuilt = AssistanceCoordinator(
        h.service, admitted=lambda f: f == "worker_summary", runtime_current=lambda _peer: True
    )
    with pytest.raises(ManualError, match="actor_resumption_required"):
        rebuilt.actor_for_task(task["id"])
    revised = rebuilt.task_revise(
        h.worker,
        str(uuid4()),
        {**data, "scope": task["scope"], "expected_revision": task["revision"]},
        task["id"],
    )
    assert rebuilt.actor_for_task(task["id"]).account_id == h.worker.account_id
    rebuilt.task_cancel(
        h.worker, str(uuid4()), {"expected_revision": revised["revision"]}, task["id"]
    )
    with pytest.raises(ManualError, match="actor_resumption_required"):
        rebuilt.actor_for_task(task["id"])


def test_context_snapshot_checks_live_lease_and_shared_scope(harness):
    h = harness
    service, data, peer = case(h)
    task = service.task_create(h.worker, str(uuid4()), data)
    with pytest.raises(ManualError, match="stale_lease"):
        service.context_snapshot(h.worker, task["id"])
    claimed = lease(service, h, task, peer)
    snapshot = service.context_snapshot(h.worker, task["id"])
    assert snapshot["allowed_tools"] == ["session_read"]
    assert snapshot["lease"]["step_id"] == claimed["step_id"]
    assert snapshot["task"]["steps_used"] == 1
    sid = data["binding"]["session_id"]
    with service.transaction(h.worker, sid, "test_expire_context", {}) as (tx, actor, _v):
        stored = service.read(tx, "task", task["id"])
        stored["lease"]["expires_at"] = stamp(datetime.now(UTC) - timedelta(seconds=1))
        service.save(tx, "task", stored, actor.account_id, sid)
    with pytest.raises(ManualError, match="stale_lease"):
        service.context_snapshot(h.worker, task["id"])


def test_runtime_fenced_during_generation_suppresses_output_and_preserves_manual(harness):
    from care_link_data.assistance_jobs import PostgresJobLedger

    h = harness
    trust = {"active": True}
    service, data, peer = case(h, runtime_current=lambda _peer: trust["active"])
    task = service.task_create(h.worker, str(uuid4()), data)
    claimed = lease(service, h, task, peer)
    reserved = service.reserve_proposal(h.worker, request(task, claimed), peer)
    ledger = PostgresJobLedger(
        h.service.store,
        current=lambda tx, row: service.inference_current(tx, row, service.actor_for_task),
    )
    job = {
        "id": str(uuid4()),
        "task_id": task["id"],
        "step_id": claimed["step_id"],
        "fence": claimed["fence"],
        "revision": task["revision"],
        "model_digest": "a" * 64,
        "prompt_digest": "b" * 64,
        "request_digest": "c" * 64,
        "deadline": datetime.now(UTC) + timedelta(seconds=20),
        "bridge_generation": "bridge-1",
    }
    assert ledger.reserve(job) is not None
    assert service.context_snapshot(h.worker, task["id"])["lease"]["owner_certificate_expires_at"]
    trust["active"] = False
    with pytest.raises(ManualError, match="runtime_fenced"):
        service.context_snapshot(h.worker, task["id"])
    assert ledger.complete(job["id"], "d" * 64, deliverable=True) is False
    assert (
        h.read("SELECT state FROM assistance.inference_job WHERE id=%s", (job["id"],))[0][0]
        == "fenced"
    )
    assert (
        h.read("SELECT count(*) FROM assistance.compute_slot WHERE job_id=%s", (job["id"],))[0][0]
        == 0
    )
    proposal = {
        **request(task, claimed),
        "candidate_text": "Fictional needs",
        "sources": [s["ref"] for s in reserved["sources"]],
        "next": None,
        "completion_claim": True,
    }
    with pytest.raises(ManualError, match="runtime_fenced"):
        service.proposal_submit(h.worker, proposal, peer, reserved["reservation_id"])
    assert h.service.session_read(h.worker, data["binding"]["session_id"])["id"]


def test_runtime_trust_binding_is_required_even_with_admitted_function(harness):
    h = harness
    service, data, peer = case(h)
    unbound = AssistanceCoordinator(h.service, admitted=lambda _function: True)
    task = unbound.task_create(h.worker, str(uuid4()), data)
    with pytest.raises(ManualError, match="runtime_fenced"):
        lease(unbound, h, task, peer)
