"""Scoped deployed negative probes; private material never leaves its custodian.

The coordinator owns creation/execution. Container-side commands emit only
enumerated outcomes, HTTP status and public certificate metadata. Expiry tests
consume an actual short-lived SPIRE SVID; they never synthesize a certificate.
"""

import argparse
import errno
import hashlib
import http.client
import json
import os
import socket
import ssl
import stat
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import httpx
import psycopg
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from tools.imp02_application.mesh import MeshTransport
from tools.imp03_runtime.config import load, record, text
from tools.imp03_shared import docker
from tools.imp03_shared.deployment import create, name
from tools.imp03_shared.model import CONFIG, MESH_IP, ROLE_UID, ROOT, mount
from tools.imp03_shared.profiles import ACTIVE

Record = dict[str, object]
PEER_PREFIX = "spiffe://care-link.demo/demo/"
TOOLS = Path("/probe-tools")
LAST_RESPONSE: Record = {}


def denied_permission(path: Path, *, connect: bool = False) -> Record:
    """Only a kernel permission error counts; missing/broken paths do not pass."""
    try:
        if connect:
            with socket.socket(socket.AF_UNIX) as client:
                client.settimeout(1)
                client.connect(str(path))
        else:
            with path.open("rb") as stream:
                stream.read(1)
    except OSError as error:
        return {
            "permission_denied": error.errno in {errno.EACCES, errno.EPERM},
            "errno": error.errno,
        }
    return {"permission_denied": False, "errno": None}


def custody_probe(role: str) -> Record:
    if role not in ROLE_UID or os.geteuid() != ROLE_UID[role]:
        raise ValueError("Exact application probe UID required")
    cases: list[Record] = []
    for sibling in ROLE_UID:
        if sibling == role:
            continue
        root = Path("/probe") / sibling
        result = denied_permission(root / "configuration/config.json")
        cases.append({"sibling": sibling, "kind": "credential", **result})
        if sibling in {"core", "data"}:
            result = denied_permission(root / "outbound/identity.sock", connect=True)
            cases.append({"sibling": sibling, "kind": "egress_socket", **result})
    return {
        "role": role,
        "uid": os.geteuid(),
        "cases": cases,
        "passed": all(case["permission_denied"] is True for case in cases),
        "scope": "Expanded read-only sibling mounts prove kernel custody; normal apps lack them.",
    }


def wrong_egress_probe() -> Record:
    if os.geteuid() != ROLE_UID["data"]:
        raise ValueError("Actual data application UID required")
    cfg = load(Path(CONFIG) / "data/config.json")
    target = record(record(cfg["outbound"])["identity"])
    origin = text(target, "origin")
    with httpx.Client(
        transport=MeshTransport(Path(text(target, "socket")), origin),
        trust_env=False,
        follow_redirects=False,
    ) as client:
        response = client.get(
            origin + "/bff/main/v1/auth/session",
            headers={
                "x-care-link-verified-spiffe": PEER_PREFIX + "core",
                "x-care-link-fence-generation": "0",
                "x-care-link-certificate-expires-at": "2099-01-01T00:00:00Z",
                "x-forwarded-client-cert": "URI=" + PEER_PREFIX + "core",
            },
            timeout=3,
        )
    return {
        "origin_role": "data",
        "target_role": "identity",
        "path": "/bff/main/v1/auth/session",
        "spoofed_claim": "core",
        "status": response.status_code,
        "passed": response.status_code in {403, 404},
        "enforcement": "local_route_absent" if response.status_code == 404 else "route_denied",
        "scope": (
            "Actual role-owned egress rejects forbidden path/header claims; no upstream TLS claim."
        ),
    }


def database_source_probe() -> Record:
    if os.geteuid() != ROLE_UID["data"]:
        raise ValueError("Exact database credential custodian UID required")
    cfg = load(Path(CONFIG) / "data/config.json")
    values = conninfo_to_dict(text(cfg, "store_dsn"))
    if (
        values.get("dbname") != "imp03_runtime_002"
        or values.get("user") != "imp03_data_runtime_002"
    ):
        raise ValueError("Exact fresh target database/login required")
    if values.get("sslmode") != "verify-full" or not values.get("sslrootcert"):
        raise ValueError("Unchanged verify-full TLS required")
    values.update(hostaddr="172.29.35.10", port="5432")
    try:
        with psycopg.connect(make_conninfo("", **values), connect_timeout=3):
            return {"passed": False, "hba_rejected": False, "sqlstate": None}
    except psycopg.Error as error:
        # Examine the diagnostic in memory, never publish it or the DSN.
        reason = error.diag.message_primary or str(error)
        hba = (
            error.sqlstate in {None, "28000"}
            and "pg_hba.conf" in reason
            and "172.29.35.50" in reason
            and ("rejects connection" in reason or "no pg_hba.conf entry" in reason)
        )
        return {
            "passed": hba,
            "hba_rejected": hba,
            "sqlstate": error.sqlstate,
            "source": "172.29.35.50",
            "tls_profile": "verify-full; original certificate hostname retained",
        }


