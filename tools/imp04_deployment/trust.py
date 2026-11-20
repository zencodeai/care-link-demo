"""Dedicated IMP-04 SPIRE bootstrap and own-bundle maintenance only."""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import docker
from .config import PRIVATE, ROLES, ROOT
from .deploy import create, name
from .prepare import write

SERVER_CONFIG = """server {
  bind_address = "0.0.0.0"
  bind_port = "8081"
  socket_path = "/run/spire/data/api.sock"
  trust_domain = "care-link.demo"
  data_dir = "/run/spire/data"
  log_level = "WARN"
  default_x509_svid_ttl = "300s"
  agent_ttl = "1h"
}
plugins {
  DataStore "sql" { plugin_data {
    database_type = "sqlite3"
    connection_string = "/run/spire/data/server.sqlite"
  } }
  KeyManager "disk" { plugin_data { keys_path = "/run/spire/data/keys.json" } }
  NodeAttestor "join_token" { plugin_data { } }
}
"""


def spire(*args: str) -> str:
    return docker.exec(name("spire-server"), ["/opt/spire/bin/spire-server", *args], root=True)


def bootstrap(private: Path, application_image: str) -> dict[str, object]:
    if private != PRIVATE or (private / "spire-bundle.pem").exists():
        raise ValueError("Fresh exact IMP-04 authority required")
    # No host mount: pass public server config through stdin to the owned seed.
    script = "import os,pathlib,sys;p=pathlib.Path('/volumes/spire-server-config/server.conf');f=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.write(f,sys.stdin.buffer.read());os.close(f)"  # noqa: E501 - fixed source-free stdin script
    docker.exec(name("seed"), ["python", "-c", script], stdin=SERVER_CONFIG, root=True)
    create("spire-server", application_image)
    docker.start(name("spire-server"))
    deadline = time.monotonic() + 30
    bundle = ""
    while time.monotonic() < deadline:
        try:
            bundle = spire(
                "bundle", "show", "-socketPath", "/run/spire/data/api.sock", "-format", "pem"
            )
            break
        except RuntimeError:
            time.sleep(0.25)
    if "BEGIN CERTIFICATE" not in bundle:
        raise RuntimeError("Independent SPIRE root not ready")
    write(private / "spire-bundle.pem", bundle.encode())
    agents = private / "agents"
    agents.mkdir(mode=0o700, exist_ok=False)
    for role in ROLES:
        parent = "spiffe://care-link.demo/host/imp04-002-" + role
        token = json.loads(
            spire(
                "token",
                "generate",
                "-socketPath",
                "/run/spire/data/api.sock",
                "-spiffeID",
                parent,
                "-ttl",
                "600",
                "-output",
                "json",
            )
        )
        directory = agents / role
        directory.mkdir(mode=0o700)
        write(directory / "join.token", str(token["value"]).encode())
        config = """agent {
  trust_domain = "care-link.demo"
  data_dir = "/config/data"
  server_address = "172.29.46.10"
  server_port = "8081"
  socket_path = "/run/spire/sockets/agent.sock"
  trust_bundle_path = "/config/bundle.crt"
  join_token_file = "/config/join.token"
  log_level = "WARN"
}
plugins {
  NodeAttestor "join_token" { plugin_data { } }
  KeyManager "disk" { plugin_data { directory = "/config/data/keys" } }
  WorkloadAttestor "unix" { plugin_data { } }
}
"""
        write(directory / "agent.conf", config.encode())
        spire(
            "entry",
            "create",
            "-socketPath",
            "/run/spire/data/api.sock",
            "-parentID",
            parent,
            "-spiffeID",
            "spiffe://care-link.demo/demo/" + role,
            "-x509SVIDTTL",
            "300",
            "-selector",
            "unix:uid:22002",
        )
    docker.copy_into(name("seed"), private / "spire-bundle.pem", "/operator/spire-bundle.pem")
    docker.copy_into(name("seed"), agents, "/operator/agents")
    return {
        "new_authority": True,
        "independent_root": True,
        "new_parent_count": len(ROLES),
        "workload_registrations": len(ROLES),
        "svid_ttl_seconds": 300,
        "agent_key_custody": "owned persistent /config/data/keys",
        "accepted_authority_accessed": False,
    }


def refresh() -> dict[str, object]:
    """Refresh own public bundles only; no agent or fence restart."""
    bundle = spire("bundle", "show", "-socketPath", "/run/spire/data/api.sock", "-format", "pem")
    if "BEGIN CERTIFICATE" not in bundle:
        raise ValueError("Own authority bundle unavailable")
    changed: list[str] = []
    for role in ROLES:
        target = ROOT + "/" + role + "/authorization/bundle.pem"
        script = "import os,pathlib,sys;p=pathlib.Path(sys.argv[1]);b=sys.stdin.buffer.read();old=p.read_bytes();changed=old!=b;tmp=p.with_suffix('.new');f=os.open(tmp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600) if changed else None;os.write(f,b) if changed else None;os.fsync(f) if changed else None;os.close(f) if changed else None;tmp.replace(p) if changed else None;print('changed' if changed else 'unchanged')"  # noqa: E501 - fixed source-free stdin script
        result = docker.exec(
            name(role + "-authorization"), ["python", "-c", script, target], stdin=bundle
        ).strip()
        if result == "changed":
            docker.stop(name(role + "-authorization"))
            docker.start(name(role + "-authorization"))
            changed.append(role)
    return {"updated_new_authorizers": changed, "accepted_targets_changed": False}
