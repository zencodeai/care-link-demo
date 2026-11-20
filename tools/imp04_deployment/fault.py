"""Expiring Docker-freezer faults for exact receipt-bound IMP-04 dependencies."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

from . import docker
from .config import PREFIX, REPO, record

WATCHDOG = """
import sys,time
from tools.imp04_deployment import docker
name,expected=sys.argv[1:]
time.sleep(20)
try:
 current=docker.inspect_container(name)
 if current['Id']==expected:docker.resume_dependency(name)
except (RuntimeError,ValueError):pass
"""


def change(role: str, action: str) -> dict[str, object]:
    if role not in {"identity", "pdp", "journal"} or action not in {"pause", "resume"}:
        raise ValueError("Exact new-target dependency barrier required")
    name = PREFIX + "-" + role + "-app"
    current = docker.inspect_container(name)
    state = record(current["State"])
    if not state.get("Running"):
        raise ValueError("Running exact new dependency required")
    if action == "pause":
        # Separate host process survives the frozen dependency and controller.
        # A replacement cannot redirect recovery to another container identity.
        subprocess.Popen(  # noqa: S603 - fixed interpreter/script and verified IDs
            [sys.executable, "-c", WATCHDOG, name, str(current["Id"])],
            cwd=REPO,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        docker.pause_dependency(name)
    else:
        docker.resume_dependency(name)
    after = docker.inspect_container(name)
    if after["Id"] != current["Id"] or record(after["State"])["Paused"] != (action == "pause"):
        raise ValueError("Dependency freezer transition not observed")
    return {
        "target": PREFIX,
        "role": role,
        "action": action,
        "container_id": current["Id"],
        "container_identity_verified": True,
        "paused_observed": action == "pause",
        "maximum_pause_seconds": 20,
        "mechanism": "Docker cgroup freezer; independent host recovery watchdog",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=["identity", "pdp", "journal"], required=True)
    parser.add_argument("--action", choices=["pause", "resume"], required=True)
    args = parser.parse_args()
    print(json.dumps(change(args.role, args.action)))


if __name__ == "__main__":
    main()
