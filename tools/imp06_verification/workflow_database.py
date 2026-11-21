"""Own only the IMP06 agentic follow-through synthetic TLS database fixture."""

import argparse
import io
from contextlib import redirect_stdout
from pathlib import Path

from tools.imp05_verification import database as fixture


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop"])
    action = parser.parse_args().action
    fixture.NAME = "care-link-imp06-003-postgres"
    fixture.DIRECTORY = Path("/private/tmp/care-link-imp06-003/database")
    fixture.PORT = 35438
    fixture.LABEL = "imp06-003-verification"
    with redirect_stdout(io.StringIO()):
        {"start": fixture.start, "stop": fixture.stop}[action]()
    print(f"Owned IMP06 workflow TLS fixture {action} completed")


if __name__ == "__main__":
    main()
