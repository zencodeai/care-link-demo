"""Pinned genuine Chrome for Testing in the existing isolated lab trust home."""

import argparse
import hashlib
import json
import secrets
import shutil
import subprocess
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import cast

from tools.demo.storage import private_write

from .continuation import require_profile
from .model import PRIVATE

ROOT = Path(__file__).resolve().parents[2]
Record = dict[str, object]
NAME = "care-link-imp03-003-cont1-review-chrome"
TRUSTED = "care-link-imp03-003-cont1-browser-ingress"
IMAGE = "care-link-imp03:review-chrome-005"


def command(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=False, timeout=240)  # noqa: S603
    if result.returncode:
        raise RuntimeError("Scoped Chrome command failed: " + args[0])
    return result.stdout.strip()


def inspect(name: str) -> Record:
    value = json.loads(command(["docker", "inspect", name]))
    if len(value) != 1:
        raise ValueError("Exact browser resource required")
    return cast(Record, value[0])


def start(*, replace: bool = False) -> Record:
    require_profile()
    output = PRIVATE / "review-recovery-005"
    output.mkdir(mode=0o700, exist_ok=True)
    capability = output / "chrome-server.json"
    original = inspect(TRUSTED)
    config = cast(Record, original["Config"])
    host = cast(Record, original["HostConfig"])
    if config["User"] != "1000:1000":
        raise ValueError("Expected existing isolated browser trust custodian")
    current = command(
        ["docker", "ps", "-a", "--filter", "name=^/" + NAME + "$", "--format", "{{.ID}}"]
    )
    if current:
        observed = inspect(NAME)
        labels = cast(Record, cast(Record, observed["Config"])["Labels"])
        if labels.get("care-link.owner") != "IMP-03-005":
            raise ValueError("Unowned browser refused")
        if not replace:
            receipt = json.loads(capability.read_text())
            if receipt["container_id"] != observed["Id"]:
                raise ValueError("Browser receipt mismatch")
            return {"container_id": observed["Id"], "retained": True}
        command(["docker", "stop", "--time", "10", cast(str, observed["Id"])])
        command(["docker", "rm", cast(str, observed["Id"])])
    build = output / "chrome-build"
    build.mkdir(mode=0o700, exist_ok=True)
    pin = json.loads((ROOT / "deploy/images/imp03-browser/chrome-inputs.json").read_text())
    archive = build / "chrome.zip"
    if not archive.exists():
        urllib.request.urlretrieve(pin["url"], archive)  # noqa: S310 - exact pinned official HTTPS input
    if hashlib.sha256(archive.read_bytes()).hexdigest() != pin["sha256"]:
        raise ValueError("Chrome for Testing digest mismatch")
    with zipfile.ZipFile(archive) as bundle:
        for item in bundle.infolist():
            destination = (build / item.filename).resolve()
            if not destination.is_relative_to(build.resolve()):
                raise ValueError("Unsafe Chrome archive member")
            bundle.extract(item, build)
            mode = item.external_attr >> 16
            if mode:
                destination.chmod(mode)
    command(
        ["docker", "tag", cast(str, original["Image"]), "care-link-imp03:review-browser-base-005"]
    )
    (build / "Dockerfile").write_text(
        "FROM care-link-imp03:review-browser-base-005\nUSER root\n"
        "COPY chrome-linux-arm64 /opt/chrome-for-testing\n"
        "COPY review-server.cjs /opt/review-server.cjs\n"
        "RUN chmod -R a+rX /opt/chrome-for-testing\n"
        'USER 1000:1000\nCMD ["node","/opt/review-server.cjs"]\n'
    )
    (build / ".dockerignore").write_text("chrome.zip\nreceipt.json\nbuild.log\n")
    shutil.copy2(
        ROOT / "deploy/images/imp03-browser/review-server.cjs", build / "review-server.cjs"
    )
    command(["docker", "build", "-t", IMAGE, str(build)])
    token = secrets.token_hex(24)
    identity = command(
        [
            "docker",
            "run",
            "-d",
            "--name",
            NAME,
            "--label",
            "care-link.scope=imp03-003-option-b",
            "--label",
            "care-link.owner=IMP-03-005",
            "--publish",
            "127.0.0.1:29901:29900",
            "--network",
            cast(str, host["NetworkMode"]),
            "--user",
            "1000:1000",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=1g",  # noqa: S108 - isolated browser tmpfs
            "--shm-size",
            "512m",
            "--env",
            "CARE_LINK_REVIEW_WS_PATH=" + token,
            "--mount",
            "type=volume,source=care-link-imp03-003-cont1-browser-home,destination=/run/browser-home",
            IMAGE,
        ]
    )
    for _ in range(100):
        if "Listening on" in command(["docker", "logs", identity]):
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("Chrome broker readiness failed")
    private_write(
        capability,
        json.dumps(
            {"container_id": identity, "endpoint": "ws://127.0.0.1:29901/" + token}
        ).encode(),
    )
    version = command(["docker", "exec", identity, "/opt/chrome-for-testing/chrome", "--version"])
    if version != "Google Chrome for Testing " + pin["version"]:
        raise ValueError("Unexpected actual Chrome product/version")
    return {"container_id": identity, "version": version, "tls_validation": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    print(json.dumps(start(replace=args.replace)))


if __name__ == "__main__":
    main()
