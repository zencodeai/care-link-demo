"""Opt-in process custody and exact receiver workload route allocation."""

import json
import os

import pytest

from tools.imp03_runtime import config
from tools.imp05_runtime.__main__ import configuration


def test_receiver_workload_identity_can_only_resolve_current_authority(monkeypatch):
    seen = {}

    def capture(_uid, rules, _fence, **_kwargs):
        seen.update({rule.spiffe_id: rule.routes for rule in rules})
        return object()

    monkeypatch.setattr(config, "BackendVerifier", capture)
    cfg = {
        "role": "identity",
        "uid": os.geteuid(),
        "proxy_uid": 20001,
        "fence_socket": "/private/not-opened",
        "fence_uid": 20002,
        "referral_enabled": True,
    }
    config.workload(cfg, "identity")
    receiver = seen["spiffe://care-link.demo/demo/receiver"]
    assert receiver == frozenset(
        {
            ("POST", "/internal/v1/manual-identity/resolve"),
            ("POST", "/internal/v1/manual-identity/current"),
        }
    )
    seen.clear()
    config.workload({**cfg, "referral_enabled": False}, "identity")
    assert "spiffe://care-link.demo/demo/receiver" not in seen


def test_receiver_process_requires_opt_in_and_separate_credentials(tmp_path):
    key = tmp_path / "content.key"
    key.write_bytes(b"x" * 32)
    key.chmod(0o600)
    path = tmp_path / "config.json"
    cfg = {
        "role": "receiver",
        "session": "imp05-001",
        "uid": os.geteuid(),
        "referral_enabled": True,
        "store_dsn": "receiver-custody-not-a-real-DSN",
        "content_key": str(key),
    }

    def write(value):
        path.write_text(json.dumps(value))
        path.chmod(0o600)

    write(cfg)
    assert configuration(path)["role"] == "receiver"
    write({**cfg, "core_signing_key": str(key)})
    with pytest.raises(ValueError, match="Cross-role"):
        configuration(path)
    write({**cfg, "referral_enabled": False})
    with pytest.raises(ValueError, match="binding"):
        configuration(path)
    write(cfg)
    key.chmod(0o644)
    with pytest.raises(ValueError, match="custody"):
        configuration(path)
