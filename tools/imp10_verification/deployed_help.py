"""Run independent IMP-10 Help and Static through a coordinated protected outage."""

from __future__ import annotations

import argparse
import base64
import hashlib
import ipaddress
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from time import monotonic, sleep, time
from typing import cast
from urllib.parse import parse_qs, urljoin, urlsplit
from uuid import uuid4

import httpx
from care_link_static import Publication
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from services.data.tests.imp10_outage_help import (
    _static_publication,  # pyright: ignore[reportPrivateUsage]
)
from tools.demo.secrets import totp
from tools.imp02_application.prepare import pem, write
from tools.imp02_application.tls import PinnedAddressTransport
from tools.imp03_runtime.config import Record, load, record, text
from tools.imp10_runtime.mesh import _render_role  # pyright: ignore[reportPrivateUsage]
from tools.imp10_runtime.routes import HELP_AUTH_ROUTES, HELP_IDENTITY_ROUTES
from tools.imp10_verification.kind_boundary import process

ROOT = Path(__file__).resolve().parents[2]
SCOPE = "care-link-imp10-008"
HOST = SCOPE + "-host"
LABEL = "care-link.scope=" + HOST
BRIDGE = SCOPE + "-net"
NODE = SCOPE + "-control-plane"
TRUST_NAMESPACE = SCOPE + "-trust"
WORKSPACE = Path("/private/tmp/care-link-imp10-008-help")
DEFAULT_KUBECONFIG = Path("/private/tmp/care-link-imp10-008-assets/kubeconfig")
HELP_ORIGIN = "https://help.imp10-008.localhost:39444"
STATIC_ORIGIN = "http://static.imp10-008.localhost:39445"
PROVIDER_ORIGIN = "https://id.imp10-008.localhost:39443"
ISSUER = PROVIDER_ORIGIN + "/realms/imp10-008-qualified"
CALLBACK = HELP_ORIGIN + "/v1/auth/callback"
IDENTITY_ORIGIN = "https://identity.imp10-008.invalid"
AGENT_ID = "spiffe://care-link.demo/host/imp10-008"
HELP_ID = "spiffe://care-link.demo/demo/help"
REQUESTS = "/help/v1/requests"
COOKIE = "__Host-care_link_help"
APP_UID = 21013
PROXY_UID = 21002
PORT = 8444

DIRECTORIES = {
    "backend": (APP_UID, PROXY_UID, 0o710),
    "outbound": (PROXY_UID, APP_UID, 0o2710),
    "spool": (APP_UID, APP_UID, 0o700),
    "app-config": (APP_UID, APP_UID, 0o700),
    "proxy-config": (PROXY_UID, PROXY_UID, 0o700),
    "agent-config": (0, 0, 0o700),
    "agent-data": (0, 0, 0o700),
    "workload-api": (0, 0, 0o755),
}
FILE_OWNERS = {
    "app-config": ("help.json", "identity.pub"),
    "proxy-config": ("envoy.json", "tls.crt", "tls.key"),
    "agent-config": ("agent.conf", "join.token", "bundle.crt"),
}

SEED = f"""
from pathlib import Path
import base64, json, os, sys
sources = json.load(sys.stdin)
for name, (uid, gid, mode) in {DIRECTORIES!r}.items():
    directory = Path('/volumes', name)
    os.chown(directory, uid, gid)
    directory.chmod(mode)
    for entry in {FILE_OWNERS!r}.get(name, ()):
        if entry in sources:
            target = directory / entry
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(base64.b64decode(sources[entry], validate=True))
                stream.flush()
                os.fsync(stream.fileno())
            os.chown(target, uid, gid)
"""

SPOOL = """
import hashlib, json, sqlite3
from care_link_help.audit import verify_history
connection = sqlite3.connect('file:/spool/help.sqlite?mode=ro', uri=True)
connection.row_factory = sqlite3.Row
connection.execute('BEGIN')
verify_history(connection)
values = {}
for name in ('request', 'operation', 'decision_nonce', 'local_event'):
    rows = connection.execute('SELECT * FROM ' + name + ' ORDER BY rowid')
    values[name] = [list(row) for row in rows]
print(json.dumps({
    'counts': {name: len(rows) for name, rows in values.items()},
    'sha256': hashlib.sha256(json.dumps(values, separators=(',', ':')).encode()).hexdigest(),
}))
"""

