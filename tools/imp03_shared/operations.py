"""Bounded protected-read measurements and an exact supervised core stop/start."""

import argparse
import json
import os
import signal
import subprocess
import time
from typing import cast

from tools.imp03_verification.extended import snapshot_target

from . import docker
from .continuation_browser import environment, wait_ready
from .continuation_evidence import EVIDENCE, lease
from .deployment import create, name
from .infrastructure import private_write
from .model import CONFIG, PRIVATE, ROLE_UID, ROOT, Record, mount


def resources() -> list[Record]:
    result = subprocess.run(  # noqa: S603 - fixed owned application names, read-only sample
        [  # noqa: S607 - existing Docker CLI
            "docker",
            "stats",
            "--no-stream",
            "--format",
            "{{json .}}",
            *[name(role + "-app") for role in ROLE_UID],
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    return [cast(Record, json.loads(line)) for line in result.stdout.splitlines()]


def stopped_backend() -> Record:
    create(
        "operations-custody-probe",
        ["python", "-c", "import time;time.sleep(60)"],
        [
            mount("core-config", CONFIG + "/core", readonly=True),
            mount("core-backend", ROOT + "/core/backend", readonly=True),
        ],
        uid=22012,
    )
    docker.start(name("operations-custody-probe"))
    try:
        script = (
            "import socket,json;from pathlib import Path;"
            f"p=Path('{CONFIG}/core/process.json');"
            f"path='{ROOT}/core/backend/app.sock';"
            "s=socket.socket(socket.AF_UNIX);s.settimeout(1);error=s.connect_ex(path);"
            "print(json.dumps({'process_receipt_present':p.exists(),"
            "'backend_socket_entry_present':Path(path).exists(),"
            "'backend_accepts_connection':error==0,'connect_errno':error}))"
        )
        return cast(
            Record,
            json.loads(docker.exec(name("operations-custody-probe"), ["python", "-c", script])),
        )
    finally:
        docker.stop(name("operations-custody-probe"))
        docker.remove_owned(name("operations-custody-probe"))


def run(attempt: int) -> Record:
    os.umask(0o077)
    output = PRIVATE / f"operations-{attempt:03}"
    output.mkdir(mode=0o700, exist_ok=False)
    time.sleep(30 - time.time() % 30 + 0.2)
    env = environment(output, "operations")
    previous = json.loads((PRIVATE / "revocation-001/extended-revocation-ready.json").read_text())
    env["CARE_LINK_IMP03_REVOKED_SESSION"] = previous["session_id"]
    result: Record = {"case": "operations", "attempt": attempt, "human_acceptance": False}
    stopped = False
    started = time.monotonic()
    try:
        result["resource_before"] = resources()
        with (PRIVATE / (output.name + ".log")).open("x") as log:
            process = subprocess.Popen(  # noqa: S603 - fixed trusted browser runner
                [  # noqa: S607 - existing locked runner
                    "pnpm",
                    "exec",
                    "playwright",
                    "test",
                    "--config",
                    "tests/e2e/imp03-extended/playwright.config.ts",
                ],
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                text=True,
            )
            try:
                ready = wait_ready(output / "operations-ready.json", process)
                if ready["phase"] != "core-shutdown":
                    raise ValueError("Exact core shutdown binding required")
                before = snapshot_target(lease())
                core = docker.inspect_container(name("core-app"))
                result["resource_after_load"] = resources()
                stopped = True
                docker.stop(name("core-app"))
                state = docker.inspect_container(name("core-app"))
                result["stop_exit_code"] = cast(Record, state["State"])["ExitCode"]
                result["stopped_backend"] = stopped_backend()
                private_write(output / "operations-stopped.json", json.dumps(ready))
                outage = wait_ready(output / "operations-outage-observed.json", process)
                if outage != ready:
                    raise ValueError("Outage observation binding differs")
                docker.start(name("core-app"))
                stopped = False
                time.sleep(1.25)
                private_write(output / "operations-resumed.json", json.dumps(ready))
                result["exit_code"] = process.wait(timeout=110)
                current = docker.inspect_container(name("core-app"))
                result["core_container_id_preserved"] = core["Id"] == current["Id"]
                after = snapshot_target(lease())
                before_tables = cast(dict[str, object], before["tables"])
                after_tables = cast(dict[str, object], after["tables"])
                result["business_rows_preserved"] = all(
                    value == after_tables.get(table)
                    for table, value in before_tables.items()
                    if not table.startswith("audit.")
                )
                result["audit_chain_valid"] = cast(Record, after["audit"])["valid"]
                result["resource_after_restart"] = resources()
            finally:
                if stopped:
                    docker.start(name("core-app"))
                    result["core_restored_in_cleanup"] = True
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=10)
    finally:
        result["duration_seconds"] = round(time.monotonic() - started, 3)
        private_write(EVIDENCE / (output.name + ".json"), json.dumps(result, indent=2))
    if result.get("exit_code") == 0:
        private_write(
            EVIDENCE / (output.name + "-observations.json"),
            (output / "observations.json").read_text(),
        )
    return result


def verified(result: Record) -> bool:
    backend = result.get("stopped_backend")
    return (
        result.get("exit_code") == 0
        and result.get("stop_exit_code") in {0, 143}
        and result.get("core_container_id_preserved") is True
        and result.get("business_rows_preserved") is True
        and result.get("audit_chain_valid") is True
        and isinstance(backend, dict)
        and cast(Record, backend).get("backend_accepts_connection") is False
        and cast(Record, backend).get("connect_errno") in {2, 111}
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt", type=int, required=True)
    args = parser.parse_args()
    value = run(args.attempt)
    print(json.dumps({k: v for k, v in value.items() if not k.startswith("resource_")}))
    if not verified(value):
        raise SystemExit(1)
