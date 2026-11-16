"""Real local raw streams/UID checks; not deployed TLS or network qualification."""

import asyncio
import os
import ssl
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from tools.imp03_shared import relay


@pytest.mark.parametrize("status,expected", [(-15, 143), (0, 0), (7, 7)])
def test_application_wrapper_preserves_exit_or_reports_signal_convention(
    monkeypatch, tmp_path, status, expected
):
    class Child:
        def wait(self, **_kwargs):
            return status

        def poll(self):
            return status

    monkeypatch.setattr(relay.subprocess, "run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(relay.subprocess, "Popen", lambda *_args, **_kwargs: Child())
    assert relay.run_application(tmp_path, "core", []) == expected


@pytest.fixture
def tmp_path():
    # macOS sockaddr_un cannot hold the default long pytest temporary path.
    with tempfile.TemporaryDirectory(prefix="imp03r-", dir="/private/tmp") as root:
        yield Path(root)


def socket_path(tmp_path: Path) -> Path:
    directory = tmp_path / "connector"
    directory.mkdir(mode=0o710)
    os.chown(directory, -1, os.getegid())
    directory.chmod(0o710)
    return directory / "fixed.sock"


async def close_writer(writer):
    writer.close()
    await writer.wait_closed()


def test_binary_roundtrip_and_half_close_have_no_target_selection_protocol(tmp_path):
    async def exercise():
        path = socket_path(tmp_path)
        received = []

        async def upstream(reader, writer):
            value = await reader.read()
            received.append(value)
            writer.write(b"fixed-target:" + value[::-1])
            await writer.drain()
            await close_writer(writer)

        target = await asyncio.start_server(upstream, "127.0.0.1", 0)
        port = target.sockets[0].getsockname()[1]
        connector = relay.UnixToTCPRelay(
            path, "127.0.0.1", port, allowed_uids=frozenset({os.geteuid()}), access_gid=os.getegid()
        )
        local = relay.LoopbackToUnixRelay(path, 0, server_uid=os.geteuid())
        await connector.start()
        await local.start()
        try:
            assert local.server.sockets[0].getsockname()[0] == "127.0.0.1"
            reader, writer = await asyncio.open_connection("127.0.0.1", local.bound_port)
            # Includes PostgreSQL SSLRequest bytes and a fake CONNECT-looking
            # string. Neither bridge parses either into an alternate target.
            payload = b"\x00\x00\x00\x08\x04\xd2\x16/CONNECT forbidden:443\r\n\x00\xff"
            writer.write(payload)
            await writer.drain()
            writer.write_eof()
            assert await asyncio.wait_for(reader.read(), 2) == b"fixed-target:" + payload[::-1]
            assert received == [payload]
            await close_writer(writer)
        finally:
            await local.close()
            await connector.close()
            target.close()
            await target.wait_closed()
        assert not path.exists()

    asyncio.run(exercise())


def test_disallowed_kernel_peer_uid_never_opens_tcp_target(tmp_path, monkeypatch):
    async def exercise():
        path = socket_path(tmp_path)
        calls = []

        async def upstream(reader, writer):
            calls.append(True)
            await close_writer(writer)

        target = await asyncio.start_server(upstream, "127.0.0.1", 0)
        connector = relay.UnixToTCPRelay(
            path,
            "127.0.0.1",
            target.sockets[0].getsockname()[1],
            allowed_uids=frozenset({os.geteuid()}),
            access_gid=os.getegid(),
        )
        monkeypatch.setattr(relay, "peer_uid", lambda _: os.geteuid() + 1)
        await connector.start()
        try:
            reader, writer = await asyncio.open_unix_connection(str(path))
            assert await asyncio.wait_for(reader.read(), 1) == b""
            await close_writer(writer)
            assert not calls
        finally:
            await connector.close()
            target.close()
            await target.wait_closed()

    asyncio.run(exercise())


def test_idle_deadline_closes_both_raw_streams(tmp_path):
    async def exercise():
        path = socket_path(tmp_path)
        closed = asyncio.Event()

        async def upstream(reader, writer):
            await reader.read()
            await close_writer(writer)
            closed.set()

        target = await asyncio.start_server(upstream, "127.0.0.1", 0)
        connector = relay.UnixToTCPRelay(
            path,
            "127.0.0.1",
            target.sockets[0].getsockname()[1],
            allowed_uids=frozenset({os.geteuid()}),
            access_gid=os.getegid(),
            limits=relay.RelayLimits(idle_timeout=0.05),
        )
        await connector.start()
        try:
            reader, writer = await asyncio.open_unix_connection(str(path))
            assert await asyncio.wait_for(reader.read(), 1) == b""
            await asyncio.wait_for(closed.wait(), 1)
            await close_writer(writer)
        finally:
            await connector.close()
            target.close()
            await target.wait_closed()

    asyncio.run(exercise())


def test_connection_limit_rejects_second_stream_without_displacing_first(tmp_path):
    async def exercise():
        path = socket_path(tmp_path)
        connected = asyncio.Event()

        async def upstream(reader, writer):
            connected.set()
            while data := await reader.read(64):
                writer.write(data)
                await writer.drain()
            await close_writer(writer)

        target = await asyncio.start_server(upstream, "127.0.0.1", 0)
        connector = relay.UnixToTCPRelay(
            path,
            "127.0.0.1",
            target.sockets[0].getsockname()[1],
            allowed_uids=frozenset({os.geteuid()}),
            access_gid=os.getegid(),
            limits=relay.RelayLimits(max_connections=1),
        )
        await connector.start()
        try:
            first_reader, first_writer = await asyncio.open_unix_connection(str(path))
            await asyncio.wait_for(connected.wait(), 1)
            second_reader, second_writer = await asyncio.open_unix_connection(str(path))
            assert await asyncio.wait_for(second_reader.read(), 1) == b""
            await close_writer(second_writer)
            first_writer.write(b"still-current")
            await first_writer.drain()
            assert await asyncio.wait_for(first_reader.readexactly(13), 1) == b"still-current"
            await close_writer(first_writer)
        finally:
            await connector.close()
            target.close()
            await target.wait_closed()

    asyncio.run(exercise())


def test_loopback_client_refuses_wrong_connector_owner(tmp_path):
    async def exercise():
        path = socket_path(tmp_path)
        server = await asyncio.start_unix_server(lambda reader, writer: writer.close(), path=path)
        os.chmod(path, 0o660)
        local = relay.LoopbackToUnixRelay(path, 0, server_uid=os.geteuid() + 1)
        await local.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", local.bound_port)
            assert await asyncio.wait_for(reader.read(), 1) == b""
            await close_writer(writer)
        finally:
            await local.close()
            server.close()
            await server.wait_closed()

    asyncio.run(exercise())


def test_unsafe_listener_parent_and_bad_limits_are_refused(tmp_path):
    path = socket_path(tmp_path)
    path.parent.chmod(0o755)
    connector = relay.UnixToTCPRelay(
        path, "127.0.0.1", 5432, allowed_uids=frozenset({os.geteuid()}), access_gid=os.getegid()
    )
    with pytest.raises(PermissionError, match="custody"):
        asyncio.run(connector.start())
    with pytest.raises(ValueError, match="deadlines"):
        relay.RelayLimits(idle_timeout=float("inf"))
    with pytest.raises(ValueError, match="connection"):
        relay.RelayLimits(max_connections=0)
    with pytest.raises(ValueError, match="absolute"):
        relay.LoopbackToUnixRelay(Path("relative.sock"), 5432, server_uid=os.geteuid())


def test_threaded_bridge_binds_only_loopback_and_releases_port(tmp_path):
    path = socket_path(tmp_path)
    with relay.ThreadedLoopbackBridge(path, 0, server_uid=os.geteuid()) as bridge:
        assert bridge.thread.is_alive()
        assert bridge.relay.server.sockets[0].getsockname()[0] == "127.0.0.1"
    assert not bridge.thread.is_alive()


def test_loopback_checks_connector_kernel_uid_after_inode_owner(tmp_path, monkeypatch):
    async def exercise():
        path = socket_path(tmp_path)
        received = []

        async def connector(reader, writer):
            received.append(await reader.read())
            await close_writer(writer)

        server = await asyncio.start_unix_server(connector, path=path)
        os.chmod(path, 0o660)
        local = relay.LoopbackToUnixRelay(path, 0, server_uid=os.geteuid())
        # The socket inode belongs to the expected UID; a different kernel peer
        # UID must still refuse before any protocol bytes are forwarded.
        monkeypatch.setattr(relay, "peer_uid", lambda _: os.geteuid() + 1)
        await local.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", local.bound_port)
            assert await asyncio.wait_for(reader.read(), 1) == b""
            await close_writer(writer)
            assert received == [b""]
        finally:
            await local.close()
            server.close()
            await server.wait_closed()

    asyncio.run(exercise())


def test_tls_verification_and_hostname_failure_survive_transparent_bridge(tmp_path):
    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic relay test CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False
        )
        .add_extension(
            x509.KeyUsage(True, False, False, False, False, True, True, False, False), critical=True
        )
        .sign(ca_key, hashes.SHA256())
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "relay-target.local")]))
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False
        )
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("relay-target.local")]), False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False)
        .sign(ca_key, hashes.SHA256())
    )
    for name, data in [
        ("ca.pem", ca.public_bytes(serialization.Encoding.PEM)),
        ("server.pem", certificate.public_bytes(serialization.Encoding.PEM)),
        (
            "server.key",
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
        ),
    ]:
        (tmp_path / name).write_bytes(data)
        (tmp_path / name).chmod(0o600)
    server_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_tls.minimum_version = ssl.TLSVersion.TLSv1_3
    server_tls.load_cert_chain(tmp_path / "server.pem", tmp_path / "server.key")
    client_tls = ssl.create_default_context(cafile=str(tmp_path / "ca.pem"))

    async def exercise():
        path = socket_path(tmp_path)

        async def target(reader, writer):
            assert await reader.readexactly(4) == b"ping"
            writer.write(b"pong")
            await writer.drain()
            await close_writer(writer)

        upstream = await asyncio.start_server(target, "127.0.0.1", 0, ssl=server_tls)
        connector = relay.UnixToTCPRelay(
            path,
            "127.0.0.1",
            upstream.sockets[0].getsockname()[1],
            allowed_uids=frozenset({os.geteuid()}),
            access_gid=os.getegid(),
        )
        local = relay.LoopbackToUnixRelay(path, 0, server_uid=os.geteuid())
        await connector.start()
        await local.start()
        ingress = relay.TCPToTCPRelay(0, "127.0.0.1", local.bound_port)
        await ingress.start()
        try:
            reader, writer = await asyncio.open_connection(
                "127.0.0.1",
                ingress.bound_port,
                ssl=client_tls,
                server_hostname="relay-target.local",
            )
            assert writer.get_extra_info("ssl_object").version() == "TLSv1.3"
            writer.write(b"ping")
            await writer.drain()
            assert await reader.readexactly(4) == b"pong"
            await close_writer(writer)
            with pytest.raises(ssl.SSLCertVerificationError):
                await asyncio.open_connection(
                    "127.0.0.1",
                    ingress.bound_port,
                    ssl=client_tls,
                    server_hostname="wrong-target.local",
                )
        finally:
            await ingress.close()
            await local.close()
            await connector.close()
            upstream.close()
            await upstream.wait_closed()

    asyncio.run(exercise())


