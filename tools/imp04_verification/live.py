"""Run native IMP-04 browser qualification; raw diagnostics stay owner-only."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import cast

from tools.imp04_deployment.config import PRIVATE, record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        choices=[
            "all",
            "normal",
            "normal-continue",
            "reload-only",
            "report-ui",
            "pending-ui",
            "manual-regression",
            "directory",
            "accessibility",
            "signin",
            "lifecycle",
            "race",
            "dependency",
            "absent-race",
            "delegation",
            "delegation-expired",
            "authority-loss",
        ],
        required=True,
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--config", type=Path, default=PRIVATE / "browser.json")
    args = parser.parse_args()
    if args.output.parent != PRIVATE or args.output.is_symlink():
        raise ValueError("Exact new-target private evidence parent required")
    args.output.mkdir(mode=0o700, exist_ok=False)
    os.umask(0o077)
    if args.config.parent != PRIVATE or args.config.is_symlink():
        raise ValueError("Exact new-target private browser configuration required")
    if args.config != PRIVATE / "browser.json" and args.phase != "authority-loss":
        raise ValueError("Isolated case browser configuration is exclusive to authority-loss")
    config = json.loads(args.config.read_text())
    secret_values: list[str] = []
    for actor in record(config["actors"]).values():
        for field in ("password", "totpSecret"):
            value = record(actor).get(field)
            if isinstance(value, str):
                secret_values.append(value)
    environment = {
        **os.environ,
        "CARE_LINK_IMP04_E2E_CONFIG": str(args.config),
        "CARE_LINK_IMP04_E2E_OUTPUT": str(args.output),
        "CARE_LINK_IMP04_E2E_PHASE": args.phase,
        "NODE_EXTRA_CA_CERTS": str(PRIVATE / "tls/ca.crt"),
    }
    if args.state:
        if args.state.parent != PRIVATE or args.state.is_symlink():
            raise ValueError("Exact new-target prior evidence directory required")
        environment["CARE_LINK_IMP04_E2E_STATE"] = str(args.state)
    if args.resume:
        environment["CARE_LINK_IMP04_E2E_RESUME"] = "1"
    log = args.output / "runner.log"
    fd = os.open(log, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as stream:
        result = subprocess.run(  # noqa: S603 - fixed harness argv, no credentials in argv
            [
                shutil.which("pnpm") or "pnpm",
                "exec",
                "playwright",
                "test",
                "--config",
                "tests/e2e/imp04-live/playwright.config.ts",
            ],  # noqa: S607
            env=environment,
            stdout=stream,
            stderr=subprocess.STDOUT,
            check=False,
        )
    summary: dict[str, object] = {
        "phase": args.phase,
        "exit_code": result.returncode,
        "private_output": str(args.output),
    }
    observed = args.output / "observations.json"
    if observed.exists():
        value = record(json.loads(observed.read_text()))
        summary["status"], summary["not_run"] = value["status"], value["not_run"]
        summary["observations"] = value["observations"]
    report = args.output / "playwright-results.json"
    if report.exists():
        value = record(json.loads(report.read_text()))
        messages: list[str] = []

        def visit(node: object) -> None:
            if isinstance(node, dict):
                row = cast(dict[str, object], node)
                error = row.get("error")
                if isinstance(error, dict):
                    message = str(cast(dict[str, object], error).get("message", "")).split("\n")[0]
                    for secret in secret_values:
                        message = message.replace(secret, "[REDACTED]")
                    messages.append(message[:350])
                for item in row.values():
                    visit(item)
            elif isinstance(node, list):
                for item in cast(list[object], node):
                    visit(item)

        visit(value)
        summary["error_first_lines"] = list(dict.fromkeys(messages))
    (args.output / "sanitized-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    compact = {k: v for k, v in summary.items() if k not in {"observations", "not_run"}}
    observed_rows = cast(list[dict[str, object]], summary.get("observations", []))
    compact["actor_checks"] = sum(row.get("case") == "Q02" for row in observed_rows)
    compact["cases"] = [
        row for row in observed_rows if row.get("case") not in {"Q02", "Q01-browser"}
    ]
    print(json.dumps(compact, indent=2))
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
