"""Owner-private atomic operator state, retaining every run journal."""

import fcntl
import json
import os
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

from .types import JsonRecord


def private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Owner-private directory required")


def read_json(path: Path) -> JsonRecord:
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
        or info.st_size > 1048576
    ):
        raise ValueError("Owner-private bounded regular file required")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return cast(JsonRecord, value)


def write_json(path: Path, value: JsonRecord) -> None:
    private_directory(path.parent)
    if path.exists() or path.is_symlink():
        read_json(path)
    fd, temporary = tempfile.mkstemp(prefix=".review-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(value, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def exclusive(directory: Path) -> Iterator[None]:
    private_directory(directory)
    path = directory / ".lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o077 or not stat.S_ISREG(info.st_mode):
            raise ValueError("Owner-private lock required")
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)
