"""Fixed raw-stream bridges for network-isolated IMP-03 application processes.

Application-local TCP endpoints are always loopback. Their protected Unix
destinations belong to separate connectors with fixed TCP destinations. The
explicit ingress connector may listen on its own container interfaces; its
operator must publish only the approved loopback browser port and target only
the protected TLS proxy. Bytes are copied without protocol inspection or TLS
termination: libpq and HTTPS retain end-to-end TLS verification.
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import math
import os
import signal
import stat
import subprocess
import sys
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Self, cast

from care_link_workload_trust import SocketCustody, peer_uid
from care_link_workload_trust.unix_server import PeerSocket

Streams = tuple[asyncio.StreamReader, asyncio.StreamWriter]
Connector = Callable[[], Awaitable[Streams]]


@dataclass(frozen=True)
class RelayLimits:
    max_connections: int = 16
    connect_timeout: float = 2.0
    idle_timeout: float = 30.0
    max_lifetime: float = 300.0
    buffer_bytes: int = 65536

    def __post_init__(self) -> None:
        if not 1 <= self.max_connections <= 128 or not 1024 <= self.buffer_bytes <= 65536:
            raise ValueError("Bounded connection and buffer limits required")
        if any(
            not math.isfinite(value) or not 0 < value <= 3600
            for value in (self.connect_timeout, self.idle_timeout, self.max_lifetime)
        ):
            raise ValueError("Finite positive relay deadlines required")


DEFAULT_LIMITS = RelayLimits()


def _socket_path(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts or path.is_symlink():
        raise ValueError("Explicit absolute, nonsymlink Unix socket required")


def _port(value: int, *, ephemeral: bool = False) -> None:
    if not (0 if ephemeral else 1) <= value <= 65535:
        raise ValueError("Invalid TCP port")


async def _close(writer: asyncio.StreamWriter) -> None:
    writer.close()
    try:
        await asyncio.wait_for(writer.wait_closed(), timeout=1)
    except (TimeoutError, OSError):
        pass


async def _copy(left: Streams, right: Streams, limits: RelayLimits) -> None:
    """Bound simultaneous buffers, inactivity, lifetime and backpressure waits."""
    loop = asyncio.get_running_loop()
    started = activity = loop.time()

    async def pump(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal activity
        while content := await reader.read(limits.buffer_bytes):
            writer.write(content)
            await writer.drain()
            activity = loop.time()
        if writer.can_write_eof():
            writer.write_eof()
            await writer.drain()

    for writer in (left[1], right[1]):
        writer.transport.set_write_buffer_limits(
            high=limits.buffer_bytes, low=limits.buffer_bytes // 4
        )
    tasks = {
        asyncio.create_task(pump(left[0], right[1])),
        asyncio.create_task(pump(right[0], left[1])),
    }
    pending: set[asyncio.Task[None]] = tasks.copy()
    try:
        while pending:
            now = loop.time()
            remaining = min(
                started + limits.max_lifetime - now, activity + limits.idle_timeout - now
            )
            if remaining <= 0:
                raise TimeoutError("Fixed stream relay deadline exceeded")
            done, pending = await asyncio.wait(
                pending, timeout=remaining, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                task.result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class _Relay:
    def __init__(self, connect: Connector, limits: RelayLimits) -> None:
        self.connect = connect
        self.limits = limits
        self.server: asyncio.Server | None = None
        self.active: set[asyncio.Task[None]] = set()

    def admitted(self, writer: asyncio.StreamWriter) -> bool:
        return True

    async def accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is None:
            await _close(writer)
            return
        if len(self.active) >= self.limits.max_connections or not self.admitted(writer):
            await _close(writer)
            return
        self.active.add(task)
        upstream: Streams | None = None
        try:
            upstream = await asyncio.wait_for(self.connect(), self.limits.connect_timeout)
            await _copy((reader, writer), upstream, self.limits)
        except (OSError, ValueError, TimeoutError):
            # No credentials, protocol bytes, target errors or request logs.
            pass
        finally:
            if upstream is not None:
                await _close(upstream[1])
            await _close(writer)
            self.active.discard(task)

    async def close(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        tasks = tuple(self.active)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def serve_forever(self) -> None:
        if self.server is None:
            raise RuntimeError("Relay is not started")
        await self.server.serve_forever()


class UnixToTCPRelay(_Relay):
    """One custodied Unix listener, exact kernel peer UIDs, one TCP target."""

    def __init__(
        self,
        socket_path: Path,
        target_host: str,
        target_port: int,
        *,
        allowed_uids: frozenset[int],
        access_gid: int,
        owner_uid: int | None = None,
        limits: RelayLimits = DEFAULT_LIMITS,
    ) -> None:
        _socket_path(socket_path)
        _port(target_port)
        if not target_host or any(character.isspace() for character in target_host):
            raise ValueError("One explicit fixed TCP target required")
        if not allowed_uids or any(uid < 0 for uid in allowed_uids) or access_gid < 0:
            raise ValueError("Explicit kernel peer UID allowlist and access GID required")
        self.path = socket_path
        self.allowed_uids = allowed_uids
        self.owner_uid = os.geteuid() if owner_uid is None else owner_uid
        self.access_gid = access_gid
        self.custody: SocketCustody | None = None

        async def connect() -> Streams:
            return await asyncio.open_connection(
                target_host, target_port, limit=limits.buffer_bytes
            )

        super().__init__(connect, limits)

    def admitted(self, writer: asyncio.StreamWriter) -> bool:
        connection = writer.get_extra_info("socket")
        return isinstance(connection, PeerSocket) and peer_uid(connection) in self.allowed_uids

    async def start(self) -> Self:
        if self.server is not None or self.custody is not None:
            raise RuntimeError("Relay already started")
        self.custody = SocketCustody(self.path, self.owner_uid, self.access_gid)
        try:
            self.server = await asyncio.start_unix_server(
                self.accept,
                path=str(self.path),
                limit=self.limits.buffer_bytes,
                backlog=self.limits.max_connections,
                cleanup_socket=False,
            )
            self.custody.bound()
            os.chown(self.path, -1, self.access_gid)
            os.chmod(self.path, 0o660)
            return self
        except BaseException:
            await self.close()
            raise

    async def close(self) -> None:
        await super().close()
        if self.custody is not None:
            self.custody.close()
            self.custody = None


class LoopbackToUnixRelay(_Relay):
    """Local TCP transport preserving the original TLS client's hostname checks."""

    def __init__(
        self,
        socket_path: Path,
        listen_port: int,
        *,
        server_uid: int,
        limits: RelayLimits = DEFAULT_LIMITS,
    ) -> None:
        _socket_path(socket_path)
        _port(listen_port, ephemeral=True)
        if server_uid < 0:
            raise ValueError("Exact connector custodian UID required")
        self.path = socket_path
        self.listen_port = listen_port
        self.server_uid = server_uid

        async def connect() -> Streams:
            _socket_path(socket_path)
            metadata = socket_path.lstat()
            if (
                not stat.S_ISSOCK(metadata.st_mode)
                or metadata.st_uid != server_uid
                or metadata.st_mode & 0o007
            ):
                raise ValueError("Protected connector socket custody required")
            upstream = await asyncio.open_unix_connection(
                str(socket_path), limit=limits.buffer_bytes
            )
            connection = upstream[1].get_extra_info("socket")
            if not isinstance(connection, PeerSocket) or peer_uid(connection) != server_uid:
                await _close(upstream[1])
                raise ValueError("Connector kernel UID differs from configured custodian")
            return upstream

        super().__init__(connect, limits)

    @property
    def bound_port(self) -> int:
        if self.server is None or not self.server.sockets:
            raise RuntimeError("Relay is not started")
        return int(self.server.sockets[0].getsockname()[1])

    async def start(self) -> Self:
        if self.server is not None:
            raise RuntimeError("Relay already started")
        self.server = await asyncio.start_server(
            self.accept,
            host="127.0.0.1",
            port=self.listen_port,
            limit=self.limits.buffer_bytes,
            backlog=self.limits.max_connections,
        )
        return self