def test_ingress_forwards_to_fixed_numeric_target_and_enforces_connection_limit():
    async def exercise():
        connected = asyncio.Event()
        received = []

        async def upstream(reader, writer):
            connected.set()
            value = await reader.read()
            received.append(value)
            writer.write(b"fixed:" + value)
            await writer.drain()
            await close_writer(writer)

        target = await asyncio.start_server(upstream, "127.0.0.1", 0)
        ingress = relay.TCPToTCPRelay(
            0,
            "127.0.0.1",
            target.sockets[0].getsockname()[1],
            limits=relay.RelayLimits(max_connections=1),
        )
        await ingress.start()
        try:
            assert ingress.server.sockets[0].getsockname()[0] == "0.0.0.0"  # noqa: S104
            reader, writer = await asyncio.open_connection("127.0.0.1", ingress.bound_port)
            await asyncio.wait_for(connected.wait(), 1)
            rejected_reader, rejected_writer = await asyncio.open_connection(
                "127.0.0.1", ingress.bound_port
            )
            assert await asyncio.wait_for(rejected_reader.read(), 1) == b""
            await close_writer(rejected_writer)
            payload = b"CONNECT caller-chosen.invalid:9999\r\n\x00\xff"
            writer.write(payload)
            await writer.drain()
            writer.write_eof()
            assert await asyncio.wait_for(reader.read(), 1) == b"fixed:" + payload
            assert received == [payload]
            await close_writer(writer)
        finally:
            await ingress.close()
            target.close()
            await target.wait_closed()

    asyncio.run(exercise())
    with pytest.raises(ValueError, match="numeric"):
        relay.TCPToTCPRelay(28443, "caller-chosen.invalid", 28443)


