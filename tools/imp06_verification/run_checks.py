"""Run the full source lane with existing dedicated TLS PostgreSQL and pinned OPA."""

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from psycopg.conninfo import make_conninfo

from tools.check import COMMANDS, ROOT

SESSION = ROOT / "doc/IMP/slices/IMP-06-bounded-ai-assistance/sessions/001-implementation"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-config", type=Path, required=True)
    parser.add_argument("--opa", type=Path, required=True)
    parser.add_argument("--attempt", required=True)
    args = parser.parse_args()
    if not args.attempt.isalnum() or len(args.attempt) > 32:
        raise ValueError("Bounded named evidence attempt required")
    settings = json.loads(args.database_config.read_text())
    if (
        settings.get("host") != "localhost"
        or settings.get("hostaddr") != "127.0.0.1"
        or str(settings.get("port")) != "35436"
        or settings.get("dbname") != "postgres"
        or settings.get("sslmode") != "verify-full"
        or not settings.get("sslrootcert")
        or not args.opa.is_file()
    ):
        raise ValueError("Exact dedicated verified-TLS fixture and existing OPA required")
    env = {
        **os.environ,
        "CARE_LINK_MANUAL_TEST_DSN": make_conninfo(**settings),
        "CARE_LINK_OPA_BINARY": str(args.opa.resolve()),
        "UV_CACHE_DIR": "/private/tmp/care-link-imp05-uv-cache",
    }
    target = SESSION / "evidence/source" / args.attempt
    target.mkdir(parents=True, exist_ok=False)
    commands = [
        *[command + ["--tb=short"] if command[-1] == "pytest" else command for command in COMMANDS],
        ["pnpm", "exec", "tsc", "-p", "tests/e2e/assistance/tsconfig.json"],
        ["pnpm", "exec", "eslint", "tests/e2e/assistance", "--max-warnings", "0"],
        ["pnpm", "exec", "prettier", "--check", "tests/e2e/assistance"],
        [sys.executable, "-m", "tools.imp05_verification.validate_plan"],
    ]
    checks: list[dict[str, object]] = []
    for index, command in enumerate(commands):
        started = datetime.now(UTC)
        result = subprocess.run(  # noqa: S603
            command, cwd=ROOT, env=env, capture_output=True, text=True, check=False
        )
        logfile = target / f"{index + 1:02d}.log"
        output = (result.stdout + result.stderr).replace(str(settings["password"]), "[redacted]")
        logfile.write_text(output)
        checks.append(
            {
                "command": command,
                "started_at": started.isoformat(),
                "completed_at": datetime.now(UTC).isoformat(),
                "exit_code": result.returncode,
                "log": str(logfile.relative_to(SESSION)),
            }
        )
        (target / "checks.json").write_text(json.dumps(checks, indent=2) + "\n")
        label = "PASS" if result.returncode == 0 else "FAIL"
        print(
            f"{index + 1}/{len(commands)} {label} " + " ".join(command),
            flush=True,
        )
        if result.returncode:
            raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