def _context(bundle: Path, cert: Path | None = None, key: Path | None = None) -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=str(bundle))
    # SPIFFE service certificates identify the server by URI SAN, not DNS SAN.
    # The verified leaf is checked for the exact URI before any request bytes.
    context.check_hostname = False
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    if cert is not None and key is not None:
        context.load_cert_chain(str(cert), str(key))
    return context


def _connect(context: ssl.SSLContext, address: str, role: str) -> ssl.SSLSocket:
    if role not in ROLE_UID or not address.startswith("172.29.34."):
        raise ValueError("Exact continuation mesh target required")
    raw = socket.create_connection((address, 8443), timeout=4)
    try:
        stream = context.wrap_socket(raw, server_hostname=role + ".imp03.mesh")
        leaf = x509.load_der_x509_certificate(cast(bytes, stream.getpeercert(binary_form=True)))
        names = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        if names.get_values_for_type(x509.UniformResourceIdentifier) != [PEER_PREFIX + role]:
            stream.close()
            raise ValueError("Verified server SPIFFE URI differs from the expected role")
        return stream
    except BaseException:
        raw.close()
        raise


def _request(stream: ssl.SSLSocket, path: str, *, method: str = "POST", spoof: bool = True) -> int:
    body = b"{}" if method == "POST" else b""
    headers = (
        (
            f"x-care-link-verified-spiffe: {PEER_PREFIX}core\r\n"
            "x-care-link-fence-generation: 0\r\n"
            "x-care-link-certificate-expires-at: 2099-01-01T00:00:00Z\r\n"
        )
        if spoof
        else ""
    )
    request = (
        f"{method} {path} HTTP/1.1\r\nHost: probe.imp03.mesh\r\n"
        "Content-Type: application/json\r\nConnection: keep-alive\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"{headers}\r\n"
    ).encode() + body
    stream.sendall(request)
    response = http.client.HTTPResponse(stream)
    try:
        response.begin()
        content = response.read(65537)
        if len(content) > 65536:
            raise ValueError("Probe response exceeds the bounded metadata limit")
        LAST_RESPONSE.clear()
        try:
            value = record(json.loads(content))
            if value.get("message_key") == "manual.invalid_request":
                LAST_RESPONSE.update(code=value.get("code"), message_key="manual.invalid_request")
        except (ValueError, UnicodeError):
            pass
        return response.status
    finally:
        response.close()


def no_svid_probe(bundle: Path = TOOLS / "bundle.pem") -> Record:
    context = _context(bundle)
    try:
        with _connect(context, MESH_IP["identity"], "identity") as stream:
            # TLS1.3 can deliver the mandatory-client-certificate alert after
            # wrap_socket returns. Read that alert before racing an HTTP write.
            try:
                received = stream.recv(1)
                return {
                    "passed": False,
                    "tls_client_certificate_rejected": False,
                    "unclassified_tls_close": not received,
                }
            except TimeoutError:
                status = _request(stream, "/bff/main/v1/auth/session", method="GET")
        return {"passed": False, "tls_client_certificate_rejected": False, "status": status}
    except ssl.SSLError as error:
        reason = str(error.reason)
        rejected = "CERTIFICATE_REQUIRED" in reason
        return {
            "passed": rejected,
            "tls_client_certificate_rejected": rejected,
            "tls_reason": reason,
            "status": None,
        }


