"""Fresh-volume initialization under the explicitly assigned Linux supervisor."""

import argparse
import json
import os
import shlex
import shutil
from pathlib import Path
from typing import cast

from tools.imp03_runtime.mesh import render

from .browser_stream import configure_rendered_browser_stream
from .config import AUTH_UID, CONFIG, ROLE_UID, ROOT, Record, text
from .prepare import prepare


def custody(path: Path, uid: int, gid: int, mode: int) -> None:
    # Fresh seed files belong to this process. Set mode before transferring
    # ownership; the seed deliberately has no CAP_FOWNER.
    path.chmod(mode)
    os.chown(path, uid, gid)


def copy_private(source: Path, target: Path, uid: int, gid: int, mode: int = 0o600) -> None:
    if target.exists() or target.is_symlink():
        raise ValueError("Fresh named-volume file required")
    shutil.copyfile(source, target)
    custody(target, uid, gid, mode)


def seed(inputs: Path) -> None:
    if os.geteuid() != 0:
        raise ValueError("Authorized Linux custody supervisor required")
    value = cast(Record, json.loads(inputs.read_text()))
    binding = cast(Record, value["binding"])
    root = Path(ROOT)
    root.mkdir(mode=0o711, exist_ok=True)
    prepared = Path(CONFIG)
    prepare(binding, prepared, assign_ownership=True)
    rendered = root / "rendered"
    render(binding, rendered)
    configure_rendered_browser_stream(rendered / "core-envoy.json")
    pki = Path("/operator/tls")
    for role, uid in ROLE_UID.items():
        destination = Path("/volumes") / (role + "-config")
        if any(destination.iterdir()):
            raise ValueError("Existing role configuration refused")
        custody(destination, uid, uid, 0o700)
        for path in (prepared / role).iterdir():
            copy_private(path, destination / path.name, uid, uid)
        if role in {"identity", "data"}:
            copy_private(pki / "ca.crt", destination / "shared-ca.crt", uid, uid)
        for suffix, owner, group, mode in [
            ("backend", uid, 22002, 0o710),
            ("outbound", 22002, uid, 0o710),
            ("authorization", AUTH_UID[role], 22002, 0o710),
            ("proxy", 22002, 22002, 0o700),
            ("agent", 0, 0, 0o700),
            ("svid", 0, 0, 0o755),
        ]:
            custody(Path("/volumes") / (role + "-" + suffix), owner, group, mode)
        auth = Path("/volumes") / (role + "-authorization")
        copy_private(
            rendered / (role + "-authorization.json"),
            auth / "config.json",
            AUTH_UID[role],
            AUTH_UID[role],
        )
        copy_private(
            Path("/operator/spire-bundle.pem"), auth / "bundle.pem", AUTH_UID[role], AUTH_UID[role]
        )
        proxy = Path("/volumes") / (role + "-proxy")
        copy_private(rendered / (role + "-envoy.json"), proxy / "envoy.json", 22002, 22002)
        agent = Path("/volumes") / (role + "-agent")
        for filename in ("agent.conf", "join.token"):
            copy_private(Path("/operator/agents") / role / filename, agent / filename, 0, 0)
        copy_private(Path("/operator/spire-bundle.pem"), agent / "bundle.crt", 0, 0)
        if role == "core":
            for filename in ("manual.crt", "manual.key"):
                copy_private(pki / filename, proxy / filename, 22002, 22002)
    operator = Path("/volumes/operator")
    if any(operator.iterdir()):
        raise ValueError("Fresh operator state volume required")
    custody(operator, 0, 0, 0o700)
    for name in ("receipt.json", "bindings.json"):
        copy_private(prepared / name, operator / name, 0, 0)
    copy_private(inputs, operator / "inputs.json", 0, 0)
    (operator / "admin.json").write_text(json.dumps(value["admin"]))
    custody(operator / "admin.json", 0, 0, 0o600)
    fence = Path("/volumes/fence")
    custody(fence, 22000, 22999, 0o710)
    (fence / "ledger").mkdir(mode=0o700)
    custody(fence / "ledger", 22000, 22000, 0o700)
    copy_private(rendered / "fence.json", fence / "config.json", 22000, 22000)
    for name, uid, gid in [
        ("identity-db", 22041, 22011),
        ("identity-provider", 22041, 22011),
        ("data-db", 22042, 22013),
    ]:
        custody(Path("/volumes") / name, uid, gid, 0o710)
    copy_private(Path("/operator/opa"), Path("/volumes/opa/opa"), 22014, 22014, 0o555)
    pg = Path("/volumes/postgres-config")
    if any(pg.iterdir()):
        raise ValueError("Fresh PostgreSQL configuration required")
    custody(pg, 999, 999, 0o700)
    for filename in ("postgres.crt", "postgres.key", "ca.crt"):
        copy_private(pki / filename, pg / filename, 999, 999)
    copy_private(Path("/operator/provider-init.sql"), pg / "provider-init.sql", 999, 999)
    (pg / "pg_hba.conf").write_text(
        "local all postgres trust\n"
        "local all all reject\n"
        "hostnossl all all 0.0.0.0/0 reject\n"
        "hostnossl all all ::/0 reject\n"
        "hostssl imp04_identity_002 imp04_identity_runtime_002 172.29.45.11/32 scram-sha-256\n"
        "hostssl imp04_runtime_002 imp04_data_runtime_002 172.29.45.12/32 scram-sha-256\n"
        "hostssl imp04_provider_002 imp04_provider_runtime_002 172.29.45.13/32 scram-sha-256\n"
        "hostssl all postgres 172.29.45.0/24 scram-sha-256\n"
        "host all all 0.0.0.0/0 reject\n"
        "host all all ::/0 reject\n"
    )
    custody(pg / "pg_hba.conf", 999, 999, 0o600)
    (pg / "postgres.env").write_text(
        "POSTGRES_PASSWORD="
        + text(value, "postgres_password")
        + "\nPGDATA=/var/lib/postgresql/data\n"
    )
    custody(pg / "postgres.env", 999, 999, 0o600)
    custody(Path("/volumes/postgres-data"), 999, 999, 0o700)
    kc = Path("/volumes/keycloak-config")
    if any(kc.iterdir()):
        raise ValueError("Fresh Keycloak configuration required")
    custody(kc, 1000, 1000, 0o700)
    for filename in ("keycloak.crt", "keycloak.key", "ca.crt"):
        copy_private(pki / filename, kc / filename, 1000, 1000)
    copy_private(Path("/operator/realm.json"), kc / "realm.json", 1000, 1000)
    (kc / "kc.env").write_text(
        "KC_DB=postgres\nKC_DB_URL="
        + shlex.quote(
            "jdbc:postgresql://postgres.imp04.internal:5432/imp04_provider_002?sslmode=verify-full&sslrootcert=/config/ca.crt"
        )
        + "\nKC_DB_USERNAME=imp04_provider_runtime_002\nKC_DB_PASSWORD="
        + text(value, "provider_database_password")
        + "\nKC_BOOTSTRAP_ADMIN_USERNAME=imp04-owner-admin\nKC_BOOTSTRAP_ADMIN_PASSWORD="
        + text(value, "provider_admin_password")
        + "\n"
    )
    custody(kc / "kc.env", 1000, 1000, 0o600)
    custody(Path("/volumes/keycloak-data"), 1000, 1000, 0o700)
    custody(Path("/volumes/browser-home"), 65532, 65532, 0o700)
    copy_private(pki / "ca.crt", Path("/volumes/browser-home/ca.crt"), 65532, 65532)
    print(json.dumps({"prepared": True, "roles": list(ROLE_UID), "live_trust": "unchecked"}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    seed(parser.parse_args().input)


if __name__ == "__main__":
    main()
