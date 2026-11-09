"""Exact-node serving-certificate approval and explicit SPIRE registrations."""

import base64
import json
import os
import stat
from pathlib import Path
from typing import cast

from cryptography import x509
from cryptography.x509.oid import NameOID

from .commands import kubectl, verify_session
from .host_support import AGENT_ID
from .model import CLUSTER, NAMESPACE, LabInputs
from .spire import TRUST_NAMESPACE


def approve_kubelet_serving(inputs: LabInputs) -> list[str]:
    verify_session(inputs)
    value = cast(dict[str, object], json.loads(kubectl(inputs, "get", "csr", "-o", "json")))
    approved: list[str] = []
    for raw in cast(list[dict[str, object]], value["items"]):
        spec = cast(dict[str, object], raw["spec"])
        if spec.get("signerName") != "kubernetes.io/kubelet-serving":
            continue
        if spec.get("username") != "system:node:" + CLUSTER + "-control-plane":
            raise ValueError("unexpected kubelet serving CSR identity")
        request = x509.load_pem_x509_csr(base64.b64decode(cast(str, spec["request"])))
        common = request.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        if len(common) != 1 or common[0].value != "system:node:" + CLUSTER + "-control-plane":
            raise ValueError("unexpected kubelet serving certificate subject")
        if not request.is_signature_valid or "server auth" not in cast(list[str], spec["usages"]):
            raise ValueError("invalid kubelet serving CSR")
        name = cast(str, cast(dict[str, object], raw["metadata"])["name"])
        kubectl(inputs, "certificate", "approve", name)
        approved.append(name)
    return approved


def server_command(inputs: LabInputs, *args: str) -> str:
    return kubectl(
        inputs,
        "-n",
        TRUST_NAMESPACE,
        "exec",
        "deployment/spire-server",
        "--",
        "/opt/spire/bin/spire-server",
        *args,
    )


def publish_bundle(inputs: LabInputs) -> str:
    verify_session(inputs)
    pem = server_command(
        inputs, "bundle", "show", "-socketPath", "/run/spire/data/api.sock", "-format", "pem"
    )
    if not x509.load_pem_x509_certificates(pem.encode()):
        raise ValueError("missing SPIRE bootstrap roots")
    for namespace, name in [(TRUST_NAMESPACE, "spire-bundle"), (NAMESPACE, "imp02-spire-bundle")]:
        value = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": name, "namespace": namespace},
            "data": {"bundle.crt": pem},
        }
        kubectl(inputs, "apply", "-f", "-", stdin=json.dumps(value))
    return pem


def register_node_alias(inputs: LabInputs) -> str:
    return server_command(
        inputs,
        "entry",
        "create",
        "-socketPath",
        "/run/spire/data/api.sock",
        "-node",
        "-parentID",
        "spiffe://care-link.demo/spire/server",
        "-spiffeID",
        "spiffe://care-link.demo/node/imp02-002",
        "-selector",
        "k8s_psat:cluster:" + CLUSTER,
        "-selector",
        "k8s_psat:agent_ns:" + TRUST_NAMESPACE,
        "-selector",
        "k8s_psat:agent_sa:spire-agent",
    )


def register_proxy(inputs: LabInputs, role: str, application_image: str, *, ttl: int = 300) -> str:
    if role not in {"identity", "main"} or not 30 <= ttl <= 3600:
        raise ValueError("bounded known proxy role and TTL required")
    return server_command(
        inputs,
        "entry",
        "create",
        "-socketPath",
        "/run/spire/data/api.sock",
        "-parentID",
        "spiffe://care-link.demo/node/imp02-002",
        "-spiffeID",
        "spiffe://care-link.demo/lab/" + role,
        "-x509SVIDTTL",
        str(ttl),
        "-selector",
        "k8s:ns:" + NAMESPACE,
        "-selector",
        "k8s:sa:" + role,
        "-selector",
        "k8s:container-name:proxy",
        "-selector",
        "k8s:container-image:" + inputs.image("envoy"),
        "-selector",
        "k8s:pod-image:" + application_image,
    )


def generate_host_token(inputs: LabInputs, path: Path) -> None:
    """Capture a single-use node bootstrap credential directly to private storage."""
    parent = path.parent.stat()
    if parent.st_uid != os.geteuid() or stat.S_IMODE(parent.st_mode) != 0o700:
        raise ValueError("host join token requires owner-only credential directory")
    response = json.loads(
        server_command(
            inputs,
            "token",
            "generate",
            "-socketPath",
            "/run/spire/data/api.sock",
            "-spiffeID",
            AGENT_ID,
            "-ttl",
            "600",
            "-output",
            "json",
        )
    )
    value = response.get("value")
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError("invalid private node bootstrap response")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def register_host_proxy(inputs: LabInputs, role: str = "help", *, ttl: int = 300) -> str:
    uid = {"help": 21002, "identity_provider": 21004}.get(role)
    if uid is None or not 30 <= ttl <= 3600:
        raise ValueError("explicit admitted host proxy role and bounded TTL required")
    return server_command(
        inputs,
        "entry",
        "create",
        "-socketPath",
        "/run/spire/data/api.sock",
        "-parentID",
        AGENT_ID,
        "-spiffeID",
        "spiffe://care-link.demo/lab/" + role,
        "-x509SVIDTTL",
        str(ttl),
        "-selector",
        "unix:uid:" + str(uid),
    )
