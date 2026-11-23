"""Install the SPIRE workload substrate in the leased IMP-10 qualification cluster."""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import re
import time
from argparse import ArgumentParser
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

from care_link_inference_bridge.tokenization import content_digest
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.x509.oid import NameOID

from tools.imp02_lab import csi, spire
from tools.imp02_lab.commands import private_json, run, verify_file
from tools.imp02_lab.model import SESSION as PREVIOUS_SESSION
from tools.imp02_lab.model import LabInputs, container_security, pod_security
from tools.imp03_runtime.authority_apps import canonical

ROOT = Path(__file__).resolve().parents[2]
SESSION = "imp10-008"
NAMESPACE = "care-link-" + SESSION
TRUST_NAMESPACE = NAMESPACE + "-trust"
NODE = NAMESPACE + "-control-plane"
NETWORK = NAMESPACE + "-net"
WORK = Path("/private/tmp") / (NAMESPACE + "-assets")
BUNDLE = "imp10-spire-bundle"
PINS = ROOT / "deploy/k8s/imp-02/products.json"
PROVIDER_PINS = (
    ROOT
    / "doc/IMP/slices/IMP-10-integrated-demonstrator/sessions/002-qualification/evidence"
    / "protected-provider-recovered.json"
)
CANDIDATE = "care-link-imp10:protected-007"
CANDIDATE_ID = "sha256:9da1df60b9ba68a8ee0e6488504ae1d205e39fa68ba9bc3de34a8fe6bd14c9fc"
REVISED_CANDIDATE = "care-link-imp10:protected-008"
FINAL_CANDIDATE = "care-link-imp10:protected-008-final"
REPLAY_FINAL_CANDIDATE = "care-link-imp10:protected-008-replay-final"
REVISIONS = {
    REVISED_CANDIDATE: CANDIDATE,
    FINAL_CANDIDATE: REVISED_CANDIDATE,
    REPLAY_FINAL_CANDIDATE: FINAL_CANDIDATE,
}
CALICO_SHA256 = "918e7b33ff89d4c08de9462345b1a9fbc68dd9f097704d620ace22f6506b24a3"
DOMAIN = "spiffe://care-link.demo"
NODE_ALIAS = f"{DOMAIN}/node/{SESSION}"
SOCKET = "/run/spire/data/api.sock"
ROLES = frozenset(
    {"core", "data", "identity", "pdp", "journal", "receiver", "training", "runtime", "inference"}
)

type Record = dict[str, object]

TCP = """
import errno, json, socket, sys
try:
    with socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=1.2):
        result = "connected"
except TimeoutError:
    result = "timeout"
except OSError as error:
    result = errno.errorcode.get(error.errno, "socket_error")
print(json.dumps({"result": result}))
"""

NO_CLIENT_CERTIFICATE = """
import json, socket, ssl, sys
context = ssl.create_default_context(cadata=sys.stdin.read())
context.check_hostname = False
context.minimum_version = ssl.TLSVersion.TLSv1_3
try:
    with socket.create_connection((sys.argv[1], 8443), timeout=2) as conn:
        with context.wrap_socket(conn) as tls:
            tls.sendall(b"GET /internal HTTP/1.1\\r\\nHost: qualification\\r\\n\\r\\n")
            result = "response_received" if tls.recv(256) else "closed_without_tls_alert"
except ssl.SSLError as error:
    result = error.reason or "unknown_tls_error"
except OSError as error:
    result = type(error).__name__
print(json.dumps({"result": result}))
"""

UNIX_HTTP = """
import http.client, json, socket, sys
address, route, body = sys.argv[1:]
with socket.socket(socket.AF_UNIX) as conn:
    conn.settimeout(5)
    conn.connect(address)
    http = http.client.HTTPConnection("workload", timeout=5)
    http.sock = conn
    http.request("POST", route, body=body, headers={"Content-Type": "application/json"})
    response = http.getresponse()
    raw = response.read(4096)
    try:
        value = json.loads(raw)
    except ValueError:
        value = None
    print(json.dumps({"status": response.status, "json": value}))
"""

