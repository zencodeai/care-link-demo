"""New-target socket and independent-root denials; no accepted credentials accessed."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.imp04_deployment import docker
from tools.imp04_deployment.config import PRIVATE, record


def verify() -> dict[str, object]:
    bundle = (PRIVATE / "spire-bundle.pem").read_text()
    script = r"""
import sys, json, socket, ssl, os, datetime
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID

root = sys.argv[1]
out = []
for foreign in (False, True):
    ctx = ssl.create_default_context(cadata=root)
    ctx.check_hostname = False
    files = []
    if foreign:
        now = datetime.datetime.now(datetime.timezone.utc)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "IMP04 diagnostic foreign root")])
        ca = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(seconds=5))
            .not_valid_after(now + datetime.timedelta(minutes=5))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
            .sign(key, hashes.SHA256())
        )
        leafkey = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        leaf = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(leafkey.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(seconds=5))
            .not_valid_after(now + datetime.timedelta(minutes=5))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
            .add_extension(
                x509.SubjectAlternativeName(
                    [x509.UniformResourceIdentifier("spiffe://care-link.demo/demo/core")]
                ),
                False,
            )
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), False)
            .sign(key, hashes.SHA256())
        )
        # Ephemeral diagnostic private key stays in memory-backed file descriptors.
        for data in (
            leaf.public_bytes(serialization.Encoding.PEM)
            + ca.public_bytes(serialization.Encoding.PEM),
            leafkey.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
        ):
            fd = os.memfd_create("imp04-foreign-diagnostic", 0)
            os.write(fd, data)
            files.append(fd)
        ctx.load_cert_chain("/proc/self/fd/" + str(files[0]), "/proc/self/fd/" + str(files[1]))
    response = b""
    error = None
    peer = None
    try:
        with socket.create_connection(("172.29.44.13", 8443), timeout=2) as sock:
            with ctx.wrap_socket(sock, server_hostname="data.imp04.mesh") as tls:
                cert = tls.getpeercert()
                peer = {
                    "uris": [v for k, v in cert.get("subjectAltName", []) if k == "URI"],
                    "not_after": cert.get("notAfter"),
                }
                tls.sendall(
                    b"POST /internal/v1/data/plan_read HTTP/1.1\r\n"
                    b"Host: data.imp04.mesh\r\nContent-Type: application/json\r\n"
                    b"Content-Length: 2\r\nConnection: close\r\n\r\n{}"
                )
                response = tls.recv(1024)
    except (ssl.SSLError, OSError) as exc:
        error = type(exc).__name__
    finally:
        for fd in files:
            os.close(fd)
    # A server may return a TLS alert or reject without an HTTP response.
    denied = bool(error) or not response or response.startswith((b"HTTP/1.1 403", b"HTTP/1.1 401"))
    out.append(
        {
            "probe": "foreign_CA_same_logical_core" if foreign else "no_client_SVID",
            "denied": denied,
            "error_class": error,
            "server_public_identity": peer,
            "http_status_line": response.split(b"\r\n")[0].decode(errors="replace")
            if response.startswith(b"HTTP/")
            else None,
        }
    )
print(json.dumps(out))
"""
    tls = json.loads(docker.exec("care-link-imp04-002-ingress", ["python", "-c", script, bundle]))
    script = r"""
import json, httpx
from pathlib import Path

p = "/run/care-link-imp03-002/core/backend/app.sock"
with httpx.Client(transport=httpx.HTTPTransport(uds=p)) as c:
    r = c.get(
        "http://localhost/dev/health",
        headers={"X-Spiffe-Id": "spiffe://care-link.demo/demo/core"},
        timeout=2,
    )
    print(
        json.dumps(
            {
                "probe": "direct_backend_forged_header",
                "status": r.status_code,
                "denied": r.status_code == 403,
                "cross_role_data_mount_absent": not Path(
                    "/run/care-link-imp03-002/configuration/data/config.json"
                ).exists(),
            }
        )
    )
"""
    backend = record(
        json.loads(docker.exec("care-link-imp04-002-core-app", ["python", "-c", script]))
    )
    return {
        "target": "care-link-imp04-002",
        "tls_probes": tls,
        "backend_probe": backend,
        "status": "passed" if all(p["denied"] for p in tls) and backend["denied"] else "failed",
        "accepted_private_credentials_accessed": False,
        "foreign_test_is_diagnostic_CA_not_an_accepted_SVID": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = verify()
    args.output.write_text(json.dumps(value, indent=2) + "\n")
    print(json.dumps(value, indent=2))
    if value["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
