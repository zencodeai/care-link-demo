"""Local enforcement evidence; certificates are synthetic, no live SPIRE/Envoy."""

import hashlib
import json
import os
import socket
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import pytest
from care_link_workload_trust import (
    AuthorizationServer,
    FenceStore,
    PeerRule,
    ProxyInputs,
    TrustDenied,
    WorkloadEnforcer,
    build_envoy,
    peer_uid,
    spire_registration,
)
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

pytestmark = pytest.mark.unit
PEER = "spiffe://care-link.demo/lab/help"
LOCAL = "spiffe://care-link.demo/lab/identity"
PATH = "/internal/v1/identity/help-authorize"


def test_mesh_auth_queries_remain_exact_bounded_and_request_bound(fixture):
    enforcer, store, _clock, xfcc, _leaf, _root = fixture
    callback = "/bff/help/v1/auth/callback"
    proof = "/bff/help/v1/auth/step-up/proof"
    scoped = WorkloadEnforcer(
        enforcer.proxy_uid,
        enforcer.trust_roots,
        (PeerRule(PEER, frozenset({("GET", callback), ("GET", proof), ("GET", PATH)})),),
        store,
        enforcer.clock,
    )
    state = "a" * 32
    assert scoped.authorize(
        enforcer.proxy_uid,
        "GET",
        callback + "?state=" + state + "&code=code&iss=https%3A%2F%2Fid.localhost%3A20443",
        xfcc,
    )
    assert scoped.authorize(
        enforcer.proxy_uid, "GET", proof + "?ceremony_id=00000000-0000-4000-8000-000000000001", xfcc
    )
    denied = [
        callback + "?state=" + state + "&state=" + state + "&code=x",
        callback + "?state=" + state + "&code=x&unknown=x",
        callback + "?state=" + state + "&code=x&error=cancelled",
        callback + "?state=" + state + "&code=" + "x" * 2049,
        callback + "?state=" + state + "&code=%ZZ",
        callback + "?state=" + state + "&code=x&error_description=%0A",
        "/bff/help/v1/auth/%63allback?state=" + state + "&code=x",
        proof + "?ceremony_id=00000000-0000-4000-8000-000000000001&extra=x",
        PATH + "?ceremony_id=00000000-0000-4000-8000-000000000001",
    ]
    for target in denied:
        with pytest.raises(TrustDenied):
            scoped.authorize(enforcer.proxy_uid, "GET", target, xfcc)


@pytest.fixture
def fixture(tmp_path):
    now = datetime.now(UTC)
    root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    root_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic test root")])
    root = (
        x509.CertificateBuilder()
        .subject_name(root_name)
        .issuer_name(root_name)
        .public_key(root_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=1), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(root_key.public_key()), critical=False
        )
        .sign(root_key, hashes.SHA256())
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([]))
        .issuer_name(root_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(seconds=1))
        .not_valid_after(now + timedelta(seconds=60))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName([x509.UniformResourceIdentifier(PEER)]), critical=True
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()),
            critical=False,
        )
        .sign(root_key, hashes.SHA256())
    )
    directory = tmp_path / "fences"
    directory.mkdir(mode=0o700)
    store = FenceStore(directory, os.getuid())
    store.initialize(frozenset({PEER, LOCAL}))
    clock = [now]
    rule = PeerRule(PEER, frozenset({("POST", PATH)}))
    enforcer = WorkloadEnforcer(os.getuid(), (root,), (rule,), store, lambda: clock[0])
    pem = leaf.public_bytes(Encoding.PEM).decode()
    cert_hash = hashlib.sha256(leaf.public_bytes(Encoding.DER)).hexdigest()
    xfcc = f'Hash={cert_hash};Cert="{quote(pem, safe="")}";URI={PEER}'
    return enforcer, store, clock, xfcc, leaf, root


def test_exact_certificate_route_and_kernel_proxy_uid(fixture):
    enforcer, _store, _clock, xfcc, _leaf, _root = fixture
    assert enforcer.authorize(os.getuid(), "POST", PATH, xfcc).spiffe_id == PEER
    with socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)[0] as channel:
        assert peer_uid(channel) == os.getuid()
    for uid, method, path in [
        (None, "POST", PATH),
        (os.getuid() + 1, "POST", PATH),
        (os.getuid(), "GET", PATH),
        (os.getuid(), "POST", PATH + "?bypass=1"),
        (os.getuid(), "POST", PATH + "%2f"),
    ]:
        with pytest.raises(TrustDenied):
            enforcer.authorize(uid, method, path, xfcc)


