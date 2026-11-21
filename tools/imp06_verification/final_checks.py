"""Bind final affected checks to immutable source hashes; no model activation."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from psycopg.conninfo import make_conninfo

ROOT = Path(__file__).resolve().parents[2]
SESSION = ROOT / "doc/IMP/slices/IMP-06-bounded-ai-assistance/sessions/001-implementation"


def source_hashes() -> dict[str, str]:
    git = shutil.which("git")
    if git is None:
        raise ValueError("Git source inventory unavailable")
    result = subprocess.run(  # noqa: S603
        [git, "ls-files", "-co", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    paths = {name.decode() for name in result.stdout.split(b"\0") if name}
    return {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in sorted(paths)
        if not name.startswith(("doc/", ".codex/", ".agents/")) and (ROOT / name).is_file()
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-config", type=Path, required=True)
    parser.add_argument("--attempt", required=True)
    args = parser.parse_args()
    if not args.attempt.isalnum():
        raise ValueError("Bounded evidence attempt required")
    settings = json.loads(args.database_config.read_text())
    if (
        settings.get("host") != "localhost"
        or settings.get("hostaddr") != "127.0.0.1"
        or str(settings.get("port")) != "35436"
        or settings.get("dbname") != "postgres"
        or settings.get("sslmode") != "verify-full"
    ):
        raise ValueError("Exact dedicated TLS fixture required")
    target = SESSION / "evidence/final" / args.attempt
    target.mkdir(parents=True, exist_ok=False)
    before = source_hashes()
    (target / "source-before.json").write_text(json.dumps(before, indent=2) + "\n")
    env = {
        **os.environ,
        "CARE_LINK_MANUAL_TEST_DSN": make_conninfo(**settings),
        "CARE_LINK_OPA_BINARY": "/private/tmp/care-link-imp03-tools/opa",
        "UV_CACHE_DIR": "/private/tmp/care-link-imp05-uv-cache",
    }
    commands = [
        ["uv", "lock", "--check"],
        [sys.executable, "tools/generate_contracts.py", "--check"],
        [sys.executable, "tools/check_boundaries.py"],
        [".venv/bin/ruff", "check", "."],
        [".venv/bin/ruff", "format", "--check", "."],
        ["pnpm", "exec", "pyright", "--project", "pyrightconfig.json"],
        [
            sys.executable,
            "-m",
            "pytest",
            "services/runtime/tests",
            "services/inference/tests",
            "host/inference-bridge/tests",
            "packages/workload-trust/tests",
            "services/data/tests/test_assistance.py",
            "services/data/tests/test_assistance_jobs.py",
            "services/data/tests/test_core_assistance_chain.py",
            "tests/unit/test_imp06_composition.py",
            "packages/policy-input/tests/test_assistance_policy.py",
            "tests/evaluation",
            "-q",
            "--tb=short",
        ],
        ["pnpm", "test"],
        ["pnpm", "typecheck"],
        ["pnpm", "build"],
        [sys.executable, "-m", "tools.imp05_verification.validate_plan"],
    ]
    checks: list[dict[str, object]] = []
    for index, command in enumerate(commands):
        started = datetime.now(UTC)
        result = subprocess.run(  # noqa: S603
            command,
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        log = target / f"{index + 1:02d}.log"
        log.write_text((result.stdout + result.stderr).replace(settings["password"], "[redacted]"))
        checks.append(
            {
                "command": command,
                "started_at": started.isoformat(),
                "completed_at": datetime.now(UTC).isoformat(),
                "exit_code": result.returncode,
                "log": str(log.relative_to(SESSION)),
            }
        )
        (target / "checks.json").write_text(json.dumps(checks, indent=2) + "\n")
        print(
            f"{index + 1}/{len(commands)} {'PASS' if result.returncode == 0 else 'FAIL'} "
            + " ".join(command),
            flush=True,
        )
        if result.returncode:
            raise SystemExit(result.returncode)
    after = source_hashes()
    (target / "source-after.json").write_text(json.dumps(after, indent=2) + "\n")
    if before != after:
        raise ValueError("Candidate source changed during final checks")
    print("Final source binding unchanged across all checks", flush=True)


if __name__ == "__main__":
    main()