SOCKET = """
import http.client, socket, sys
path = '/run/care-link/backend/help.sock'
connection = http.client.HTTPConnection('help.localhost', timeout=2)
def connect():
    connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.sock.settimeout(2)
    connection.sock.connect(path)
connection.connect = connect
try:
    connection.request('GET', '/help/health')
    response = connection.getresponse()
    print(response.status)
except PermissionError:
    print('kernel_denied')
"""


def require(actual: bool, message: str) -> None:
    if not actual:
        raise ValueError(message)


def command(*arguments: str, timeout: int = 40, stdin: str | None = None) -> str:
    result = subprocess.run(  # noqa: S603
        arguments, input=stdin, text=True, capture_output=True, check=False, timeout=timeout
    )
    if result.returncode:
        # Neither provider URLs nor configuration/credential command output belongs in receipts.
        raise RuntimeError(f"{arguments[0]} {arguments[1]} failed ({result.returncode})")
    return result.stdout.strip()


def docker(*args: str, stdin: str | None = None) -> str:
    return command("docker", *args, stdin=stdin)


def kubectl(kubeconfig: Path, *args: str) -> str:
    return command("kubectl", "--kubeconfig", str(kubeconfig), "--context", "kind-" + SCOPE, *args)


def spire(kubeconfig: Path, *args: str) -> str:
    operation, subcommand, *options = args
    return kubectl(
        kubeconfig,
        "-n",
        TRUST_NAMESPACE,
        "exec",
        "deployment/spire-server",
        "--",
        "/opt/spire/bin/spire-server",
        operation,
        subcommand,
        "-socketPath",
        "/run/spire/data/api.sock",
        *options,
    )


def mount(name: str, path: str, *, read_only: bool = False) -> tuple[str, str]:
    return "--mount", f"type=volume,source={HOST}-{name},target={path}" + (
        ",readonly" if read_only else ""
    )


@contextmanager
def owned_container(name: str, image: str, options: list[str], args: list[str]) -> Iterator[str]:
    full_name = f"{HOST}-{name}"
    identity = docker(
        "run",
        "--detach",
        "--pull=never",
        "--label",
        LABEL,
        "--name",
        full_name,
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--memory",
        "192m",
        "--pids-limit",
        "96",
        *options,
        image,
        *args,
    )
    try:
        yield identity
    finally:
        if (
            docker("inspect", "--format", '{{index .Config.Labels "care-link.scope"}}', identity)
            != HOST
        ):
            raise ValueError("Refusing to remove an unowned host container")
        docker("rm", "--force", identity)


@contextmanager
def owned_volumes() -> Iterator[None]:
    created: list[str] = []
    try:
        existing = docker("volume", "ls", "--format", "{{.Name}}").splitlines()
        for name in DIRECTORIES:
            full_name = HOST + "-" + name
            require(full_name not in existing, "Dedicated Help volume names must be fresh")
            created.append(docker("volume", "create", "--label", LABEL, full_name))
        yield
    finally:
        for volume in reversed(created):
            if (
                docker(
                    "volume", "inspect", "--format", '{{index .Labels "care-link.scope"}}', volume
                )
                != HOST
            ):
                raise ValueError("Refusing to remove an unowned host volume")
            docker("volume", "rm", volume)


def bridge_addresses() -> tuple[str, str]:
    bridge = record(json.loads(docker("network", "inspect", "--format", "{{json .}}", BRIDGE)))
    labels = record(bridge["Labels"])
    require(
        labels.get("care-link.scope") == "imp10-008", "Unexpected lease owner for Docker bridge"
    )
    node_cluster = docker(
        "inspect", "--format", '{{index .Config.Labels "io.x-k8s.kind.cluster"}}', NODE
    )
    require(node_cluster == SCOPE, "Unexpected Kind lease owner")
    members = record(bridge["Containers"])
    nodes = [record(item) for item in members.values() if record(item).get("Name") == NODE]
    require(len(nodes) == 1, "Kind node must be present on the owned bridge")
    ipam = cast(list[Record], record(bridge["IPAM"])["Config"])
    subnet = ipaddress.ip_network(
        next(text(row, "Subnet") for row in ipam if ":" not in text(row, "Subnet"))
    )
    node_ip = text(nodes[0], "IPv4Address").split("/")[0]
    proxy_ip = str(subnet[-17])
    taken = {text(record(item), "IPv4Address").split("/")[0] for item in members.values()}
    require(proxy_ip not in taken, "The reserved host Help proxy IP is occupied")
    return node_ip, proxy_ip


