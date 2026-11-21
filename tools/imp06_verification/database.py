"""Own a dedicated synthetic TLS PostgreSQL fixture; never adopt live resources."""

import argparse
import io
from contextlib import redirect_stdout
from pathlib import Path

from tools.imp05_verification import database as fixture


def configure() -> None:
    fixture.NAME = "care-link-imp06-001-postgres"
    fixture.DIRECTORY = Path("/private/tmp/care-link-imp06-001/database")
    fixture.PORT = 35436
    fixture.LABEL = "imp06-001-verification"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop"])
    args = parser.parse_args()
    configure()
    with redirect_stdout(io.StringIO()):
        {"start": fixture.start, "stop": fixture.stop}[args.action]()
    print(f"Owned IMP-06 TLS PostgreSQL fixture: {args.action} completed (loopback35436)")


if __name__ == "__main__":
    main()
