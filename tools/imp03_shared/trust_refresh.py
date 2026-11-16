"""Refresh only continuation authorizers from the existing SPIRE authority."""

import argparse
import hashlib
import json
import os
import time
from datetime import UTC, datetime
from typing import cast

from cryptography import x509

from . import docker
from .continuation import require_profile
from .deployment import name
from .infrastructure import command, private_write, verify_cluster
from .model import AUTH_UID, NODE, PRIVATE, ROOT, Record


def refresh() -> Record:
    require_profile()
    verify_cluster()
    # The old temporary workstation kubeconfig may no longer exist. The exact
    # verified kind node already owns its existing authenticated local client.
    bundle = command(
        [
            "docker",
            "exec",
            NODE,
            "kubectl",
            "--kubeconfig",
            "/etc/kubernetes/admin.conf",
            "-n",
            "care-link-imp02-002-trust",
            "exec",
            "deployment/spire-server",
            "--",
            "/opt/spire/bin/spire-server",
            "bundle",
            "show",
            "-socketPath",
            "/run/spire/data/api.sock",
            "-format",
            "pem",
        ]
    )
    roots = x509.load_pem_x509_certificates(bundle.encode())
    now = datetime.now(UTC)
    if not roots or not any(
        root.not_valid_before_utc <= now < root.not_valid_after_utc for root in roots
    ):
        raise ValueError("Current roots from the existing SPIRE authority required")
    result: Record = {
        "recorded_at": now.isoformat(),
        "source": "Existing SPIRE server via exact verified kind node; public bundle only",
        "bundle_sha256": hashlib.sha256(bundle.encode()).hexdigest(),
        "roles": [],
        "issuer_policy_changed": False,
        "fences_changed": False,
    }
    roles: list[Record] = []
    for role, uid in AUTH_UID.items():
        target = name(role + "-authorization")
        metadata = docker.inspect_container(target)
        if cast(Record, metadata["Config"])["User"] != f"{uid}:{uid}":
            raise ValueError("Exact authorization custodian required")
        path = ROOT + "/" + role + "/authorization/bundle.pem"
        old = docker.exec(
            target,
            [
                "python",
                "-c",
                "from pathlib import Path;print(Path('" + path + "').read_text(),end='')",
            ],
        )
        changed = old != bundle
        if changed:
            backup = PRIVATE / (
                "trust-bundle-" + role + "-" + hashlib.sha256(old.encode()).hexdigest() + ".pem"
            )
            if not backup.exists():
                private_write(backup, old)
            script = (
                "import os,sys;from pathlib import Path;"
                f"p=Path('{path}');s=p.lstat();"
                f"assert s.st_uid=={uid} and s.st_mode&0o777==0o600 and not p.is_symlink();"
                "t=p.with_name('bundle.refresh.tmp');"
                "f=os.open(t,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);"
                "o=os.fdopen(f,'wb');o.write(sys.stdin.buffer.read());o.flush();os.fsync(o.fileno());o.close();"
                "os.replace(t,p);d=os.open(p.parent,os.O_RDONLY|os.O_DIRECTORY);os.fsync(d);os.close(d)"
            )
            docker.exec(target, ["python", "-c", script], stdin=bundle)
            docker.stop(target)
            docker.start(target)
        roles.append(
            {"role": role, "container_id": metadata["Id"], "changed_and_restarted": changed}
        )
    result["roles"] = roles
    return result


def watch(seconds: int, interval: int) -> None:
    """Bounded operator maintenance for the current synthetic review only."""
    if not 1 <= seconds <= 14400 or not 5 <= interval <= 60:
        raise ValueError("Review maintenance must be bounded to four hours")
    require_profile()
    os.umask(0o077)
    started = time.monotonic()
    receipt = PRIVATE / "trust-watch-receipt.json"
    private_write(
        receipt,
        json.dumps(
            {
                "pid": os.getpid(),
                "started_at": datetime.now(UTC).isoformat(),
                "duration_seconds": seconds,
                "interval_seconds": interval,
                "scope": (
                    "Continuation public bundles only; "
                    "no new issuer policy, credentials or fence authority"
                ),
            }
        ),
    )
    log = PRIVATE / "trust-watch.jsonl"
    with log.open("x") as stream:
        while time.monotonic() - started < seconds:
            try:
                result = refresh()
                result["status"] = "checked"
            except Exception as error:
                # Never weaken verification on failure or expose raw command
                # output/credentials in a background diagnostic.
                result = {
                    "recorded_at": datetime.now(UTC).isoformat(),
                    "status": "refresh_unavailable",
                    "error_class": type(error).__name__,
                }
            stream.write(json.dumps(result) + "\n")
            stream.flush()
            if result["status"] == "checked":
                print("Continuation public trust bundles checked", flush=True)
            remaining = seconds - (time.monotonic() - started)
            if remaining > 0:
                time.sleep(min(interval, remaining))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch-seconds", type=int)
    parser.add_argument("--interval-seconds", type=int, default=30)
    args = parser.parse_args()
    if args.watch_seconds is None:
        print(json.dumps(refresh(), indent=2))
    else:
        watch(args.watch_seconds, args.interval_seconds)
