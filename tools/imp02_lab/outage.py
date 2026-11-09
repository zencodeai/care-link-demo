"""Nonce-bound filesystem handshake, never a public browser control endpoint."""

import json
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast
from uuid import UUID

type Phase = Literal["main_down", "identity_down", "restored"]


@dataclass(frozen=True)
class OutageResult:
    applied: bool
    mock_used: bool


class OutageController:
    def __init__(self, directory: Path, apply: Callable[[Phase], OutageResult]) -> None:
        self.directory, self.apply = directory, apply
        self.last_nonce: str | None = None
        metadata = directory.stat()
        if (
            not directory.is_absolute()
            or directory.is_symlink()
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise ValueError("outage control requires existing owner-only session directory")

    def poll_once(self) -> bool:
        path = self.directory / "request.json"
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return False
        try:
            metadata = os.fstat(fd)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_size > 2048
            ):
                raise ValueError("unsafe outage request")
            value = cast(dict[str, object], json.loads(os.read(fd, 2049)))
        finally:
            os.close(fd)
        if not isinstance(value, dict) or set(value) != {"nonce", "phase"}:
            raise ValueError("invalid outage request")
        nonce, phase = value["nonce"], value["phase"]
        if (
            not isinstance(nonce, str)
            or str(UUID(nonce)) != nonce
            or phase not in {"main_down", "identity_down", "restored"}
        ):
            raise ValueError("invalid outage phase/nonce")
        if nonce == self.last_nonce:
            return False
        result = self.apply(cast(Phase, phase))
        if not result.applied:
            return False
        payload = json.dumps(
            {"nonce": nonce, "phase": phase, "status": "applied", "mock_used": result.mock_used}
        ).encode()
        target = self.directory / "ack.json"
        temporary = self.directory / ("ack-" + nonce + ".tmp")
        ack = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(ack, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)
        self.last_nonce = nonce
        return True