def test_application_preflight_failure_closes_bridge_and_never_starts_serving(monkeypatch):
    observed = []

    class Bridge:
        def __init__(self, path, port, *, server_uid):
            assert (path, port, server_uid) == (Path("/connector/db.sock"), 5432, 23000)

        def start(self):
            observed.append("bridge_started")
            return self

        def close(self):
            observed.append("bridge_closed")

    def check(command, *, check):
        assert command == [
            sys.executable,
            "-m",
            "tools.imp03_runtime",
            "check",
            "--root",
            "/runtime/configuration",
            "--role",
            "identity",
        ]
        assert check is True
        observed.append("preflight_failed")
        raise subprocess.CalledProcessError(1, command)

    def forbidden(*args, **kwargs):
        pytest.fail("Serving child must not start after failed configuration check")

    monkeypatch.setattr(relay, "ThreadedLoopbackBridge", Bridge)
    monkeypatch.setattr(relay.subprocess, "run", check)
    monkeypatch.setattr(relay.subprocess, "Popen", forbidden)
    with pytest.raises(subprocess.CalledProcessError):
        relay.run_application(
            Path("/runtime/configuration"),
            "identity",
            [(5432, 23000, Path("/connector/db.sock"))],
        )
    assert observed == ["bridge_started", "preflight_failed", "bridge_closed"]
