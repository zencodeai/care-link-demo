"""Concrete operator composition components, without Docker/provider/DB side effects."""

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest

from tools.demo.models import CORE_PROTOCOL, SLOTS, Environment
from tools.demo.storage import private_write
from tools.imp03_shared.review_environment import ContextPublisher, CredentialRotation, TrustSteward
from tools.imp03_shared.review_provider import ReviewProviderError


def environment(tmp_path: Path) -> Environment:
    tmp_path.chmod(0o700)
    return Environment.parse(
        {
            "schema_version": 1,
            "environment_id": "review-lab",
            "core_protocol": CORE_PROTOCOL,
            "scenario_version": "1",
            "base_domain": "qualification.localhost",
            "port": 29443,
            "actors": {
                slot: {
                    "account_id": str(uuid4()),
                    "provider_subject": str(uuid4()),
                    "role": role,
                    "username": "synthetic-" + slot,
                    "secret_ref": "demo-" + slot,
                }
                for slot, role in SLOTS.items()
            },
            "ownership": {
                "kind": "receipt",
                "resource_id": "owned",
                "receipt_path": str(tmp_path / "receipt.json"),
                "receipt_sha256": "a" * 64,
            },
            "lifecycle": {"socket": str(tmp_path / "operator.sock"), "peer_uid": os.geteuid()},
        }
    )


def targets() -> list[dict[str, object]]:
    return [
        {
            "container": "care-link-imp03-003-cont1-" + role + "-app",
            "container_id": digit * 64,
            "path": "/run/care-link-imp03-002/configuration/" + role + "/review-contexts.json",
            "uid": uid,
        }
        for role, uid, digit in [("identity", 22011, "a"), ("core", 22012, "b")]
    ]


def test_context_publication_uses_exact_ids_and_custodian_with_verified_content(
    tmp_path: Path,
) -> None:
    env = environment(tmp_path)
    bindings = targets()
    calls: list[tuple[list[str], str]] = []

    def inspect(name: str) -> dict[str, object]:
        found = next(item for item in bindings if item["container"] == name)
        return {"Id": found["container_id"], "Config": {"User": f"{found['uid']}:{found['uid']}"}}

    def execute(args: list[str], payload: str) -> str:
        calls.append((args, payload))
        return hashlib.sha256(payload.encode()).hexdigest()

    publisher = ContextPublisher(env, bindings, inspect=inspect, execute=execute)
    run_id = str(uuid4())
    contexts = {
        origin: {
            "run_id": run_id,
            "slot_id": slot,
            "account_id": env.value["actors"][slot]["account_id"],
            "provider_subject": env.value["actors"][slot]["provider_subject"],
            "role": SLOTS[slot],
            "state": "active",
        }
        for slot, origin in env.origins(run_id).items()
    }
    publisher(contexts)
    assert len(calls) == 2
    assert calls[0][0][:3] == ["--user", "22011:22011", "a" * 64]
    assert calls[1][0][:3] == ["--user", "22012:22012", "b" * 64]
    assert json.loads(calls[0][1]) == contexts
    damaged = {**next(iter(contexts.values())), "password": "must-not-publish"}
    with pytest.raises(ValueError, match="unknown fields"):
        publisher({next(iter(contexts)): damaged})
    assert len(calls) == 2


def test_changed_container_identity_prevents_context_publication(tmp_path: Path) -> None:
    env = environment(tmp_path)
    publisher = ContextPublisher(
        env,
        targets(),
        inspect=lambda _name: {"Id": "c" * 64, "Config": {"User": "22011:22011"}},
        execute=lambda _args, _payload: pytest.fail("must not execute"),
    )
    with pytest.raises(ValueError, match="identity changed"):
        publisher({})


def test_runtime_registry_capacity_refuses_before_touching_either_target(tmp_path: Path) -> None:
    publisher = ContextPublisher(
        environment(tmp_path),
        targets(),
        inspect=lambda _name: pytest.fail("must not inspect or publish"),
        execute=lambda _args, _payload: pytest.fail("must not publish"),
    )
    with pytest.raises(ValueError, match="capacity exceeded"):
        publisher({"oversized": "x" * 262144})