def browser_tls() -> tuple[bytes, bytes]:
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CARE-Link synthetic 008 Help")])
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    hostname = urlsplit(HELP_ORIGIN).hostname
    if hostname is None:
        raise ValueError("Explicit Help browser origin required")
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=2))
        .not_valid_after(now + timedelta(hours=12))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(key, hashes.SHA256())
    )
    return certificate.public_bytes(serialization.Encoding.PEM), pem(key)


def prepare(
    workspace: Path,
    identity_key: Path,
    node: str,
    proxy: str,
    kubeconfig: Path,
    products: Record,
    *,
    preflight: bool,
) -> tuple[Path, str]:
    workspace.mkdir(mode=0o700)
    sources = workspace / "sources"
    sources.mkdir(mode=0o700)
    certificate, key = browser_tls()
    write(sources / "tls.crt", certificate)
    write(sources / "tls.key", key)
    write(
        sources / "identity.pub",
        identity_key.read_bytes() if not preflight else preflight_public_key(),
    )
    app: Record = {
        "session": "imp10-protected",
        "role": "help",
        "uid": APP_UID,
        "proxy_uid": PROXY_UID,
        "backend_socket": "/run/care-link/backend/help.sock",
        "outbound_socket": "/run/care-link/outbound/identity.sock",
        "identity_origin": IDENTITY_ORIGIN,
        "origin": HELP_ORIGIN,
        "static_origin": STATIC_ORIGIN,
        "spool": "/spool/help.sqlite",
        "signing_key_id": "imp10-008-identity",
        "signing_public_key": "/config/identity.pub",
        "web_directory": "/app/apps/web/dist",
    }
    write(sources / "help.json", json.dumps(app).encode())
    images, versions = record(products["images"]), record(products["selected_versions"])
    pins = {
        "envoy_image": images["envoy"],
        "envoy_version": versions["envoy"],
        "spire_image": images["spire_agent"],
        "spire_version": versions["spire"],
        "svid_ttl_seconds": 300,
    }
    roles: dict[str, Record] = {
        "identity": {"address": node, "port": 30443},
        "help": {
            "backend_socket": app["backend_socket"],
            "outbound": {"identity": app["outbound_socket"]},
            "spire_socket": "/run/spire/sockets/agent.sock",
            "browser": {
                "address": proxy,
                "origin": HELP_ORIGIN,
                "port": PORT,
                "certificate": "/config/tls.crt",
                "private_key": "/config/tls.key",
            },
        },
    }
    proxy_config = _render_role(
        "help", roles, {"identity": {"help": HELP_AUTH_ROUTES | HELP_IDENTITY_ROUTES}}, pins
    )["help-envoy.json"]
    envoy = json.dumps(proxy_config, sort_keys=True).encode()
    write(sources / "envoy.json", envoy)
    if not preflight:
        bootstrap(sources, node, kubeconfig)
    return sources, hashlib.sha256(envoy).hexdigest()


def preflight_public_key() -> bytes:
    # Preflight has no authority. Its ephemeral signing pin only enables startup.
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    return (
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    )


def bootstrap(sources: Path, node: str, kubeconfig: Path) -> None:
    response = record(
        json.loads(
            spire(
                kubeconfig,
                "token",
                "generate",
                "-spiffeID",
                AGENT_ID,
                "-ttl",
                "600",
                "-output",
                "json",
            )
        )
    )
    write(sources / "join.token", text(response, "value").encode())
    bundle = spire(kubeconfig, "bundle", "show", "-format", "pem").encode()
    require(bool(x509.load_pem_x509_certificates(bundle)), "No live SPIRE trust bundle")
    write(sources / "bundle.crt", bundle)
    found = record(
        json.loads(spire(kubeconfig, "entry", "show", "-spiffeID", HELP_ID, "-output", "json"))
    )
    entries = cast(list[Record], found["entries"])
    if entries:
        require(
            len(entries) == 1
            and entries[0].get("parent_id")
            == {"trust_domain": "care-link.demo", "path": "/host/imp10-008"}
            and entries[0].get("selectors") == [{"type": "unix", "value": f"uid:{PROXY_UID}"}]
            and entries[0].get("x509_svid_ttl") == 300
            and entries[0].get("admin") is False
            and entries[0].get("downstream") is False
            and entries[0].get("dns_names") == []
            and entries[0].get("federates_with") == [],
            "Existing Help SPIRE registration differs from the owned lease",
        )
    else:
        spire(
            kubeconfig,
            "entry",
            "create",
            "-parentID",
            AGENT_ID,
            "-spiffeID",
            HELP_ID,
            "-x509SVIDTTL",
            "300",
            "-selector",
            f"unix:uid:{PROXY_UID}",
        )
    configuration = f"""
agent {{
  trust_domain = "care-link.demo"
  data_dir = "/run/spire/data"
  server_address = "{node}"
  server_port = "30881"
  socket_path = "/run/spire/sockets/agent.sock"
  trust_bundle_path = "/config/bundle.crt"
  join_token_file = "/config/join.token"
  log_level = "WARN"
}}
plugins {{
  NodeAttestor "join_token" {{ plugin_data {{ }} }}
  KeyManager "disk" {{ plugin_data {{ directory = "/run/spire/data/keys" }} }}
  WorkloadAttestor "unix" {{ plugin_data {{ }} }}
}}
"""
    write(sources / "agent.conf", configuration.encode())


