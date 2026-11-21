"""Real coordinator retrieval, stale catalog and typed protocol-tool behavior."""

import json
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from care_link_contracts import validate_contract
from care_link_data.assistance import AssistanceCoordinator
from care_link_domain import ManualError
from care_link_knowledge import KnowledgeCatalog

from services.data.tests.test_assistance import case, draft, lease, request, review_body

ROOT = Path(__file__).resolve().parents[3]


def knowledge_case(h, *, regions=None):
    _previous, data, peer = case(h)
    # The common manual fixture deliberately leaves jurisdiction unknown.
    # This owned synthetic test explicitly assigns the admitted scenario region.
    with psycopg.connect(h.database.admin) as connection:
        connection.execute(
            "UPDATE core.session SET jurisdiction='CA-XX' WHERE id=%s",
            (data["binding"]["session_id"],),
        )
    catalog = KnowledgeCatalog.from_path(ROOT / "config/demo/knowledge/catalog.json")
    service = AssistanceCoordinator(
        h.service,
        admitted=lambda f: f == "worker_summary",
        runtime_current=lambda _peer: True,
        knowledge=catalog,
        knowledge_regions={"CA-XX": "CA-ON"} if regions is None else regions,
    )
    return service, data, peer


def test_retrieval_keeps_patient_and_protocol_sources_separate_and_pins_catalog(harness):
    h = harness
    service, data, peer = knowledge_case(h)
    task = service.task_create(h.worker, str(uuid4()), data)
    claimed = lease(service, h, task, peer)
    reserved = service.reserve_proposal(h.worker, request(task, claimed), peer)
    sources = reserved["sources"]
    assert any(row["ref"]["kind"] == "assertion" for row in sources)
    assert any(row["ref"]["kind"] == "protocol" for row in sources)
    assert all(len(row["text"]) <= 2000 for row in sources if row["ref"]["kind"] == "protocol")
    context = service.task_context(h.worker, task["id"])
    validate_contract("AssistanceTaskContext", context)
    assert context["execution_fence"] == claimed["fence"]
    assert context["available"]
    with service.transaction(h.worker, data["binding"]["session_id"], "test_catalog_pin", {}) as (
        tx,
        _a,
        _v,
    ):
        stored = service.read(tx, "task", task["id"])
        assert stored["knowledge_digest"] == service.knowledge.digest
        assert stored["knowledge_sources"]
    assert "protocol_read" in service.context_snapshot(h.worker, task["id"])["allowed_tools"]


def test_unbound_synthetic_region_cannot_gain_clinical_context(harness):
    h = harness
    service, data, _peer = knowledge_case(h, regions={})
    with pytest.raises(ManualError, match="knowledge_scope_unavailable"):
        service.task_create(h.worker, str(uuid4()), data)
    assert h.service.session_read(h.worker, data["binding"]["session_id"])["id"]


def test_catalog_replacement_stales_review_and_requires_explicit_revision(harness):
    h = harness
    service, data, peer = knowledge_case(h)
    task = service.task_create(h.worker, str(uuid4()), data)
    prepared = draft(service, h, task, peer)
    content = json.loads((ROOT / "config/demo/knowledge/catalog.json").read_text())
    content["revision"] = "2"
    content["entries"][0]["title"] += " updated"
    service.knowledge = KnowledgeCatalog.from_bytes(json.dumps(content).encode())
    assert not service.task_context(h.worker, task["id"])["available"]
    assert service.draft_read(h.worker, prepared["id"])["state"] == "stale"
    with pytest.raises(ManualError, match="knowledge_changed"):
        service.draft_review(h.worker, str(uuid4()), review_body(prepared), prepared["id"])
    revised = service.task_revise(
        h.worker,
        str(uuid4()),
        {**data, "scope": task["scope"], "expected_revision": task["revision"]},
        task["id"],
    )
    assert service.task_context(h.worker, revised["id"])["available"]
    assert revised["steps_used"] == 1


def test_protocol_read_is_catalog_pinned_locale_scoped_bounded_and_idempotent(harness):
    h = harness
    service, data, peer = knowledge_case(h)
    task = service.task_create(h.worker, str(uuid4()), data)
    claimed = lease(service, h, task, peer)
    command = {
        **request(task, claimed),
        "invocation_id": str(uuid4()),
        "arguments": {
            "tool": "protocol_read",
            "artifact_digest": service.knowledge.digest,
            "section_id": "shared-goals",
            "locale": "en-CA",
        },
    }
    result = service.tool_invoke(h.worker, command, peer)
    validate_contract("Observation", result)
    assert result["result"]["kind"] == "success"
    assert result["taint"] == "untrusted"
    assert result["sources"][0]["kind"] == "protocol"
    assert service.tool_invoke(h.worker, command, peer) == result
    denied = service.tool_invoke(
        h.worker,
        {
            **command,
            "invocation_id": str(uuid4()),
            "arguments": {**command["arguments"], "locale": "fr-CA"},
        },
        peer,
    )
    assert denied["result"]["kind"] == "failure"
    assert denied["sources"] == []
    assert service.task_read(h.worker, task["id"])["tools_used"] == 2


def test_future_effective_knowledge_cannot_change_task_selection_without_revision(harness):
    from care_link_data.values import stamp

    h = harness
    service, data, peer = knowledge_case(h)
    now = h.service.clock()
    clock = [now]
    h.service.clock = lambda: clock[0]
    content = json.loads((ROOT / "config/demo/knowledge/catalog.json").read_text())
    first = next(
        row
        for row in content["entries"]
        if row["locale"] == "en-CA"
        and row["status"] == "synthetic_demo"
        and "worker" in row["roles"]
    )
    future = {
        **first,
        "id": str(uuid4()),
        "section_id": "future-knowledge",
        "text": "Fictional needs future administrative preparation.",
        "effective_at": stamp(now + timedelta(milliseconds=5)),
        "keywords": ["fictional", "needs"],
    }
    content["entries"].append(future)
    service.knowledge = KnowledgeCatalog.from_bytes(json.dumps(content).encode())
    task = service.task_create(h.worker, str(uuid4()), data)
    claimed = lease(service, h, task, peer)
    before = service.context_snapshot(h.worker, task["id"])["sources"]
    assert future["id"] not in [row["ref"]["id"] for row in before]
    clock[0] = now + timedelta(milliseconds=6)
    after = service.context_snapshot(h.worker, task["id"])["sources"]
    assert after == before
    assert service.task_context(h.worker, task["id"])["available"]
    revised = service.task_revise(
        h.worker,
        str(uuid4()),
        {**data, "scope": task["scope"], "expected_revision": task["revision"]},
        task["id"],
    )
    lease(service, h, revised, peer, fence=str(int(claimed["fence"]) + 1))
    refreshed = service.context_snapshot(h.worker, task["id"])["sources"]
    assert future["id"] in [row["ref"]["id"] for row in refreshed]
    assert revised["steps_used"] == 1
