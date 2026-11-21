"""Dedicated IMP-09 disposable TLS database; never adopts the demo database."""

import argparse
import io
from contextlib import redirect_stdout
from pathlib import Path

from tools.imp05_verification import database as fixture


def configure() -> None:
    fixture.NAME = "care-link-imp09-001-postgres"
    fixture.DIRECTORY = Path("/private/tmp/care-link-imp09-001/database")
    fixture.PORT = 35439
    fixture.LABEL = "imp09-001-verification"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop"])
    args = parser.parse_args()
    configure()
    with redirect_stdout(io.StringIO()):
        {"start": fixture.start, "stop": fixture.stop}[args.action]()
    print(f"Owned IMP-09 TLS PostgreSQL fixture: {args.action} completed (loopback35439)")


if __name__ == "__main__":
    main()
