"""Smoke-test only the named core image; remove only the container created here."""

import argparse
import json
import shutil
import subprocess
from uuid import uuid4

PROBE = r"""
import importlib.metadata
import json
import os
import pathlib
import time
import urllib.error
import urllib.request

from care_link_contracts import parse_contract

assert os.getuid() == 65532, "Expected nonroot image user"
installed = {d.metadata["Name"].lower() for d in importlib.metadata.distributions()}
assert {"care-link-core", "care-link-contracts", "uvicorn", "fastapi", "cryptography"} <= installed
assert not installed & {"pytest", "ruff", "hatchling", "types-jsonschema",
                        "care-link-identity", "care-link-help", "care-link-static",
                        "care-link-workload-trust",
                        "care-link-data", "care-link-policy-input", "care-link-recovery-control",
                        "psycopg", "psycopg-binary", "pyjwt"}
try:
    pathlib.Path("/app/forbidden-write").write_text("unexpected")
except OSError:
    pass
else:
    raise AssertionError("Container filesystem was writable")

url = "http://127.0.0.1:8011"
for attempt in range(50):
    try:
        with urllib.request.urlopen(url + "/dev/health", timeout=0.2) as response:
            capability = parse_contract("DeveloperCapability", response.read().decode())
        break
    except (urllib.error.URLError, TimeoutError):
        time.sleep(0.1)
else:
    raise AssertionError("Developer API did not become ready")

verdicts = []
def expect(path, raw, expected, code=None):
    request = urllib.request.Request(
        url + path,
        data=raw.encode() if raw is not None else None,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            status, body = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, body = error.code, error.read()
    assert status == expected, (path, status, expected)
    if code:
        parsed = parse_contract("Error", body.decode())
        assert parsed["code"] == code
    elif status == 204:
        assert body == b""
    verdicts.append({"path": path, "status": status})

expect("/dev/contracts/RevisionCommand", '{"expected_revision":"1"}', 204)
expect("/dev/contracts/RevisionCommand",
       '{"expected_revision":"9223372036854775808"}', 422, "INVALID_REQUEST")
expect("/dev/contracts/RevisionCommand",
       '{"expected_revision":"1","expected_revision":"2"}', 400, "INVALID_REQUEST")
session = {
    "tags": {"environment": "demo", "population": "synthetic"},
    "participant_kind": "pid", "jurisdiction": None, "locale": "en-CA",
    "channel": "web", "persona_id": None, "fixture_id": None,
}
expect("/dev/contracts/SessionCreate", json.dumps(session), 204)
session["tags"]["extra"] = True
expect("/dev/contracts/SessionCreate", json.dumps(session), 422, "INVALID_REQUEST")
expect("/v1/sessions", None, 503, "CAPABILITY_DISABLED")
expect("/v1/sessions", "{}", 503, "CAPABILITY_DISABLED")
print(json.dumps({"uid": os.getuid(), "capability": capability,
                  "installed_distributions": sorted(installed), "checks": verdicts}, indent=2))
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="care-link-core:imp-01")
    args = parser.parse_args()
    docker = shutil.which("docker")
    if docker is None:
        raise SystemExit("Docker CLI unavailable")
    identifier = ""
    try:
        started = subprocess.run(  # noqa: S603
            [
                docker,
                "create",
                "--pull=never",
                "--name",
                f"care-link-imp01-{uuid4().hex[:12]}",
                "--label",
                "care-link.slice=IMP-01",
                "--network",
                "none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--pids-limit=64",
                "--memory=256m",
                "--cpus=1",
                args.image,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        identifier = started.stdout.strip()
        subprocess.run([docker, "start", identifier], check=True)  # noqa: S603
        inspected = subprocess.run(  # noqa: S603
            [docker, "inspect", identifier],
            check=True,
            capture_output=True,
            text=True,
        )
        container = json.loads(inspected.stdout)[0]
        host = container["HostConfig"]
        if not (
            host["ReadonlyRootfs"]
            and host["NetworkMode"] == "none"
            and "ALL" in host["CapDrop"]
            and "no-new-privileges" in host["SecurityOpt"]
            and not container["Mounts"]
            and not host["PortBindings"]
        ):
            raise SystemExit("Restricted smoke container settings did not match")
        print(
            json.dumps(
                {
                    "image_id": container["Image"],
                    "read_only": True,
                    "network": "none",
                    "ports": [],
                    "mounts": [],
                    "capabilities_dropped": host["CapDrop"],
                    "security_options": host["SecurityOpt"],
                }
            ),
            flush=True,
        )
        subprocess.run([docker, "exec", identifier, "python", "-c", PROBE], check=True)  # noqa: S603
    except subprocess.CalledProcessError:
        if identifier:
            subprocess.run([docker, "logs", identifier], check=False)  # noqa: S603
        raise
    finally:
        if identifier:
            subprocess.run([docker, "rm", "--force", identifier], check=True)  # noqa: S603


if __name__ == "__main__":
    main()
