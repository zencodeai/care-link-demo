"""Acknowledge an operator-applied barrier; never fabricates a dependency fault.

The browser establishes current protected success before publishing its nonce.
Only actual failed HTTP requests after the receipt can pass the live checks.
"""

import argparse
import json
import os
import stat
from pathlib import Path
from uuid import UUID

PHASES = ("identity-loss", "pdp-loss", "journal-loss", "audit-loss", "fenced")


def acknowledge(directory: Path, phase: str) -> None:
    info = directory.lstat()
    if (
        not directory.is_absolute()
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_mode & 0o077
    ):
        raise ValueError("Absolute private browser evidence directory required")
    path = directory / "barrier-ready.json"
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.geteuid():
        raise ValueError("Owner-only live barrier request required")
    value = json.loads(path.read_text())
    if (
        set(value) != {"session", "phase", "nonce"}
        or value["session"] != "imp03-002"
        or value["phase"] != phase
        or phase not in PHASES
        or str(UUID(value["nonce"])) != value["nonce"]
    ):
        raise ValueError("Wrong live barrier binding")
    receipt = directory / "barrier-applied.json"
    fd = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    print("Barrier acknowledged; actual live denials still determine the result.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase", choices=PHASES, required=True)
    args = parser.parse_args()
    acknowledge(args.output, args.phase)


if __name__ == "__main__":
    main()
