"""Durable custody restores disposable operator inputs without stale credentials."""

import json
import os
import shutil
from pathlib import Path

from test_demo_review_environment import environment

from tools.demo.secrets import VaultSecrets
from tools.demo.storage import private_directory, private_read, private_write
from tools.imp03_shared import review_start


def test_restore_after_temporary_cleanup_uses_current_credentials_and_durable_receipts(
    tmp_path: Path, monkeypatch
) -> None:
    env = environment(tmp_path)
    state = tmp_path / "state"
    private_directory(state, create=True)
    key = tmp_path / "vault.key"
    private_write(key, os.urandom(32))
    store = VaultSecrets(state / "vault", key)
    manifest = tmp_path / "environment.json"
    private_write(manifest, json.dumps(env.value).encode())
    users = {}
    labels = {
        "participant": "participant",
        "worker1": "worker",
        "worker2": "worker2",
        "supervisor": "supervisor",
    }
    for slot, label in labels.items():
        actor = env.value["actors"][slot]
        users[label] = {
            "id": actor["provider_subject"],
            "account_id": actor["account_id"],
            "password": "obsolete-password",
            "totp_secret": "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP",
        }
        store.put(
            actor["secret_ref"],
            json.dumps(
                {
                    "password": "current-password-" + slot,
                    "totp_secret": "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP",
                    "revision": "2",
                }
            ),
        )
    store.put(
        "bootstrap",
        json.dumps(
            {
                "admin": {"dsn": "private-test-dsn"},
                "provider_state": {"users": users},
                "provider_admin_password": "private-admin",
            }
        ),
    )
    runtime = tmp_path / "temporary-runtime"
    descriptor = tmp_path / "operator-bootstrap.json"
    private_write(
        descriptor,
        json.dumps(
            {
                "schema_version": 1,
                "state_root": str(state),
                "vault_key_file": str(key),
                "bootstrap_ref": "bootstrap",
                "environment_manifest": str(manifest),
                "runtime_dir": str(runtime),
                "ca_file": str(tmp_path / "ca.crt"),
                "registry_path": str(tmp_path / "contexts.json"),
                "socket": str(tmp_path / "operator.sock"),
                "contexts_targets": [],
            }
        ).encode(),
    )

    class Operator:
        def __init__(self, config: Path) -> None:
            self.config = json.loads(private_read(config))

    monkeypatch.setattr(review_start, "require_profile", lambda: None)
    monkeypatch.setattr(review_start, "ReviewEnvironment", Operator)
    for _ in range(2):
        operator = review_start.restore(descriptor)
        restored = json.loads(private_read(Path(operator.config["provider_state"])))
        for slot, label in labels.items():
            assert restored["users"][label]["password"] == "current-password-" + slot
        assert operator.config["credential_receipts"] == str(tmp_path / "credential-operations")
        assert not Path(operator.config["credential_receipts"]).is_relative_to(runtime)
        shutil.rmtree(runtime)
