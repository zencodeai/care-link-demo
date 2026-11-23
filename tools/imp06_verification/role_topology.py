"""Run a fresh, private IMP-06 Docker mesh qualification with pinned SPIRE/Envoy."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import subprocess
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from care_link_workload_trust import (
    OutboundListener,
    PeerRule,
    ProxyInputs,
    add_outbound,
    build_envoy,
)

from tools.imp03_runtime.mesh import rename
from tools.imp06_runtime.routes import RUNTIME_ROUTES, inbound

from .role_topology_processes import (
    BASE,
    CLAIM,
    FENCE_GROUP,
    FENCE_OWNER,
    FENCE_RESTRICT,
    MANUAL_CHANNEL,
    ROLES,
    UID,
    app_mounts,
    destinations,
    spiffe,
)

ROOT = Path(__file__).resolve().parents[2]
PREFIX = "care-link-imp06-005-mesh"
LABEL = "care-link.session=" + PREFIX
PROBE_SOURCE = Path(__file__).with_name("role_topology_processes.py")
SPIRE_CTL = "/opt/spire/bin/spire-server"
SPIRE_SOCKET = "/run/spire/data/api.sock"
TTL_SECONDS = 90
SERVER = """server {
  bind_address = "0.0.0.0"
  bind_port = "8081"
  socket_path = "/run/spire/data/api.sock"
  trust_domain = "care-link.demo"
  data_dir = "/run/spire/data"
  log_level = "WARN"
  default_x509_svid_ttl = "90s"
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
AGENT = """agent {
  trust_domain = "care-link.demo"
  data_dir = "/config/data"
  server_address = "SERVER_ADDRESS"
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

Record = dict[str, object]


def record(value: object) -> Record:
    if not isinstance(value, dict):
        raise ValueError("object required")
    return cast(Record, value)


def docker(*arguments: str, stdin: str | None = None, timeout: int = 30) -> str:
    # Fixed executable, named resources, and no tokens in argv or reported errors.
    result = subprocess.run(  # noqa: S603
        ["docker", *arguments],  # noqa: S607
        input=stdin,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.strip().splitlines()
        raise RuntimeError(
            f"Docker {arguments[0]} failed ({result.returncode})"
            + (f" — {detail[-1][:240]}" if detail else "")
        )
    return result.stdout.strip()


def resource(suffix: str) -> str:
    return PREFIX + "-" + suffix


def mount(volume: str, target: str, *, part: str = "", readonly: bool = False) -> str:
    return (
        "type=volume,source="
        + resource(volume)
        + ",target="
        + target
        + (",volume-subpath=" + part if part else "")
        + (",readonly" if readonly else "")
    )


def retry(operation: Callable[[], str], label: str, *, seconds: int = 35) -> str:
    deadline = time.monotonic() + seconds
    while True:
        try:
            return operation()
        except RuntimeError as error:
            if time.monotonic() >= deadline:
                raise RuntimeError(label) from error
            time.sleep(0.5)


def envoy_config(
    role: str, addresses: dict[str, str], images: dict[str, str], versions: dict[str, str]
) -> Record:
    is_runtime = role == "runtime"
    inputs = ProxyInputs(
        spiffe(role),
        (PeerRule(spiffe("core"), RUNTIME_ROUTES),) if is_runtime else inbound(role),
        addresses[role],
        8443,
        BASE + "/backend/service.sock",
        BASE + "/authorization/auth.sock",
        BASE + "/spire/agent.sock",
        images["envoy"],
        versions["envoy"],
        images["spire_agent"],
        versions["spire"],
        TTL_SECONDS,
    )
    config = build_envoy(inputs)
    record(config["node"])["cluster"] = PREFIX
    if is_runtime:
        resources = record(config["static_resources"])
        resources["listeners"] = []
        resources["clusters"] = [cast(list[object], resources["clusters"])[-1]]
    for destination, routes in destinations(role).items():
        config = add_outbound(
            config,
            OutboundListener(
                spiffe(role),
                spiffe(destination),
                addresses[destination],
                8443,
                BASE + "/outbound/" + destination + ".sock",
                routes,
            ),
        )
        resources = record(config["static_resources"])
        listeners = cast(list[object], resources["listeners"])
        clusters = cast(list[object], resources["clusters"])
        listeners[-1] = rename(listeners[-1], destination)
        # Recycle upstream pools ahead of SVID expiry to exercise automatic rotation.
        record(clusters[-1])["common_http_protocol_options"] = {"max_connection_duration": "20s"}
        clusters[-1] = rename(clusters[-1], destination)
    return config


class Lab:
    def __init__(self, image: str) -> None:
        self.image = docker("image", "inspect", "--format", "{{.Id}}", image)
        if not self.image.startswith("sha256:") or len(self.image) != 71:
            raise ValueError("local immutable candidate image required")
        products = record(json.loads((ROOT / "deploy/k8s/imp-02/products.json").read_text()))
        self.images = cast(dict[str, str], products["images"])
        self.versions = cast(dict[str, str], products["selected_versions"])
        self.containers: list[str] = []
        self.volumes: list[str] = []
        self.networks: list[str] = []

    def fresh(self) -> None:
        for kind, arguments in [
            ("container", ("ps", "-a")),
            ("volume", ("volume", "ls")),
            ("network", ("network", "ls")),
        ]:
            existing = docker(*arguments, "--filter", "label=" + LABEL, "--quiet")
            if existing:
                raise ValueError(f"Fresh qualification required — existing labeled {kind}")

    def network(self, suffix: str) -> ipaddress.IPv4Network:
        name = resource(suffix)
        subnet = {"routing": "172.31.250.0/24", "issuer": "172.31.251.0/24"}[suffix]
        docker("network", "create", "--internal", "--subnet", subnet, "--label", LABEL, name)
        self.networks.append(name)
        value = docker("network", "inspect", "--format", "{{(index .IPAM.Config 0).Subnet}}", name)
        return ipaddress.IPv4Network(value)

    def volume(self, suffix: str) -> None:
        name = resource(suffix)
        docker("volume", "create", "--label", LABEL, name)
        self.volumes.append(name)

    def run(
        self,
        suffix: str,
        args: list[str],
        mounts: list[str],
        *,
        uid: int = 0,
        groups: tuple[int, ...] = (),
        net: str = "none",
        address: str = "",
        pid: str = "",
        image: str | None = None,
        caps: tuple[str, ...] = (),
        detached: bool = True,
        stdin: str | None = None,
    ) -> str:
        name = resource(suffix)
        command = [
            "run",
            "--pull",
            "never",
            "--name",
            name,
            "--label",
            LABEL,
            "--network",
            net,
            "--read-only",
            "--security-opt",
            "no-new-privileges",
            "--cap-drop",
            "ALL",
            "--user",
            f"{uid}:{uid}",
            "--pids-limit",
            "64",
            "--memory",
            "224m",
        ]
        for group in groups:
            command += ["--group-add", str(group)]
        for capability in caps:
            command += ["--cap-add", capability]
        if address:
            command += ["--ip", address]
        if pid:
            command += ["--pid", "container:" + resource(pid)]
        if detached:
            command.append("-d")
        if stdin is not None:
            command.append("-i")
        for value in mounts:
            command += ["--mount", value]
        if image is None:
            command += [
                "--env",
                "PYTHONPATH=/app",
                "--mount",
                f"type=bind,source={PROBE_SOURCE},target=/qualification.py,readonly",
            ]
        # Docker can publish the container after the CLI times out. Record the
        # expected name before creation; cleanup still checks its exact lease label.
        self.containers.append(name)
        return docker(*command, image or self.image, *args, stdin=stdin)

    def process(self, suffix: str, *args: str, stdin: str | None = None) -> str:
        flags = ("-i",) if stdin is not None else ()
        return docker(
            "exec",
            *flags,
            resource(suffix),
            "python",
            "/qualification.py",
            *args,
            stdin=stdin,
            timeout=120,
        )

    def spire(self, *args: str) -> str:
        return docker("exec", resource("spire-server"), SPIRE_CTL, *args)

    def bootstrap(self) -> dict[str, str]:
        mesh, trust = self.network("routing"), self.network("issuer")
        addresses = {role: str(mesh[10 + i]) for i, role in enumerate(ROLES)}
        for suffix in ("issuer", "fence", *ROLES):
            self.volume(suffix)
        seed_mounts = [mount(suffix, "/seed/" + suffix) for suffix in ("issuer", "fence", *ROLES)]
        self.run(
            "seed",
            ["python", "/qualification.py", "seed"],
            seed_mounts,
            caps=("CHOWN", "DAC_OVERRIDE", "FOWNER", "FSETID"),
            stdin=SERVER,
            detached=False,
        )
        self.run(
            "spire-server",
            ["-config", "/config/server.conf"],
            [
                mount("issuer", "/config", part="config", readonly=True),
                mount("issuer", "/run/spire/data", part="data"),
            ],
            image=self.images["spire_server"],
            net=resource("issuer"),
            address=str(trust[10]),
        )
        bundle = retry(
            lambda: self.spire("bundle", "show", "-socketPath", SPIRE_SOCKET, "-format", "pem"),
            "disposable SPIRE root not ready",
        )
        if "BEGIN CERTIFICATE" not in bundle:
            raise RuntimeError("disposable SPIRE root unavailable")
        for role in ROLES:
            parent = "spiffe://care-link.demo/host/imp06-005-" + role
            token = record(
                json.loads(
                    self.spire(
                        "token",
                        "generate",
                        "-socketPath",
                        SPIRE_SOCKET,
                        "-spiffeID",
                        parent,
                        "-ttl",
                        "600",
                        "-output",
                        "json",
                    )
                )
            )["value"]
            self.spire(
                "entry",
                "create",
                "-socketPath",
                SPIRE_SOCKET,
                "-parentID",
                parent,
                "-spiffeID",
                spiffe(role),
                "-x509SVIDTTL",
                str(TTL_SECONDS),
                "-selector",
                "unix:uid:" + str(UID[role].proxy),
            )
            self.run(
                role + "-configure",
                ["python", "/qualification.py", "configure", role],
                [mount(role, "/seed/" + role)],
                caps=("CHOWN", "DAC_OVERRIDE"),
                stdin=json.dumps(
                    {
                        "bundle": bundle,
                        "token": token,
                        "agent": AGENT.replace("SERVER_ADDRESS", str(trust[10])),
                        "envoy": envoy_config(role, addresses, self.images, self.versions),
                    }
                ),
                detached=False,
            )
        self.run(
            "fence",
            ["python", "/qualification.py", "fence"],
            [mount("fence", BASE + "/fence")],
            uid=FENCE_OWNER,
            groups=(FENCE_GROUP,),
        )
        return addresses

    def start_roles(self, addresses: dict[str, str]) -> None:
        for role in ROLES:
            owners = UID[role]
            self.run(
                role + "-agent",
                ["-config", "/config/agent.conf"],
                [
                    mount(role, "/config", part="agent"),
                    mount(role, "/run/spire/sockets", part="spire"),
                ],
                image=self.images["spire_agent"],
                net=resource("issuer"),
            )
            if role != "runtime":
                self.run(
                    role + "-authorization",
                    ["python", "/qualification.py", "authorize", role],
                    [
                        mount(role, BASE + "/authorization", part="authorization"),
                        mount("fence", BASE + "/fence", readonly=True),
                    ],
                    uid=owners.authorization,
                    groups=(owners.proxy, FENCE_GROUP),
                )
            self.run(
                role + "-app",
                ["python", "/qualification.py", "serve", role],
                [
                    mount(role, BASE + "/" + part, part=part, readonly=readonly)
                    for part, readonly in app_mounts(role)
                ]
                + ([mount("fence", BASE + "/fence", readonly=True)] if role != "runtime" else []),
                uid=owners.app,
                groups=(owners.proxy, FENCE_GROUP) if role != "runtime" else (),
            )
            self.run(
                role + "-proxy",
                [
                    "-c",
                    BASE + "/proxy/envoy.json",
                    "--log-level",
                    "critical",
                    "--disable-hot-restart",
                    "--concurrency",
                    "1",
                ],
                [
                    mount(role, BASE + "/" + part, part=part, readonly=part != "outbound")
                    for part in ("proxy", "backend", "outbound", "authorization", "spire")
                ],
                image=self.images["envoy"],
                net=resource("routing"),
                address=addresses[role],
                pid=role + "-agent",
                uid=owners.proxy,
            )

    def cleanup(self) -> dict[str, int]:
        for names, listing, arguments, field in (
            (self.containers, ("ps", "-a"), ("rm", "-f"), "{{.Names}}"),
            (self.volumes, ("volume", "ls"), ("volume", "rm"), "{{.Name}}"),
            (self.networks, ("network", "ls"), ("network", "rm"), "{{.Name}}"),
        ):
            labeled = set(
                docker(
                    *listing, "--filter", "label=" + LABEL, "--format", field, timeout=60
                ).splitlines()
            )
            if not labeled <= set(names):
                raise RuntimeError("qualification cleanup ownership mismatch")
            if labeled:
                docker(
                    *arguments, *(name for name in reversed(names) if name in labeled), timeout=120
                )
        return {
            "containers": len(self.containers),
            "volumes": len(self.volumes),
            "networks": len(self.networks),
        }


def post(
    lab: Lab, caller: str, destination: str, path: str, body: Record, *, direct: bool = False
) -> Record:
    return record(
        json.loads(
            lab.process(
                caller + "-app",
                "direct" if direct else "post",
                destination,
                path,
                stdin=json.dumps(body),
            )
        )
    )


def state_matches(response: Record, status: int, authenticated: str | None = None) -> bool:
    return response["status"] == status and (
        authenticated is None or response["authenticated_peer"] == spiffe(authenticated)
    )


def wire_inference() -> Record:
    ident = "11111111-1111-4111-8111-111111111111"
    return {
        "job_id": ident,
        "task_id": ident,
        "step_id": ident,
        "fence": "1",
        "function": "worker_summary",
        "model_digest": "a" * 64,
        "prompt_digest": "a" * 64,
        "items": [
            {
                "source": {
                    "kind": "assertion",
                    "id": ident,
                    "revision": "1",
                    "digest": "a" * 64,
                    "observed_at": "2026-11-20T12:00:00Z",
                    "verification": "unverified",
                },
                "label": "untrusted_report",
                "text": "Synthetic fixture only.",
                "critical": True,
            }
        ],
        "budgets": {
            "max_steps": 1,
            "max_tools": 0,
            "max_proposal_attempts": 1,
            "context_tokens": 1024,
            "output_tokens": 128,
        },
        "deadline": (datetime.now(UTC).replace(microsecond=0)).isoformat().replace("+00:00", "Z"),
    }


def qualify(lab: Lab, addresses: dict[str, str]) -> Record:
    def ready() -> str:
        response = lab.process("runtime-app", "claim")
        if json.loads(response) != {"task_id": None, "task_revision": None, "fence": None}:
            raise RuntimeError("unexpected Core work claim")
        return response

    receipt = retry(ready, "Runtime-to-Core authenticated claim unavailable", seconds=50)

    def attestation() -> str:
        response = post(lab, "runtime", "core", CLAIM, {})
        if not state_matches(response, 200, "runtime"):
            raise RuntimeError(f"missing authenticated Runtime attestation: {response}")
        return json.dumps(response)

    claimed = record(
        json.loads(retry(attestation, "Runtime claim attestation unavailable", seconds=35))
    )

    core_data = "/internal/v1/data/session_create"
    infer_data = "/internal/v1/data/assistance/inference/current"
    jobs = "/internal/v1/inference/jobs"
    bridge = "/internal/v1/inference/execute"
    infer_body: Record = {"fixture": "no_business_authority"}
    cases: tuple[tuple[str, str, str, str, Record, int], ...] = (
        ("Core to Data manual session schema", "core", "data", core_data, {}, 400),
        ("Core to Inference disabled context", "core", "inference", jobs, wire_inference(), 503),
        ("Inference to Data current context", "inference", "data", infer_data, infer_body, 200),
        ("Data to Core manual channel", "data", "core", MANUAL_CHANNEL, {}, 200),
    )
    allowed: dict[str, Record] = {"Runtime to Core real work claim": record(json.loads(receipt))}
    for name, caller, destination, path, body, status in cases:
        response = post(lab, caller, destination, path, body)
        if not state_matches(response, status, caller):
            raise RuntimeError(f"expected authenticated app response for {name}: {response}")
        allowed[name] = response
    deadline = datetime.now(UTC) + timedelta(seconds=20)
    provider = post(
        lab,
        "inference",
        "host-inference-bridge",
        bridge,
        {
            "payload": {"fixture": "bridge_transport"},
            "deadline": deadline.isoformat().replace("+00:00", "Z"),
        },
    )
    if not state_matches(provider, 200, "inference") or provider["body"] != {
        "fixture": "provider_response",
        "model_called": False,
    }:
        raise RuntimeError(f"synthetic provider transport failed: {provider}")
    allowed["Inference to bridge execution adapter"] = provider

    adverse = {}
    for tag, caller, destination, path in (
        ("Runtime cannot use Core manual channel", "runtime", "core", MANUAL_CHANNEL),
        ("Core cannot access Inference-scoped Data ledger", "core", "data", infer_data),
        ("Inference cannot access Core-scoped Data commands", "inference", "data", core_data),
    ):
        denied = post(lab, caller, destination, path, {})
        if not state_matches(denied, 404) or denied["authenticated_peer"] is not None:
            raise RuntimeError(f"expected route rejection for {tag}: {denied}")
        adverse[tag] = denied
    denied = post(lab, "core", "core", CLAIM, {}, direct=True)
    if not state_matches(denied, 403):
        raise RuntimeError("forged attestation accepted from wrong local UID")
    adverse["forged attestation on direct backend socket"] = denied
    network: dict[str, Record] = {}
    for role in ROLES:
        checks = record(json.loads(lab.process(role + "-app", "isolation", addresses["core"])))
        if (
            checks["active_interfaces"] != ["lo"]
            or checks["no_ipv4_routes"] is not True
            or checks["effective_capabilities"] != 0
            or checks["direct_tcp"] != ["network_unreachable"] * 3
            or checks["uid"] != UID[role].app
            or (role == "runtime" and checks["mounted_socket_directories"] != ["outbound"])
        ):
            raise RuntimeError(f"failed kernel namespace or custody check for {role}")
        network[role] = checks

    original = claimed["peer_certificate_digest"]

    def rotate() -> str:
        response = post(lab, "runtime", "core", CLAIM, {})
        if not state_matches(response, 200, "runtime") or response["peer_certificate_digest"] in (
            None,
            original,
        ):
            raise RuntimeError("replacement SVID unobserved")
        return str(response["peer_certificate_digest"])

    rotated = retry(rotate, "automatic Runtime SVID rotation unobserved", seconds=105)
    lab.process("core-app", "claim-armed")
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(post, lab, "runtime", "core", CLAIM, {})
        retry(
            lambda: lab.process("core-app", "claim-entered"),
            "in-flight work claim not observed",
            seconds=12,
        )
        restriction = record(
            json.loads(
                lab.run(
                    "restriction",
                    ["python", "/qualification.py", "restrict"],
                    [mount("fence", BASE + "/fence", readonly=True)],
                    uid=FENCE_RESTRICT,
                    groups=(FENCE_GROUP,),
                    detached=False,
                )
            )
        )
        lab.process("core-app", "claim-finish")
        in_flight = running.result(timeout=24)
    revoked = post(lab, "runtime", "core", CLAIM, {})
    manual = post(lab, "data", "core", MANUAL_CHANNEL, {})
    if (
        restriction["durable"] is not True
        or restriction["generation"] != 1
        or not state_matches(in_flight, 403)
        or not state_matches(revoked, 403)
        or not state_matches(manual, 200, "data")
    ):
        raise RuntimeError(
            f"live restriction or manual continuity failed: {in_flight}, {revoked}, {manual}"
        )
    return {
        "state": "passed",
        "allowed_routes": allowed,
        "denied_routes": adverse,
        "app_network_and_kernel_custody": network,
        "runtime_svid_rotation": {
            "old_peer_certificate_digest": original,
            "new_peer_certificate_digest": rotated,
            "requested_ttl_seconds": TTL_SECONDS,
        },
        "live_restriction": {
            "durable_receipt": restriction,
            "in_flight_result": in_flight,
            "subsequent_result": revoked,
            "unaffected_manual_channel": manual,
        },
        "limits": [
            "Unix UID workload attestation in Docker, not Kubernetes service-account attestation.",
            "The separately isolated role apps, proxies and authorizers use real SPIRE SVIDs.",
            "Evidence covers transport, Core claim, selected handlers and manual channels.",
            "Business authority, durable work and model dependencies are synthetic or disabled. "
            "Live LM Studio and participant release are outside this fixture.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="Locally cached candidate application image")
    parser.add_argument("--output", type=Path, required=True, help="Fresh JSON evidence path")
    parser.add_argument("--run", action="store_true", help="Start only named disposable objects")
    args = parser.parse_args()
    if not args.run or args.output.exists() or not args.output.parent.is_dir():
        parser.error("explicit --run and a new output path in an existing directory required")
    lab = Lab(args.image)
    lab.fresh()
    evidence: Record = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "candidate_image": lab.image,
        "harness_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (Path(__file__), PROBE_SOURCE)
        },
        "pins": {key: lab.images[key] for key in ("envoy", "spire_server", "spire_agent")},
        "scope": "Disposable Docker dependency fixture with real SPIRE and Envoy",
    }
    try:
        addresses = lab.bootstrap()
        lab.start_roles(addresses)
        evidence.update(qualify(lab, addresses))
    finally:
        evidence["cleanup"] = lab.cleanup()
        lab.fresh()
    with args.output.open("x") as stream:
        json.dump(evidence, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"state": "passed", "output": str(args.output)}))


if __name__ == "__main__":
    main()
