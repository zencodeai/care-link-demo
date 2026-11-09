"""Restriction-only, fsync'd local workload ledger. No positive permission cache.

The ledger is an OS-custodied local restriction source, not a business journal or
proof against host rollback/root compromise. Every read verifies the full chain.
"""

import fcntl
import hashlib
import json
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import cast


class TrustDenied(PermissionError):
    """Content-free authorization failure."""


def _canonical(value: dict[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise TrustDenied("corrupt fence")
        result[key] = value
    return result


@dataclass(frozen=True)
class FenceState:
    generation: int
    allowed: frozenset[str]
    denied: frozenset[str]
    commands: tuple[tuple[str, str], ...]
    head: str

    def admits(self, peer: str) -> bool:
        return peer in self.allowed and peer not in self.denied


class FenceStore:
    def __init__(
        self, directory: Path, owner_uid: int, filename: str = "workload-fence.jsonl"
    ) -> None:
        if filename != Path(filename).name or owner_uid < 0:
            raise ValueError("invalid fence custody")
        self.directory, self.owner_uid, self.filename = directory, owner_uid, filename

    @contextmanager
    def _directory(self) -> Iterator[int]:
        try:
            fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError as error:
            raise TrustDenied("fence directory unavailable") from error
        try:
            metadata = os.fstat(fd)
            if metadata.st_uid != self.owner_uid or stat.S_IMODE(metadata.st_mode) != 0o700:
                raise TrustDenied("unsafe fence directory")
            yield fd
        finally:
            os.close(fd)

    def _read_fd(self, fd: int) -> FenceState:
        metadata = os.fstat(fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != self.owner_uid
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size > 1024 * 1024
        ):
            raise TrustDenied("unsafe fence file")
        os.lseek(fd, 0, os.SEEK_SET)
        raw = bytearray()
        remaining = metadata.st_size
        while remaining:
            chunk = os.read(fd, min(remaining, 64 * 1024))
            if not chunk:
                raise TrustDenied("fence short read")
            raw.extend(chunk)
            remaining -= len(chunk)
        after = os.fstat(fd)
        if after.st_size != metadata.st_size or after.st_mtime_ns != metadata.st_mtime_ns:
            raise TrustDenied("fence changed while reading")
        if not raw or not raw.endswith(b"\n") or len(raw) > 1024 * 1024:
            raise TrustDenied("incomplete fence")
        try:
            rows = [
                cast(dict[str, object], json.loads(line, object_pairs_hook=_unique))
                for line in raw.decode("utf-8", errors="strict").splitlines()
            ]
            first = rows[0]
            if (
                set(first) != {"version", "generation", "allowed", "previous", "hash"}
                or first["version"] != 1
                or type(first["version"]) is not int
                or type(first["generation"]) is not int
                or first["generation"] != 0
                or first["previous"] != "0" * 64
            ):
                raise TrustDenied("invalid fence genesis")
            allowed = first["allowed"]
            if (
                not isinstance(allowed, list)
                or not allowed
                or any(not isinstance(x, str) for x in cast(list[object], allowed))
            ):
                raise TrustDenied("invalid fence peers")
            peers = frozenset(cast(list[str], allowed))
            if len(peers) != len(cast(list[object], allowed)):
                raise TrustDenied("duplicate fence peer")
            generation, denied, commands, previous = (
                0,
                set[str](),
                list[tuple[str, str]](),
                "0" * 64,
            )
            for index, row in enumerate(rows):
                content = {k: v for k, v in row.items() if k != "hash"}
                expected = hashlib.sha256(_canonical(content)).hexdigest()
                if (
                    row["hash"] != expected
                    or row["previous"] != previous
                    or type(row["generation"]) is not int
                    or row["generation"] != index
                ):
                    raise TrustDenied("broken fence chain")
                if index:
                    if set(row) != {"generation", "peer", "command_id", "previous", "hash"}:
                        raise TrustDenied("invalid restriction shape")
                    peer, command = row["peer"], row["command_id"]
                    if (
                        not isinstance(peer, str)
                        or peer not in peers
                        or not isinstance(command, str)
                        or any(key == command for key, _ in commands)
                    ):
                        raise TrustDenied("invalid restriction")
                    denied.add(peer)
                    commands.append((command, peer))
                previous = expected
                generation = index
            return FenceState(generation, peers, frozenset(denied), tuple(commands), previous)
        except (ValueError, UnicodeError, KeyError, TypeError) as error:
            raise TrustDenied("corrupt fence") from error

    def read(self) -> FenceState:
        with self._directory() as directory:
            try:
                fd = os.open(self.filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
                try:
                    fcntl.flock(fd, fcntl.LOCK_SH)
                    return self._read_fd(fd)
                finally:
                    os.close(fd)
            except OSError as error:
                raise TrustDenied("fence unavailable") from error

    def durable_read(self) -> FenceState:
        """Confirm bytes durably before acknowledging a previously uncertain command.

        Shared flock excludes the append writer. A crash may have left complete
        but previously unacknowledged bytes in cache; fsync makes this read a
        fresh durability confirmation rather than inventing an old receipt.
        """
        with self._directory() as directory:
            try:
                fd = os.open(self.filename, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
                try:
                    fcntl.flock(fd, fcntl.LOCK_SH)
                    state = self._read_fd(fd)
                    os.fsync(fd)
                    return state
                finally:
                    os.close(fd)
            except OSError as error:
                raise TrustDenied("durable fence unavailable") from error

    def initialize(self, allowed: frozenset[str]) -> None:
        """Explicit local provisioning, exclusive create only; never repairs/replaces.

        The operator creates the protected directory under its declared custody.
        No HTTP handler invokes this administrative method.
        """
        if not allowed or any(not peer.startswith("spiffe://care-link.demo/") for peer in allowed):
            raise ValueError("exact demo SPIFFE identities required")
        row: dict[str, object] = {
            "version": 1,
            "generation": 0,
            "allowed": sorted(allowed),
            "previous": "0" * 64,
        }
        row["hash"] = hashlib.sha256(_canonical(row)).hexdigest()
        with self._directory() as directory:
            fd = os.open(
                self.filename,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory,
            )
            try:
                self._write(fd, _canonical(row) + b"\n")
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(directory)

    @staticmethod
    def _write(fd: int, payload: bytes) -> None:
        offset = 0
        while offset < len(payload):
            written = os.write(fd, payload[offset:])
            if written <= 0:
                raise TrustDenied("fence write incomplete")
            offset += written

    def restrict(self, peer: str, command_id: str, expected_generation: int) -> FenceState:
        """Append only; release/unfence requires a separate human-reviewed mechanism."""
        if not command_id or len(command_id) > 128:
            raise ValueError("bounded command identity required")
        with self._directory() as directory:
            try:
                fd = os.open(self.filename, os.O_RDWR | os.O_NOFOLLOW, dir_fd=directory)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX)
                    state = self._read_fd(fd)
                    prior = next(
                        (target for command, target in state.commands if command == command_id),
                        None,
                    )
                    if prior is not None:
                        if prior != peer:
                            raise TrustDenied("restriction command conflict")
                        os.fsync(fd)
                        return state
                    if expected_generation != state.generation or peer not in state.allowed:
                        raise TrustDenied("stale restriction target")
                    row: dict[str, object] = {
                        "generation": state.generation + 1,
                        "peer": peer,
                        "command_id": command_id,
                        "previous": state.head,
                    }
                    row["hash"] = hashlib.sha256(_canonical(row)).hexdigest()
                    os.lseek(fd, 0, os.SEEK_END)
                    self._write(fd, _canonical(row) + b"\n")
                    os.fsync(fd)
                    return self._read_fd(fd)
                finally:
                    os.close(fd)
            except OSError as error:
                raise TrustDenied("restriction unavailable") from error