class TCPToTCPRelay(_Relay):
    """Trusted browser-ingress connector to one configured numeric TLS target.

    This is not an application listener or HTTP proxy. Docker publication and
    network membership belong to the operator; the target must be the protected
    core TLS proxy, which performs browser TLS and request authorization.
    """

    def __init__(
        self,
        listen_port: int,
        target_host: str,
        target_port: int,
        *,
        limits: RelayLimits = DEFAULT_LIMITS,
    ) -> None:
        _port(listen_port, ephemeral=True)
        _port(target_port)
        try:
            target = str(ipaddress.ip_address(target_host))
        except ValueError:
            raise ValueError("Explicit numeric ingress target IP required") from None
        self.listen_port = listen_port

        async def connect() -> Streams:
            return await asyncio.open_connection(target, target_port, limit=limits.buffer_bytes)

        super().__init__(connect, limits)

    @property
    def bound_port(self) -> int:
        if self.server is None or not self.server.sockets:
            raise RuntimeError("Relay is not started")
        return int(self.server.sockets[0].getsockname()[1])

    async def start(self) -> Self:
        if self.server is not None:
            raise RuntimeError("Relay already started")
        self.server = await asyncio.start_server(
            self.accept,
            host="0.0.0.0",  # noqa: S104 - trusted connector; operator publishes exact loopback port
            port=self.listen_port,
            limit=self.limits.buffer_bytes,
            backlog=self.limits.max_connections,
        )
        return self


