"""Temporary operator journals: cleanup barriers, retry and bounded readiness."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from care_link_core.plans_review_context import PlansReviewContexts

from tools.imp04_review.lifecycle import PlansReviewLifecycle, operation
from tools.imp04_review.storage import read_json


class Adapter:
    def __init__(self):
        self.events = []
        self.fail_prepare = False
        self.fail_close = False

    def prepare(self, run, checkpoint):
        self.events.append(("prepare", run["run_id"]))
        run["steps"]["prepared"] = True
        checkpoint()
        if self.fail_prepare:
            raise RuntimeError("Fixture authority unavailable")
        selections = {
            slot: {
                "session_id": operation(run, "session:" + slot),
                "plan_id": None,
                "recipient_id": None,
            }
            for slot in run["actors"]
        }
        selections["pid"]["plan_id"] = operation(run, "plan")
        selections["pid"]["recipient_id"] = run["actors"]["worker1"]["account_id"]
        selections["worker1"]["session_id"] = selections["pid"]["session_id"]
        selections["worker1"]["plan_id"] = selections["pid"]["plan_id"]
        return selections

    def close(self, run, checkpoint):
        self.events.append(("close", run["run_id"]))
        if self.fail_close:
            raise RuntimeError("Scoped cleanup unavailable")
        run["steps"]["retired"] = True
        checkpoint()


@pytest.fixture
def manager(tmp_path):
    adapter = Adapter()
    now = [datetime(2026, 11, 17, tzinfo=UTC)]
    manager = PlansReviewLifecycle(
        tmp_path / "state",
        tmp_path / "registry" / "origins.json",
        adapter,
        environment_id="synthetic-plans-test",
        target_id="temporary-test-store",
        port=30443,
        clock=lambda: now[0],
    )
    return manager, adapter, now


def test_start_fresh_closes_old_before_new_and_retains_history(manager):
    lifecycle, adapter, _now = manager
    first = lifecycle.start_fresh(lifetime_seconds=7200)
    second = lifecycle.start_fresh(lifetime_seconds=7200)
    assert adapter.events == [
        ("prepare", first["run_id"]),
        ("close", first["run_id"]),
        ("prepare", second["run_id"]),
    ]
    assert set(first["actors"]) == {"pid", "carer", "professional", "worker1"}
    assert first["actors"]["pid"]["origin"] != second["actors"]["pid"]["origin"]
    registry = read_json(lifecycle.registry_path)
    assert len(registry) == 4
    assert {row["state"] for row in registry.values()} == {"active"}
    context = PlansReviewContexts(
        lifecycle.registry_path, "https://legacy.localhost", clock=lifecycle.clock
    )
    assert len(context.entries()) == 4
    for path in lifecycle.state_dir.rglob("*.json"):
        assert path.stat().st_mode & 0o077 == 0
    assert (
        read_json(lifecycle.state_dir / "runs" / (first["run_id"] + ".json"))["state"] == "closed"
    )


def test_failed_cleanup_prevents_new_preparation_and_ready_urls(manager):
    lifecycle, adapter, _now = manager
    first = lifecycle.start_fresh(lifetime_seconds=3600)
    adapter.fail_close = True
    with pytest.raises(RuntimeError, match="cleanup"):
        lifecycle.start_fresh(lifetime_seconds=3600)
    assert lifecycle.inspect()["state"] == "closing"
    assert "actors" not in lifecycle.inspect()
    assert len([event for event in adapter.events if event[0] == "prepare"]) == 1
    assert {row["state"] for row in read_json(lifecycle.registry_path).values()} == {"closing"}
    adapter.fail_close = False
    second = lifecycle.start_fresh(lifetime_seconds=3600)
    assert second["run_id"] != first["run_id"]


def test_prepare_retry_is_same_namespace_and_never_publishes_early(manager):
    lifecycle, adapter, _now = manager
    run_id = str(uuid4())
    adapter.fail_prepare = True
    with pytest.raises(RuntimeError):
        lifecycle.start_fresh(lifetime_seconds=3600, run_id=run_id)
    assert not lifecycle.registry_path.exists()
    assert lifecycle.inspect()["state"] == "preparing"
    adapter.fail_prepare = False
    ready = lifecycle.start_fresh(lifetime_seconds=3600, run_id=run_id)
    assert ready["run_id"] == run_id
    events = len(adapter.events)
    assert lifecycle.start_fresh(lifetime_seconds=3600, run_id=run_id) == ready
    assert len(adapter.events) == events


def test_closed_run_cannot_be_revived_and_inspection_hides_expired_urls(manager):
    lifecycle, _adapter, now = manager
    first = lifecycle.start_fresh(lifetime_seconds=1)
    now[0] += timedelta(seconds=1)
    assert "actors" not in lifecycle.inspect()
    lifecycle.close()
    with pytest.raises(ValueError, match="revived"):
        lifecycle.start_fresh(lifetime_seconds=3600, run_id=first["run_id"])


@pytest.mark.parametrize("lifetime", [0, 14401, True, 1.5])
def test_lifetime_is_explicitly_bounded(manager, lifetime):
    with pytest.raises(ValueError):
        manager[0].start_fresh(lifetime_seconds=lifetime)


def test_unsafe_registry_symlink_and_foreign_target_are_refused(manager, tmp_path):
    lifecycle, _adapter, _now = manager
    lifecycle.start_fresh(lifetime_seconds=3600)
    target = tmp_path / "unrelated.json"
    target.write_text(json.dumps({"do_not_touch": True}))
    lifecycle.registry_path.unlink()
    lifecycle.registry_path.symlink_to(target)
    with pytest.raises(ValueError, match="private"):
        lifecycle.close()
    assert json.loads(target.read_text()) == {"do_not_touch": True}


def test_serving_registry_is_bounded_but_every_run_journal_is_retained(manager):
    lifecycle, _adapter, _now = manager
    for _ in range(12):
        ready = lifecycle.start_fresh(lifetime_seconds=3600)
        assert len(read_json(lifecycle.registry_path)) == 4
        assert lifecycle.registry_path.stat().st_size < 262144
        assert all(
            actor["url"] == actor["origin"] + "/plans-review" for actor in ready["actors"].values()
        )
    assert len(list((lifecycle.state_dir / "runs").glob("*.json"))) == 12


def test_identity_context_loader_requires_explicit_opt_in_and_exact_fields(manager):
    from tools.imp03_runtime.review_identity import load_contexts

    lifecycle, _adapter, _now = manager
    lifecycle.start_fresh(lifetime_seconds=3600)
    with pytest.raises(ValueError):
        load_contexts(lifecycle.registry_path)
    assert {
        row.state
        for row in load_contexts(lifecycle.registry_path, interactive_review_enabled=True).values()
    } == {"active"}
    lifecycle.close()
    assert {
        row.state
        for row in load_contexts(lifecycle.registry_path, interactive_review_enabled=True).values()
    } == {"closed"}
    value = read_json(lifecycle.registry_path)
    next(iter(value.values()))["arbitrary_authority"] = "operator"
    lifecycle.registry_path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        load_contexts(lifecycle.registry_path, interactive_review_enabled=True)


def test_crash_between_journal_and_pointer_write_resumes_exact_preparation(manager, monkeypatch):
    import tools.imp04_review.lifecycle as module

    lifecycle, _adapter, _now = manager
    run_id = str(uuid4())
    original = module.write_json

    def interrupted(path, value):
        if path.name == "current.json":
            raise OSError("Interrupted pointer publication")
        return original(path, value)

    monkeypatch.setattr(module, "write_json", interrupted)
    with pytest.raises(OSError):
        lifecycle.start_fresh(lifetime_seconds=3600, run_id=run_id)
    assert not lifecycle.registry_path.exists()
    monkeypatch.setattr(module, "write_json", original)
    assert lifecycle.start_fresh(lifetime_seconds=3600, run_id=run_id)["state"] == "ready"