NETWORK_CONTROL = "g10-unadmitted-control"
BRIDGE_PROXY = NAMESPACE + "-model-proxy"
BRIDGE_LEASE = NAMESPACE + "-model"
DEPENDENCIES = (
    ("core", "data", 8443),
    ("core", "identity", 8443),
    ("core", "pdp", 8443),
    ("data", "journal", 8443),
    ("core", "training", 8443),
    ("core", "receiver", 8443),
    ("data", "postgres", 5432),
    ("identity", "keycloak", 8443),
)


def kubectl(*arguments: str, stdin: str | None = None, timeout: int = 300) -> str:
    return run(
        [
            "kubectl",
            "--kubeconfig",
            str(WORK / "kubeconfig"),
            "--context",
            "kind-" + NAMESPACE,
            *arguments,
        ],
        stdin=stdin,
        timeout=timeout,
    )


def _apply(*items: Record) -> str:
    return kubectl(
        "apply",
        "-f",
        "-",
        stdin=json.dumps({"apiVersion": "v1", "kind": "List", "items": items}),
    )


def _owned_node() -> tuple[str, str]:
    lease_path = WORK / "lease.json"
    lease = {"session": SESSION, "cluster": NAMESPACE}
    if lease_path.is_symlink() or json.loads(lease_path.read_text()) != lease:
        raise ValueError("Expected the dedicated G-10 lease file")
    scope = run(
        ["docker", "network", "inspect", "--format", '{{index .Labels "care-link.scope"}}', NETWORK]
    ).strip()
    label = run(
        ["docker", "inspect", "--format", '{{index .Config.Labels "io.x-k8s.kind.cluster"}}', NODE]
    ).strip()
    networks = cast(
        dict[str, dict[str, str]],
        json.loads(
            run(["docker", "inspect", "--format", "{{json .NetworkSettings.Networks}}", NODE])
        ),
    )
    if scope != SESSION or label != NAMESPACE or set(networks) != {NETWORK}:
        raise ValueError("Expected the dedicated G-10 node on its own bridge")
    identifier = run(["docker", "inspect", "--format", "{{.Id}}", NODE]).strip()
    return identifier, networks[NETWORK]["IPAddress"]


def _namespace() -> tuple[Record, Record]:
    return (
        {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": NAMESPACE,
                "labels": {
                    "care-link.session": SESSION,
                    "pod-security.kubernetes.io/enforce": "restricted",
                },
            },
        },
        {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {"name": "default-deny", "namespace": NAMESPACE},
            "spec": {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]},
        },
    )


def _inputs() -> LabInputs:
    pins = cast(Record, json.loads(PINS.read_text()))
    return LabInputs(
        cast(dict[str, str], pins["images"]),
        WORK / "kind",
        WORK / "calico-pinned.yaml",
        WORK,
        cast(str, pins["kind_sha256"]),
        CALICO_SHA256,
    )


def _node_admission() -> tuple[str, str, frozenset[str]]:
    observed = cast(Record, json.loads(kubectl("get", "node", NODE, "-o", "json")))
    statuses = cast(Record, observed["status"])
    addresses = cast(list[dict[str, str]], statuses["addresses"])
    ready = cast(list[dict[str, str]], statuses["conditions"])
    if not any(item["type"] == "Ready" and item["status"] == "True" for item in ready):
        raise ValueError("Expected the leased Kubernetes node to be Ready")
    (ip,) = (item["address"] for item in addresses if item["type"] == "InternalIP")
    names = frozenset(
        {NODE}
        | {item["address"] for item in addresses if item["type"] in {"Hostname", "InternalDNS"}}
    )
    return cast(dict[str, str], observed["metadata"])["uid"], ip, names