def test_reused_peer_certificate_loses_permission_on_live_fence(fixture):
    enforcer, store, _clock, xfcc, _leaf, _root = fixture
    assert enforcer.authorize(os.getuid(), "POST", PATH, xfcc)
    state = store.restrict(PEER, "compromise-command", 0)
    assert state.generation == 1 and not state.admits(PEER)
    assert store.restrict(PEER, "compromise-command", 0) == state
    with pytest.raises(TrustDenied):
        enforcer.authorize(os.getuid(), "POST", PATH, xfcc)
    with pytest.raises(TrustDenied):
        store.restrict(PEER, "other-command", 0)


def test_reused_peer_certificate_expires_per_operation(fixture):
    enforcer, _store, clock, xfcc, _leaf, _root = fixture
    assert enforcer.authorize(os.getuid(), "POST", PATH, xfcc)
    clock[0] += timedelta(seconds=61)
    with pytest.raises(TrustDenied):
        enforcer.authorize(os.getuid(), "POST", PATH, xfcc)


@pytest.mark.parametrize("damage", ["missing", "torn", "mode", "symlink"])
def test_missing_corrupt_or_unsafe_live_fence_denies(fixture, damage, tmp_path):
    enforcer, store, _clock, xfcc, _leaf, _root = fixture
    path = store.directory / store.filename
    if damage == "missing":
        path.unlink()
    elif damage == "torn":
        with path.open("ab") as stream:
            stream.write(b'{"generation":')
    elif damage == "mode":
        path.chmod(0o644)
    else:
        path.rename(tmp_path / "elsewhere")
        path.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(TrustDenied):
        enforcer.authorize(os.getuid(), "POST", PATH, xfcc)


@pytest.mark.parametrize("change", ["uri", "chain", "hash", "duplicate", "multi"])
def test_forged_or_ambiguous_forwarded_certificate_denied(fixture, change):
    enforcer, _store, _clock, xfcc, _leaf, _root = fixture
    if change == "uri":
        xfcc = xfcc.replace(PEER, "spiffe://care-link.demo/lab/runtime")
    elif change == "chain":
        xfcc = xfcc.replace("Cert=", 'Chain="invalid";Cert=')
    elif change == "hash":
        xfcc = "Hash=" + "f" * 64 + xfcc[xfcc.index(";") :]
    elif change == "duplicate":
        xfcc += ";URI=" + PEER
    else:
        xfcc += "," + xfcc
    with pytest.raises(TrustDenied):
        enforcer.authorize(os.getuid(), "POST", PATH, xfcc)


def test_unix_http_listener_denies_untrusted_process_even_with_spoofed_peer_header(
    fixture, tmp_path
):
    enforcer, _store, _clock, xfcc, _leaf, _root = fixture
    enforcer.proxy_uid = os.getuid() + 1
    with tempfile.TemporaryDirectory(prefix="cl-", dir=tempfile.gettempdir()) as scratch:
        directory = Path(scratch)
        directory.chmod(0o710)
        os.chown(directory, -1, os.getgid())
        address = directory / "a.sock"
        server = AuthorizationServer(address, enforcer, os.getuid(), os.getgid())
        thread = threading.Thread(target=server.handle_request)
        thread.start()
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
                channel.settimeout(2)
                channel.connect(str(address))
                request = (
                    f"POST {PATH} HTTP/1.0\r\nHost: local\r\n"
                    f"X-Forwarded-Client-Cert: {xfcc}\r\n"
                    f"X-Proxy-Uid: {enforcer.proxy_uid}\r\nContent-Length: 0\r\n\r\n"
                )
                channel.sendall(request.encode())
                response = channel.recv(4096)
                assert b" 403 " in response and b"x-care-link-verified-spiffe" not in response
        finally:
            thread.join(timeout=2)
            server.server_close()
        assert not thread.is_alive()


def proxy_inputs():
    return ProxyInputs(
        LOCAL,
        (PeerRule(PEER, frozenset({("POST", PATH)})),),
        "127.0.0.1",
        8443,
        "/run/care-link/backend.sock",
        "/run/care-link/auth.sock",
        "/run/spire/agent.sock",
        "envoyproxy/envoy@sha256:" + "a" * 64,
        "1.0.0",
        "ghcr.io/spiffe/spire-agent@sha256:" + "b" * 64,
        "1.0.0",
        60,
    )


