"""Restore disposable operator inputs from durable credential custody and serve."""

import argparse
import json
from pathlib import Path

from tools.demo.models import Environment, record, text
from tools.demo.secrets import KeychainSecrets, VaultSecrets, credential
from tools.demo.storage import private_directory, private_read, private_write

from .review_environment import ReviewEnvironment, require_profile


def restore(descriptor: Path) -> ReviewEnvironment:
    require_profile()
    config = record(json.loads(private_read(descriptor)))
    if config.get("schema_version") != 1:
        raise ValueError("Operator bootstrap version mismatch")
    state_root = Path(text(config, "state_root"))
    key = config.get("vault_key_file")
    store = VaultSecrets(state_root / "vault", Path(str(key))) if key else KeychainSecrets()
    bootstrap = record(json.loads(store.get(text(config, "bootstrap_ref"))))
    manifest_path = Path(text(config, "environment_manifest"))
    environment = Environment.parse(json.loads(private_read(manifest_path)))
    provider = record(bootstrap["provider_state"])
    users = record(provider["users"])
    slots = {
        "participant": "participant",
        "worker1": "worker",
        "worker2": "worker2",
        "supervisor": "supervisor",
    }
    for slot, label in slots.items():
        actor = record(record(environment.value["actors"])[slot])
        current = credential(store.get(text(actor, "secret_ref")))
        issued = record(users[label])
        if issued["account_id"] != actor["account_id"] or issued["id"] != actor["provider_subject"]:
            raise ValueError("Durable issued actor binding mismatch")
        issued["password"], issued["totp_secret"] = current["password"], current["totp_secret"]
    runtime = Path(text(config, "runtime_dir"))
    private_directory(runtime, create=True)
    private_write(runtime / "admin.json", json.dumps(bootstrap["admin"]).encode())
    private_write(runtime / "provider-state.json", json.dumps(provider).encode())
    private_write(
        runtime / "provider-admin.txt", text(bootstrap, "provider_admin_password").encode()
    )
    operator = {
        "environment_manifest": str(manifest_path),
        "admin_config": str(runtime / "admin.json"),
        "provider_state": str(runtime / "provider-state.json"),
        "provider_admin_password_file": str(runtime / "provider-admin.txt"),
        "ca_file": config["ca_file"],
        "registry_path": config["registry_path"],
        "socket": config["socket"],
        "contexts_targets": config["contexts_targets"],
        "maintenance_profile": "continuation-001",
        "credential_receipts": str(descriptor.parent / "credential-operations"),
    }
    private_write(runtime / "operator.json", json.dumps(operator).encode())
    result = ReviewEnvironment(runtime / "operator.json")
    master = Path(text(config, "registry_path"))
    if master.exists():
        contexts = record(json.loads(private_read(master)))
        for raw in contexts.values():
            context = record(raw)
            context["state"] = result.admin.inspect(text(context, "run_id"))["state"]
        result.publisher(contexts)
        private_write(master, json.dumps(contexts).encode())
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--descriptor", type=Path, required=True)
    args = parser.parse_args()
    restore(args.descriptor).serve()


if __name__ == "__main__":
    main()
