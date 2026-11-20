"""No implicit target, environment, lifetime, provider action or browser launch."""

import argparse
import json
from pathlib import Path

from .operator import request


def main() -> None:
    parser = argparse.ArgumentParser(description="Explicit synthetic plans review lifecycle")
    parser.add_argument("--config", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start-fresh")
    start.add_argument("--lifetime-seconds", type=int, required=True)
    start.add_argument("--run-id", required=True, help="New UUID, retained as the retry token")
    commands.add_parser("inspect")
    commands.add_parser("close")
    args = parser.parse_args()
    print(
        json.dumps(
            request(
                args.config,
                args.command,
                lifetime_seconds=getattr(args, "lifetime_seconds", None),
                run_id=getattr(args, "run_id", None),
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