def test_steward_owned_lifecycle_and_failure_is_not_ready(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    event = threading.Event()
    steward = TrustSteward(lambda: event.set(), tmp_path / "steward.json")
    assert steward.current() is False
    steward.start()
    assert event.wait(timeout=2)
    deadline = time.monotonic() + 2
    while not (tmp_path / "steward.json").exists() and time.monotonic() < deadline:
        time.sleep(0.001)
    assert steward.current() is True
    steward.close()
    assert steward.current() is False

    def failing() -> None:
        event.set()
        raise ValueError("private-value-never-recorded")

    event.clear()
    broken = TrustSteward(failing, tmp_path / "failure.json")
    broken.start()
    assert event.wait(timeout=2)
    broken.close()
    assert broken.current() is False
    assert "private-value" not in (tmp_path / "failure.json").read_text()


class FakeProvider:
    def __init__(self, actor: dict[str, object]) -> None:
        self.actor, self.password = actor, str(actor["password"])
        self.after_effect_failure = False
        self.before_effect_failure = False
        self.effects = 0

    def verify_password(self, account: str, password: str, seed: str) -> dict[str, object]:
        if password != self.password:
            raise ReviewProviderError("provider_password_verification_failed")
        return {"account_id": account, "provider_subject": self.actor["id"], "verified": True}

    def rotate(self, account: str, password: str, seed: str) -> dict[str, object]:
        if self.before_effect_failure:
            self.before_effect_failure = False
            raise ReviewProviderError("provider_admin_unavailable")
        self.password = password
        self.effects += 1
        if self.after_effect_failure:
            self.after_effect_failure = False
            raise ReviewProviderError("provider_admin_unavailable")
        return self.verify_password(account, password, seed)


def rotation_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env = environment(tmp_path)
    bound = env.value["actors"]["worker1"]
    actor = {
        "id": bound["provider_subject"],
        "account_id": bound["account_id"],
        "username": bound["username"],
        "roles": [bound["role"]],
        "password": "old-password-" * 3,
        "totp_secret": "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ",
    }
    state_file = tmp_path / "provider.json"
    private_write(state_file, json.dumps({"users": {"worker": actor}}).encode())
    provider = FakeProvider(actor)
    rotation = CredentialRotation(
        env, state_file, tmp_path / "not-read", tmp_path / "not-read", tmp_path / "operations"
    )
    monkeypatch.setattr(rotation, "_provider", lambda _state: provider)
    request = {
        "environment_id": env.id,
        "slot": "worker1",
        "account_id": bound["account_id"],
        "operation_id": str(uuid4()),
        "previous_revision": "1",
        "credential_revision": "2",
        "credential": {
            "password": "new-password-two-" * 3,
            "totp_secret": actor["totp_secret"],
            "revision": "2",
        },
    }
    return rotation, provider, request, state_file


@pytest.mark.parametrize("failure", ["before_effect_failure", "after_effect_failure"])
def test_pending_rotation_resumes_same_declared_payload(
    failure: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rotation, provider, request, state_file = rotation_fixture(tmp_path, monkeypatch)
    setattr(provider, failure, True)
    with pytest.raises(ReviewProviderError):
        rotation(request)
    receipt = rotation.receipts / (request["operation_id"] + ".json")
    assert json.loads(receipt.read_text())["state"] == "pending"
    assert request["credential"]["password"] not in receipt.read_text()
    assert rotation(request)["verified"] is True
    assert provider.effects == 1
    assert (
        json.loads(state_file.read_text())["users"]["worker"]["password"]
        == request["credential"]["password"]
    )


def test_old_confirmed_rotation_receipt_cannot_rewind_newer_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rotation, provider, first, state_file = rotation_fixture(tmp_path, monkeypatch)
    first_result = rotation(first)
    second = {
        **first,
        "operation_id": str(uuid4()),
        "previous_revision": "2",
        "credential_revision": "3",
        "credential": {
            **first["credential"],
            "password": "new-password-three-" * 3,
            "revision": "3",
        },
    }
    rotation(second)
    assert rotation(first) == first_result
    assert provider.effects == 2
    assert (
        json.loads(state_file.read_text())["users"]["worker"]["password"]
        == second["credential"]["password"]
    )
    changed = {**first, "credential": {**first["credential"], "password": "changed-payload-" * 3}}
    with pytest.raises(ValueError, match="identity conflict"):
        rotation(changed)
