"""Run the foundation fast lane. Requires prior locked project setup; acquires nothing."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = [
    ["uv", "lock", "--check"],
    ["pnpm", "install", "--offline", "--frozen-lockfile", "--lockfile-only", "--ignore-scripts"],
    ["uv", "run", "--locked", "python", "tools/generate_contracts.py", "--check"],
    ["uv", "run", "--locked", "python", "tools/check_boundaries.py"],
    ["uv", "run", "--locked", "python", "tools/check_imp02_admission.py"],
    ["uv", "run", "--locked", "ruff", "check", "."],
    ["uv", "run", "--locked", "ruff", "format", "--check", "."],
    ["pnpm", "exec", "pyright", "--project", "pyrightconfig.json"],
    ["pnpm", "typecheck"],
    ["pnpm", "lint"],
    ["pnpm", "format:check"],
    ["uv", "run", "--locked", "pytest"],
    ["pnpm", "exec", "tsc", "-p", "tests/e2e/imp02/tsconfig.json"],
    ["pnpm", "exec", "eslint", "tests/e2e/imp02", "--max-warnings", "0"],
    ["pnpm", "exec", "prettier", "--check", "tests/e2e/imp02"],
    ["pnpm", "test"],
    ["pnpm", "build"],
]


def main() -> None:
    for command in COMMANDS:
        print("+ " + " ".join(command), flush=True)
        result = subprocess.run(command, cwd=ROOT, check=False)  # noqa: S603
        if result.returncode:
            sys.exit(result.returncode)


if __name__ == "__main__":
    main()