def seed(image: str, sources: Path) -> None:
    volumes = [option for name in DIRECTORIES for option in mount(name, "/volumes/" + name)]
    with owned_container(
        "seed",
        image,
        [
            "--network=none",
            "--user=0:0",
            "--cap-add=CHOWN",
            "--cap-add=FOWNER",
            "--cap-add=DAC_OVERRIDE",
            *volumes,
        ],
        ["python", "-c", "from time import sleep; sleep(120)"],
    ) as identity:
        payload = {
            path.name: base64.b64encode(path.read_bytes()).decode() for path in sources.iterdir()
        }
        docker("exec", "-i", identity, "python", "-c", SEED, stdin=json.dumps(payload))


def wait_for[T](action: Callable[[], T], label: str, seconds: float = 40) -> T:
    end = monotonic() + seconds
    while True:
        try:
            return action()
        except (RuntimeError, ValueError, httpx.HTTPError) as exc:
            if monotonic() >= end:
                raise RuntimeError(label) from exc
            sleep(0.3)


def socket_check(app: str, image: str, *, require_uid_guard: bool) -> dict[str, object]:
    def acceptable() -> str:
        result = docker("exec", "--user", f"{PROXY_UID}:{PROXY_UID}", app, "python", "-c", SOCKET)
        require(result == "200", "Assigned proxy cannot reach Help backend")
        return result

    allowed = wait_for(acceptable, "Help backend did not become ready")
    denied = docker(
        "run",
        "--rm",
        "--pull=never",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--user",
        "21014:21014",
        *mount("backend", "/run/care-link/backend", read_only=True),
        image,
        "python",
        "-c",
        SOCKET,
    )
    require(denied == "kernel_denied", "An unrelated Linux UID reached private Help")
    app_uid = docker("exec", "--user", f"{APP_UID}:{APP_UID}", app, "python", "-c", SOCKET)
    if require_uid_guard:
        require(app_uid == "403", "Help backend accepted a same-container non-proxy kernel peer")
    return {
        "expected_proxy_health": int(allowed),
        "application_uid_http": int(app_uid),
        "unrelated_uid": denied,
    }


class BrowserTransport(httpx.BaseTransport):
    """Only exact leased browser origins can receive synthetic credentials."""

    def __init__(self, help_ca: Path, provider_ca: Path) -> None:
        self.routes = {
            HELP_ORIGIN: PinnedAddressTransport(HELP_ORIGIN, "127.0.0.1", str(help_ca)),
            PROVIDER_ORIGIN: PinnedAddressTransport(PROVIDER_ORIGIN, "127.0.0.1", str(provider_ca)),
        }

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        origin = str(request.url.copy_with(path="/", query=None, fragment=None)).removesuffix("/")
        if origin not in self.routes or request.url.userinfo:
            raise ValueError("Browser destination is outside the Help lease")
        return self.routes[origin].handle_request(request)

    def close(self) -> None:
        for route in self.routes.values():
            route.close()


