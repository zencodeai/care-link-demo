"""Verify the leased Kind node, Calico active controls, and host Static."""

# ruff: noqa: S101

import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic, sleep

import httpx
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from services.data.tests.imp10_outage_help import _static_publication
from tools.imp02_lab.model import LabInputs
from tools.imp02_lab.network import LISTENER, manifests, namespace

SCOPE = os.environ.get("CARE_LINK_IMP10_KIND_LEASE", "imp10-005")
if re.fullmatch(r"imp10-[0-9]{3}", SCOPE) is None:
    raise ValueError("Expected an IMP-10 qualification lease identifier")
CLUSTER = "care-link-" + SCOPE
NODE = CLUSTER + "-control-plane"
NETWORK = CLUSTER + "-net"
FIXTURE = CLUSTER + "-network-control"
IMAGE = "care-link-imp10:qualification-002-final"
ROOT = Path(__file__).resolve().parents[2]
ASSETS = Path("/private/tmp") / (CLUSTER + "-assets")
PORTS = (8443, 5432, 8011, 1234, 18443)
CORE_PATH = "/dev/health"
TCP_PROBE = """
import socket, sys
try:
    peer = socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=0.8)
except TimeoutError:
    print('timeout')
else:
    with peer:
        peer.settimeout(2)
        print(peer.recv(256).decode().strip())
"""
CORE_PROBE = """
import http.client, json, sys
client = http.client.HTTPConnection(sys.argv[1], 8443, timeout=2)
client.request('GET', '/dev/health')
response = client.getresponse()
assert response.status == 200
print(json.dumps(json.loads(response.read())))
"""


