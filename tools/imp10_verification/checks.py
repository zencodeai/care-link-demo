"""Run and record the pinned IMP-10 source lane on an owned PostgreSQL fixture."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from psycopg.conninfo import make_conninfo

from tools.check import COMMANDS, ROOT

CONNECTION = Path("/private/tmp/care-link-imp09-001/database/connection.json")


def clock() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def run(target: Path, opa: Path) -> int:
    settings = json.loads(CONNECTION.read_text())
    if (
        settings.get("hostaddr") != "127.0.0.1"
        or settings.get("port") != "35439"
        or settings.get("sslmode") != "verify-full"
    ):
        raise ValueError("Use only the owned verified-TLS loopback fixture")
    if not opa.is_file():
        raise ValueError("Pinned OPA is required")
    connex = make_conninfo(**settings)
    env = {
        **os.environ,
        "CARE_LINK_MANUAL_TEST_DSN": connex,
        "CARE_LINK_OPA_BINARY": str(opa.resolve()),
        "CARE_LINK_IMP10_LOAD_EVIDENCE": str(target / "load.json"),
        "CARE_LINK_JOURNEY_PROVIDER": "fixture",
        "CARE_LINK_JOURNEY_EVIDENCE": str(target / "matched-assistance.json"),
        "UV_OFFLINE": "1",
    }
    target.mkdir(parents=True, exist_ok=False)
    commands = [
        command + ["--tb=short", "--junitxml", str(target / "pytest.xml")]
        if command[-1] == "pytest"
        else command
        for command in COMMANDS
    ]
    commands.extend(
        [
            ["pnpm", "exec", "tsc", "-p", "tests/e2e/training/tsconfig.json"],
            ["pnpm", "exec", "eslint", "tests/e2e/training", "--max-warnings", "0"],
            [
                "pnpm",
                "exec",
                "prettier",
                "--check",
                "tests/e2e/training",
                "config/demo/imp10/training-artifact.json",
                "packages/contracts/training.schema.json",
            ],
            [
                sys.executable,
                "-m",
                "pytest",
                "--tb=short",
                "--junitxml",
                str(target / "matched-assistance.xml"),
                "tests/evaluation/qwen_combined_journey.py",
            ],
            ["git", "diff", "--check"],
        ]
    )
    checks = []
    for index, command in enumerate(commands, start=1):
        started = clock()
        result = subprocess.run(  # noqa: S603
            command, cwd=ROOT, env=env, capture_output=True, text=True, check=False
        )
        output = (result.stdout + result.stderr).replace(connex, "[private fixture DSN]")
        output = output.replace(settings["password"], "[private fixture credential]")
        path = target / f"{index:02d}.log"
        path.write_text(output)
        checks.append(
            {
                "command": command,
                "started_at": started,
                "completed_at": clock(),
                "exit_code": result.returncode,
                "log": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
        (target / "checks.json").write_text(json.dumps(checks, indent=2) + "\n")
        print(f"{index}/{len(commands)} exit={result.returncode} " + " ".join(command), flush=True)
    return int(any(check["exit_code"] for check in checks))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--opa", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.out.resolve(), args.opa))


if __name__ == "__main__":
    main()