class LoginForm(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.forms: list[tuple[str, dict[str, str], set[str]]] = []
        self.current: tuple[str, dict[str, str], set[str]] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "form" and (values.get("method") or "").lower() == "post":
            self.current = (values.get("action") or "", {}, set())
        if tag == "input" and self.current is not None:
            if name := values.get("name"):
                self.current[2].add(name)
                if values.get("type") == "hidden":
                    self.current[1][name] = values.get("value") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self.current is not None:
            self.forms.append(self.current)
            self.current = None


def login_form(response: httpx.Response) -> tuple[str, dict[str, str], set[str]]:
    require(
        response.status_code == 200 and len(response.content) < 256 * 1024,
        "Help provider login failed",
    )
    parser = LoginForm()
    parser.feed(response.text)
    forms = [item for item in parser.forms if item[2] & {"password", "otp"}]
    require(len(forms) == 1, "Unrecognized leased Keycloak form")
    target, fields, names = forms[0]
    destination = urljoin(str(response.request.url), target)
    require(
        destination.startswith(ISSUER + "/login-actions/")
        and "/login-actions/" in urlsplit(destination).path,
        "Unexpected Keycloak form destination",
    )
    return destination, fields, names


@dataclass(frozen=True)
class Actor:
    role: str
    username: str
    password: str = field(repr=False)
    otp_seed: str | None = field(default=None, repr=False)


def sign_in(client: httpx.Client, actor: Actor) -> str:
    bootstrap_response = client.get(HELP_ORIGIN + "/v1/auth/csrf")
    require(
        bootstrap_response.status_code == 200,
        f"Help CSRF bootstrap returned {bootstrap_response.status_code}",
    )
    csrf = text(record(bootstrap_response.json()), "csrf_token")
    start = client.post(
        HELP_ORIGIN + "/v1/auth/login",
        json={
            "role": actor.role,
            "return_route": "participant" if actor.role == "pid" else "workforce",
            "locale": "en-CA",
        },
        headers={"Origin": HELP_ORIGIN, "X-CSRF-Token": csrf},
    )
    require(start.status_code == 200, f"Help login initiation returned {start.status_code}")
    authorization = text(record(start.json()), "authorization_url")
    query = parse_qs(urlsplit(authorization).query)
    require(
        authorization.startswith(ISSUER + "/protocol/openid-connect/auth?")
        and query.get("client_id") == ["care-link-imp10-008-help"]
        and query.get("redirect_uri") == [CALLBACK]
        and query.get("code_challenge_method") == ["S256"],
        "Unexpected Help client or issuer",
    )
    response = client.get(authorization)
    used: set[str] = set()
    for _ in range(8):
        if response.is_redirect:
            target = urljoin(str(response.request.url), response.headers.get("location", ""))
            require(
                target.startswith(ISSUER + "/") or target.startswith(CALLBACK + "?"),
                "Unexpected Help login redirect",
            )
            response = client.get(target, headers={"Accept": "text/html"})
            if target.startswith(HELP_ORIGIN):
                if response.status_code != 303:
                    category = "transport"
                    try:
                        body = record(response.json())
                        safe = body.get("message_key", body.get("state"))
                        if isinstance(safe, str) and re.fullmatch(r"[a-z_.]{1,64}", safe):
                            category = safe
                    except ValueError:
                        pass
                    raise ValueError(
                        f"Help {actor.role} callback returned {response.status_code} ({category})"
                    )
                break
            continue
        target, fields, names = login_form(response)
        method = "password" if "password" in names else "otp"
        require(method not in used, "Leased Keycloak rejected a login factor")
        used.add(method)
        if method == "password":
            fields.update(username=actor.username, password=actor.password)
        elif actor.otp_seed is not None:
            if time() % 30 > 21:
                sleep(30 - time() % 30 + 0.2)
            fields["otp"], _ = totp(actor.otp_seed)
        else:
            raise ValueError("Leased Help actor requires an independently supplied MFA factor")
        response = client.post(target, data=fields)
    else:
        raise ValueError("Leased Help login exceeded its redirect budget")
    view = client.get(HELP_ORIGIN + "/v1/auth/session")
    require(
        view.status_code == 200 and record(view.json()).get("role") == actor.role,
        "Help role mismatch",
    )
    require(
        bool(client.cookies.get(COOKIE)) and used == {"password", "otp"},
        "No distinct Help cookie or provider login",
    )
    return text(record(client.get(HELP_ORIGIN + "/v1/auth/csrf").json()), "csrf_token")


def receive_json(client: httpx.Client, path: str, expected: int = 200) -> Record:
    response = client.get(HELP_ORIGIN + path)
    require(response.status_code == expected, f"Help GET {path} returned {response.status_code}")
    return record(response.json())


def create_request(client: httpx.Client, csrf: str, locale: str, key: str) -> httpx.Response:
    return client.post(
        HELP_ORIGIN + REQUESTS,
        headers={"Origin": HELP_ORIGIN, "X-CSRF-Token": csrf, "Idempotency-Key": key},
        json={"locale": locale, "jurisdiction": None},
    )


def positive(client: httpx.Client, csrf: str, locale: str, key: str) -> tuple[str, Record]:
    started = monotonic()
    response = create_request(client, csrf, locale, key)
    require(response.status_code == 200, f"Private Help create returned {response.status_code}")
    view = record(response.json())
    require(
        view.get("state") == "recorded" and view.get("connection_confirmed") is False,
        "Help falsely confirmed a connection or lost the recorded request",
    )
    identifier = text(view, "id")
    require(
        receive_json(client, REQUESTS + "/" + identifier) == view, "Help status lost the record"
    )
    return identifier, {
        "locale": locale,
        "state": "recorded",
        "connection_confirmed": False,
        "elapsed_ms": round((monotonic() - started) * 1000, 3),
    }


def private_unavailable(
    client: httpx.Client,
    worker: httpx.Client,
    csrf: str,
    worker_csrf: str,
    app: str,
    identifier: str,
    key: str,
) -> Record:
    def custody() -> Record:
        return record(json.loads(docker("exec", app, "python", "-c", SPOOL)))

    snapshot = custody()
    url = HELP_ORIGIN + REQUESTS + "/" + identifier
    expected = {
        "message_key": "help.identity_unavailable",
        "static_url": STATIC_ORIGIN + "/fallback",
    }
    calls = {
        "status": lambda: client.get(url),
        "new_create": lambda: create_request(client, csrf, "en-CA", str(uuid4())),
        "retry_create": lambda: create_request(client, csrf, "en-CA", key),
        "accept": lambda: worker.post(
            url + "/accept",
            headers={
                "Origin": HELP_ORIGIN,
                "X-CSRF-Token": worker_csrf,
                "Idempotency-Key": str(uuid4()),
            },
            json={"expected_revision": "1"},
        ),
    }
    observations: Record = {}
    for name, call in calls.items():
        response = call()
        require(
            response.status_code == 503 and response.json() == expected,
            f"Private Help {name} failed to return typed Identity-unavailable state",
        )
        observations[name] = {
            "status": response.status_code,
            "elapsed_ms": round(response.elapsed.total_seconds() * 1000, 3),
        }
    require(
        custody() == snapshot, "The private Help spool or audit changed without current authority"
    )
    return {"private_operations": observations, "durable_spool_unchanged": True, "spool": snapshot}


def verify_static(publication: Publication) -> Record:
    public = "http://127.0.0.1:39445"
    authority = STATIC_ORIGIN.removeprefix("http://")
    with httpx.Client(timeout=2, trust_env=False, headers={"Host": authority}) as client:
        for content in publication.texts:
            page = client.get(public + "/fallback", params={"locale": content.locale})
            manifest = client.get(
                public + "/demo-static/v1/manifest", params={"locale": content.locale}
            )
            require(
                page.status_code == 200 and manifest.status_code == 200, "Signed Static unavailable"
            )
            require(
                content.title in page.text and content.text in page.text, "Static content drift"
            )
            require(
                manifest.json() == publication.owner_manifest(content.locale),
                "Static manifest drift",
            )
            require(
                all(
                    "cookie" not in item.request.headers
                    and "set-cookie" not in item.headers
                    and item.headers.get("cache-control") == "no-store"
                    for item in (page, manifest)
                ),
                "Unexpected Static cookie or caching behavior",
            )
    return {
        "artifact_digest": publication.artifact_digest,
        "locales": ["en-CA", "fr-CA"],
        "cookie_free": True,
    }


def static_host(workspace: Path) -> tuple[list[str], Publication]:
    store, publication = _static_publication(
        workspace / "static-publication",
        lambda: datetime.now(UTC),  # pyright: ignore[reportArgumentType]
    )
    key = workspace / "static.pub"
    write(
        key,
        store.key.public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ),
    )
    return [
        str(ROOT / ".venv/bin/care-link-static"),
        "--directory",
        str(store.directory),
        "--review-public-key",
        str(key),
        "--allow-owner-demo",
        "--port",
        "39445",
    ], publication