def _serving_certificates(node_ip: str, names: frozenset[str]) -> list[str]:
    requests = cast(list[Record], json.loads(kubectl("get", "csr", "-o", "json"))["items"])
    approvals: list[str] = []
    for raw in requests:
        spec = cast(Record, raw["spec"])
        if spec["signerName"] != "kubernetes.io/kubelet-serving":
            continue
        status = cast(Record, raw["status"])
        if status.get("certificate") or status.get("conditions"):
            continue
        identity = "system:node:" + NODE
        request = x509.load_pem_x509_csr(
            base64.b64decode(cast(str, spec["request"]), validate=True)
        )
        common = request.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        san = request.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        dns = set(san.get_values_for_type(x509.DNSName))
        ips = {str(value) for value in san.get_values_for_type(x509.IPAddress)}
        if (
            spec["username"] != identity
            or "system:nodes" not in cast(list[str], spec["groups"])
            or "server auth" not in cast(list[str], spec["usages"])
            or not request.is_signature_valid
            or len(common) != 1
            or common[0].value != identity
            or NODE not in dns
            or not dns <= names
            or ips != {node_ip}
            or len(san) != len(dns) + len(ips)
        ):
            raise ValueError("Unexpected leased kubelet serving CSR identity or SAN")
        name = cast(dict[str, str], raw["metadata"])["name"]
        kubectl("certificate", "approve", name)
        approvals.append(name)
    return approvals


def server(*arguments: str) -> str:
    return kubectl(
        "-n",
        TRUST_NAMESPACE,
        "exec",
        "deployment/spire-server",
        "--",
        "/opt/spire/bin/spire-server",
        *arguments,
    ).strip()


def _publish_roots() -> str:
    pem = server("bundle", "show", "-socketPath", SOCKET, "-format", "pem")
    if not x509.load_pem_x509_certificates(pem.encode()):
        raise ValueError("Missing SPIRE bootstrap roots")
    maps: list[Record] = [
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": name, "namespace": namespace},
            "data": {"bundle.crt": pem},
        }
        for namespace, name in [(TRUST_NAMESPACE, "spire-bundle"), (NAMESPACE, BUNDLE)]
    ]
    _apply(*maps)
    return hashlib.sha256(pem.encode()).hexdigest()


def _register_node() -> None:
    server(
        "entry",
        "create",
        "-socketPath",
        SOCKET,
        "-node",
        "-parentID",
        DOMAIN + "/spire/server",
        "-spiffeID",
        NODE_ALIAS,
        "-selector",
        "k8s_psat:cluster:" + NAMESPACE,
        "-selector",
        "k8s_psat:agent_ns:" + TRUST_NAMESPACE,
        "-selector",
        "k8s_psat:agent_sa:spire-agent",
    )


def _node_image(image: str) -> tuple[str, str]:
    imported = json.loads(run(["docker", "exec", NODE, "crictl", "inspecti", image]))["status"]
    (reference,) = imported["repoDigests"]
    if not re.fullmatch(r"[a-z0-9./_-]+@sha256:[a-f0-9]{64}", reference):
        raise ValueError("Expected an immutable image reference from the leased container runtime")
    if "@" in image and reference.removeprefix("docker.io/") != image.removeprefix("docker.io/"):
        raise ValueError("The local container runtime image differs from the distribution pin")
    return cast(str, reference), cast(str, imported["id"])


def _selector_values(role: str, image: str, envoy: str) -> tuple[str, ...]:
    return (
        "k8s:ns:" + NAMESPACE,
        "k8s:sa:" + role,
        "k8s:container-name:proxy",
        "k8s:container-image:" + envoy,
        "k8s:pod-image:" + image,
    )


def _entry_arguments(role: str, image: str, envoy: str) -> list[str]:
    selectors = [
        part for item in _selector_values(role, image, envoy) for part in ("-selector", item)
    ]
    return [
        "-socketPath",
        SOCKET,
        "-parentID",
        NODE_ALIAS,
        "-spiffeID",
        DOMAIN + "/demo/" + role,
        "-x509SVIDTTL",
        "300",
        *selectors,
    ]


