"""Fail-closed single-host Ed25519 restriction journal.

A data fsync followed by a head replacement is deliberately not a distributed
transaction. Any interrupted unmatched tail is quarantined rather than adopted.
"""

import fcntl
import os
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

from care_link_contracts import ContractError, validate_contract
from care_link_domain import JournalState, ManualError
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .encoding import (
    canonical,
    digest,
    fsync_directory,
    read,
    record,
    signed,
    stamp,
    verify,
    write_new,
)

ZERO = "0" * 64
MAX_REVISION = 9223372036854775807


class FileJournal:
    def __init__(
        self,
        path: Path,
        private_key: Ed25519PrivateKey,
        key_id: str,
        *,
        expected_journal_id: str,
        expected_generation: int = 1,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        crash_hook: Callable[[str], None] | None = None,
    ) -> None:
        self.path = path
        self.private_key = private_key
        self.key_id = key_id
        self.journal_id = str(UUID(expected_journal_id))
        self.generation = expected_generation
        self.clock = clock
        self.crash_hook = crash_hook
        self._lock = threading.RLock()
        self._last_tip: int = 0
        self._last_digest: str = ZERO
        if path.is_symlink() or not path.is_dir():
            raise ManualError("journal.custody_unavailable", 503)
        # Opening existing state never creates a missing head/origin/tail.
        self.head()

    @classmethod
    def provision(
        cls,
        path: Path,
        private_key: Ed25519PrivateKey,
        key_id: str,
        *,
        journal_id: str | None = None,
        generation: int = 1,
        serving_generation: int = 1,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> FileJournal:
        if not key_id or len(key_id) > 128:
            raise ValueError("bounded key identity required")
        if not 1 <= generation <= MAX_REVISION or not 1 <= serving_generation <= MAX_REVISION:
            raise ValueError("positive generation required")
        identity = str(UUID(journal_id)) if journal_id is not None else str(uuid4())
        path.mkdir(mode=0o700, parents=False, exist_ok=False)
        origin: dict[str, object] = {
            "format_version": "care.journal.origin.v1",
            "journal_id": identity,
            "generation": str(generation),
            "serving_generation": str(serving_generation),
            "key_id": key_id,
        }
        write_new(path / "origin.json", canonical(signed(origin, private_key)))
        write_new(path / "records.jsonl", b"")
        write_new(path / "writer.lock", b"")
        head: dict[str, object] = {
            "journal_id": identity,
            "generation": str(generation),
            "tip": "0",
            "tip_digest": ZERO,
            "restriction_barrier": "0",
            "serving_generation": str(serving_generation),
            "key_id": key_id,
        }
        write_new(path / "head.json", canonical(signed(head, private_key)))
        fsync_directory(path)
        fsync_directory(path.parent)
        return cls(
            path,
            private_key,
            key_id,
            expected_journal_id=identity,
            expected_generation=generation,
            clock=clock,
        )

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        with self._lock:
            try:
                descriptor = os.open(self.path / "writer.lock", os.O_RDWR | os.O_NOFOLLOW)
                with os.fdopen(descriptor, "rb") as lock:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                    try:
                        yield
                    finally:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            except OSError as error:
                raise ManualError("journal.custody_unavailable", 503) from error

    def _verified(self) -> tuple[dict[str, object], list[dict[str, object]]]:
        origin = verify(record(read(self.path / "origin.json")), self.private_key)
        expected_origin: dict[str, object] = {
            "format_version": "care.journal.origin.v1",
            "journal_id": self.journal_id,
            "generation": str(self.generation),
            "serving_generation": origin.get("serving_generation"),
            "key_id": self.key_id,
        }
        if origin != expected_origin:
            raise ManualError("journal.identity_mismatch", 503)
        head = verify(record(read(self.path / "head.json")), self.private_key)
        raw = read(self.path / "records.jsonl")
        if raw and not raw.endswith(b"\n"):
            raise ManualError("journal.torn_tail", 503)
        lines = raw.splitlines()
        previous, barrier, serving = ZERO, 0, int(str(origin["serving_generation"]))
        records: list[dict[str, object]] = []
        commands: set[str] = set()
        for sequence, line in enumerate(lines, start=1):
            entry = record(line)
            try:
                validate_contract("JournalRecord", entry)
            except ContractError as error:
                raise ManualError("journal.corrupt", 503) from error
            unsigned = verify(entry, self.private_key)
            claimed_hash = unsigned.pop("hash", None)
            if (
                unsigned.get("journal_id") != self.journal_id
                or unsigned.get("generation") != str(self.generation)
                or unsigned.get("sequence") != str(sequence)
                or unsigned.get("previous_hash") != previous
                or unsigned.get("key_id") != self.key_id
                or claimed_hash != digest(canonical(unsigned))
            ):
                raise ManualError("journal.chain_invalid", 503)
            command = cast(dict[str, object], entry["command"])
            command_id = str(command["command_id"])
            if command_id in commands or command.get("expected_tip") != str(sequence - 1):
                raise ManualError("journal.command_invalid", 503)
            commands.add(command_id)
            self._semantic(command)
            if command["kind"] in {"restrict_intent", "serving_fence"}:
                barrier = sequence
            if command["kind"] == "serving_fence":
                serving = 0
            previous = str(claimed_hash)
            records.append(entry)
        expected_head: dict[str, object] = {
            "journal_id": self.journal_id,
            "generation": str(self.generation),
            "tip": str(len(lines)),
            "tip_digest": previous,
            "restriction_barrier": str(barrier),
            "serving_generation": str(serving),
            "key_id": self.key_id,
        }
        if head != expected_head:
            raise ManualError("journal.head_mismatch", 503)
        if len(lines) < self._last_tip or (
            len(lines) == self._last_tip and previous != self._last_digest
        ):
            raise ManualError("journal.rollback_suspected", 503)
        self._last_tip, self._last_digest = len(lines), previous
        return head, records

    @staticmethod
    def _semantic(command: dict[str, object]) -> None:
        restriction = cast(dict[str, object], command["restriction"])
        kind = command["kind"]
        if kind == "serving_switch":
            raise ManualError("journal.serving_promotion_unavailable", 503)
        if kind in {"checkpoint", "db_commit_observed", "relax_intent"} and restriction != {
            "kind": "none"
        }:
            raise ManualError("journal.invalid_terminal_payload", 422)
        if kind == "restrict_intent" and restriction.get("kind") in {"none", "serving_fence"}:
            raise ManualError("journal.restriction_required", 422)
        if kind == "serving_fence" and restriction.get("kind") != "serving_fence":
            raise ManualError("journal.invalid_serving_fence", 422)
        if kind == "relax_intent" and command.get("relaxation_evidence_digest") is None:
            raise ManualError("journal.relaxation_evidence_required", 403)

    def _state(self, head: dict[str, object]) -> JournalState:
        return JournalState(
            journal_id=self.journal_id,
            generation=self.generation,
            tip=int(str(head["tip"])),
            tip_digest=str(head["tip_digest"]),
            restriction_barrier=int(str(head["restriction_barrier"])),
            serving_generation=int(str(head["serving_generation"])),
            observed_at=self.clock(),
        )

    def head(self) -> JournalState:
        with self._exclusive():
            head, _ = self._verified()
            return self._state(head)

    def records(self) -> tuple[dict[str, object], ...]:
        """Host-recovery inspection; callers still require scoped host authority."""
        with self._exclusive():
            _, records = self._verified()
            return tuple(records)

    def append(self, request: dict[str, object]) -> JournalState:
        # Freeze caller-owned containers before validation and signing.
        request = record(canonical(request))
        validate_contract("JournalAppend", request)
        self._semantic(request)
        with self._exclusive():
            head, records = self._verified()
            for entry in records:
                command = cast(dict[str, object], entry["command"])
                if command["command_id"] == request["command_id"]:
                    if canonical(command) != canonical(request):
                        raise ManualError("journal.idempotency_conflict", 409)
                    return self._state(head)
            tip = int(str(head["tip"]))
            if request["expected_tip"] != str(tip):
                raise ManualError("journal.stale_tip", 409)
            if tip >= MAX_REVISION:
                raise ManualError("journal.sequence_exhausted", 503)
            sequence = tip + 1
            unsigned: dict[str, object] = {
                "format_version": "care.journal.v1",
                "journal_id": self.journal_id,
                "generation": str(self.generation),
                "sequence": str(sequence),
                "command": request,
                "previous_hash": head["tip_digest"],
                "key_id": self.key_id,
                "durable_at": stamp(self.clock()),
            }
            entry = signed({**unsigned, "hash": digest(canonical(unsigned))}, self.private_key)
            validate_contract("JournalRecord", entry)
            descriptor = os.open(
                self.path / "records.jsonl", os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW
            )
            with os.fdopen(descriptor, "ab") as handle:
                handle.write(canonical(entry) + b"\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._crash("after_record_fsync")
            new_head: dict[str, object] = {
                **head,
                "tip": str(sequence),
                "tip_digest": entry["hash"],
            }
            if request["kind"] in {"restrict_intent", "serving_fence"}:
                new_head["restriction_barrier"] = str(sequence)
            if request["kind"] == "serving_fence":
                new_head["serving_generation"] = "0"
            temporary = self.path / ("head-" + str(uuid4()) + ".tmp")
            write_new(temporary, canonical(signed(new_head, self.private_key)))
            self._crash("after_head_fsync")
            os.replace(temporary, self.path / "head.json")
            self._crash("after_head_replace")
            fsync_directory(self.path)
            self._crash("after_directory_fsync")
            verified, _ = self._verified()
            return self._state(verified)

    def _crash(self, point: str) -> None:
        if self.crash_hook is not None:
            self.crash_hook(point)