def test_envoy_spire_candidate_is_exact_default_deny_and_requires_pins():
    inputs = proxy_inputs()
    config = build_envoy(inputs)
    raw = json.dumps(config)
    assert '"failure_mode_allow": false' in raw and "SANITIZE_SET" in raw
    assert "require_client_certificate" in raw and "match_typed_subject_alt_names" in raw
    assert "typed_per_filter_config" not in raw and '"admin"' not in raw
    assert '"pipe"' in raw and "spire_agent" in raw
    registration = spire_registration(
        inputs,
        parent_spiffe_id="spiffe://care-link.demo/spire/agent/test",
        namespace="care-link-lab",
        service_account="identity",
        proxy_container_name="proxy",
        workload_image="local/identity@sha256:" + "c" * 64,
    )
    assert "k8s:ns:care-link-lab" in registration["selectors"]
    assert any(
        value.startswith("k8s:container-image:") and "@sha256:" in value
        for value in registration["selectors"]
    )
    with pytest.raises(ValueError):
        ProxyInputs(**(vars(inputs) | {"envoy_image": "envoyproxy/envoy:latest"}))


def test_short_ledger_reads_cannot_admit_a_valid_prefix(fixture, monkeypatch):
    enforcer, store, _clock, xfcc, _leaf, _root = fixture
    store.restrict(PEER, "restrict", 0)
    real_read = os.read
    monkeypatch.setattr(os, "read", lambda fd, size: real_read(fd, min(size, 19)))
    assert store.read().generation == 1
    with pytest.raises(TrustDenied):
        enforcer.authorize(os.getuid(), "POST", PATH, xfcc)


def test_certificate_expiry_is_checked_after_live_fence_read(fixture, monkeypatch):
    enforcer, store, clock, xfcc, _leaf, _root = fixture
    actual = store.read

    def slow_read():
        result = actual()
        clock[0] += timedelta(seconds=61)
        return result

    monkeypatch.setattr(store, "read", slow_read)
    with pytest.raises(TrustDenied):
        enforcer.authorize(os.getuid(), "POST", PATH, xfcc)


def test_backend_bridge_requires_kernel_capsule_current_fence_and_expiry(fixture, monkeypatch):
    from types import SimpleNamespace

    from care_link_workload_trust import SOCKET_PEER_SCOPE_KEY, BackendVerifier, SocketPeer

    enforcer, store, _clock, xfcc, _leaf, _root = fixture
    admission = enforcer.authorize(os.getuid(), "POST", PATH, xfcc)
    expires_at = admission.certificate_expires_at.isoformat().replace("+00:00", "Z")
    request = SimpleNamespace(
        scope={},
        method="POST",
        url=SimpleNamespace(path=PATH),
        headers={
            "x-care-link-verified-spiffe": PEER,
            "x-care-link-fence-generation": "0",
            "x-care-link-certificate-expires-at": expires_at,
        },
    )
    with pytest.raises(ValueError):
        BackendVerifier(os.getuid(), enforcer.rules, store, backend_uid=os.geteuid())
    # Explicit process-identity fixture; no distinct-user positive channel claim.
    monkeypatch.setattr(os, "geteuid", lambda: os.getuid() + 1)
    verify = BackendVerifier(os.getuid(), enforcer.rules, store, backend_uid=os.getuid() + 1)
    assert not verify(request, "help")

    request.scope[SOCKET_PEER_SCOPE_KEY] = SocketPeer(os.getuid() + 1)
    assert not verify(request, "help")
    request.scope[SOCKET_PEER_SCOPE_KEY] = SocketPeer(os.getuid())
    assert verify(request, "help")
    request.headers["x-care-link-certificate-expires-at"] = "2000-01-01T00:00:00Z"
    assert not verify(request, "help")
    request.headers["x-care-link-certificate-expires-at"] = (
        admission.certificate_expires_at.isoformat().replace("+00:00", "Z")
    )
    store.restrict(PEER, "compromise", 0)
    assert not verify(request, "help")