def register_proxy(role: str, image: str, envoy: str) -> None:
    """Admit only the exact proxy container in the role's qualified workload."""
    if role not in ROLES:
        raise ValueError("Unknown protected qualification role")
    server("entry", "create", *_entry_arguments(role, image, envoy))


def _role_registrations() -> dict[str, tuple[str, frozenset[str]]]:
    document = json.loads(server("entry", "show", "-socketPath", SOCKET, "-output", "json"))
    result: dict[str, tuple[str, frozenset[str]]] = {}
    parent = {"trust_domain": "care-link.demo", "path": f"/node/{SESSION}"}
    for entry in document["entries"]:
        identity = entry["spiffe_id"]
        if entry["parent_id"] != parent or identity["trust_domain"] != "care-link.demo":
            continue
        path = cast(str, identity["path"])
        if not path.startswith("/demo/"):
            continue
        role = path.removeprefix("/demo/")
        if role not in ROLES:
            continue
        if role in result or entry["admin"] or entry["x509_svid_ttl"] != 300:
            raise ValueError("Unexpected active workload registration")
        selectors = frozenset(item["type"] + ":" + item["value"] for item in entry["selectors"])
        result[role] = (entry["id"], selectors)
    if frozenset(result) != ROLES or document["next_page_token"]:
        raise ValueError("The current complete G-10 role registrations are required")
    return result


def rebind_candidate(digest: str, output: Path, *, revised_tag: str = REVISED_CANDIDATE) -> None:
    """Transition existing exact image selectors to the approved revision."""
    started = datetime.now(UTC)
    node_id, _ = _owned_node()
    if re.fullmatch(r"sha256:[a-f0-9]{64}", digest) is None:
        raise ValueError("An explicit local revised-candidate digest is required")
    previous_tag = REVISIONS[revised_tag]
    local = run(["docker", "image", "inspect", "--format", "{{.Id}}", revised_tag]).strip()
    if local != digest:
        raise ValueError("The revised-candidate tag does not match the reviewed local digest")
    verify_file(_inputs().kind_binary, _inputs().kind_sha256)
    run([str(WORK / "kind"), "load", "docker-image", revised_tag, "--name", NAMESPACE])
    previous, _ = _node_image(previous_tag)
    revised, node_image_id = _node_image(revised_tag)
    envoy, _ = _node_image(_inputs().image("envoy"))
    registrations = _role_registrations()
    if any(
        selectors
        not in {
            frozenset(_selector_values(role, previous, envoy)),
            frozenset(_selector_values(role, revised, envoy)),
        }
        for role, (_, selectors) in registrations.items()
    ):
        raise ValueError("An existing workload selector differs from the scoped candidate")
    for role, (entry_id, selectors) in registrations.items():
        if selectors == frozenset(_selector_values(role, revised, envoy)):
            continue
        server(
            "entry",
            "update",
            "-entryID",
            entry_id,
            *_entry_arguments(role, revised, envoy),
        )
    observed = _role_registrations()
    if any(
        observed[role] != (entry_id, frozenset(_selector_values(role, revised, envoy)))
        for role, (entry_id, _) in registrations.items()
    ):
        raise ValueError("The revised binding changed more than the expected image selector")
    private_json(
        output,
        {
            "started_at": started.isoformat(),
            "ended_at": datetime.now(UTC).isoformat(),
            "namespace": NAMESPACE,
            "docker_node_id": node_id,
            "previous_image_tag": previous_tag,
            "image_tag": revised_tag,
            "image_id": local,
            "node_image_id": node_image_id,
            "node_repo_digests": [revised],
            "envoy_node_repo_digest": envoy,
            "roles": sorted(observed),
            "registration_ids_preserved": True,
        },
    )


def _install_roles(inputs: LabInputs) -> None:
    # Reuse the established PSAT and CSI topology, changing only the lab binding.
    documents = json.dumps([*spire.manifests(inputs), *csi.manifests(inputs)])
    _apply(*cast(list[Record], json.loads(documents.replace(PREVIOUS_SESSION, SESSION))))


