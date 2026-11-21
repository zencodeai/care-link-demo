"""Disposable Linux check of the Runtime-to-Core socket and restrictive fence.

Run as root inside a fresh network-none container with /tmp on tmpfs. Only the
supervisor starts privileged. This fixture uses ephemeral mTLS over a Unix
socket and production Core trust checks. It does not provision Envoy or SPIRE.
"""

import errno
import http.server
import json
import os
import socket
import socketserver
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NoReturn, cast
from urllib.parse import quote
from uuid import uuid4

import httpx
import uvicorn
from care_link_core.assistance_broker import InferenceBroker
from care_link_core.assistance_broker.ports import Coordinator, InferencePort
from care_link_core.assistance_broker.routes import attach_broker_routes
from care_link_domain import ManualError
from care_link_runtime import HttpBrokerTransport
from care_link_workload_trust import (
    BackendVerifier,
    FenceServer,
    FenceStore,
    TrustDenied,
    UnixFenceClient,
    WorkloadEnforcer,
)
from care_link_workload_trust.uvicorn_adapter import ProtectedUnixH11Protocol
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse

from tools.imp06_runtime.routes import inbound
from tools.imp06_runtime.trust import runtime_verifier

CORE, PROXY, RUNTIME, RESTRICT, FENCE_GROUP = 65532, 65531, 65530, 65529, 65528
CORE_ID = "spiffe://care-link.demo/demo/core"
RUNTIME_ID = "spiffe://care-link.demo/demo/runtime"
CLAIM = "/internal/v1/broker/work"
ORIGIN = "https://core:8443"
EMPTY = {"task_id": None, "task_revision": None, "fence": None}


def require(condition: bool, label: str) -> None:
    if not condition:
        raise RuntimeError(label)


def bind_directory(path: Path, uid: int, gid: int, mode: int) -> None:
    path.mkdir(mode=mode)
    path.chmod(mode)
    os.chown(path, uid, gid)


def loopback_only() -> bool:
    active = {
        name
        for _, name in socket.if_nameindex()
        if int((Path("/sys/class/net") / name / "flags").read_text().strip(), 16) & 1
    }
    return active == {"lo"} and len(Path("/proc/net/route").read_text().splitlines()) == 1


def capabilities() -> str:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("CapEff:"):
            return line.split()[1]
    raise RuntimeError("effective capability evidence unavailable")


