"""Exact additive SPIRE and PostgreSQL exposure; no old target reconciliation."""

import json
import os
import subprocess
from pathlib import Path
from typing import cast

from .model import KUBE, NODE, PG_NODEPORT, PREFIX, Record
from .profiles import ACTIVE


def command(args: list[str], *, stdin: str | None = None, timeout: int = 30) -> str:
    result = subprocess.run(  # noqa: S603 - coordinator-defined command vectors
        args, input=stdin, capture_output=True, text=True, timeout=timeout, check=False
    )
    if result.returncode:
        raise RuntimeError("Named infrastructure command failed: " + args[0])
    return result.stdout


def private_write(path: Path, value: str | bytes) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(value.encode() if isinstance(value, str) else value)
        stream.flush()
        os.fsync(stream.fileno())


def verify_cluster() -> str:
    node = json.loads(command(["docker", "inspect", NODE]))[0]
    if node["Config"]["Labels"].get("io.x-k8s.kind.cluster") != "care-link-imp02-002":
        raise ValueError("Exact retained kind cluster required")
    return cast(str, node["NetworkSettings"]["Networks"]["kind"]["IPAddress"])


def spire(*args: str) -> str:
    return command(
        KUBE
        + [
            "-n",
            "care-link-imp02-002-trust",
            "exec",
            "deployment/spire-server",
            "--",
            "/opt/spire/bin/spire-server",
            *args,
        ]
    )


def initialize_spire(private: Path, roles: list[str]) -> Record:
    """Fresh exact aliases and UID registrations; tokens never enter evidence."""
    verify_cluster()
    observed = spire("entry", "show", "-socketPath", "/run/spire/data/api.sock")
    for role in roles:
        if "spiffe://care-link.demo/host/" + ACTIVE.parent_prefix + role in observed or (
            ACTIVE.name == "original" and "spiffe://care-link.demo/demo/" + role in observed
        ):
            raise ValueError("Existing IMP-03 identity refused; inspect partial state")
    private_write(private / "spire-entries-before.txt", observed)
    bundle = spire("bundle", "show", "-socketPath", "/run/spire/data/api.sock", "-format", "pem")
    private_write(private / "spire-bundle.pem", bundle)
    node_address = verify_cluster()
    (private / "agents").mkdir(mode=0o700)
    entries: dict[str, str] = {}
    for role in roles:
        alias = "spiffe://care-link.demo/host/" + ACTIVE.parent_prefix + role
        directory = private / "agents" / role
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
        config = f'''agent {{
  trust_domain = "care-link.demo"
  data_dir = "/run/spire/data"
  server_address = "{node_address}"
  server_port = "30881"
  socket_path = "/run/spire/sockets/agent.sock"
  trust_bundle_path = "/config/bundle.crt"
  join_token_file = "/config/join.token"
  log_level = "WARN"
}}
plugins {{
  NodeAttestor "join_token" {{ plugin_data {{ }} }}
  KeyManager "memory" {{ plugin_data {{ }} }}
  WorkloadAttestor "unix" {{ plugin_data {{ }} }}
}}
'''
        private_write(directory / "agent.conf", config)
        entry = spire(
            "entry",
            "create",
            "-socketPath",
            "/run/spire/data/api.sock",
            "-parentID",
            alias,
            "-spiffeID",
            "spiffe://care-link.demo/demo/" + role,
            "-x509SVIDTTL",
            "300",
            "-selector",
            "unix:uid:22002",
        )
        entries[role] = entry.strip()
    return {"workload_registrations": entries, "new_parent_count": len(roles)}


def postgres_access(addresses: list[str]) -> None:
    """Add one narrowly named service and source-bound ingress policy."""
    import ipaddress

    verify_cluster()
    for address in addresses:
        parsed = ipaddress.ip_address(address)
        if parsed.version != 4 or not parsed.is_private:
            raise ValueError("Actual private connector IPv4 addresses required")
    for kind, suffix in (("service", "postgres"), ("networkpolicy", "postgres-routes")):
        probe = json.loads(command(KUBE + ["-n", "care-link-imp02-002", "get", kind, "-o", "json"]))
        if any(x["metadata"]["name"] == PREFIX + "-" + suffix for x in probe["items"]):
            raise ValueError("Existing additive PostgreSQL resource refused")
    documents = [
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": PREFIX + "-postgres",
                "namespace": "care-link-imp02-002",
                "labels": {"care-link.scope": "imp03-003-option-b"},
            },
            "spec": {
                "type": "NodePort",
                "selector": {"app": "postgres"},
                "ports": [
                    {"name": "tls", "port": 5432, "targetPort": 5432, "nodePort": PG_NODEPORT}
                ],
            },
        },
        {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {
                "name": PREFIX + "-postgres-routes",
                "namespace": "care-link-imp02-002",
                "labels": {"care-link.scope": "imp03-003-option-b"},
            },
            "spec": {
                "podSelector": {"matchLabels": {"app": "postgres"}},
                "policyTypes": ["Ingress"],
                "ingress": [
                    {
                        "from": [{"ipBlock": {"cidr": address + "/32"}} for address in addresses],
                        "ports": [{"protocol": "TCP", "port": 5432}],
                    }
                ],
            },
        },
    ]
    command(
        KUBE + ["create", "-f", "-"],
        stdin=json.dumps({"apiVersion": "v1", "kind": "List", "items": documents}),
    )
