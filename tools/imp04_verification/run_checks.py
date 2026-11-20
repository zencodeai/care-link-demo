"""Run source checks against an existing dedicated IMP-04 TLS fixture; acquire nothing."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from psycopg.conninfo import make_conninfo

ROOT = Path(__file__).resolve().parents[2]
SESSION = ROOT / "doc/IMP/slices/IMP-04-plans-consent-directory/sessions/001-implementation"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-config", type=Path, required=True)
    parser.add_argument("--opa", type=Path, required=True)
    args = parser.parse_args()
    settings = json.loads(args.database_config.read_text())
    if (
        settings.get("host") != "localhost"
        or settings.get("hostaddr") != "127.0.0.1"
        or str(settings.get("port")) != "25434"
        or settings.get("dbname") != "postgres"
        or settings.get("sslmode") != "verify-full"
        or not settings.get("sslrootcert")
        or not args.opa.is_file()
    ):
        raise ValueError("Exact dedicated TLS fixture and existing OPA binary required")
    env = {
        **os.environ,
        "CARE_LINK_MANUAL_TEST_DSN": make_conninfo(**settings),
        "CARE_LINK_OPA_BINARY": str(args.opa.resolve()),
        "UV_CACHE_DIR": "/private/tmp/care-link-imp04-uv-cache",
    }
    commands = [
        ("uv-lock", ["uv", "lock", "--check"]),
        (
            "pnpm-lock",
            [
                "pnpm",
                "install",
                "--offline",
                "--frozen-lockfile",
                "--lockfile-only",
                "--ignore-scripts",
            ],
        ),
        ("contracts", [sys.executable, "tools/generate_contracts.py", "--check"]),
        ("boundaries", [sys.executable, "tools/check_boundaries.py"]),
        ("admission", [sys.executable, "tools/check_imp02_admission.py"]),
        ("ruff", [sys.executable, "-m", "ruff", "check", "."]),
        ("python-format", [sys.executable, "-m", "ruff", "format", "--check", "."]),
        ("pyright", ["pnpm", "exec", "pyright", "--project", "pyrightconfig.json"]),
        ("typescript", ["pnpm", "typecheck"]),
        ("eslint", ["pnpm", "lint"]),
        ("prettier", ["pnpm", "format:check"]),
        ("python-tests", [sys.executable, "-m", "pytest", "-q", "--tb=short"]),
        ("web-tests", ["pnpm", "test"]),
        ("web-build", ["pnpm", "build"]),
    ]
    evidence = SESSION / "evidence"
    evidence.mkdir(exist_ok=True)
    checks: list[dict[str, object]] = []
    for name, command in commands:
        result = subprocess.run(  # noqa: S603
            command, cwd=ROOT, env=env, capture_output=True, text=True, check=False
        )
        log = result.stdout + result.stderr
        (evidence / (name + ".log")).write_text(log)
        checks.append(
            {
                "name": name,
                "command": command,
                "exit_code": result.returncode,
                "evidence": "evidence/" + name + ".log",
            }
        )
        (SESSION / "checks.json").write_text(json.dumps(checks, indent=2) + "\n")
        print(name + ": " + ("passed" if result.returncode == 0 else "FAILED"), flush=True)
        if result.returncode:
            raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
