"""Owned TLS loopback listeners for the synthetic IMP-10 outage topology."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import ssl
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import monotonic
from types import TracebackType
from typing import Any

import httpx
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from starlette.types import ASGIApp

_HOST = "127.0.0.1"
_LIFECYCLE_TIMEOUT = 8


def _issue_loopback_certificate(directory: Path) -> ssl.SSLContext:
    now = datetime.now(UTC)
    root_key = ec.generate_private_key(ec.SECP256R1())
    root_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "IMP-10 fixture CA")])
    root_identifier = x509.SubjectKeyIdentifier.from_public_key(root_key.public_key())

    def certificate() -> x509.CertificateBuilder:
        return (
            x509.CertificateBuilder()
            .issuer_name(root_name)
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=1))
        )

    root = (
        certificate()
        .subject_name(root_name)
        .public_key(root_key.public_key())
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(root_identifier, critical=False)
        .add_extension(
            x509.KeyUsage(False, False, False, False, False, True, True, False, False),
            critical=True,
        )
        .sign(root_key, hashes.SHA256())
    )
    server_key = ec.generate_private_key(ec.SECP256R1())
    server_cert = (
        certificate()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "IMP-10 loopback")]))
        .public_key(server_key.public_key())
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(_HOST))]),
            critical=False,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(root_identifier),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()), critical=False
        )
        .sign(root_key, hashes.SHA256())
    )
    (directory / "loopback.pem").write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))
    (directory / "loopback.key").write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    trust = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    trust.minimum_version = ssl.TLSVersion.TLSv1_3
    trust.load_verify_locations(
        cadata=root.public_bytes(serialization.Encoding.PEM).decode("ascii")
    )
    return trust


def _reserve_listener(port: int = 0) -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((_HOST, port))
    except BaseException:
        listener.close()
        raise
    return listener


class _ServerThread:
    def __init__(self, name: str, app: ASGIApp, listener: socket.socket, tls: Path):
        self.app = app
        self.listener = listener
        self.failure: BaseException | None = None
        self.exited = Event()
        self._running_task: tuple[asyncio.AbstractEventLoop, asyncio.Task[None]] | None = None
        config = uvicorn.Config(
            app,
            interface="asgi3",
            http="h11",
            ws="none",
            proxy_headers=False,
            log_config=None,
            timeout_graceful_shutdown=2,
            ssl_certfile=tls / "loopback.pem",
            ssl_keyfile=tls / "loopback.key",
        )
        config.load()
        assert config.ssl is not None
        config.ssl.minimum_version = ssl.TLSVersion.TLSv1_3
        self.server = uvicorn.Server(config)
        self.thread = Thread(target=self._serve, name=f"imp10-{name}", daemon=True)

    async def _run_server(self) -> None:
        task = asyncio.current_task()
        assert task is not None
        self._running_task = asyncio.get_running_loop(), task
        await self.server.serve(sockets=[self.listener])

    def _serve(self) -> None:
        try:
            asyncio.run(self._run_server())
        except BaseException as error:
            self.failure = error
        finally:
            self.listener.close()
            self.exited.set()

    def start(self) -> None:
        self.thread.start()
        deadline = monotonic() + _LIFECYCLE_TIMEOUT
        while not self.server.started:
            if self.exited.wait(0.01):
                raise RuntimeError(f"{self.thread.name} failed to start") from self.failure
            if monotonic() >= deadline:
                raise TimeoutError(f"{self.thread.name} did not start")

    def close(self) -> None:
        self.server.should_exit = True
        try:
            if self.thread.ident is not None:
                self.thread.join(_LIFECYCLE_TIMEOUT)
                if self.thread.is_alive():
                    if self._running_task is not None:
                        loop, task = self._running_task
                        with suppress(RuntimeError):
                            loop.call_soon_threadsafe(task.cancel)
                    self.listener.close()
                    self.thread.join(1)
                    raise TimeoutError(f"{self.thread.name} did not stop")
                if self.failure is not None:
                    raise RuntimeError(f"{self.thread.name} failed") from self.failure
        finally:
            self.listener.close()


class _Role:
    def __init__(self) -> None:
        self.reservation: socket.socket | None = _reserve_listener()
        self.port: int = self.reservation.getsockname()[1]
        self.running: _ServerThread | None = None
        self.restart_factory: Callable[[], ASGIApp] | None = None

    def close(self) -> None:
        running, self.running = self.running, None
        if running is not None:
            running.close()
        if self.reservation is not None:
            self.reservation.close()
            self.reservation = None


class RoleTopology:
    """Run fixture apps on individually stoppable, privately trusted role origins."""

    def __init__(self, tmp_path: Path) -> None:
        self._tmp_path = tmp_path
        self._active: ExitStack | None = None
        self._roles: dict[str, _Role] = {}

    def __enter__(self) -> RoleTopology:
        if self._active is not None:
            raise RuntimeError("Outage topology is already active")
        with ExitStack() as entering:
            self._tls = Path(
                entering.enter_context(TemporaryDirectory(prefix="imp10-tls-", dir=self._tmp_path))
            )
            self._trust = _issue_loopback_certificate(self._tls)
            self._active = entering.pop_all()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        try:
            return self._resources().__exit__(exc_type, exc, traceback)
        finally:
            self._active = None
            self._roles.clear()

    def _resources(self) -> ExitStack:
        if self._active is None:
            raise RuntimeError("Outage topology requires an active context")
        return self._active

    @property
    def trust(self) -> ssl.SSLContext:
        """Expose the fixture CA for product adapters routed through this topology."""
        self._resources()
        return self._trust

    def origin(self, name: str) -> str:
        resources = self._resources()
        if name not in self._roles:
            role = _Role()
            resources.callback(role.close)
            self._roles[name] = role
        return f"https://{_HOST}:{self._roles[name].port}"

    def start(
        self, name: str, app: ASGIApp, *, restart_factory: Callable[[], ASGIApp] | None = None
    ) -> None:
        self.origin(name)
        role = self._roles[name]
        if role.running is not None:
            raise RuntimeError(f"{name} is already running")
        if role.reservation is None:
            role.reservation = _reserve_listener(role.port)
        role.running = _ServerThread(name, app, role.reservation, self._tls)
        role.reservation = None
        role.restart_factory = restart_factory
        try:
            role.running.start()
        except BaseException:
            role.close()
            raise

    @contextmanager
    def pause(self, name: str) -> Iterator[None]:
        role = self._roles[name]
        if role.running is None:
            raise RuntimeError(f"{name} is already stopped")
        app = role.running.app
        role.close()
        try:
            yield
        finally:
            factory = role.restart_factory
            self.start(name, app if factory is None else factory(), restart_factory=factory)

    def _require_owned_origin(self, request: httpx.Request) -> None:
        url = request.url
        if (
            url.scheme != "https"
            or url.host != _HOST
            or all(role.port != url.port for role in self._roles.values())
        ):
            raise ValueError("Outage topology clients require an owned HTTPS origin")

    def client(self, **kwargs: Any) -> httpx.Client:
        resources = self._resources()
        if kwargs.keys() & {"event_hooks", "mounts", "proxy", "transport"}:
            raise TypeError("Outage topology clients require the fixture transport")
        kwargs.setdefault("limits", httpx.Limits(max_keepalive_connections=0))
        client = httpx.Client(
            verify=self._trust,
            trust_env=False,
            event_hooks={"request": [self._require_owned_origin]},
            **kwargs,
        )
        resources.callback(client.close)
        return client