def run(*command: str, stdin: str | None = None, timeout: int = 30) -> str:
    completed = subprocess.run(  # noqa: S603
        command,
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if completed.returncode:
        raise RuntimeError(
            f"{command[0]} failed with exit {completed.returncode}: {completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def k(*args: str, stdin: str | None = None, timeout: int = 30) -> str:
    return run(
        "kubectl",
        "--kubeconfig",
        str(ASSETS / "kubeconfig"),
        "--context",
        "kind-" + CLUSTER,
        "--namespace",
        CLUSTER,
        *args,
        stdin=stdin,
        timeout=timeout,
    )


def check_owner() -> tuple[str, str, str]:
    node = json.loads(run("docker", "inspect", "--format", "{{json .}}", NODE))
    if (
        node["Config"]["Labels"]["io.x-k8s.kind.cluster"] != CLUSTER
        or list(node["NetworkSettings"]["Networks"]) != [NETWORK]
        or not node["State"]["Running"]
        or node["NetworkSettings"]["Ports"]["6443/tcp"][0]["HostIp"] != "127.0.0.1"
    ):
        raise ValueError("Expected the running owned Kind node on the private bridge")
    scope = run(
        "docker", "network", "inspect", "--format", '{{index .Labels "care-link.scope"}}', NETWORK
    )
    if scope != SCOPE:
        raise ValueError("Expected an owned Docker bridge")
    image = run("docker", "image", "inspect", "--format", "{{.Id}}", IMAGE)
    receipt = (
        ROOT
        / "doc/IMP/slices/IMP-10-integrated-demonstrator/sessions"
        / "002-qualification/evidence/final-image-smoke.json"
    )
    assert json.loads(receipt.read_text())["image_id"] == image
    observed = json.loads(k("get", "node", NODE, "-o", "json"))
    assert any(
        c["type"] == "Ready" and c["status"] == "True" for c in observed["status"]["conditions"]
    )
    return node["Id"], observed["metadata"]["uid"], image


def configure_fixtures(address: str) -> None:
    pins = json.loads((ROOT / "deploy/k8s/imp-02/products.json").read_text())
    inputs = LabInputs(
        pins["images"],
        ASSETS / "kind",
        ASSETS / "calico.yaml",
        ASSETS,
        pins["kind_sha256"],
        pins["calico_manifest_sha256"],
    )
    ns = namespace()
    ns["metadata"].update(
        name=CLUSTER,
        labels={
            "care-link.session": SCOPE,
            "pod-security.kubernetes.io/enforce": "restricted",
        },
    )
    items = manifests(inputs, address)
    for item in items:
        meta = item["metadata"]
        meta["namespace"] = CLUSTER
        meta["labels"]["care-link.session"] = SCOPE
        if item["kind"] == "Pod":
            item["spec"]["restartPolicy"] = "Always"
            container = item["spec"]["containers"][0]
            container.update(image=IMAGE, imagePullPolicy="Never")
            if meta["name"] == "broker-fixture":
                container["command"] = [
                    "python",
                    "-m",
                    "uvicorn",
                    "care_link_core.app:create_app",
                    "--factory",
                    "--host",
                    "0.0.0.0",  # noqa: S104 - reachable only inside the controlled pod network
                    "--port",
                    "8443",
                    "--no-access-log",
                ]
                container["resources"]["limits"] = {"cpu": "500m", "memory": "256Mi"}
    k("create", "-f", "-", stdin=json.dumps(ns))
    k("create", "-f", "-", stdin=json.dumps({"apiVersion": "v1", "kind": "List", "items": items}))
    k("wait", "--for=condition=Ready", "pod", "--all", "--timeout=90s", timeout=100)


def probe(pod: str, target: str, port: int) -> str:
    return k("exec", pod, "--", "python", "-c", TCP_PROBE, target, str(port))


def pod_address(pod: str) -> str:
    return k("get", "pod", pod, "-o", "jsonpath={.status.podIP}")


def cni(address: str) -> dict[str, object]:
    core = pod_address("broker-fixture")
    denied = pod_address("denied-fixture")
    allowed = json.loads(k("exec", "runtime-probe", "--", "python", "-c", CORE_PROBE, core))
    targets = [("pod_control", denied, port) for port in PORTS] + [("outside_node", address, 18443)]
    observations = []
    for location, target, port in targets:
        first = probe("allowed-probe", target, port)
        denied_result = probe("runtime-probe", target, port)
        second = probe("allowed-probe", target, port)
        assert (first, denied_result, second) == (
            "IMP02_ACTIVE_CONTROL",
            "timeout",
            "IMP02_ACTIVE_CONTROL",
        )
        observations.append(
            {
                "target": location,
                "ipv4": target,
                "port": port,
                "allowed_before": first,
                "restricted": denied_result,
                "allowed_after": second,
            }
        )
    disabled = k(
        "exec",
        "runtime-probe",
        "--",
        "cat",
        "/proc/sys/net/ipv6/conf/all/disable_ipv6",
        "/proc/sys/net/ipv6/conf/default/disable_ipv6",
    ).splitlines()
    assert disabled == ["1", "1"]
    pods = json.loads(k("get", "pod", "-o", "json"))["items"]
    result = {
        item["metadata"]["name"]: item["status"]["containerStatuses"][0]["imageID"] for item in pods
    }
    assert len(result) == 4
    return {
        "runtime_to_core_developer_health": allowed,
        "active_controls": observations,
        "runtime_pod_ipv6_disabled": True,
        "pod_image_ids": result,
    }


@contextmanager
def process(command: list[str]) -> Iterator[subprocess.Popen[bytes]]:
    with subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as child:  # noqa: S603
        try:
            yield child
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)


def open_port() -> str:
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        return str(reservation.getsockname()[1])


def ready_get(client: httpx.Client, url: str) -> httpx.Response:
    deadline = monotonic() + 10
    while True:
        try:
            response = client.get(url)
            response.raise_for_status()
            return response
        except httpx.TransportError:
            if monotonic() >= deadline:
                raise
            sleep(0.15)


def recovered_core(expected: object) -> None:
    deadline = monotonic() + 60
    while True:
        try:
            address = pod_address("broker-fixture")
            observed = k("exec", "runtime-probe", "--", "python", "-c", CORE_PROBE, address)
            assert json.loads(observed) == expected
            return
        except (RuntimeError, subprocess.TimeoutExpired):
            # Node and pod readiness may briefly describe the pre-stop state.
            if monotonic() >= deadline:
                raise
            sleep(0.5)


def outage(node: str, uid: str, workspace: Path) -> dict[str, object]:
    store, publication = _static_publication(workspace / "static", lambda: datetime.now(UTC))
    key = workspace / "static-review.pem"
    key.write_bytes(store.key.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
    static_port, forwarded = open_port(), open_port()
    static = [
        str(ROOT / ".venv/bin/care-link-static"),
        "--directory",
        str(store.directory),
        "--review-public-key",
        str(key),
        "--allow-owner-demo",
        "--port",
        static_port,
    ]
    port_forward = [
        "kubectl",
        "--kubeconfig",
        str(ASSETS / "kubeconfig"),
        "--context",
        "kind-" + CLUSTER,
        "--namespace",
        CLUSTER,
        "port-forward",
        "--address",
        "127.0.0.1",
        "pod/broker-fixture",
        forwarded + ":8443",
    ]
    with (
        process(static) as host,
        httpx.Client(
            transport=httpx.HTTPTransport(retries=0), timeout=2, trust_env=False
        ) as client,
    ):

        def verify_static() -> dict[str, str]:
            for content in publication.texts:
                site = f"http://127.0.0.1:{static_port}"
                page = ready_get(client, site + "/fallback?locale=" + content.locale)
                manifest = ready_get(
                    client, site + "/demo-static/v1/manifest?locale=" + content.locale
                )
                assert content.title in page.text and content.text in page.text
                assert manifest.json() == publication.owner_manifest(content.locale)
                assert (
                    "cookie" not in page.request.headers
                    and "cookie" not in manifest.request.headers
                )
            assert host.poll() is None
            return {"artifact_digest": publication.artifact_digest, "process_id": str(host.pid)}

        url = f"http://127.0.0.1:{forwarded}{CORE_PATH}"
        before_static = verify_static()
        with process(port_forward):
            before_core = ready_get(client, url).json()
            began = monotonic()
            try:
                run("docker", "stop", "--time", "12", node)
                assert run("docker", "inspect", "--format", "{{.State.Running}}", node) == "false"
                try:
                    client.get(url)
                except httpx.TransportError:
                    pass
                else:
                    raise AssertionError("Forwarded Core stayed reachable during node stop")
                during_static = verify_static()
            finally:
                run("docker", "start", node)
        k("wait", "--for=condition=Ready", "node/" + NODE, "--timeout=100s", timeout=115)
        k("wait", "--for=condition=Ready", "pod/broker-fixture", "--timeout=100s", timeout=115)
        assert k("get", "node", NODE, "-o", "jsonpath={.metadata.uid}") == uid
        recovered_core(before_core)
        recovered_port = open_port()
        with process([*port_forward[:-1], recovered_port + ":8443"]):
            recovered_url = f"http://127.0.0.1:{recovered_port}{CORE_PATH}"
            assert ready_get(client, recovered_url).json() == before_core
        assert before_static == during_static == verify_static()
        return {
            "node": NODE,
            "node_id": node,
            "node_uid": uid,
            "container_actually_stopped": True,
            "core_developer_health_unreachable": True,
            "core_developer_health_restored": True,
            "tests_and_recovery_ms": round((monotonic() - began) * 1000, 3),
            "static": {**before_static, "locales": ["en-CA", "fr-CA"], "loopback_http": True},
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output must be a new receipt")
    os.umask(0o077)
    started = datetime.now(UTC).isoformat()
    node, uid, image = check_owner()
    workspace = ASSETS / "boundary-state"
    workspace.mkdir(mode=0o700)
    container = run(
        "docker",
        "run",
        "--detach",
        "--name",
        FIXTURE,
        "--label",
        "care-link.scope=" + SCOPE,
        "--network",
        NETWORK,
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pull=never",
        IMAGE,
        "python",
        "-u",
        "-c",
        LISTENER,
    )
    try:
        address = run(
            "docker",
            "inspect",
            "--format",
            '{{(index .NetworkSettings.Networks "' + NETWORK + '").IPAddress}}',
            container,
        )
        configure_fixtures(address)
        network_receipt = cni(address)
        outage_receipt = outage(node, uid, workspace)
    finally:
        scope = run(
            "docker",
            "inspect",
            "--format",
            '{{index .Config.Labels "care-link.scope"}}',
            container,
        )
        if scope != SCOPE:
            raise ValueError("Expected the owned network control fixture")
        run("docker", "rm", "--force", container)
    receipt = {
        "started_at": started,
        "ended_at": datetime.now(UTC).isoformat(),
        "image_id": image,
        "calico_manifest_sha256": hashlib.sha256(
            (ASSETS / "calico-pinned.yaml").read_bytes()
        ).hexdigest(),
        "cni": network_receipt,
        "outage": outage_receipt,
        "scope": "Current developer image health, active CNI controls, and separate host Static.",
    }
    with args.output.open("x") as output:
        json.dump(receipt, output, indent=2)
        output.write("\n")


if __name__ == "__main__":
    main()
