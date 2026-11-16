"""Explicit synthetic-demo operator commands; never selects an original target by default."""

import argparse
import json
import sys
import webbrowser
from pathlib import Path

from .errors import DemoError
from .models import record
from .secrets import VaultSecrets
from .storage import Registry
from .toolkit import DemoToolkit


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="python -m tools.demo")
    root.add_argument("--state-root", type=Path)
    root.add_argument(
        "--vault-key-file", type=Path, help="Explicit encrypted fallback; otherwise OS keychain"
    )
    groups = root.add_subparsers(dest="group", required=True)
    environment = groups.add_parser("environment").add_subparsers(dest="command", required=True)
    register = environment.add_parser("register")
    register.add_argument("--manifest", required=True, type=Path)
    for command in ("inspect", "doctor"):
        environment.add_parser(command).add_argument("--environment", required=True)
    doctor = groups.add_parser("doctor")
    doctor.add_argument("--environment", required=True)
    run = groups.add_parser("run").add_subparsers(dest="command", required=True)
    run.add_parser("list").add_argument("--environment", required=True)
    create = run.add_parser("create")
    create.add_argument("--environment", required=True)
    create.add_argument("--scenario", default="manual-service")
    create.add_argument("--run-id")
    for command in ("inspect", "resume", "close"):
        run.add_parser(command).add_argument("--run", required=True)
    opening = run.add_parser("open")
    opening.add_argument("--run", required=True)
    opening.add_argument("--actor", required=True)
    opening.add_argument("--print-only", action="store_true")
    actors = groups.add_parser("actors").add_subparsers(dest="command", required=True)
    actors.add_parser("list").add_argument("--run", required=True)
    credentials = groups.add_parser("credentials").add_subparsers(dest="command", required=True)
    for command in ("import", "reveal", "otp", "rotate"):
        actor = credentials.add_parser(command)
        actor.add_argument("--environment", required=True)
        actor.add_argument("--actor", required=True)
        if command == "import":
            actor.add_argument("--stdin", action="store_true", required=True)
        if command == "reveal":
            actor.add_argument("--reveal-password", action="store_true", required=True)
        if command == "otp":
            actor.add_argument(
                "--fresh", action="store_true", help="Wait for the next OTP window (at most31s)"
            )
        if command == "rotate":
            actor.add_argument("--operation-id", help="Resume the original pending rotation")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        registry = Registry(args.state_root)
        store = (
            VaultSecrets(registry.root / "vault", args.vault_key_file)
            if args.vault_key_file
            else None
        )
        toolkit = DemoToolkit(registry, secrets_store=store)
        if args.group == "environment":
            if args.command == "register":
                result = toolkit.register(record(json.loads(args.manifest.read_text())))
            elif args.command == "inspect":
                result = toolkit.environment(args.environment).value
            else:
                result = toolkit.doctor(args.environment)
        elif args.group == "doctor":
            result = toolkit.doctor(args.environment)
        elif args.group == "run":
            if args.command == "list":
                result = toolkit.list_runs(args.environment)
            elif args.command == "create":
                result = toolkit.create(
                    args.environment, scenario=args.scenario, run_id=args.run_id
                )
            elif args.command == "resume":
                result = toolkit.resume(args.run)
            elif args.command == "close":
                result = toolkit.close(args.run)
            elif args.command == "inspect":
                result = toolkit.inspect(args.run)
            else:
                run = toolkit.inspect(args.run)
                readiness = toolkit.doctor(str(run["environment_id"]))
                if readiness["ready"] is not True:
                    raise DemoError("environment_not_ready")
                url = toolkit.actor_url(args.run, args.actor)
                if not args.print_only and not webbrowser.open(url, new=2):
                    raise DemoError("browser_open_failed")
                result = {"url": url, "opened": not args.print_only}
        elif args.group == "actors":
            result = toolkit.actors(args.run)
        elif args.command == "import":
            raw = sys.stdin.read(8193)
            if len(raw) > 8192:
                raise DemoError("credential_input_too_large")
            result = toolkit.import_credential(args.environment, args.actor, raw)
        elif args.command == "reveal":
            print(toolkit.reveal_password(args.environment, args.actor))
            return 0
        elif args.command == "otp":
            result = toolkit.otp(args.environment, args.actor, fresh=args.fresh)
        else:
            result = toolkit.rotate(args.environment, args.actor, operation_id=args.operation_id)
        print(json.dumps(result, indent=2))
        return 2 if result.get("ready") is False else 0
    except DemoError as error:
        print(json.dumps({"error": error.code}), file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, TypeError):
        # Paths, provider responses and malformed secret inputs may include
        # sensitive text. Never render exception messages or traceback here.
        print(json.dumps({"error": "invalid_or_unavailable_input"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