def _issued_svid(
    role: str, api: Path, binary: Path, directory: Path
) -> tuple[Path, Path, x509.Certificate]:
    if os.geteuid() != 22002 or role not in ROLE_UID:
        raise ValueError("Exact attested proxy UID and named role required")
    if binary != TOOLS / "spire-agent" or (
        not api.is_absolute()
        or ".." in api.parts
        or api.name != "agent.sock"
        or not str(api).startswith((ROOT + "/", "/probe-api/"))
    ):
        raise ValueError("Only the exact mounted executable and scoped API path are permitted")
    if not api.is_socket() or not binary.is_file():
        raise ValueError("Assigned API socket and pinned probe executable required")
    directory.mkdir(mode=0o700, exist_ok=False)
    response = subprocess.run(  # noqa: S603 - caller supplies fixed scoped mounted executable
        [
            str(binary),
            "api",
            "fetch",
            "x509",
            "-socketPath",
            str(api),
            "-write",
            str(directory),
            "-silent",
        ],
        capture_output=True,
        check=False,
        timeout=10,
    )
    if response.returncode:
        raise ValueError("Actual SPIRE SVID fetch failed; private diagnostics suppressed")
    leaves: list[tuple[Path, x509.Certificate]] = []
    keys: list[Path] = []
    for path in directory.iterdir():
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
            raise ValueError("Private SVID output custody differs from the probe")
        path.chmod(0o600)
        value = path.read_bytes()
        if b"PRIVATE KEY-----" in value:
            keys.append(path)
        if value.startswith(b"-----BEGIN CERTIFICATE-----"):
            certificates = x509.load_pem_x509_certificates(value)
            if not certificates:
                continue
            leaf = certificates[0]
            try:
                names = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            except x509.ExtensionNotFound:
                continue
            if names.get_values_for_type(x509.UniformResourceIdentifier) == [PEER_PREFIX + role]:
                leaves.append((path, leaf))
    if len(leaves) != 1 or len(keys) != 1:
        raise ValueError("One exact role SVID and private key required")
    cert_path, leaf = leaves[0]
    key = serialization.load_pem_private_key(keys[0].read_bytes(), password=None)
    if key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    ) != leaf.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    ):
        raise ValueError("Actual SVID key binding differs")
    return cert_path, keys[0], leaf


def direct_role_probe(api: Path, binary: Path, bundle: Path) -> Record:
    cert, key, leaf = _issued_svid("data", api, binary, Path("/tmp/svid"))  # noqa: S108
    with _connect(_context(bundle, cert, key), MESH_IP["identity"], "identity") as stream:
        status = _request(stream, "/bff/main/v1/auth/session", method="GET")
    return {
        "passed": status == 403,
        "status": status,
        "client_spiffe_id": PEER_PREFIX + "data",
        "server_spiffe_id": PEER_PREFIX + "identity",
        "leaf_sha256": hashlib.sha256(leaf.public_bytes(serialization.Encoding.DER)).hexdigest(),
        "scope": (
            "Actual data SVID direct TLS; spoofed core headers deny at the core-only BFF route."
        ),
    }


def expiry_probe(api: Path, binary: Path, bundle: Path) -> Record:
    cert, key, leaf = _issued_svid("core", api, binary, Path("/tmp/svid"))  # noqa: S108
    remaining = (leaf.not_valid_after_utc - datetime.now(UTC)).total_seconds()
    if not 3 <= remaining <= 90:
        raise ValueError("Actual fresh SVID must expire within 3–90 seconds for this probe")
    context = _context(bundle, cert, key)
    stream = _connect(context, MESH_IP["data"], "data")
    result: Record = {
        "client_spiffe_id": PEER_PREFIX + "core",
        "server_spiffe_id": PEER_PREFIX + "data",
        "not_after": leaf.not_valid_after_utc.isoformat(),
        "leaf_sha256": hashlib.sha256(leaf.public_bytes(serialization.Encoding.DER)).hexdigest(),
    }
    try:
        descriptor = stream.fileno()
        first = _request(stream, "/internal/v1/data/session_create", spoof=False)
        result["preexpiry_status"] = first
        result["preexpiry_error"] = dict(LAST_RESPONSE)
        if first not in {400, 422} or LAST_RESPONSE != {
            "code": "INVALID_REQUEST",
            "message_key": "manual.invalid_request",
        }:
            result["passed"] = False
            result["reason"] = "Pre-expiry transport was not admitted; no expiry claim"
            return result
        kept_open = True
        while datetime.now(UTC) < leaf.not_valid_after_utc:
            remaining = (leaf.not_valid_after_utc - datetime.now(UTC)).total_seconds()
            time.sleep(min(1.0, max(0.05, remaining)))
            if datetime.now(UTC) >= leaf.not_valid_after_utc:
                break
            try:
                status = _request(stream, "/internal/v1/data/session_create", spoof=False)
                if status != first:
                    kept_open = False
                    break
            except (OSError, http.client.HTTPException):
                kept_open = False
                break
        delay = (leaf.not_valid_after_utc - datetime.now(UTC)).total_seconds() + 0.2
        if delay > 0:
            time.sleep(delay)
        result["same_connection_preserved_until_expiry"] = (
            kept_open and stream.fileno() == descriptor
        )
        try:
            status = _request(stream, "/internal/v1/data/session_create", spoof=False)
            result["same_connection_postexpiry_status"] = status
            result["same_connection_postexpiry_denied"] = kept_open and status == 403
        except (OSError, http.client.HTTPException):
            result["same_connection_postexpiry_status"] = None
            result["same_connection_postexpiry_denied"] = kept_open
    finally:
        stream.close()
    # This is a second TLS socket with the SAME saved expired credential, not
    # a fresh fetch from an agent that may meanwhile have renewed its own SVID.
    try:
        with _connect(context, MESH_IP["data"], "data") as fresh:
            try:
                fresh.recv(1)
                status = None
            except TimeoutError:
                status = _request(fresh, "/internal/v1/data/session_create", spoof=False)
        result["new_connection_status"] = status
        result["new_connection_tls_expiry_rejected"] = False
    except ssl.SSLError as error:
        reason = str(error.reason)
        result["new_connection_tls_reason"] = reason
        result["expiry_specific_tls_alert"] = "EXPIRED" in reason
        result["new_connection_tls_expiry_rejected"] = (
            reason in {"SSLV3_ALERT_CERTIFICATE_EXPIRED", "SSLV3_ALERT_CERTIFICATE_UNKNOWN"}
            and datetime.now(UTC) >= leaf.not_valid_after_utc
        )
        result["new_connection_scope"] = (
            "Same saved credential admitted before expiry, now expired and rejected by a remote "
            "certificate alert; generic certificate alert does not identify "
            "the server's internal cause."
        )
    result["passed"] = (
        result.get("same_connection_preserved_until_expiry") is True
        and result.get("same_connection_postexpiry_denied") is True
        and result.get("new_connection_tls_expiry_rejected") is True
    )
    return result