def phases(
    client: httpx.Client,
    worker: httpx.Client,
    csrf: str,
    worker_csrf: str,
    app: str,
    publication: Publication,
    control: Path,
    result: Record,
) -> None:
    key = str(uuid4())
    require(receive_json(client, "/help/health")["alive"] is True, "Host Help is unavailable")
    identifier, before = positive(client, csrf, "en-CA", key)
    result["before"] = {"private_help": before, "static": verify_static(publication)}
    write(control / "ready", b"ready\n")
    done: set[str] = set()
    deadline = monotonic() + 45 * 60
    while monotonic() < deadline:
        if (control / "core-down").exists() and "core-down" not in done:
            result["core_down"] = {
                "private_help": positive(client, csrf, "fr-CA", str(uuid4()))[1],
                "static": verify_static(publication),
            }
            done.add("core-down")
            write(control / "core-down.observed", json.dumps(result["core_down"]).encode())
        if (control / "node-down").exists() and "node-down" not in done:
            current = docker("inspect", "--format", "{{.State.Running}}", NODE)
            require(current == "false", "Whole-node phase needs the stopped owned node")
            require(
                receive_json(client, "/help/health")["alive"] is True,
                "Host Help was lost with Kind",
            )
            result["node_down"] = {
                **private_unavailable(client, worker, csrf, worker_csrf, app, identifier, key),
                "node_container_running": False,
                "help_container_id": app,
                "static": verify_static(publication),
            }
            done.add("node-down")
            write(control / "node-down.observed", json.dumps(result["node_down"]).encode())
        if (control / "recovered").exists() and "node-down" in done:

            def recovered() -> Record:
                found = receive_json(client, REQUESTS + "/" + identifier)
                require(
                    found.get("connection_confirmed") is False and found.get("state") == "recorded",
                    "Recovered Help changed the request state",
                )
                return found

            wait_for(
                recovered, "Original Help record did not recover with fresh authority", seconds=90
            )
            result["after"] = {
                "original_request_recovered": True,
                "private_help": positive(client, csrf, "en-CA", str(uuid4()))[1],
                "static": verify_static(publication),
                "durable": record(json.loads(docker("exec", app, "python", "-c", SPOOL))),
            }
            write(control / "recovered.observed", json.dumps(result["after"]).encode())
            return
        sleep(0.35)
    raise RuntimeError("Coordinator did not signal the required outage and recovery phases")


