"""Execute trusted-browser continuation cases and exact operator barriers."""

import argparse
import json
import os
import signal
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID

import psycopg

from tools.imp03_verification.extended import compare_snapshots, snapshot_target

from . import docker, qualification
from .continuation_evidence import EVIDENCE, lease
from .deployment import name
from .infrastructure import private_write
from .model import CONFIG, PRIVATE, Record


def environment(output: Path, mode: str) -> dict[str, str]:
    endpoint = json.loads((PRIVATE / "browser-server.json").read_text())["endpoint"]
    return {
        **os.environ,
        "CARE_LINK_IMP03_E2E_CONFIG": str(PRIVATE / "browser.json"),
        "CARE_LINK_IMP03_E2E_OUTPUT": str(output),
        "CARE_LINK_IMP03_EXTENDED_CASE": mode,
        "CARE_LINK_IMP03_EXTENDED_LOCALE": "en-CA",
        "PW_TEST_CONNECT_WS_ENDPOINT": endpoint,
        "PW_TEST_CONNECT_EXPOSE_NETWORK": "<loopback>",
        "NODE_EXTRA_CA_CERTS": str(PRIVATE / "tls-renewal/ca.crt"),
    }


def wait_ready(path: Path, process: subprocess.Popen[str]) -> Record:
    deadline = time.monotonic() + 110
    while not path.exists():
        if process.poll() is not None or time.monotonic() >= deadline:
            raise RuntimeError("Trusted browser did not reach exact operator readiness")
        time.sleep(0.2)
    info = path.lstat()
    if (
        not path.is_file()
        or path.is_symlink()
        or info.st_uid != os.geteuid()
        or info.st_mode & 0o077
    ):
        raise ValueError("Private browser readiness required")
    value = cast(Record, json.loads(path.read_text()))
    required = {"session", "phase", "nonce", "session_id", "principal_id"}
    if path.name == "commit-ready.json":
        required.add("operation_id")
    if path.name.startswith("operations-"):
        required.add("revision")
    if set(value) != required or value["session"] != "imp03-002":
        raise ValueError("Wrong continuation readiness binding")
    for field in required - {"session", "phase", "revision"}:
        if str(UUID(str(value[field]))) != value[field]:
            raise ValueError("Canonical barrier identities required")
    browser = json.loads((PRIVATE / "browser.json").read_text())
    if value["principal_id"] != browser["accounts"]["pid"]:
        raise ValueError("Exact issued participant required")
    target = lease()
    target.inspect()
    with psycopg.connect(target.dsn()) as connection:
        row = connection.execute(
            "SELECT participant_account_id FROM core.session WHERE id=%s",
            (value["session_id"],),
        ).fetchone()
        if row is None or str(row[0]) != value["principal_id"]:
            raise ValueError("Session does not belong to exact issued participant")
    return value


def restrict_acl(ready: Record) -> None:
    if ready["phase"] != "acl-revocation":
        raise ValueError("Exact ACL barrier required")
    # Deliberate operator fault in the current ACL source. This is not a product
    # BFF restriction workflow or a claim of journalled rights administration.
    with psycopg.connect(lease().dsn()) as connection:
        row = connection.execute(
            "SELECT revision,revoked_at FROM core.session_acl WHERE session_id=%s "
            "AND principal_id=%s AND purpose='support' FOR UPDATE",
            (ready["session_id"], ready["principal_id"]),
        ).fetchone()
        if row is None or row[1] is not None:
            raise ValueError("Fresh exact active support ACL required")
        connection.execute(
            "UPDATE core.session_acl SET revoked_at=clock_timestamp(),revision=revision+1 "
            "WHERE session_id=%s AND principal_id=%s AND purpose='support'",
            (ready["session_id"], ready["principal_id"]),
        )
        connection.execute(
            "UPDATE core.session_guard SET access_revision=access_revision+1 WHERE session_id=%s",
            (ready["session_id"],),
        )


def arm_commit(ready: Record) -> None:
    if ready["phase"] != "database-ack-loss":
        raise ValueError("Exact database acknowledgement barrier required")
    target = lease()
    with psycopg.connect(target.dsn()) as connection:
        if connection.execute(
            "SELECT 1 FROM durable.operation WHERE operation_id=%s", (ready["operation_id"],)
        ).fetchone():
            raise ValueError("Fresh operation ID required")
    marker = {
        "session": "imp03-002",
        "journal_id": target.journal_id,
        "operation_id": ready["operation_id"],
        "principal_id": ready["principal_id"],
        "operation_name": "session_human_request",
        "expires_at": (datetime.now(UTC) + timedelta(seconds=60))
        .isoformat()
        .replace("+00:00", "Z"),
    }
    script = (
        "import os,sys;from pathlib import Path;"
        f"p=Path('{CONFIG}/data/commit-ack-fault.json');"
        "f=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);"
        "os.write(f,sys.stdin.buffer.read());os.fsync(f);os.close(f)"
    )
    docker.exec(name("data-app"), ["python", "-c", script], stdin=json.dumps(marker))