def _inside(container: str, args: list[str]) -> Record:
    # Feed current source over stdin so its exact version is independent of an
    # already built serving image. No credential is placed in argv/stdout.
    value = docker.exec(
        container,
        [
            "/usr/bin/env",
            "CARE_LINK_IMP03_PROFILE=continuation-001",
            "python",
            "-",
            *args,
            "--report-only",
        ],
        stdin=Path(__file__).read_text(),
    )
    return record(json.loads(value))


def run_basic() -> Record:
    if ACTIVE.name != "continuation-001":
        raise ValueError("Explicit fresh continuation profile required")
    cases: list[Record] = []
    for role, uid in ROLE_UID.items():
        suffix = "negative-custody-" + role
        mounts = [
            mount(sibling + "-config", "/probe/" + sibling + "/configuration", readonly=True)
            for sibling in ROLE_UID
            if sibling != role
        ] + [
            mount(sibling + "-outbound", "/probe/" + sibling + "/outbound", readonly=True)
            for sibling in ("core", "data")
            if sibling != role
        ]
        create(
            suffix,
            ["python", "-c", "import time;time.sleep(120)"],
            mounts,
            uid=uid,
            groups=["22002", "22999"],
        )
        docker.start(name(suffix))
        try:
            cases.append(
                {"kind": "kernel_custody", **_inside(name(suffix), ["custody", "--role", role])}
            )
        finally:
            docker.stop(name(suffix))
            docker.remove_owned(name(suffix))
    cases.append({"kind": "role_egress_route", **_inside(name("data-app"), ["egress"])})
    create(
        "negative-db-source",
        ["python", "-c", "import time;time.sleep(120)"],
        [mount("data-config", CONFIG + "/data", readonly=True)],
        uid=ROLE_UID["data"],
        network=ACTIVE.prefix + "-database",
        ip="172.29.35.50",
    )
    docker.start(name("negative-db-source"))
    try:
        cases.append(
            {"kind": "database_source", **_inside(name("negative-db-source"), ["database"])}
        )
    finally:
        docker.stop(name("negative-db-source"))
        docker.remove_owned(name("negative-db-source"))
    return {"cases": cases, "passed": all(case.get("passed") is True for case in cases)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=["basic", "custody", "egress", "database", "no-svid", "direct-role", "expiry"],
    )
    parser.add_argument("--role", choices=list(ROLE_UID))
    parser.add_argument("--api", type=Path)
    parser.add_argument("--binary", type=Path, default=TOOLS / "spire-agent")
    parser.add_argument("--bundle", type=Path, default=TOOLS / "bundle.pem")
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    if args.command == "basic":
        result = run_basic()
    elif args.command == "custody":
        if args.role is None:
            parser.error("custody requires --role")
        result = custody_probe(args.role)
    elif args.command == "egress":
        result = wrong_egress_probe()
    elif args.command == "database":
        result = database_source_probe()
    elif args.command == "no-svid":
        result = no_svid_probe(args.bundle)
    else:
        if args.api is None:
            parser.error("actual SVID probes require assigned --api")
        result = (direct_role_probe if args.command == "direct-role" else expiry_probe)(
            args.api, args.binary, args.bundle
        )
    print(json.dumps(result))
    if result.get("passed") is not True and not args.report_only:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