def execute(args: argparse.Namespace) -> Record:
    image = docker("image", "inspect", "--format", "{{.Id}}", args.image)
    require(image.startswith("sha256:") and len(image) == 71, "Immutable local candidate required")
    products = record(json.loads((ROOT / "deploy/k8s/imp-02/products.json").read_text()))
    images = record(products["images"])
    node_ip, proxy_ip = bridge_addresses()
    print(
        f"Independent Help bridge address {proxy_ip}; "
        f"Identity requires incoming mTLS on {node_ip}:30443",
        flush=True,
    )
    workspace = (
        WORKSPACE
        if not args.preflight
        else Path(tempfile.mkdtemp(prefix=WORKSPACE.name + "-")).resolve() / "fixture"
    )
    sources, envoy_digest = prepare(
        workspace,
        args.identity_key,
        node_ip,
        proxy_ip,
        args.kubeconfig,
        products,
        preflight=args.preflight,
    )
    static_command, publication = static_host(workspace)
    result: Record = {
        "scope": "Owned separate host Help, protected native-role image, and signed Static",
        "candidate_image_id": image,
        "envoy_configuration_sha256": envoy_digest,
        "help_workload_id": HELP_ID,
        "sources_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    with ExitStack() as stack:
        static = stack.enter_context(process(static_command))
        result["static_process_id"] = static.pid
        result["static_preflight"] = wait_for(
            lambda: verify_static(publication), "Static startup failed"
        )
        stack.enter_context(owned_volumes())
        seed(image, sources)
        app = stack.enter_context(
            owned_container(
                "app",
                image,
                [
                    "--network=none",
                    "--user",
                    f"{APP_UID}:{APP_UID}",
                    "--group-add",
                    str(PROXY_UID),
                    *mount("backend", "/run/care-link/backend"),
                    *mount("outbound", "/run/care-link/outbound", read_only=True),
                    *mount("app-config", "/config", read_only=True),
                    *mount("spool", "/spool"),
                ],
                [
                    "python",
                    "-m",
                    "tools.imp10_runtime.serve",
                    "--role",
                    "help",
                    "--config",
                    "/config/help.json",
                ],
            )
        )
        result["help_container_id"] = app
        result["backend_socket"] = socket_check(app, image, require_uid_guard=not args.preflight)
        if args.preflight:
            result["protected_workload_authority"] = "not_run"
            result["cluster_outage"] = "not_run"
            return result
        agent = stack.enter_context(
            owned_container(
                "agent",
                text(images, "spire_agent"),
                [
                    "--network",
                    BRIDGE,
                    "--user=0:0",
                    *mount("agent-config", "/config", read_only=True),
                    *mount("agent-data", "/run/spire/data"),
                    *mount("workload-api", "/run/spire/sockets"),
                ],
                ["-config", "/config/agent.conf"],
            )
        )
        proxy = stack.enter_context(
            owned_container(
                "proxy",
                text(images, "envoy"),
                [
                    "--network",
                    BRIDGE,
                    "--ip",
                    proxy_ip,
                    "--user",
                    f"{PROXY_UID}:{PROXY_UID}",
                    "--pid",
                    "container:" + agent,
                    "--publish",
                    f"127.0.0.1:39444:{PORT}",
                    *mount("backend", "/run/care-link/backend", read_only=True),
                    *mount("outbound", "/run/care-link/outbound"),
                    *mount("proxy-config", "/config", read_only=True),
                    *mount("workload-api", "/run/spire/sockets", read_only=True),
                ],
                ["-c", "/config/envoy.json", "--disable-hot-restart", "--log-level", "warning"],
            )
        )
        result["proxy_container_id"] = proxy
        result["spire_agent_container_id"] = agent
        keyfile = sources / "tls.crt"
        client = stack.enter_context(
            httpx.Client(
                transport=BrowserTransport(keyfile, args.provider_ca), timeout=7, trust_env=False
            )
        )
        worker = stack.enter_context(
            httpx.Client(
                transport=BrowserTransport(keyfile, args.provider_ca), timeout=7, trust_env=False
            )
        )
        wait_for(
            lambda: receive_json(client, "/v1/auth/csrf"),
            "Help did not reach current Identity over its SPIRE egress",
            seconds=480,
        )
        denied = client.post(HELP_ORIGIN + "/internal/v1/identity/help-authorize", json={})
        require(
            denied.status_code == 403, "Help browser ingress exposed an internal authority route"
        )
        result["browser_internal_authority_denied"] = denied.status_code
        credentials = load(args.browser_users)
        factors = load(args.browser_totp) if args.browser_totp is not None else {}
        pid, worker_id = "imp10-008-pid", "imp10-008-worker"
        csrf = sign_in(
            client, Actor("pid", pid, text(credentials, pid), cast(str | None, factors.get(pid)))
        )
        worker_actor = (
            Actor(
                "worker",
                worker_id,
                text(credentials, worker_id),
                cast(str | None, factors.get(worker_id)),
            )
            if worker_id in credentials
            else None
        )
        worker_csrf = sign_in(worker, worker_actor) if worker_actor is not None else csrf
        result["accept_actor_role"] = "worker" if worker_actor is not None else "pid"
        control = workspace / "control"
        control.mkdir(mode=0o700)
        phases(
            client,
            worker if worker_actor is not None else client,
            csrf,
            worker_csrf,
            app,
            publication,
            control,
            result,
        )
        require(
            static.poll() is None and verify_static(publication) == result["static_preflight"],
            "The independent Static process changed while verifying Help",
        )
    result["owned_processes_cleaned"] = True
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--identity-key", type=Path, required=True)
    parser.add_argument("--provider-ca", type=Path, required=True)
    parser.add_argument("--browser-users", type=Path, required=True)
    parser.add_argument("--browser-totp", type=Path)
    parser.add_argument("--kubeconfig", type=Path, default=DEFAULT_KUBECONFIG)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    require(not args.output.exists(), "Output must be new")
    try:
        result = execute(args)
    except (OSError, ValueError, RuntimeError, httpx.HTTPError) as error:
        detail = (
            str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__
        )
        raise SystemExit("Independent Help qualification stopped: " + detail) from None
    write(args.output, (json.dumps(result, indent=2) + "\n").encode())
    print("Independent Help qualification evidence recorded.", flush=True)


if __name__ == "__main__":
    main()