def cancel_unconsumed(ready: Record) -> None:
    script = (
        "import json;from pathlib import Path;"
        f"p=Path('{CONFIG}/data/commit-ack-fault.json');"
        "v=json.loads(p.read_text()) if p.exists() else None;"
        f"assert v is None or v['operation_id']=='{ready['operation_id']}';"
        "p.rename(p.with_name('commit-ack-fault.cancelled.json')) if v is not None else None"
    )
    docker.exec(name("data-app"), ["python", "-c", script])


def run(mode: str, attempt: int) -> Record:
    if mode not in {"commit-ack", "revocation"}:
        raise ValueError("Exact continuation case required")
    os.umask(0o077)
    output = PRIVATE / f"{mode}-{attempt:03}"
    output.mkdir(mode=0o700, exist_ok=False)
    # The provider deliberately rejects OTP reuse. Separate runner processes
    # cannot share its in-memory last-window map, so begin in a fresh window.
    time.sleep(30 - time.time() % 30 + 0.2)
    result: Record = {"case": mode, "attempt": attempt, "human_acceptance": False}
    ready: Record | None = None
    started = time.monotonic()
    try:
        with (PRIVATE / (output.name + ".log")).open("x") as stream:
            process = subprocess.Popen(  # noqa: S603 - fixed locked browser runner
                [  # noqa: S607 - existing locked local runner
                    "pnpm",
                    "exec",
                    "playwright",
                    "test",
                    "--config",
                    "tests/e2e/imp03-extended/playwright.config.ts",
                ],
                env=environment(output, mode),
                stdout=stream,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                text=True,
            )
            try:
                prefix = "commit" if mode == "commit-ack" else "extended-revocation"
                ready = wait_ready(output / (prefix + "-ready.json"), process)
                if mode == "commit-ack":
                    arm_commit(ready)
                else:
                    restrict_acl(ready)
                before = snapshot_target(lease())
                private_write(output / (prefix + "-applied.json"), json.dumps(ready))
                result["exit_code"] = process.wait(timeout=150)
                after = snapshot_target(lease())
                result["audit_valid"] = cast(Record, after["audit"])["valid"]
                if mode == "revocation":
                    result["effect_comparison"] = compare_snapshots(before, after)
                    result["scope"] = (
                        "Injected exact current support ACL; retained; "
                        "no product rights workflow claim"
                    )
                elif result["exit_code"] == 0:
                    with psycopg.connect(lease().dsn()) as connection:
                        counts = connection.execute(
                            "SELECT (SELECT count(*) FROM workforce.queue_entry "
                            "WHERE session_id=%s),"
                            "(SELECT count(*) FROM durable.operation WHERE operation_id=%s "
                            "AND operation_name='session_human_request' AND state='committed'),"
                            "(SELECT count(*) FROM audit.event WHERE operation_id=%s "
                            "AND decision='PERMIT')",
                            (ready["session_id"], ready["operation_id"], ready["operation_id"]),
                        ).fetchone()
                    result["exactly_one_durable_effect"] = counts == (1, 1, 1)
                    result["queue_operation_canonical_audit_counts"] = counts
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=10)
    finally:
        if mode == "commit-ack" and ready is not None:
            cancel_unconsumed(ready)
        result["duration_seconds"] = round(time.monotonic() - started, 3)
        private_write(EVIDENCE / (output.name + ".json"), json.dumps(result, indent=2))
    if result.get("exit_code") == 0:
        private_write(
            EVIDENCE / (output.name + "-observations.json"),
            (output / "observations.json").read_text(),
        )
    return result


def verified(result: Record) -> bool:
    if result.get("exit_code") != 0:
        return False
    if result.get("case") == "commit-ack":
        return (
            result.get("exactly_one_durable_effect") is True and result.get("audit_valid") is True
        )
    if result.get("case") == "revocation":
        comparison = result.get("effect_comparison")
        return (
            isinstance(comparison, dict)
            and cast(Record, comparison).get("no_prohibited_observed_effect") is True
            and result.get("audit_valid") is True
        )
    return (
        result.get("forbidden_business_effect_absent") is True
        and result.get("exact_barrier_restored") is True
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "case",
        choices=[
            "commit-ack",
            "revocation",
            "identity-loss",
            "pdp-loss",
            "journal-loss",
            "audit-loss",
        ],
    )
    parser.add_argument("--attempt", type=int, required=True)
    args = parser.parse_args()
    if args.case.endswith("-loss"):
        time.sleep(30 - time.time() % 30 + 0.2)
        os.environ.update(environment(PRIVATE, "unused"))
        target = lease()
        qualification.EVIDENCE = EVIDENCE
        result = qualification.run(
            args.case,
            args.attempt,
            PRIVATE,
            observe=lambda: snapshot_target(target),
            compare=compare_snapshots,
            quiescence_seconds=1.25,
        )
    else:
        result = run(args.case, args.attempt)
    print(json.dumps(result))
    if not verified(result):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
