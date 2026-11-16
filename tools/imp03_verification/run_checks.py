"""Run complete source and fresh PostgreSQL/OPA checks without touching IMP-02.

The existing named IMP-03 verification fixture is exclusively leased for this
invocation; an existing container is refused and prior private files preserved.
"""

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo

from . import database

ROOT = Path(__file__).resolve().parents[2]


def run(output: Path, opa: Path) -> int:
    if not output.is_absolute() or output.is_symlink():
        raise ValueError("Fresh absolute private evidence directory required")
    pins = json.loads((ROOT / "config/demo/imp03/products.json").read_text())
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise ValueError(
            "This verification runner is pinned to the accepted macOS ARM64 workstation"
        )
    if hashlib.sha256(opa.read_bytes()).hexdigest() != pins["opa"]["darwin_arm64_sha256"]:
        raise ValueError("OPA executable does not match the pinned product digest")
    for executable in ("docker", "uv", "pnpm", "node"):
        if shutil.which(executable) is None:
            raise ValueError("Required existing tool unavailable: " + executable)
    docker = shutil.which("docker")
    if docker is None:
        raise ValueError("Docker CLI unavailable")
    probe = subprocess.run(  # noqa: S603
        [docker, "ps", "-a", "--filter", "name=^/" + database.NAME + "$", "--format", "{{.ID}}"],
        check=True,
        capture_output=True,
        text=True,
    )
    if probe.stdout.strip():
        raise ValueError("Existing IMP-03 fixture refused; inspect ownership before cleanup")
    output.mkdir(mode=0o700, exist_ok=False)
    if database.DIRECTORY.exists():
        info = database.DIRECTORY.lstat()
        if database.DIRECTORY.is_symlink() or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError("Unsafe prior private fixture directory")
        archive = Path(tempfile.mkdtemp(prefix="care-link-imp03-prior-", dir="/private/tmp"))
        shutil.move(str(database.DIRECTORY), str(archive / "database"))
    database.start()
    results: dict[str, int] = {}
    try:
        settings = json.loads((database.DIRECTORY / "connection.json").read_text())
        deadline = time.monotonic() + 60
        while True:
            try:
                with psycopg.connect(**settings, connect_timeout=1) as connection:
                    tls = connection.execute(
                        "SELECT ssl,version FROM pg_stat_ssl WHERE pid=pg_backend_pid()"
                    ).fetchone()
                    if tls != (True, "TLSv1.3"):
                        raise ValueError("Fixture TLS qualification failed")
                break
            except psycopg.Error:
                if time.monotonic() >= deadline:
                    raise ValueError("PostgreSQL readiness deadline exceeded") from None
                time.sleep(0.5)
        dsn = make_conninfo(**settings)
        lanes = [
            (
                "full-check",
                [sys.executable, "tools/check.py"],
                {
                    "CARE_LINK_MANUAL_TEST_DSN": dsn,
                    "CARE_LINK_OPA_BINARY": str(opa),
                    "CARE_LINK_IMP03_CAPTURE": "1",
                },
            ),
            (
                "provisioning",
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "tests/integration/imp03_runtime/test_provisioning.py",
                ],
                {
                    "CARE_LINK_IMP03_PROVISION_TEST_DSN": dsn,
                },
            ),
        ]
        for name, command, additional in lanes:
            environment = {
                key: value
                for key, value in os.environ.items()
                if key
                not in {
                    "CARE_LINK_MANUAL_TEST_DSN",
                    "CARE_LINK_IMP03_PROVISION_TEST_DSN",
                    "CARE_LINK_OPA_BINARY",
                    "CARE_LINK_IMP03_CAPTURE",
                }
            }
            print(
                "Running " + name + "; sanitized log: " + str(output / (name + ".log")), flush=True
            )
            result = subprocess.run(  # noqa: S603
                command,
                cwd=ROOT,
                env={**environment, **additional},
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
            sanitized = result.stdout.replace(settings["password"], "[REDACTED]")
            sanitized = re.sub(r"password=[^\s'\"]+", "password=[REDACTED]", sanitized)
            path = output / (name + ".log")
            path.write_text(sanitized)
            path.chmod(0o600)
            results[name] = result.returncode
            print("\n".join(sanitized.splitlines()[-20:]), flush=True)
            if result.returncode:
                break
    finally:
        database.stop()
    (output / "results.json").write_text(
        json.dumps(
            {
                "session": "imp03-002",
                "lanes": results,
                "live_provider_workload_browser": "not_run",
                "human_acceptance": False,
            },
            indent=2,
        )
        + "\n"
    )
    return int(any(results.values()))


def main() -> None:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--opa", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.output, args.opa))


if __name__ == "__main__":
    main()