def initialize(output: Path) -> None:
    started = datetime.now(UTC)
    inputs = _inputs()
    verify_file(inputs.kind_binary, inputs.kind_sha256)
    verify_file(inputs.calico_manifest, inputs.calico_sha256)
    docker_id, bridge_ip = _owned_node()
    node_uid, node_ip, names = _node_admission()
    if node_ip != bridge_ip:
        raise ValueError("Leased Kubernetes and bridge addresses differ")
    image = run(["docker", "image", "inspect", "--format", "{{.Id}}", CANDIDATE]).strip()
    if image != CANDIDATE_ID:
        raise ValueError("The current protected-image digest is required")
    run(["docker", "exec", NODE, "crictl", "pull", inputs.image("envoy")], timeout=180)
    app_reference, _ = _node_image(CANDIDATE)
    envoy_reference, _ = _node_image(inputs.image("envoy"))
    _apply(*_namespace())
    approvals = _serving_certificates(node_ip, names)
    _install_roles(inputs)
    kubectl("-n", TRUST_NAMESPACE, "rollout", "status", "deployment/spire-server", "--timeout=200s")
    deadlines = time.monotonic() + 45
    while True:
        approvals.extend(_serving_certificates(node_ip, names))
        try:
            digest = _publish_roots()
            break
        except RuntimeError:
            if time.monotonic() >= deadlines:
                raise
            time.sleep(1)
    _register_node()
    for role in sorted(ROLES):
        register_proxy(role, app_reference, envoy_reference)
    for workload in ("daemonset/spire-agent", "daemonset/spiffe-csi"):
        kubectl("-n", TRUST_NAMESPACE, "rollout", "status", workload, "--timeout=200s")
    kube_csi = json.loads(kubectl("get", "csinode", NODE, "-o", "json"))
    if "csi.spiffe.io" not in {item["name"] for item in kube_csi["spec"]["drivers"]}:
        raise ValueError("SPIFFE CSI registration not observed on the leased node")
    entries = server("entry", "show", "-socketPath", SOCKET)
    if any(f"{DOMAIN}/demo/{role}" not in entries for role in ROLES):
        raise ValueError("A protected workload registration is missing")
    private_json(
        output,
        {
            "started_at": started.isoformat(),
            "ended_at": datetime.now(UTC).isoformat(),
            "namespace": NAMESPACE,
            "trust_namespace": TRUST_NAMESPACE,
            "node": NODE,
            "node_uid": node_uid,
            "docker_id": docker_id,
            "docker_bridge_address": bridge_ip,
            "calico_manifest_sha256": CALICO_SHA256,
            "candidate_image": CANDIDATE,
            "candidate_image_id": image,
            "candidate_cri_image": app_reference,
            "envoy_cri_image": envoy_reference,
            "approved_serving_certificates": sorted(set(approvals)),
            "spire_psat_node_alias": NODE_ALIAS,
            "spire_bundle_sha256": digest,
            "spire_registered_roles": sorted(ROLES),
            "spire_csi_node_ready": True,
            "default_deny_applied": True,
        },
    )


def _control_pod() -> Record:
    candidate = kubectl(
        "-n",
        NAMESPACE,
        "get",
        "deployment/core",
        "-o",
        'jsonpath={.spec.template.spec.containers[?(@.name=="app")].image}',
    ).strip()
    if candidate not in {CANDIDATE, *REVISIONS}:
        raise ValueError("The deployment must use a known G-10 candidate image")
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": NETWORK_CONTROL,
            "namespace": NAMESPACE,
            "labels": {"care-link.session": SESSION, "care-link.fixture": NETWORK_CONTROL},
        },
        "spec": {
            "automountServiceAccountToken": False,
            "securityContext": pod_security(),
            "restartPolicy": "Never",
            "containers": [
                {
                    "name": "app",
                    "image": candidate,
                    "imagePullPolicy": "Never",
                    "command": ["python", "-c", "import time; time.sleep(1200)"],
                    "securityContext": container_security(),
                    "resources": {"limits": {"cpu": "100m", "memory": "64Mi"}},
                }
            ],
        },
    }


