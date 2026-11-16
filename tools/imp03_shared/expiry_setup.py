"""Create only fresh disposable attestation probes, never alter serving entries."""

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import cast

from . import docker
from .continuation import require_profile
from .continuation_evidence import EVIDENCE
from .deployment import create, name, wait_socket
from .infrastructure import private_write, spire
from .model import MESH_NETWORK, PRIVATE, mount


def probe(container: str, command: list[str], tag: str) -> dict[str, object]:
    metadata = docker.inspect_container(name(container))
    source = Path(__file__).with_name("negative.py").read_text()
    result = subprocess.run(  # noqa: S603 - exact owned inspected container and source
        [  # noqa: S607 - existing Docker CLI
            "docker",
            "exec",
            "--interactive",
            str(metadata["Id"]),
            "/usr/bin/env",
            "CARE_LINK_IMP03_PROFILE=continuation-001",
            "python",
            "-",
            *command,
            "--report-only",
        ],
        input=source,
        text=True,
        capture_output=True,
        timeout=110,
    )
    private_write(PRIVATE / (tag + ".log"), result.stdout + result.stderr)
    if result.returncode or not result.stdout.strip():
        raise RuntimeError("Scoped negative probe failed; diagnostics retained privately: " + tag)
    value = json.loads(result.stdout)
    value["probe_source_sha256"] = hashlib.sha256(source.encode()).hexdigest()
    private_write(EVIDENCE / (tag + ".json"), json.dumps(value, indent=2))
    return value


def run() -> dict[str, object]:
    require_profile()
    alias = "spiffe://care-link.demo/host/imp03-003-cont1-expiry"
    if alias in spire("entry", "show", "-socketPath", "/run/spire/data/api.sock"):
        raise ValueError("Existing expiry alias refused")
    for suffix in ("negative-tools", "expiry-agent", "expiry-svid"):
        docker.create_volume(name(suffix))
    create(
        "negative-seed",
        ["python", "-c", "import time;time.sleep(7200)"],
        [mount("negative-tools", "/probe-tools"), mount("expiry-agent", "/expiry-config")],
        uid=0,
        cap_add=["CHOWN", "DAC_OVERRIDE"],
        tmpfs=["/operator:rw,noexec,nosuid,size=128m,mode=0700"],
    )
    docker.start(name("negative-seed"))
    directory = PRIVATE / "expiry-agent"
    directory.mkdir(mode=0o700)
    token = json.loads(
        spire(
            "token",
            "generate",
            "-socketPath",
            "/run/spire/data/api.sock",
            "-spiffeID",
            alias,
            "-ttl",
            "600",
            "-output",
            "json",
        )
    )
    private_write(directory / "join.token", token["value"])
    private_write(directory / "agent.conf", (PRIVATE / "agents/core/agent.conf").read_text())
    bundle = spire("bundle", "show", "-socketPath", "/run/spire/data/api.sock", "-format", "pem")
    private_write(directory / "bundle.crt", bundle)
    docker.copy_into(name("negative-seed"), directory, "/operator/expiry")
    docker.copy_into(name("negative-seed"), PRIVATE / "spire-agent-linux", "/operator/spire-agent")
    script = (
        "import os,shutil;from pathlib import Path;"
        "tools=Path('/probe-tools');tools.chmod(0o755);"
        "shutil.copyfile('/operator/spire-agent',tools/'spire-agent');"
        "(tools/'spire-agent').chmod(0o555);"
        "shutil.copyfile('/operator/expiry/bundle.crt',tools/'bundle.pem');"
        "(tools/'bundle.pem').chmod(0o444);"
        "cfg=Path('/expiry-config');cfg.chmod(0o700);"
        "[(shutil.copyfile(p,cfg/p.name),(cfg/p.name).chmod(0o600)) "
        "for p in Path('/operator/expiry').iterdir()]"
    )
    docker.exec(name("negative-seed"), ["python", "-c", script], root=True)
    entry = spire(
        "entry",
        "create",
        "-socketPath",
        "/run/spire/data/api.sock",
        "-parentID",
        alias,
        "-spiffeID",
        "spiffe://care-link.demo/demo/core",
        "-x509SVIDTTL",
        "30",
        "-selector",
        "unix:uid:22002",
    )
    match = re.search(r"Entry ID\s*:\s*([0-9a-f-]{36})", entry)
    if match is None:
        raise ValueError("Fresh expiry registration receipt missing")
    entry_id = match[1]
    inputs = json.loads((PRIVATE / "inputs.json").read_text())
    create(
        "expiry-agent",
        ["-config", "/config/agent.conf"],
        [
            mount("expiry-agent", "/config", readonly=True),
            mount("expiry-svid", "/run/spire/sockets"),
        ],
        uid=0,
        image=inputs["binding"]["pins"]["spire_image"],
        network="kind",
        tmpfs=["/run/spire/data:rw,noexec,nosuid,size=16m,mode=0700"],
    )
    docker.start(name("expiry-agent"))
    result: dict[str, object] = {"registration_id": entry_id, "requested_ttl_seconds": 30}
    for suffix, uid, api, parent, action in [
        ("negative-no-svid", 65532, None, None, "no-svid"),
        ("negative-direct-role", 22002, "data", "data-agent", "direct-role"),
        ("negative-expiry", 22002, "expiry", "expiry-agent", "expiry"),
    ]:
        mounts = [mount("negative-tools", "/probe-tools", readonly=True)]
        if api:
            mounts.append(mount(api + "-svid", "/probe-api/" + api, readonly=True))
        create(
            suffix,
            ["python", "-c", "import time;time.sleep(240)"],
            mounts,
            uid=uid,
            network=MESH_NETWORK,
            pid=name(parent) if parent else None,
            tmpfs=["/tmp:rw,noexec,nosuid,size=16m,mode=1777"],  # noqa: S108
        )
        docker.start(name(suffix))
        try:
            arguments = [action]
            if api:
                path = "/probe-api/" + api + "/agent.sock"
                wait_socket(name(suffix), path)
                arguments += ["--api", path]
            result[action] = probe(suffix, arguments, action)
        finally:
            docker.stop(name(suffix))
            docker.remove_owned(name(suffix))
    docker.stop(name("expiry-agent"))
    docker.remove_owned(name("expiry-agent"))
    docker.stop(name("negative-seed"))
    docker.remove_owned(name("negative-seed"))
    spire("entry", "delete", "-socketPath", "/run/spire/data/api.sock", "-entryID", entry_id)
    result["temporary_workload_entry_removed"] = True
    result["node_alias_registration_retained"] = alias
    result["passed"] = all(
        isinstance(result[k], dict) and cast(dict[str, object], result[k]).get("passed") is True
        for k in ("no-svid", "direct-role", "expiry")
    )
    private_write(EVIDENCE / "negative-attestation-summary.json", json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    print(json.dumps(run()))
