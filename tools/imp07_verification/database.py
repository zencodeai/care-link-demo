"""Create and remove only the owned IMP-07 disposable TLS PostgreSQL fixture."""

import argparse
import io
from contextlib import redirect_stdout
from pathlib import Path

from tools.imp05_verification import database as fixture


def configure() -> None:
    fixture.NAME = "care-link-imp07-001-postgres"
    fixture.DIRECTORY = Path("/private/tmp/care-link-imp07-001/database")
    fixture.PORT = 35437
    fixture.LABEL = "imp07-001-verification"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop"])
    args = parser.parse_args()
    configure()
    with redirect_stdout(io.StringIO()):
        {"start": fixture.start, "stop": fixture.stop}[args.action]()
    print(f"Owned IMP-07 TLS PostgreSQL fixture: {args.action} completed (loopback35437)")


if __name__ == "__main__":
    main()
