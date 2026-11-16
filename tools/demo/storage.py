"""Owner-only atomic local registry, with process locks and no runtime credentials."""

import fcntl
import json
import os
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .errors import DemoError
from .models import SCHEMA_VERSION, Record, identifier, record


def default_root() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/CARE-Link Demo"
    return (
        Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "care-link-demo"
    )


def private_directory(path: Path, *, create: bool = False) -> None:
    if not path.is_absolute() or any(part == ".." for part in path.parts):
        raise DemoError("absolute_private_path_required")
    # Do not traverse symlinks, including a symlinked parent.
    for ancestor in [*reversed(path.parents), path]:
        if ancestor.is_symlink():
            raise DemoError("private_path_symlink")
    if not path.exists() and create:
        path.mkdir(parents=True, mode=0o700)
    try:
        item = path.lstat()
    except OSError as error:
        raise DemoError("private_directory_missing") from error
    if (
        not stat.S_ISDIR(item.st_mode)
        or item.st_uid != os.geteuid()
        or stat.S_IMODE(item.st_mode) != 0o700
    ):
        raise DemoError("private_directory_custody")


def private_read(path: Path, *, limit: int = 1024 * 1024) -> bytes:
    private_directory(path.parent)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            item = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(item.st_mode)
                or item.st_uid != os.geteuid()
                or stat.S_IMODE(item.st_mode) != 0o600
            ):
                raise DemoError("private_file_custody")
            raw = stream.read(limit + 1)
            if len(raw) > limit:
                raise DemoError("private_file_too_large")
            return raw
    except OSError as error:
        raise DemoError("private_file_unavailable") from error


def private_write(path: Path, raw: bytes) -> None:
    private_directory(path.parent)
    if path.exists() or path.is_symlink():
        private_read(path)
    temporary = path.with_name("." + path.name + "." + uuid4().hex)
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


class Registry:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_root()
        private_directory(self.root, create=True)
        self.path = self.root / "registry.json"
        self.locks = self.root / "locks"
        private_directory(self.locks, create=True)

    @contextmanager
    def lock(self, scope: str = "registry") -> Iterator[None]:
        path = self.locks / (identifier(scope) + ".lock")
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            item = os.fstat(fd)
            if (
                item.st_uid != os.geteuid()
                or not stat.S_ISREG(item.st_mode)
                or stat.S_IMODE(item.st_mode) != 0o600
            ):
                raise DemoError("lock_custody")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def read(self) -> Record:
        if not self.path.exists() and not self.path.is_symlink():
            return {
                "schema_version": SCHEMA_VERSION,
                "environments": {},
                "runs": {},
                "operations": {},
                "credential_operations": {},
            }
        try:
            value = record(json.loads(private_read(self.path)))
        except (ValueError, UnicodeError) as error:
            raise DemoError("registry_invalid") from error
        if (
            set(value)
            != {"schema_version", "environments", "runs", "operations", "credential_operations"}
            or type(value["schema_version"]) is not int
            or value["schema_version"] != SCHEMA_VERSION
        ):
            raise DemoError("registry_version_incompatible")
        for key in ("environments", "runs", "operations", "credential_operations"):
            record(value[key])
        return value

    def write(self, value: Record) -> None:
        private_write(self.path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())