def _inside(ref: str, program: str, *arguments: str, stdin: str | None = None) -> Record:
    args = ("-i",) if stdin is not None else ()
    result = kubectl(
        "-n",
        NAMESPACE,
        "exec",
        *args,
        ref,
        "-c",
        "app",
        "--",
        "python",
        "-c",
        program,
        *arguments,
        stdin=stdin,
        timeout=15,
    )
    return cast(Record, json.loads(result))


def _endpoint(service: str) -> str:
    raw = json.loads(
        kubectl(
            "-n",
            NAMESPACE,
            "get",
            "endpointslices",
            "--selector=kubernetes.io/service-name=" + service,
            "-o",
            "json",
        )
    )
    addresses = {
        address
        for item in raw["items"]
        if item["addressType"] == "IPv4"
        for endpoint in item["endpoints"]
        if endpoint["conditions"].get("ready") is True
        for address in endpoint["addresses"]
    }
    (address,) = addresses
    return cast(str, address)


def _connect(caller: str, address: str, port: int) -> str:
    return cast(str, _inside(caller, TCP, address, str(port))["result"])


def _tcp_control(caller: str, target: str, address: str, port: int, restricted: str) -> Record:
    allowed = "deployment/" + caller
    before = _connect(allowed, address, port)
    denied = _connect(restricted, address, port)
    after = _connect(allowed, address, port)
    return {
        "target": target,
        "address": address,
        "port": port,
        "allowed_caller": caller,
        "allowed_before": before,
        "restricted": denied,
        "allowed_after": after,
        "passed": before == "connected" and denied == "timeout" and after == "connected",
    }


def _bridge_control(restricted: str) -> Record:
    proxy = json.loads(run(["docker", "inspect", "--format", "{{json .}}", BRIDGE_PROXY]))
    networks = proxy["NetworkSettings"]["Networks"]
    bindings = cast(Record, proxy["NetworkSettings"].get("Ports") or {})
    if (
        proxy["Config"]["Labels"].get("care-link.scope") != BRIDGE_LEASE
        or not proxy["State"]["Running"]
        or set(networks) != {NETWORK}
        or any(bindings.values())
        or proxy["Config"]["Image"].removeprefix("docker.io/")
        != _inputs().image("envoy").removeprefix("docker.io/")
    ):
        raise ValueError("The independent host bridge must match the current private lease")
    address = ipaddress.IPv4Address(networks[NETWORK]["IPAddress"])
    if not address.is_private or address.is_loopback:
        raise ValueError("The independent host bridge requires its real private network address")
    result = _tcp_control("inference", "host-inference-bridge", str(address), 8443, restricted)
    result["docker_container_id"] = proxy["Id"]
    return result


def _negative_controls(restricted: str, runtime: bool) -> list[Record]:
    dependencies = list(DEPENDENCIES)
    if runtime:
        dependencies.append(("core", "inference", 8443))
    results: list[Record] = []
    for caller, target, port in dependencies:
        known = {"target": target, "port": port, "allowed_caller": caller}
        result: Record
        try:
            result = _tcp_control(caller, target, _endpoint(target), port, restricted)
        except (RuntimeError, ValueError) as error:
            result = {**known, "error": str(error), "passed": False}
        results.append(result)
    if runtime:
        try:
            results.append(_bridge_control(restricted))
        except (RuntimeError, ValueError) as error:
            results.append(
                {"target": "host-inference-bridge", "error": str(error), "passed": False}
            )
    return results


def _proxy_request(caller: str, target: str, path: str, value: Record) -> Record:
    return _inside(
        "deployment/" + caller,
        UNIX_HTTP,
        f"/sockets/outbound/owned/{target}.sock",
        path,
        json.dumps(value),
    )


