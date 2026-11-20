"""One-shot live timing adapter never changes authority and fails closed."""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from care_link_domain import ManualError

from tools.imp04_deployment import qualification as module


def test_adapter_requires_explicit_target_activation(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DIRECTORY", tmp_path)
    monkeypatch.delenv("CARE_LINK_IMP04_QUALIFICATION", raising=False)
    with pytest.raises(ValueError, match="activation"):
        module.TimingBarrier(tmp_path)


def make_barrier(tmp_path, monkeypatch, **overrides):
    tmp_path.chmod(0o700)
    monkeypatch.setattr(module, "DIRECTORY", tmp_path)
    monkeypatch.setenv("CARE_LINK_IMP04_QUALIFICATION", "plans-002")
    actor, nonce = str(uuid4()), str(uuid4())
    marker = {
        "version": "imp04.qualification.v1",
        "target": "care-link-imp04-002",
        "phase": "before_policy",
        "action": "plan_read",
        "actor_id": actor,
        "nonce": nonce,
        "expires_at": (datetime.now(UTC) + timedelta(seconds=3)).isoformat(),
        **overrides,
    }
    path = tmp_path / "armed.json"
    path.write_text(json.dumps(marker))
    path.chmod(0o600)
    return module.TimingBarrier(tmp_path), actor, nonce


def test_barrier_claims_only_exact_actor_action_then_releases_once(tmp_path, monkeypatch):
    barrier, actor, nonce = make_barrier(tmp_path, monkeypatch)
    barrier.enter("before_policy", "plan_read", str(uuid4()), str(uuid4()))
    assert (tmp_path / "armed.json").exists()
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(barrier.enter, "before_policy", "plan_read", actor, str(uuid4()))
        ready = tmp_path / ("ready-" + nonce + ".json")
        deadline = time.monotonic() + 0.5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.005)
        assert ready.exists()
        assert not (tmp_path / "armed.json").exists()
        release = tmp_path / ("release-" + nonce + ".json")
        release.write_text(json.dumps({"nonce": nonce}))
        release.chmod(0o600)
        pending.result(timeout=1)
    assert (tmp_path / ("finished-" + nonce + ".json")).is_file()
    barrier.enter("before_policy", "plan_read", actor, str(uuid4()))


def test_expired_and_foreign_marker_fail_closed(tmp_path, monkeypatch):
    barrier, actor, _nonce = make_barrier(tmp_path, monkeypatch, target="care-link-imp03-003")
    with pytest.raises(ManualError, match="qualification_control_invalid"):
        barrier.enter("before_policy", "plan_read", actor, str(uuid4()))
    (tmp_path / "armed.json").unlink()
    barrier, actor, _nonce = make_barrier(
        tmp_path, monkeypatch, expires_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    )
    with pytest.raises(ManualError, match="qualification_control_invalid"):
        barrier.enter("before_policy", "plan_read", actor, str(uuid4()))


def test_public_marker_is_rejected(tmp_path, monkeypatch):
    barrier, actor, _nonce = make_barrier(tmp_path, monkeypatch)
    os.chmod(tmp_path / "armed.json", 0o644)
    with pytest.raises(ManualError, match="qualification_control_invalid"):
        barrier.enter("before_policy", "plan_read", actor, str(uuid4()))
