"""Record actual source checks using only the owned IMP09 disposable TLS fixture."""

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

SESSION = ROOT / "doc/IMP/slices/IMP-09-backup-and-recovery/sessions/001-implementation"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--lane", choices=["source", "slice"], default="source")
    args = parser.parse_args()
    if not args.attempt.isalnum() or len(args.attempt) > 32:
        raise ValueError("bounded attempt required")
    settings = json.loads(
        Path("/private/tmp/care-link-imp09-001/database/connection.json").read_text()
    )
    if settings.get("port") != "35439" or settings.get("sslmode") != "verify-full":
        raise ValueError("owned verified-TLS fixture only")
    env = {
        **os.environ,
        "CARE_LINK_MANUAL_TEST_DSN": make_conninfo(**settings),
        "CARE_LINK_OPA_BINARY": "/private/tmp/care-link-imp03-tools/opa",
        "UV_CACHE_DIR": "/private/tmp/care-link-imp09-uv-cache",
    }
    target = SESSION / "evidence" / args.lane / args.attempt
    target.mkdir(parents=True, exist_ok=False)
    commands = [
        command + ["--tb=short", "--junitxml", str(target / "pytest.xml")]
        if command[-1] == "pytest"
        else command
        for command in COMMANDS
    ]
    commands.extend(
        [
            ["pnpm", "exec", "tsc", "-p", "tests/e2e/recovery/tsconfig.json"],
            ["pnpm", "exec", "eslint", "tests/e2e/recovery", "--max-warnings", "0"],
            ["pnpm", "exec", "prettier", "--check", "tests/e2e/recovery"],
            [sys.executable, "-m", "tools.imp05_verification.validate_plan"],
        ]
    )
    if args.lane == "slice":
        selected = [
            str(p.relative_to(ROOT))
            for pattern in [
                "services/data/tests/test_imp09*.py",
                "services/core/tests/test_imp09*.py",
                "services/identity/tests/test_imp09*.py",
                "host/recovery-control/tests/*.py",
                "host/help/tests/test_imp09*.py",
            ]
            for p in sorted(ROOT.glob(pattern))
        ]
        commands = [
            [
                sys.executable,
                "-m",
                "pytest",
                *selected,
                "-q",
                "--tb=short",
                "--junitxml",
                str(target / "pytest.xml"),
            ]
        ]
    results: list[dict[str, object]] = []
    for index, command in enumerate(commands):
        started = datetime.now(UTC).isoformat()
        result = subprocess.run(  # noqa: S603
            command, cwd=ROOT, env=env, capture_output=True, text=True, check=False
        )  # noqa: S603
        output = (result.stdout + result.stderr).replace(settings["password"], "[redacted]")
        path = target / f"{index + 1:02d}.log"
        path.write_text(output)
        results.append(
            {
                "command": command,
                "started_at": started,
                "completed_at": datetime.now(UTC).isoformat(),
                "exit_code": result.returncode,
                "log": str(path.relative_to(SESSION)),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
        (target / "checks.json").write_text(json.dumps(results, indent=2) + "\n")
        print(
            f"{index + 1}/{len(commands)} "
            + ("PASS " if result.returncode == 0 else "FAIL ")
            + " ".join(command),
            flush=True,
        )
        if result.returncode:
            raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