def _mtls_controls(journal_key: Path) -> Record:
    nonce = str(uuid4())
    read = _proxy_request(
        "data", "journal", "/internal/v1/journal/head", {"nonce": nonce, "command": None}
    )
    raw = read["json"]
    if not isinstance(raw, dict):
        raise ValueError(f"The deployed mTLS Journal read returned HTTP {read['status']}")
    signed = cast(Record, raw)
    key = load_pem_public_key(journal_key.read_bytes())
    if (
        not isinstance(key, Ed25519PublicKey)
        or read["status"] != 200
        or signed.get("nonce") != nonce
        or set(signed) != {"nonce", "state", "signature"}
    ):
        raise ValueError("The deployed mTLS Journal read did not produce a bound signed head")
    signature = cast(str, signed.pop("signature"))
    key.verify(base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)), canonical(signed))
    blocked = _proxy_request("data", "journal", "/internal/v1/journal/unlisted", {})
    bundle = kubectl(
        "-n", NAMESPACE, "get", "configmap", BUNDLE, "-o", "jsonpath={.data.bundle\\.crt}"
    )
    no_certificate = _inside(
        "deployment/data", NO_CLIENT_CERTIFICATE, _endpoint("journal"), stdin=bundle
    )["result"]
    return {
        "positive": {
            "caller": "data",
            "target": "journal",
            "status": read["status"],
            "signed_nonce_bound_head_verified": True,
        },
        "unlisted_path_status": blocked["status"],
        "no_client_certificate": no_certificate,
        "passed": blocked["status"] in {403, 404}
        and no_certificate
        in {"TLSV13_ALERT_CERTIFICATE_REQUIRED", "SSLV3_ALERT_HANDSHAKE_FAILURE"},
    }


def _runtime_to_core() -> Record:
    # The missing operation ID is rejected after the authenticated workload
    # reaches the broker, before it may claim an actual queued task.
    broker = _proxy_request("runtime", "core", "/internal/v1/broker/work", {})
    value = broker["json"]
    message = cast(Record, value).get("message_key") if isinstance(value, dict) else None
    return {
        "caller": "runtime",
        "target": "core",
        "status": broker["status"],
        "message_key": message,
        "passed": broker["status"] == 400 and message == "manual.invalid_identifier",
    }


def _inference_to_bridge() -> Record:
    expected = json.loads(PROVIDER_PINS.read_text())["observations"]
    messages = [{"role": "user", "content": "Synthetic model boundary check."}]
    digest = content_digest(messages)
    route = "/internal/v1/inference/tokenize"
    bad = _proxy_request(
        "inference",
        "host-inference-bridge",
        route,
        {"messages": messages, "content_digest": "0" * 64},
    )
    answer = _proxy_request(
        "inference",
        "host-inference-bridge",
        route,
        {"messages": messages, "content_digest": digest},
    )
    statuses = {"positive_status": answer["status"], "bad_content_digest_status": bad["status"]}
    raw = answer["json"]
    if not isinstance(raw, dict):
        return {**statuses, "passed": False}
    proof = cast(Record, raw)
    pins = ("artifact_digest", "tokenizer_digest", "template_digest", "model_window")
    tokens = proof.get("input_tokens")
    return {
        **statuses,
        "model_pins": {name: proof.get(name) for name in pins},
        "content_digest": proof.get("content_digest"),
        "input_tokens": tokens,
        "passed": (
            answer["status"] == 200
            and bad["status"] == 400
            and proof.get("content_digest") == digest
            and proof.get("model_identifier") == expected["model"]
            and proof.get("loaded_model_id") == expected["model"]
            and all(proof.get(name) == expected[name] for name in pins)
            and isinstance(tokens, int)
            and tokens > 0
        ),
    }


