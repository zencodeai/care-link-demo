"""Durable, current authority for the one evaluated IMP-06 model function.

Control custody owns the directory and its writable ledger. Role processes
receive read-only access and independently provisioned expected release pins.
The ledger never supplies trust roots, serving approvals, or measured pins.
"""

import os
import re
import sqlite3
import stat
from collections.abc import Callable, Iterator, Mapping
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import cast
from uuid import UUID

from care_link_domain import ManualError
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .release_custody_records import (
    EVALUATORS,
    ChangeClass,
    EvaluatorAck,
    EvaluatorBoot,
    HumanApproval,
    Purpose,
    ReleaseArtifact,
    ReleaseObservation,
    ReleaseRecord,
)
from .releases import ReleaseBindings

MAX_RECORD_BYTES = 128 * 1024
MAX_ACK_LIFETIME = timedelta(minutes=5)
_EPOCH_LIMIT = 9223372036854775807

_SCHEMA = """
BEGIN IMMEDIATE;
CREATE TABLE activations (
    epoch INTEGER PRIMARY KEY CHECK(epoch >= 0),
    id TEXT UNIQUE,
    state TEXT NOT NULL CHECK(state IN ('disabled', 'staged', 'active')),
    artifact BLOB,
    signature BLOB,
    approval BLOB,
    approval_signature BLOB
);
CREATE TABLE boots (
    sequence INTEGER PRIMARY KEY,
    instance TEXT NOT NULL,
    id TEXT UNIQUE NOT NULL
);
CREATE TABLE acknowledgments (
    epoch INTEGER NOT NULL,
    instance TEXT NOT NULL,
    evidence BLOB NOT NULL,
    signature BLOB NOT NULL,
    PRIMARY KEY (epoch, instance)
);
INSERT INTO activations (epoch, state) VALUES (0, 'disabled');
COMMIT;
"""


class ReleaseDenied(PermissionError):
    """Content-free deny at the control boundary."""


@dataclass(frozen=True)
class ReviewAuthority:
    key: Ed25519PublicKey
    maximum_class: ChangeClass


@dataclass(frozen=True)
class ReleaseTrust:
    target: str
    purpose: Purpose
    artifact_keys: Mapping[str, Ed25519PublicKey]
    evaluator_keys: Mapping[str, Ed25519PublicKey]
    reviewers: Mapping[str, ReviewAuthority] = field(default_factory=lambda: {})

    def __post_init__(self) -> None:
        if (
            re.fullmatch(r"[a-z0-9][a-z0-9-]{0,68}", self.target) is None
            or self.purpose not in ("serving", "qualification")
            or self.target.startswith("qual-") != (self.purpose == "qualification")
            or bool(self.reviewers) != (self.purpose == "serving")
            or not self.artifact_keys
            or frozenset(self.evaluator_keys) != EVALUATORS
        ):
            raise ValueError("invalid release trust configuration")
        keys = [
            *self.artifact_keys.values(),
            *self.evaluator_keys.values(),
            *(reviewer.key for reviewer in self.reviewers.values()),
        ]
        if len({key.public_bytes_raw() for key in keys}) != len(keys):
            raise ValueError("release authority keys must have distinct custody")
        object.__setattr__(self, "artifact_keys", MappingProxyType(dict(self.artifact_keys)))
        object.__setattr__(self, "evaluator_keys", MappingProxyType(dict(self.evaluator_keys)))
        object.__setattr__(self, "reviewers", MappingProxyType(dict(self.reviewers)))


def _decode[T: ReleaseRecord](record_type: type[T], value: object) -> T:
    if not isinstance(value, bytes) or not 0 < len(value) <= MAX_RECORD_BYTES:
        raise ReleaseDenied("invalid release evidence bytes")
    record = record_type.model_validate_json(value)
    # A canonical reserialization rejects duplicate, unknown or defaulted
    # fields at the signed boundary and identifies the exact persisted bytes.
    if record.signing_bytes() != value:
        raise ReleaseDenied("noncanonical release evidence")
    return record


