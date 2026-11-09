"""Generate exact private role configurations from the actual lab bindings."""

import json
from pathlib import Path
from uuid import uuid4

from psycopg.conninfo import make_conninfo

from .prepare import NAMESPACE, write
from .provider_bootstrap import oidc_settings


def generate(root: Path, provider_address: str) -> dict[str, dict[str, bytes]]:
    secrets = root / "secrets"
    state = json.loads((root / "provider-state.json").read_text())
    passwords = json.loads((secrets / "passwords.json").read_text())
    subjects = {
        str(uuid4()): "spiffe://care-link.demo/lab/" + role
        for role in ("main", "help", "identity", "identity_provider")
    }
    identity = {
        "owner_account_id": state["users"]["main"]["account_id"],
        "lifecycle_client_id": state["clients"]["lifecycle"]["client_id"],
        "lifecycle_client_secret": state["clients"]["lifecycle"]["secret"],
        "backend_socket": "/run/care-link/backend/app.sock",
        "fence_socket": "/run/care-link/fence/fence.sock",
        "store_dsn": make_conninfo(
            host=f"postgres.{NAMESPACE}.svc.cluster.local",
            port=5432,
            dbname="identity",
            user="identity_runtime",
            password=passwords["identity_runtime_password"],
            sslmode="verify-full",
            sslrootcert="/config/ca.crt",
        ),
        "custody_key": "/config/custody.key",
        "signing_key": "/config/identity-signing.key",
        "signing_key_id": "imp02-002",
        "ca_file": "/config/ca.crt",
        "provider_address": provider_address,
        "signal_issuer": "care-link-imp02-local-signals",
        "signal_public_key": "/config/signals.pub",
        "workload_subjects": subjects,
        "main_origin": state["main_origin"],
        "help_origin": state["help_origin"],
        "oidc_main": oidc_settings(state, "main"),
        "oidc_help": oidc_settings(state, "help"),
    }
    results = {"identity": {"identity.json": (json.dumps(identity, indent=2) + "\n").encode()}}
    for name in ("custody.key", "identity-signing.key", "signals.pub", "ca.crt"):
        results["identity"][name] = (secrets / name).read_bytes()
    for role in ("main", "help"):
        config = {
            "backend_socket": "/run/care-link/backend/app.sock",
            "outbound_socket": "/run/care-link/outbound/proxy.sock",
            "identity_origin": "https://identity.mesh.local:8443",
            "origin": state[role + "_origin"],
            "web_directory": "/app/web/" + role,
            "static_origin": "https://static.localhost:21443",
            "signing_key_id": "imp02-002",
            "signing_public_key": "/config/identity-signing.pub",
        }
        if role == "help":
            config["spool"] = "/spool/help.sqlite"
        results[role] = {
            role + ".json": (json.dumps(config, indent=2) + "\n").encode(),
            "identity-signing.pub": (secrets / "identity-signing.pub").read_bytes(),
        }
    output = root / "role-configs"
    output.mkdir(mode=0o700)
    for role, files in results.items():
        directory = output / role
        directory.mkdir(mode=0o700)
        for name, content in files.items():
            write(directory / name, content)
    # Public identifiers are not permission grants and contain no bearer material.
    write(root / "workload-subjects.json", (json.dumps(subjects, indent=2) + "\n").encode())
    browser = {
        "mainOrigin": state["main_origin"],
        "helpOrigin": state["help_origin"],
        "oidcOrigin": "https://id.localhost:20443",
        "staticOrigin": "https://static.localhost:21443",
        "ignoreHTTPSErrors": True,
        "staticReviewProfile": "owner_review_local_demo",
    }
    for key, actor in [
        ("participant", "participant"),
        ("otherParticipant", "other"),
        ("worker", "worker"),
    ]:
        user = state["users"][actor]
        browser[key] = {
            "username": user["username"],
            "password": user["password"],
            "totpSecret": user["totp_secret"],
        }
    write(root / "browser.json", (json.dumps(browser, indent=2) + "\n").encode())
    return results