class ThreadedLoopbackBridge:
    """A bounded background event loop for an ordinary application supervisor."""

    def __init__(
        self,
        socket_path: Path,
        listen_port: int,
        *,
        server_uid: int,
        limits: RelayLimits = DEFAULT_LIMITS,
    ) -> None:
        self.relay = LoopbackToUnixRelay(
            socket_path, listen_port, server_uid=server_uid, limits=limits
        )
        self.loop: asyncio.AbstractEventLoop | None = None
        self.stop: asyncio.Event | None = None
        self.ready = threading.Event()
        self.error: BaseException | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> Self:
        if self.thread is not None:
            raise RuntimeError("Threaded relay already started")

        async def run() -> None:
            self.loop = asyncio.get_running_loop()
            self.stop = asyncio.Event()
            try:
                await self.relay.start()
                self.ready.set()
                await self.stop.wait()
            finally:
                await self.relay.close()

        def entry() -> None:
            try:
                asyncio.run(run())
            except BaseException as error:
                self.error = error
            finally:
                self.ready.set()

        self.thread = threading.Thread(target=entry, name="imp03-loopback-relay", daemon=True)
        self.thread.start()
        if not self.ready.wait(timeout=5):
            self.close()
            raise TimeoutError("Local relay startup deadline exceeded")
        if self.error is not None:
            self.close()
            raise RuntimeError("Local relay startup failed") from self.error
        return self

    def close(self) -> None:
        if self.loop is not None and self.stop is not None and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self.stop.set)
        if self.thread is not None:
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                raise TimeoutError("Local relay shutdown deadline exceeded")

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(self, *_: object) -> None:
        self.close()


def run_application(root: Path, role: str, forwards: list[tuple[int, int, Path]]) -> int:
    """Keep exact child argv/PID receipts available to the existing pidfd helper."""
    if role not in {"identity", "core", "data", "pdp", "journal"} or not root.is_absolute():
        raise ValueError("Exact role and absolute runtime root required")
    bridges: list[ThreadedLoopbackBridge] = []
    child: subprocess.Popen[bytes] | None = None
    original: dict[int, int | Callable[[int, FrameType | None], object] | None] = {}
    try:
        for port, uid, path in forwards:
            bridges.append(ThreadedLoopbackBridge(path, port, server_uid=uid).start())
        subprocess.run(  # noqa: S603 - fixed configuration check before serving the exact role
            [
                sys.executable,
                "-m",
                "tools.imp03_runtime",
                "check",
                "--root",
                str(root),
                "--role",
                role,
            ],
            check=True,
        )
        child = subprocess.Popen(  # noqa: S603 - fixed module and bounded role/root
            [
                sys.executable,
                "-m",
                "tools.imp03_runtime",
                "serve",
                "--root",
                str(root),
                "--role",
                role,
            ]
        )

        def forward(signum: int, _frame: FrameType | None) -> None:
            if child.poll() is None:
                child.send_signal(signum)

        for signum in (signal.SIGTERM, signal.SIGINT):
            original[signum] = signal.signal(signum, forward)
        status = child.wait()
        return status if status >= 0 else 128 - status
    finally:
        for signum, handler in original.items():
            signal.signal(signum, handler)
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=2)
        for bridge in reversed(bridges):
            bridge.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    unix = commands.add_parser("unix")
    unix.add_argument("--socket", type=Path, required=True)
    unix.add_argument("--target-host", required=True)
    unix.add_argument("--target-port", type=int, required=True)
    unix.add_argument("--allowed-uid", type=int, action="append", required=True)
    unix.add_argument("--access-gid", type=int, required=True)
    local = commands.add_parser("loopback")
    local.add_argument("--socket", type=Path, required=True)
    local.add_argument("--listen-port", type=int, required=True)
    local.add_argument("--server-uid", type=int, required=True)
    ingress = commands.add_parser("ingress")
    ingress.add_argument("--listen-port", type=int, required=True)
    ingress.add_argument("--target-host", required=True)
    ingress.add_argument("--target-port", type=int, required=True)
    app = commands.add_parser("run")
    app.add_argument("--root", type=Path, required=True)
    app.add_argument(
        "--role", choices=("identity", "core", "data", "pdp", "journal"), required=True
    )
    app.add_argument("--forward", nargs=3, action="append", metavar=("PORT", "UID", "SOCKET"))
    args = parser.parse_args()
    if args.command == "run":
        forwards = [
            (int(port), int(uid), Path(path))
            for port, uid, path in cast(list[list[str]], args.forward or [])
        ]
        raise SystemExit(run_application(args.root, args.role, forwards))

    async def run() -> None:
        relay: UnixToTCPRelay | LoopbackToUnixRelay | TCPToTCPRelay
        if args.command == "unix":
            relay = UnixToTCPRelay(
                args.socket,
                args.target_host,
                args.target_port,
                allowed_uids=frozenset(cast(list[int], args.allowed_uid)),
                access_gid=args.access_gid,
            )
        elif args.command == "ingress":
            relay = TCPToTCPRelay(args.listen_port, args.target_host, args.target_port)
        else:
            relay = LoopbackToUnixRelay(args.socket, args.listen_port, server_uid=args.server_uid)
        await relay.start()
        try:
            await relay.serve_forever()
        finally:
            await relay.close()

    asyncio.run(run())


if __name__ == "__main__":
    main()
