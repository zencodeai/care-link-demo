"""One-shot commit-acknowledgement loss for the explicit continuation launcher.

Nothing here exposes an HTTP control or changes normal PostgresStore defaults.
The launcher alone may inject this connection factory for its leased synthetic
target. A matching transaction really commits before the driver error is raised.
"""

import fcntl
import json
import os
import stat
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import cast
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

Record = dict[str, object]
ConnectionContext = AbstractContextManager[psycopg.Connection[Record]]
MARKER = "commit-ack-fault.json"
CONSUMED = "commit-ack-fault.consumed.json"
LOCK = ".commit-ack-fault.lock"
MAX_MARKER_BYTES = 4096
REJECTED = "Qualification commit-acknowledgement control rejected"
LOST = "Qualification committed transaction acknowledgement lost"


def _directory(path: Path) -> None:
    info = path.lstat()
    if (
        not path.is_absolute()
        or path.is_symlink()
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise ValueError("Owner-only absolute qualification control directory required")


def _file(info: os.stat_result) -> None:
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise ValueError("Owner-only regular qualification control file required")


@contextmanager
def _exclusive(directory: Path) -> Iterator[None]:
    descriptor = os.open(directory / LOCK, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        _file(os.fstat(descriptor))
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def _unique(pairs: list[tuple[str, object]]) -> Record:
    result: Record = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate qualification control field")
        result[key] = value
    return result


@dataclass(frozen=True)
class _Marker:
    record: Record
    content: bytes
    device: int
    inode: int


def _read(path: Path) -> tuple[bytes, os.stat_result]:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        _file(before)
        content = os.read(descriptor, MAX_MARKER_BYTES + 1)
        after = os.fstat(descriptor)
        if (
            len(content) > MAX_MARKER_BYTES
            or before.st_size != len(content)
            or (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size)
        ):
            raise ValueError("Qualification control changed or exceeded its bound")
        return content, after
    finally:
        os.close(descriptor)


def _marker(directory: Path) -> _Marker | None:
    path = directory / MARKER
    try:
        content, info = _read(path)
    except FileNotFoundError:
        return None
    if (directory / CONSUMED).exists() or (directory / CONSUMED).is_symlink():
        raise ValueError("Qualification one-shot control was already consumed")
    value: object = json.loads(content, object_pairs_hook=_unique)
    if not isinstance(value, dict):
        raise ValueError("Qualification control object required")
    record = cast(Record, value)
    if set(record) != {
        "session",
        "journal_id",
        "operation_id",
        "principal_id",
        "operation_name",
        "expires_at",
    }:
        raise ValueError("Exact qualification control fields required")
    if record["session"] != "imp03-002" or record["operation_name"] != "session_human_request":
        raise ValueError("Wrong qualification operation or runtime lease")
    for key in ("journal_id", "operation_id", "principal_id"):
        identity = record[key]
        if not isinstance(identity, str) or str(UUID(identity)) != identity:
            raise ValueError("Canonical qualification operation identities required")
    expiry = record["expires_at"]
    if (
        not isinstance(expiry, str)
        or not expiry.endswith("Z")
        or datetime.fromisoformat(expiry).utcoffset() != UTC.utcoffset(None)
        or datetime.fromisoformat(expiry) <= datetime.now(UTC)
    ):
        raise ValueError("Current UTC qualification control expiry required")
    return _Marker(record, content, info.st_dev, info.st_ino)


def _matches(connection: psycopg.Connection[Record], marker: _Marker) -> bool:
    guard = connection.execute("SELECT journal_id FROM control.guard WHERE key='demo'").fetchone()
    if guard is None or str(guard.get("journal_id")) != marker.record["journal_id"]:
        raise ValueError("Qualification control belongs to another journal")
    operation = connection.execute(
        "SELECT operation_id,principal_id,operation_name,xmin::text::bigint AS born_xid,"
        "mod(pg_current_xact_id()::text::numeric,4294967296)::bigint AS current_xid "
        "FROM durable.operation WHERE operation_id=%s",
        (marker.record["operation_id"],),
    ).fetchone()
    return operation is not None and (
        str(operation.get("operation_id")) == marker.record["operation_id"]
        and str(operation.get("principal_id")) == marker.record["principal_id"]
        and operation.get("operation_name") == marker.record["operation_name"]
        and type(operation.get("born_xid")) is int
        and type(operation.get("current_xid")) is int
        and operation.get("born_xid") == operation.get("current_xid")
    )


def _consume(directory: Path, marker: _Marker) -> None:
    source, target = directory / MARKER, directory / CONSUMED
    content, info = _read(source)
    if (info.st_dev, info.st_ino, content) != (marker.device, marker.inode, marker.content):
        raise ValueError("Qualification control changed during commit")
    # Hard-link creation is exclusive: an existing destination cannot be
    # overwritten. No marker is consumed before the successful real commit.
    os.link(source, target, follow_symlinks=False)
    linked = target.lstat()
    if (linked.st_dev, linked.st_ino) != (marker.device, marker.inode):
        raise ValueError("Qualification control inode changed during consumption")
    source.unlink()
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class _CommitAcknowledgement(ConnectionContext):
    def __init__(self, connection: psycopg.Connection[Record], directory: Path) -> None:
        self.connection, self.directory = connection, directory

    def __enter__(self) -> psycopg.Connection[Record]:
        return self.connection.__enter__()

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        if kind is not None:
            return self.connection.__exit__(kind, error, traceback)
        try:
            _directory(self.directory)
            try:
                (self.directory / MARKER).lstat()
            except FileNotFoundError:
                return self.connection.__exit__(None, None, None)
            with _exclusive(self.directory):
                try:
                    marker = _marker(self.directory)
                    matched = marker is not None and _matches(self.connection, marker)
                except (OSError, ValueError, psycopg.Error):
                    rejected = psycopg.OperationalError(REJECTED)
                    self.connection.__exit__(type(rejected), rejected, None)
                    raise rejected from None
                result = self.connection.__exit__(None, None, None)
                if matched and marker is not None:
                    _consume(self.directory, marker)
                    raise psycopg.OperationalError(LOST)
                return result
        except (OSError, ValueError):
            # A pre-commit custody failure rolls back; a post-commit consumption
            # failure remains an unknown acknowledgement, never a fake success.
            if not self.connection.closed:
                rejected = psycopg.OperationalError(REJECTED)
                self.connection.__exit__(type(rejected), rejected, None)
            raise psycopg.OperationalError(REJECTED) from None


def connection_factory(directory: Path) -> Callable[[str], ConnectionContext]:
    """Create the optional one-shot wrapper; ordinary connections stay unchanged."""
    _directory(directory)

    def connect(dsn: str) -> ConnectionContext:
        connection = psycopg.Connection[Record].connect(
            dsn, connect_timeout=1, row_factory=dict_row
        )
        return _CommitAcknowledgement(connection, directory)

    return connect