def test_fenced_destination_stops_same_peer_certificate_and_backend_connection(
    fixture, monkeypatch
):
    from types import SimpleNamespace

    from care_link_workload_trust import SOCKET_PEER_SCOPE_KEY, BackendVerifier, SocketPeer

    previous, store, _clock, xfcc, _leaf, _root = fixture
    authorizer = WorkloadEnforcer(
        previous.proxy_uid,
        previous.trust_roots,
        previous.rules,
        store,
        previous.clock,
        local_spiffe_id=LOCAL,
    )
    first = authorizer.authorize(os.getuid(), "POST", PATH, xfcc)
    # This capsule and certificate remain identical across operations, as on
    # an already accepted connection. Local compromise does not fence caller.
    request = SimpleNamespace(
        scope={SOCKET_PEER_SCOPE_KEY: SocketPeer(os.getuid())},
        method="POST",
        url=SimpleNamespace(path=PATH),
        headers={
            "x-care-link-verified-spiffe": PEER,
            "x-care-link-fence-generation": "0",
            "x-care-link-certificate-expires-at": first.certificate_expires_at.isoformat().replace(
                "+00:00", "Z"
            ),
        },
    )
    monkeypatch.setattr(os, "geteuid", lambda: os.getuid() + 1)
    backend = BackendVerifier(
        os.getuid(), previous.rules, store, backend_uid=os.getuid() + 1, local_spiffe_id=LOCAL
    )
    assert backend(request, "help")
    state = store.restrict(LOCAL, "local-compromise", 0)
    assert state.admits(PEER) and not state.admits(LOCAL)
    # Give the old connection the newest generation too: local fencing must
    # deny independently of a stale header or caller/certificate revocation.
    request.headers["x-care-link-fence-generation"] = str(state.generation)
    assert not backend(request, "help")
    with pytest.raises(TrustDenied, match="destination workload fenced"):
        authorizer.authorize(os.getuid(), "POST", PATH, xfcc)


def test_local_identity_configuration_rejects_noncanonical_scope(fixture, monkeypatch):
    from care_link_workload_trust import BackendVerifier

    enforcer, store, _clock, _xfcc, _leaf, _root = fixture
    with pytest.raises(ValueError):
        WorkloadEnforcer(
            os.getuid(),
            enforcer.trust_roots,
            enforcer.rules,
            store,
            local_spiffe_id="spiffe://untrusted.example/lab/identity",
        )
    monkeypatch.setattr(os, "geteuid", lambda: os.getuid() + 1)
    with pytest.raises(ValueError):
        BackendVerifier(
            os.getuid(),
            enforcer.rules,
            store,
            backend_uid=os.getuid() + 1,
            local_spiffe_id="identity",
        )


def test_uvicorn_connection_hook_mints_kernel_peer_only_for_actual_unix_socket():
    import asyncio

    from care_link_workload_trust import SOCKET_PEER_SCOPE_KEY, ProtectedUnixH11Protocol, SocketPeer
    from uvicorn import Config
    from uvicorn.server import ServerState

    class Transport(asyncio.Transport):
        def __init__(self, channel):
            self.channel, self.closed = channel, False

        def get_extra_info(self, name, default=None):
            return self.channel if name == "socket" else default

        def close(self):
            self.closed = True

        def is_closing(self):
            return self.closed

    async def check():
        captured = []

        async def app(scope, receive, send):
            captured.append(dict(scope))

        async def receive():
            return {"type": "http.disconnect"}

        async def send(message):
            pass

        for family in (socket.AF_UNIX, socket.AF_INET, None):
            if family == socket.AF_UNIX:
                channel, other = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
            elif family == socket.AF_INET:
                channel = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                other = None
            else:
                channel, other = None, None
            try:
                config = Config(
                    app,
                    http=ProtectedUnixH11Protocol,
                    ws="none",
                    lifespan="off",
                    access_log=False,
                    proxy_headers=False,
                )
                protocol = ProtectedUnixH11Protocol(
                    config, ServerState(), {}, _loop=asyncio.get_running_loop()
                )
                transport = Transport(channel)
                protocol.connection_made(transport)
                scope = {"type": "http", SOCKET_PEER_SCOPE_KEY: SocketPeer(999999)}
                await protocol.app(scope, receive, send)
                if family == socket.AF_UNIX:
                    assert captured[-1][SOCKET_PEER_SCOPE_KEY].uid == os.getuid()
                else:
                    assert SOCKET_PEER_SCOPE_KEY not in captured[-1] and transport.closed
                protocol.connection_lost(None)
            finally:
                if channel is not None:
                    channel.close()
                if other is not None:
                    other.close()

    asyncio.run(check())