def certificates(folder: Path) -> None:
    """Issue workload-fixture credentials wholly inside the disposable tmpfs."""
    now = datetime.now(UTC)
    key = ec.generate_private_key(ec.SECP256R1())
    root_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "IMP06 fixture CA")])

    def builder() -> x509.CertificateBuilder:
        return (
            x509.CertificateBuilder()
            .issuer_name(root_name)
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(minutes=10))
        )

    def usage(ca: bool) -> x509.KeyUsage:
        return x509.KeyUsage(True, False, False, False, False, ca, ca, False, False)

    identifier = x509.SubjectKeyIdentifier.from_public_key(key.public_key())
    ca = (
        builder()
        .subject_name(root_name)
        .public_key(key.public_key())
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(identifier, critical=False)
        .add_extension(usage(True), critical=True)
        .sign(key, hashes.SHA256())
    )
    (folder / "ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    for role, uid, identity in (("proxy", PROXY, CORE_ID), ("runtime", RUNTIME, RUNTIME_ID)):
        private = ec.generate_private_key(ec.SECP256R1())
        names: list[x509.GeneralName] = [x509.UniformResourceIdentifier(identity)]
        if role == "proxy":
            names.append(x509.DNSName("core"))
        purpose = (
            ExtendedKeyUsageOID.SERVER_AUTH if role == "proxy" else ExtendedKeyUsageOID.CLIENT_AUTH
        )
        leaf = (
            builder()
            .subject_name(x509.Name([]))
            .public_key(private.public_key())
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName(names), critical=True)
            .add_extension(x509.ExtendedKeyUsage([purpose]), critical=False)
            .add_extension(usage(False), critical=True)
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(identifier),
                critical=False,
            )
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(private.public_key()), critical=False
            )
            .sign(key, hashes.SHA256())
        )
        (folder / (role + ".pem")).write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
        key_path = folder / (role + ".key")
        with key_path.open("xb") as stream:
            stream.write(
                private.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
        key_path.chmod(0o600)
        os.chown(key_path, uid, uid)


def trust(folder: Path, role: str) -> ssl.SSLContext:
    purpose = ssl.Purpose.CLIENT_AUTH if role == "proxy" else ssl.Purpose.SERVER_AUTH
    tls = ssl.create_default_context(purpose, cafile=str(folder / "ca.pem"))
    tls.minimum_version = ssl.TLSVersion.TLSv1_3
    tls.verify_mode = ssl.CERT_REQUIRED
    tls.load_cert_chain(folder / (role + ".pem"), folder / (role + ".key"))
    return tls


def excluded(*_args: object) -> NoReturn:
    raise RuntimeError("isolated empty-queue fixture invoked a non-claim operation")


def serve_core(folder: Path) -> None:
    verify = BackendVerifier(
        PROXY,
        inbound("core"),
        UnixFenceClient(folder / "fence/control.sock", 0),
        backend_uid=CORE,
        local_spiffe_id=CORE_ID,
    )
    broker = InferenceBroker(
        cast(Coordinator, None),
        cast(InferencePort, None),
        actor_for_task=excluded,
        release=excluded,
    )
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

    async def error_response(_request: Request, error: Exception) -> JSONResponse:
        if not isinstance(error, ManualError):
            raise error
        return JSONResponse({"code": error.code}, status_code=error.status)

    app.add_exception_handler(ManualError, error_response)
    attach_broker_routes(app, broker, runtime_verifier(verify))
    listener = socket.socket(socket.AF_UNIX)
    path = folder / "backend/claim.sock"
    listener.bind(str(path))
    path.chmod(0o660)
    listener.listen()
    config = uvicorn.Config(
        app, http=ProtectedUnixH11Protocol, proxy_headers=False, log_level="warning"
    )
    uvicorn.Server(config).run(sockets=[listener])


class Relay(socketserver.UnixStreamServer):
    """Fixture mTLS ingress for one authenticated Core broker API."""

    def __init__(self, folder: Path) -> None:
        self.tls = trust(folder, "proxy")
        root = x509.load_pem_x509_certificate((folder / "ca.pem").read_bytes())
        self.check = WorkloadEnforcer(
            PROXY,
            (root,),
            inbound("core"),
            UnixFenceClient(folder / "fence/control.sock", 0),
            local_spiffe_id=CORE_ID,
        )
        self.backend = folder / "backend/claim.sock"
        entrance = folder / "egress/core.sock"
        super().__init__(str(entrance), RelayRequest)
        entrance.chmod(0o660)

    def get_request(self) -> tuple[socket.socket, str]:
        raw, address = super().get_request()
        raw.settimeout(4)
        try:
            return self.tls.wrap_socket(raw, server_side=True), address
        except OSError:
            raw.close()
            raise


class RelayRequest(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_POST(self) -> None:
        relay = cast(Relay, self.server)
        tls = cast(ssl.SSLSocket, self.connection)
        peer_certificate = tls.getpeercert(binary_form=True)
        if peer_certificate is None:
            self.send_error(403)
            return
        leaf = x509.load_der_x509_certificate(peer_certificate)
        uri = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        (identity,) = uri.get_values_for_type(x509.UniformResourceIdentifier)
        certificate = quote(leaf.public_bytes(serialization.Encoding.PEM), safe="")
        size = self.headers.get("Content-Length")
        status, body = 403, b""
        if size == "2" and self.rfile.read(2) == b"{}":
            try:
                admission = relay.check.authorize(
                    os.geteuid(), "POST", self.path, f"Cert={certificate};URI={identity}"
                )
            except TrustDenied:
                pass
            else:
                expires = admission.certificate_expires_at.isoformat().replace("+00:00", "Z")
                headers = {
                    "Idempotency-Key": self.headers.get("Idempotency-Key", ""),
                    "x-care-link-verified-spiffe": admission.spiffe_id,
                    "x-care-link-fence-generation": str(admission.fence_generation),
                    "x-care-link-certificate-digest": admission.certificate_digest,
                    "x-care-link-certificate-expires-at": expires,
                }
                transport = httpx.HTTPTransport(uds=str(relay.backend))
                with httpx.Client(transport=transport, trust_env=False, timeout=2) as backend:
                    response = backend.post("http://core" + self.path, json={}, headers=headers)
                status, body = response.status_code, response.content
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def runtime(folder: Path) -> None:
    require(os.geteuid() == RUNTIME and int(capabilities(), 16) == 0, "runtime credentials")
    require(loopback_only(), "runtime interface confinement")
    for family, address in (
        (socket.AF_INET, ("192.0.2.1", 443)),
        (socket.AF_INET6, ("2001:db8::1", 443)),
    ):
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            probe.settimeout(1)
            unreachable = probe.connect_ex(address)
        require(unreachable in (errno.ENETUNREACH, errno.EHOSTUNREACH), "runtime has IP route")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1)
        require(probe.connect_ex(("127.0.0.1", 1234)) == errno.ECONNREFUSED, "port 1234 accessible")
    with socket.socket(socket.AF_UNIX) as probe:
        try:
            probe.connect(str(folder / "backend/claim.sock"))
        except PermissionError:
            pass
        else:
            raise RuntimeError("Runtime accessed the protected Core backend")
    uncredentialed = ssl.create_default_context(cafile=str(folder / "ca.pem"))
    transport = httpx.HTTPTransport(uds=str(folder / "egress/core.sock"), verify=uncredentialed)
    with httpx.Client(transport=transport, trust_env=False, timeout=2) as client:
        try:
            client.post(ORIGIN + CLAIM, json={})
        except (httpx.ConnectError, httpx.ReadError, httpx.WriteError):
            pass
        else:
            raise RuntimeError("credential-free connection reached Core through fixture mTLS")
    tls = trust(folder, "runtime")
    transport = httpx.HTTPTransport(uds=str(folder / "egress/core.sock"), verify=tls)
    broker = HttpBrokerTransport(tls, transport=transport)
    used_streams: list[object] = []

    def capture(response: httpx.Response) -> None:
        used_streams.append(response.extensions.get("network_stream"))

    broker.client.event_hooks["response"].append(capture)
    try:
        require(broker.poll_work() == EMPTY, "Core did not return validated empty work item")
        denied = broker.client.post(ORIGIN + "/internal/v1/inference/jobs", json={})
        require(denied.status_code == 403, "Runtime unexpectedly admitted inference route")
        print("ready", flush=True)
        require(sys.stdin.readline() == "restricted\n", "fence supervisor missing")
        try:
            broker.poll_work()
        except httpx.HTTPStatusError as error:
            require(error.response.status_code == 403, "unexpected revocation status")
        else:
            raise RuntimeError("revoked Runtime retained Core access")
        require(
            len(used_streams) == 3
            and used_streams[0] is not None
            and all(stream is used_streams[0] for stream in used_streams),
            "Runtime transport failed to reuse the original TLS connection",
        )
    finally:
        broker.close()


def spoof_proxy(folder: Path) -> None:
    """Reach the backend as the fixture's group member with a different kernel UID."""
    transport = httpx.HTTPTransport(uds=str(folder / "backend/claim.sock"))
    with httpx.Client(transport=transport, trust_env=False, timeout=2) as client:
        expires = (datetime.now(UTC) + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
        response = client.post(
            "http://core" + CLAIM,
            json={},
            headers={
                "Idempotency-Key": str(uuid4()),
                "x-care-link-verified-spiffe": RUNTIME_ID,
                "x-care-link-fence-generation": "0",
                "x-care-link-certificate-digest": "a" * 64,
                "x-care-link-certificate-expires-at": expires,
            },
        )
        require(response.status_code == 403, "forged proxy attestation passed the kernel UID check")


def spawn(folder: Path, role: str, uid: int, group: int, *extra: int) -> subprocess.Popen[str]:
    return subprocess.Popen(  # noqa: S603
        [sys.executable, __file__, role, str(folder)],
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        user=uid,
        group=group,
        extra_groups=extra,
    )


def wait_socket(path: Path, process: subprocess.Popen[str]) -> None:
    for _index in range(100):
        require(process.poll() is None, "fixture service exited before readiness")
        if path.is_socket():
            return
        time.sleep(0.05)
    raise RuntimeError("fixture socket did not become ready")


def main() -> None:
    require(sys.platform == "linux" and os.geteuid() == 0, "requires disposable Linux container")
    require(loopback_only(), "supervisor requires a network-none namespace")
    with tempfile.TemporaryDirectory(prefix="care-link-imp06-004-isolation-", dir="/tmp") as tmp:
        folder = Path(tmp)
        folder.chmod(0o711)
        bind_directory(folder / "backend", CORE, PROXY, 0o710)
        bind_directory(folder / "egress", PROXY, RUNTIME, 0o710)
        bind_directory(folder / "fence", 0, FENCE_GROUP, 0o710)
        bind_directory(folder / "ledger", 0, 0, 0o700)
        certificates(folder)
        store = FenceStore(folder / "ledger", 0)
        store.initialize(frozenset({CORE_ID, RUNTIME_ID}))
        fence = FenceServer(
            folder / "fence/control.sock",
            store,
            owner_uid=0,
            access_gid=FENCE_GROUP,
            read_uids=frozenset({CORE, PROXY}),
            restrict_uid=RESTRICT,
        )
        thread = threading.Thread(
            target=fence.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        thread.start()
        children: list[subprocess.Popen[str]] = []
        try:
            core = spawn(folder, "core", CORE, PROXY, FENCE_GROUP)
            children.append(core)
            wait_socket(folder / "backend/claim.sock", core)
            proxy = spawn(folder, "proxy", PROXY, RUNTIME, PROXY, FENCE_GROUP)
            children.append(proxy)
            wait_socket(folder / "egress/core.sock", proxy)
            spoof = spawn(folder, "spoof", RESTRICT, RESTRICT, PROXY)
            children.append(spoof)
            require(spoof.wait(timeout=5) == 0, "Core backend kernel UID challenge failed")
            worker = spawn(folder, "runtime", RUNTIME, RUNTIME)
            children.append(worker)
            require(
                worker.stdout is not None and worker.stdout.readline() == "ready\n",
                "baseline isolation checks failed",
            )
            restrict = spawn(folder, "restrict", RESTRICT, RESTRICT, FENCE_GROUP)
            children.append(restrict)
            require(restrict.wait(timeout=5) == 0, "persistent fence restriction failed")
            if worker.stdin is None:
                raise RuntimeError("runtime stdin unavailable")
            worker.stdin.write("restricted\n")
            worker.stdin.flush()
            require(worker.wait(timeout=6) == 0, "live runtime fence check failed")
            print(
                json.dumps(
                    {
                        "scope": "disposable Linux; fixture mTLS; protected Core route",
                        "only_active_interface": "lo",
                        "runtime_effective_capabilities": 0,
                        "non_loopback_ip_connect": "IPv4 and IPv6 unreachable",
                        "runtime_namespace_port_1234": "connection refused",
                        "direct_core_backend_socket": "permission denied",
                        "wrong_kernel_uid_forged_attestation": 403,
                        "fixture_mtls_without_client_certificate": "connection rejected",
                        "runtime_core_claim": "200, schema-valid empty work item",
                        "runtime_inference_route": 403,
                        "runtime_core_claim_after_fence": "403 on the original TLS connection",
                        "fence_generation": store.read().generation,
                        "envoy_spire_role_topology": "not_run",
                        "release_qualification": "not_run",
                    },
                    indent=2,
                )
            )
        finally:
            for process in reversed(children):
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=3)
            fence.shutdown()
            thread.join()
            fence.server_close()


if __name__ == "__main__":
    if len(sys.argv) == 1:
        main()
    else:
        role, workspace = sys.argv[1:]
        location = Path(workspace)
        if role == "core":
            serve_core(location)
        elif role == "proxy":
            with Relay(location) as server:
                server.serve_forever()
        elif role == "runtime":
            runtime(location)
        elif role == "spoof":
            spoof_proxy(location)
        elif role == "restrict":
            client = UnixFenceClient(location / "fence/control.sock", 0)
            client.restrict(RUNTIME_ID, str(uuid4()), 0)
        else:
            raise ValueError("unknown fixture role")
