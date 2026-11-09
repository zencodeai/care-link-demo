"""Narrow command runner with a private kubeconfig and fixed named cluster."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

from .model import CLUSTER, SESSION, LabInputs


def verify_file(path: Path, expected: str) -> None:
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError("lab acquisition mismatch: " + path.name)


def run(command: list[str], *, stdin: str | None = None, timeout: int = 300) -> str:
    result = subprocess.run(  # noqa: S603
        command, input=stdin, text=True, capture_output=True, timeout=timeout, check=False
    )
    if result.returncode:
        # Commands never contain generated passwords; manifests go through stdin
        # or private paths. Avoid echoing arbitrary server output into reports.
        raise RuntimeError(
            "lab command failed: "
            + " ".join(command[:4])
            + " (exit "
            + str(result.returncode)
            + ")"
        )
    return result.stdout


def kubectl(inputs: LabInputs, *args: str, stdin: str | None = None) -> str:
    return run(
        [
            "kubectl",
            "--kubeconfig",
            str(inputs.state_dir / "kubeconfig"),
            "--context",
            "kind-" + CLUSTER,
            *args,
        ],
        stdin=stdin,
    )


def private_json(path: Path, value: object) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def verify_session(inputs: LabInputs) -> None:
    state = json.loads((inputs.state_dir / "lease.json").read_text())
    if state != {"session": SESSION, "cluster": CLUSTER}:
        raise ValueError("wrong disposable lab resource binding")
    result = json.loads(run(["docker", "inspect", CLUSTER + "-control-plane"]))
    labels = result[0]["Config"]["Labels"]
    if labels.get("io.x-k8s.kind.cluster") != CLUSTER:
        raise ValueError("Docker target is not this named kind cluster")