def _pod_images(runtime: bool) -> dict[str, dict[str, str]]:
    required = {role for caller, target, _ in DEPENDENCIES for role in (caller, target)}
    if runtime:
        required.update({"runtime", "inference"})
    pods = json.loads(kubectl("-n", NAMESPACE, "get", "pods", "-o", "json"))
    role_registrations = _role_registrations()
    evidence: dict[str, dict[str, str]] = {}
    for pod in pods["items"]:
        role = pod["metadata"]["labels"].get("app")
        if role not in required or pod["metadata"].get("deletionTimestamp"):
            continue
        if role in evidence:
            raise ValueError("Expected one live workload pod for each probed role")
        containers = pod["status"]["containerStatuses"]
        if not all(container["ready"] for container in containers):
            raise ValueError("All containers in the probed workload must be ready")
        images = {container["name"]: container["imageID"] for container in containers}
        if role in ROLES:
            _, selectors = role_registrations[role]
            if (
                "k8s:pod-image:" + images["app"] not in selectors
                or "k8s:container-image:" + images["proxy"] not in selectors
            ):
                raise ValueError("A running protected role does not match its exact CRI selectors")
        evidence[role] = images
    if evidence.keys() != required:
        raise ValueError("Protected dependency pod inventory is incomplete")
    return evidence


def probe_roles(output: Path, journal_key: Path, *, runtime: bool = False) -> bool:
    started = datetime.now(UTC)
    node, _ = _owned_node()
    restricted = "deployment/runtime" if runtime else "pod/" + NETWORK_CONTROL
    if not runtime:
        kubectl("create", "-f", "-", stdin=json.dumps(_control_pod()))
    try:
        if runtime:
            kubectl("-n", NAMESPACE, "rollout", "status", restricted, "--timeout=90s")
        else:
            kubectl("-n", NAMESPACE, "wait", "--for=condition=Ready", restricted, "--timeout=90s")
        images = _pod_images(runtime)
        controls = _negative_controls(restricted, runtime)
        try:
            workload = _mtls_controls(journal_key)
        except (InvalidSignature, RuntimeError, ValueError) as error:
            workload = {"passed": False, "error": str(error) or type(error).__name__}
        core = _runtime_to_core() if runtime else None
        bridge = None
        if runtime:
            try:
                bridge = _inference_to_bridge()
            except (RuntimeError, ValueError) as error:
                bridge = {"passed": False, "error": str(error)}
    finally:
        if not runtime:
            kubectl("-n", NAMESPACE, "delete", "pod", NETWORK_CONTROL, "--wait=true", timeout=60)
    passed = all(row["passed"] for row in controls) and bool(workload["passed"])
    passed = passed and (core is None or bool(core["passed"]))
    passed = passed and (bridge is None or bool(bridge["passed"]))
    private_json(
        output,
        {
            "started_at": started.isoformat(),
            "ended_at": datetime.now(UTC).isoformat(),
            "namespace": NAMESPACE,
            "docker_node_id": node,
            "restricted_caller": restricted,
            "actual_runtime": runtime,
            "pod_image_ids": images,
            "runtime_to_core_mtls": core,
            "inference_to_host_bridge_mtls": bridge,
            "tcp_controls": controls,
            "workload_controls": workload,
            "passed": passed,
        },
    )
    return passed


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--probe-with-journal-key", type=Path)
    image = parser.add_mutually_exclusive_group()
    image.add_argument("--bind-revised-image", metavar="SHA256")
    image.add_argument("--bind-final-image", metavar="SHA256")
    image.add_argument("--bind-replay-final-image", metavar="SHA256")
    parser.add_argument("--runtime", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        parser.error("Live bootstrap requires the current cluster lease and --execute")
    if digest := (args.bind_revised_image or args.bind_final_image or args.bind_replay_final_image):
        if args.probe_with_journal_key or args.runtime:
            parser.error("Candidate rebinding and role probing are separate operations")
        tags = {
            args.bind_revised_image: REVISED_CANDIDATE,
            args.bind_final_image: FINAL_CANDIDATE,
            args.bind_replay_final_image: REPLAY_FINAL_CANDIDATE,
        }
        rebind_candidate(digest, args.output, revised_tag=tags[digest])
    elif args.probe_with_journal_key:
        raise SystemExit(
            0 if probe_roles(args.output, args.probe_with_journal_key, runtime=args.runtime) else 1
        )
    else:
        if args.runtime:
            parser.error("--runtime requires --probe-with-journal-key")
        initialize(args.output)