def _signature(key: Ed25519PublicKey, signature: object, evidence: ReleaseRecord) -> None:
    if not isinstance(signature, bytes) or len(signature) != 64:
        raise ReleaseDenied("invalid evidence signature")
    key.verify(signature, evidence.signing_bytes())


def _utc(value: str) -> datetime:
    if not value.endswith("Z"):
        raise ReleaseDenied("release timestamp must be UTC")
    return datetime.fromisoformat(value)


def _advance(epoch: object) -> int:
    if type(epoch) is not int or not 0 <= epoch < _EPOCH_LIMIT:
        raise ReleaseDenied("invalid release epoch")
    return epoch + 1


class ReleaseCustody:
    def __init__(
        self,
        path: Path,
        *,
        trust: ReleaseTrust,
        owner_uid: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.path, self.trust, self.owner_uid, self.clock = path.absolute(), trust, owner_uid, clock

    def _directory(self) -> None:
        info = self.path.parent.stat(follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != self.owner_uid or info.st_mode & 0o022:
            raise ReleaseDenied("unsafe release custody directory")

    def initialize(self) -> None:
        """Provision a new ledger as its owner, never replace a prior activation."""
        self._directory()
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
        os.close(descriptor)
        with closing(self._connect(write=True)) as connection:
            connection.executescript(_SCHEMA)
        descriptor = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _connect(self, *, write: bool) -> sqlite3.Connection:
        self._directory()
        info = self.path.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != self.owner_uid
            or info.st_nlink != 1
            or info.st_mode & 0o022
            or (write and os.geteuid() != self.owner_uid)
        ):
            raise ReleaseDenied("unsafe release custody ledger")
        connection = sqlite3.connect(
            self.path.as_uri() + ("?mode=rw" if write else "?mode=ro"),
            uri=True,
            timeout=0.05,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _transaction(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        try:
            with closing(self._connect(write=write)) as connection, connection:
                if write:
                    connection.execute("PRAGMA synchronous=FULL")
                connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                yield connection
        except ReleaseDenied:
            raise
        except (
            sqlite3.Error,
            InvalidSignature,
            OSError,
            ValueError,
            KeyError,
            TypeError,
            ManualError,
        ) as error:
            raise ReleaseDenied("release authority unavailable") from error

    @staticmethod
    def _latest(connection: sqlite3.Connection) -> sqlite3.Row:
        row = cast(
            sqlite3.Row | None,
            connection.execute("SELECT * FROM activations ORDER BY epoch DESC LIMIT 1").fetchone(),
        )
        if row is None:
            raise ReleaseDenied("release ledger unavailable")
        return row

    @staticmethod
    def _boot(connection: sqlite3.Connection, instance: str) -> str | None:
        row = cast(
            sqlite3.Row | None,
            connection.execute(
                "SELECT id FROM boots WHERE instance = ? ORDER BY sequence DESC LIMIT 1",
                (instance,),
            ).fetchone(),
        )
        return cast(str, row["id"]) if row is not None else None

    def _artifact(self, row: sqlite3.Row) -> ReleaseArtifact:
        artifact = _decode(ReleaseArtifact, row["artifact"])
        if artifact.target != self.trust.target or artifact.purpose != self.trust.purpose:
            raise ReleaseDenied("release artifact scope mismatch")
        _signature(self.trust.artifact_keys[artifact.signer], row["signature"], artifact)
        self._approval(artifact, row)
        return artifact

    def _approval(self, artifact: ReleaseArtifact, row: sqlite3.Row) -> None:
        if self.trust.purpose == "qualification":
            if row["approval"] is not None or row["approval_signature"] is not None:
                raise ReleaseDenied("qualification cannot carry serving approval")
            return
        approval = _decode(HumanApproval, row["approval"])
        reviewer = self.trust.reviewers[approval.reviewer]
        _signature(reviewer.key, row["approval_signature"], approval)
        if (
            approval.target != artifact.target
            or approval.bundle_digest != artifact.bundle_digest
            or approval.activation_id != row["id"]
            or approval.epoch != row["epoch"]
            or approval.reviewer in {artifact.proposer, artifact.signer}
            or approval.authority != artifact.change_class
            or approval.authority > reviewer.maximum_class
            or not _utc(approval.issued_at) <= self.clock() < _utc(approval.expires_at)
        ):
            raise ReleaseDenied("current independent release approval required")

    def stage(
        self,
        artifact: ReleaseArtifact,
        signature: bytes,
        *,
        activation_id: str,
        expected_epoch: int,
        approval: HumanApproval | None = None,
        approval_signature: bytes | None = None,
    ) -> int:
        """Persist a new, initially restricted activation under compare-and-set."""
        try:
            canonical_id = str(UUID(activation_id))
        except ValueError as error:
            raise ReleaseDenied("canonical activation identity required") from error
        if canonical_id != activation_id:
            raise ReleaseDenied("canonical activation identity required")
        epoch = _advance(expected_epoch)
        with self._transaction(write=True) as connection:
            if self._latest(connection)["epoch"] != expected_epoch:
                raise ReleaseDenied("stale release epoch")
            connection.execute(
                "INSERT INTO activations VALUES (?, ?, 'staged', ?, ?, ?, ?)",
                (
                    epoch,
                    activation_id,
                    artifact.signing_bytes(),
                    signature,
                    approval.signing_bytes() if approval else None,
                    approval_signature,
                ),
            )
            self._artifact(self._latest(connection)).validated_function()
        return epoch

    def prepare(self, observation: ReleaseObservation) -> ReleaseArtifact:
        """Validate the exact staged pins before an evaluator runs its self-check."""
        with self._transaction() as connection:
            artifact = self._artifact(self._latest(connection))
            if artifact.observation != observation:
                raise ReleaseDenied("local release pins differ")
            artifact.validated_function()
            return artifact

    def current_boot(self, instance: str) -> str | None:
        if instance not in EVALUATORS:
            raise ReleaseDenied("unknown evaluator")
        with self._transaction() as connection:
            return self._boot(connection, instance)

    def register_boot(self, boot: EvaluatorBoot, signature: bytes) -> None:
        """Accept a signed new boot only from the exact instance and predecessor."""
        with self._transaction(write=True) as connection:
            boot = _decode(EvaluatorBoot, boot.signing_bytes())
            if boot.purpose != self.trust.purpose or boot.target != self.trust.target:
                raise ReleaseDenied("evaluator boot scope mismatch")
            _signature(self.trust.evaluator_keys[boot.instance], signature, boot)
            current = self._boot(connection, boot.instance)
            if current == boot.boot_id:
                return
            if current != boot.previous_boot_id:
                raise ReleaseDenied("stale evaluator boot")
            connection.execute(
                "INSERT INTO boots (instance, id) VALUES (?, ?)", (boot.instance, boot.boot_id)
            )

    def _matches_ack(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        bundle_digest: str,
        ack: EvaluatorAck,
        signature: object,
    ) -> bool:
        _signature(self.trust.evaluator_keys[ack.instance], signature, ack)
        issued, expires = _utc(ack.issued_at), _utc(ack.expires_at)
        return (
            ack.purpose == self.trust.purpose
            and ack.target == self.trust.target
            and ack.activation_id == row["id"]
            and ack.epoch == row["epoch"]
            and ack.bundle_digest == bundle_digest
            and ack.boot_id == self._boot(connection, ack.instance)
            and issued <= self.clock() < expires <= issued + MAX_ACK_LIFETIME
        )

    def acknowledge(self, acknowledgment: EvaluatorAck, signature: bytes) -> None:
        with self._transaction(write=True) as connection:
            row = self._latest(connection)
            artifact = self._artifact(row)
            ack = _decode(EvaluatorAck, acknowledgment.signing_bytes())
            if not self._matches_ack(connection, row, artifact.bundle_digest, ack, signature):
                raise ReleaseDenied("stale evaluator acknowledgment")
            existing = cast(
                sqlite3.Row | None,
                connection.execute(
                    "SELECT evidence FROM acknowledgments WHERE epoch = ? AND instance = ?",
                    (ack.epoch, ack.instance),
                ).fetchone(),
            )
            if existing is not None:
                prior = _decode(EvaluatorAck, existing["evidence"])
                if prior == ack:
                    return
                if prior.boot_id == ack.boot_id and _utc(prior.issued_at) >= _utc(ack.issued_at):
                    raise ReleaseDenied("stale evaluator acknowledgment")
            connection.execute(
                """INSERT INTO acknowledgments VALUES (?, ?, ?, ?)
                   ON CONFLICT(epoch, instance) DO UPDATE
                   SET evidence = excluded.evidence, signature = excluded.signature""",
                (ack.epoch, ack.instance, ack.signing_bytes(), signature),
            )

    def _ready(self, connection: sqlite3.Connection, row: sqlite3.Row, bundle_digest: str) -> bool:
        rows = connection.execute(
            "SELECT instance, evidence, signature FROM acknowledgments WHERE epoch = ?",
            (row["epoch"],),
        ).fetchall()
        if frozenset(record["instance"] for record in rows) != EVALUATORS:
            return False
        for record in rows:
            ack = _decode(EvaluatorAck, record["evidence"])
            if (
                ack.status != "ready"
                or ack.instance != record["instance"]
                or not self._matches_ack(connection, row, bundle_digest, ack, record["signature"])
            ):
                return False
        return True

    def activate(self, *, expected_epoch: int) -> None:
        with self._transaction(write=True) as connection:
            row = self._latest(connection)
            if type(expected_epoch) is not int or row["epoch"] != expected_epoch:
                raise ReleaseDenied("stale release epoch")
            artifact = self._artifact(row)
            artifact.validated_function()
            if not self._ready(connection, row, artifact.bundle_digest):
                raise ReleaseDenied("current evaluator acknowledgments required")
            connection.execute(
                "UPDATE activations SET state = 'active' WHERE epoch = ?", (expected_epoch,)
            )

    def disable(self, *, expected_epoch: int) -> int:
        """Commit restrictive epoch first. Stale activation and ACKs cannot undo it."""
        epoch = _advance(expected_epoch)
        with self._transaction(write=True) as connection:
            if self._latest(connection)["epoch"] != expected_epoch:
                raise ReleaseDenied("stale release epoch")
            connection.execute(
                "INSERT INTO activations (epoch, state) VALUES (?, 'disabled')", (epoch,)
            )
        return epoch

    def _bindings(
        self, observation: ReleaseObservation, *, instance: str, boot_id: str
    ) -> ReleaseBindings:
        if instance not in EVALUATORS:
            raise ReleaseDenied("unknown evaluator")
        with self._transaction() as connection:
            row = self._latest(connection)
            artifact = self._artifact(row)
            if artifact.observation != observation or self._boot(connection, instance) != boot_id:
                raise ReleaseDenied("local evaluator pins or boot differ")
            manifest, function = artifact.validated_function()
            epoch = cast(int, row["epoch"])

        def current() -> bool:
            try:
                with self._transaction() as connection:
                    now = self._latest(connection)
                    if (
                        now["state"] != "active"
                        or now["epoch"] != epoch
                        or self._boot(connection, instance) != boot_id
                    ):
                        return False
                    selected = self._artifact(now)
                    bundle_digest = selected.bundle_digest
                    return bundle_digest == manifest.release_digest and self._ready(
                        connection, now, bundle_digest
                    )
            except ReleaseDenied:
                return False

        return ReleaseBindings(manifest, (function,), current, observation.catalog_digest)

    def serving_bindings(
        self, observation: ReleaseObservation, *, instance: str, boot_id: str
    ) -> ReleaseBindings:
        if self.trust.purpose != "serving":
            raise ReleaseDenied("serving release trust required")
        return self._bindings(observation, instance=instance, boot_id=boot_id)

    def qualification_bindings(
        self, observation: ReleaseObservation, *, instance: str, boot_id: str
    ) -> ReleaseBindings:
        if self.trust.purpose != "qualification":
            raise ReleaseDenied("disposable qualification trust required")
        return self._bindings(observation, instance=instance, boot_id=boot_id)
