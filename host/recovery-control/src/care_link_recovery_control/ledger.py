"""Signed single-host recovery ledger, serialized and durably replaced."""

import fcntl
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from care_link_domain import ManualError
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .encoding import canonical, fsync_directory, read, record, signed, verify, write_new

MAX_GENERATION = 9223372036854775807


class RecoveryLedger:
    def __init__(self, path: Path, signer: Ed25519PrivateKey) -> None:
        if path.is_symlink() or not path.is_dir():
            raise ManualError("recovery.custody_unavailable", 503)
        self.path = path
        self.signer = signer
        self.lock = threading.RLock()
        self.high_water = 0
        self._depth = 0
        with self.exclusive():
            self.load()

    @classmethod
    def provision(
        cls, path: Path, signer: Ed25519PrivateKey, *, initial_serving_generation: int = 1
    ) -> RecoveryLedger:
        if not 1 <= initial_serving_generation < MAX_GENERATION:
            raise ValueError("bounded initial serving generation required")
        path.mkdir(mode=0o700, parents=False, exist_ok=False)
        write_new(path / "writer.lock", b"")
        value: dict[str, object] = {
            "format_version": "care.recovery.v1",
            "revision": 0,
            "targets": {},
            "promotions": {},
            "commands": {},
            "serving": None,
            "next_generation": initial_serving_generation + 1,
        }
        write_new(path / "ledger.json", canonical(signed(value, signer)))
        fsync_directory(path)
        fsync_directory(path.parent)
        return cls(path, signer)

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        with self.lock:
            if self._depth:
                self._depth += 1
                try:
                    yield
                finally:
                    self._depth -= 1
                return
            try:
                descriptor = os.open(self.path / "writer.lock", os.O_RDWR | os.O_NOFOLLOW)
                with os.fdopen(descriptor, "rb") as handle:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                    self._depth = 1
                    try:
                        yield
                    finally:
                        self._depth = 0
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError as error:
                raise ManualError("recovery.custody_unavailable", 503) from error

    def load(self) -> dict[str, object]:
        try:
            value = verify(record(read(self.path / "ledger.json")), self.signer)
        except OSError as error:
            raise ManualError("recovery.ledger_unavailable", 503) from error
        if (
            value.get("format_version") != "care.recovery.v1"
            or not isinstance(value.get("revision"), int)
            or int(str(value["revision"])) < self.high_water
            or (
                value.get("next_generation") is not None
                and (
                    type(value.get("next_generation")) is not int
                    or not 1 <= int(str(value["next_generation"])) <= MAX_GENERATION
                )
            )
            or any(
                not isinstance(value.get(k), dict) for k in ("targets", "promotions", "commands")
            )
        ):
            raise ManualError("recovery.ledger_invalid", 503)
        self.high_water = int(str(value["revision"]))
        return value

    def save(self, value: dict[str, object]) -> None:
        value["revision"] = int(str(value["revision"])) + 1
        temporary = self.path / (str(uuid4()) + ".tmp")
        write_new(temporary, canonical(signed(value, self.signer)))
        os.replace(temporary, self.path / "ledger.json")
        fsync_directory(self.path)
        self.high_water = int(str(value["revision"]))
