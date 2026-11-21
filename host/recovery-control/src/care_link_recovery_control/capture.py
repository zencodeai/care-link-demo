"""Encrypted immutable capture and quarantine-only staging.

The caller supplies a consistent database dump/WAL position. This package does
not assert consistency of arbitrary input, execute a live restore, or promote a
serving generation. A separate current-rights validator is required after import.
"""

import re
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

from care_link_contracts import validate_contract
from care_link_domain import JournalState, ManualError
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

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

HEX = re.compile(r"^[0-9a-f]{64}$")
OBJECT_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}$")


@dataclass(frozen=True)
class CaptureMetadata:
    schema_version: str
    schema_digest: str
    artifact_digest: str
    audit_digest: str
    wal_position: str


@dataclass(frozen=True)
class QuarantineRestore:
    backup_id: str
    target_id: str
    path: Path
    manifest_digest: str
    journal: JournalState
    state: str = "quarantined_unvalidated"
    serving_allowed: bool = False


class EncryptedCaptures:
    def __init__(
        self,
        path: Path,
        encryption_key: bytes,
        signing_key: Ed25519PrivateKey,
        key_id: str,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if len(encryption_key) != 32 or not key_id or len(key_id) > 128:
            raise ValueError("separate 256-bit encryption key and key identity required")
        if path.is_symlink() or not path.is_dir():
            raise ManualError("capture.custody_unavailable", 503)
        self.path = path
        self.cipher = AESGCM(encryption_key)
        self.signer = signing_key
        self.key_id = key_id
        self.clock = clock

    @staticmethod
    def provision(path: Path) -> None:
        path.mkdir(mode=0o700, parents=False, exist_ok=False)
        fsync_directory(path.parent)

    def capture(
        self,
        backup_id: str,
        objects: Mapping[str, bytes],
        metadata: CaptureMetadata,
        journal: JournalState,
        *,
        capture_at: datetime,
    ) -> dict[str, object]:
        identity = str(UUID(backup_id))
        objects = dict(objects)
        if not objects or "database.dump" not in objects:
            raise ValueError("consistent database.dump input required")
        if any(not OBJECT_NAME.fullmatch(name) or name == "manifest.json" for name in objects):
            raise ValueError("bounded flat inventory object names required")
        if (
            not 1 <= len(metadata.schema_version) <= 64
            or not 1 <= len(metadata.wal_position) <= 128
        ):
            raise ValueError("schema version and WAL position required")
        if any(
            not HEX.fullmatch(value)
            for value in (metadata.schema_digest, metadata.artifact_digest, metadata.audit_digest)
        ):
            raise ValueError("exact schema, artifact and audit digests required")
        if capture_at.tzinfo is None or capture_at > self.clock():
            raise ValueError("original nonfuture UTC capture time required")
        expires_at = capture_at + timedelta(days=7)
        if self.clock() >= expires_at:
            raise ManualError("capture.expired", 410)
        manifest: dict[str, object] = {
            "format_version": "care.capture.v1",
            "id": identity,
            "key_id": self.key_id,
            "capture_at": stamp(capture_at),
            "expires_at": stamp(expires_at),
            "schema_version": metadata.schema_version,
            "schema_digest": metadata.schema_digest,
            "artifact_digest": metadata.artifact_digest,
            "audit_digest": metadata.audit_digest,
            "wal_position": metadata.wal_position,
            "journal_id": journal.journal_id,
            "journal_generation": str(journal.generation),
            "journal_tip": str(journal.tip),
            "journal_digest": journal.tip_digest,
            "journal_barrier": str(journal.restriction_barrier),
            "serving_generation": str(journal.serving_generation),
            "objects": [
                {"name": name, "digest": digest(value), "size": len(value)}
                for name, value in sorted(objects.items())
            ],
        }
        destination = self.path / identity
        if destination.exists():
            existing = self._manifest(identity)
            if canonical(existing) != canonical(manifest):
                raise ManualError("capture.idempotency_conflict", 409)
            self._decrypt(identity, existing)
            return self._view(existing)
        # A partial directory is never silently adopted or overwritten on retry.
        destination.mkdir(mode=0o700, exist_ok=False)
        associated = canonical(manifest)
        for name, value in sorted(objects.items()):
            nonce = secrets.token_bytes(12)
            encrypted = nonce + self.cipher.encrypt(nonce, value, associated + name.encode())
            write_new(destination / (name + ".aesgcm"), encrypted)
        write_new(destination / "manifest.json", canonical(signed(manifest, self.signer)))
        fsync_directory(destination)
        fsync_directory(self.path)
        verified = self._manifest(identity)
        self._decrypt(identity, verified)
        return self._view(verified)

    def _manifest(self, identity: str, *, allow_expired: bool = False) -> dict[str, object]:
        directory = self.path / str(UUID(identity))
        if directory.is_symlink() or not directory.is_dir():
            raise ManualError("capture.custody_unavailable", 503)
        try:
            manifest = verify(record(read(directory / "manifest.json")), self.signer)
        except OSError as error:
            raise ManualError("capture.incomplete", 503) from error
        keys = {
            "format_version",
            "id",
            "key_id",
            "capture_at",
            "expires_at",
            "schema_version",
            "schema_digest",
            "artifact_digest",
            "audit_digest",
            "wal_position",
            "journal_id",
            "journal_generation",
            "journal_tip",
            "journal_digest",
            "journal_barrier",
            "serving_generation",
            "objects",
        }
        if set(manifest) != keys or (
            manifest.get("format_version") != "care.capture.v1"
            or manifest.get("id") != identity
            or manifest.get("key_id") != self.key_id
        ):
            raise ManualError("capture.manifest_invalid", 503)
        capture_at = datetime.fromisoformat(str(manifest["capture_at"]).replace("Z", "+00:00"))
        expires_at = datetime.fromisoformat(str(manifest["expires_at"]).replace("Z", "+00:00"))
        if expires_at != capture_at + timedelta(days=7):
            raise ManualError("capture.manifest_invalid", 503)
        if not allow_expired and self.clock() >= expires_at:
            raise ManualError("capture.expired", 410)
        return manifest

    def _decrypt(self, identity: str, manifest: dict[str, object]) -> dict[str, bytes]:
        inventory = manifest.get("objects")
        if not isinstance(inventory, list) or not inventory:
            raise ManualError("capture.inventory_invalid", 503)
        result: dict[str, bytes] = {}
        associated = canonical(manifest)
        directory = self.path / identity
        try:
            for item in cast(list[object], inventory):
                if not isinstance(item, dict):
                    raise ValueError("inventory item")
                entry = cast(dict[str, object], item)
                name = entry.get("name")
                if (
                    set(entry) != {"name", "digest", "size"}
                    or not isinstance(name, str)
                    or not OBJECT_NAME.fullmatch(name)
                    or name in result
                ):
                    raise ValueError("invalid inventory")
                encrypted = read(directory / (name + ".aesgcm"))
                value = self.cipher.decrypt(
                    encrypted[:12], encrypted[12:], associated + name.encode()
                )
                if digest(value) != entry["digest"] or len(value) != entry["size"]:
                    raise ValueError("object digest mismatch")
                result[name] = value
        except (InvalidTag, ValueError, OSError) as error:
            raise ManualError("capture.object_invalid", 503) from error
        expected_files = {"manifest.json", *(name + ".aesgcm" for name in result)}
        if {item.name for item in directory.iterdir()} != expected_files:
            raise ManualError("capture.inventory_incomplete", 503)
        return result

    def manifest(self, backup_id: str) -> dict[str, object]:
        """Verified immutable metadata for recovery binding; no plaintext objects."""
        return self._manifest(str(UUID(backup_id)))

    def inventory(self) -> tuple[dict[str, object], ...]:
        """Every retained capture, preserving its original expiry after restores."""
        result: list[dict[str, object]] = []
        for entry in sorted(self.path.iterdir()):
            identity = str(UUID(entry.name))
            manifest = self._manifest(identity, allow_expired=True)
            expires = datetime.fromisoformat(str(manifest["expires_at"]).replace("Z", "+00:00"))
            if self.clock() < expires:
                self._decrypt(identity, manifest)
            view = self._view(manifest)
            if self.clock() >= expires:
                view["state"] = "expired"
            result.append(view)
        return tuple(result)

    def expire(self, backup_id: str, *, retained_by_hold: bool) -> dict[str, object]:
        """Account for known encrypted copies; this is not physical erasure proof.

        The maintenance composition obtains current hold authority before calling.
        The signed original manifest remains as the immutable accounting record.
        """
        identity = str(UUID(backup_id))
        manifest = self._manifest(identity, allow_expired=True)
        expires = datetime.fromisoformat(str(manifest["expires_at"]).replace("Z", "+00:00"))
        if self.clock() < expires or retained_by_hold:
            raise ManualError("capture.expiry_or_hold_denied", 409)
        directory = self.path / identity
        names = cast(list[dict[str, object]], manifest["objects"])
        expected = {"manifest.json", *(str(item["name"]) + ".aesgcm" for item in names)}
        if not {entry.name for entry in directory.iterdir()} <= expected:
            raise ManualError("capture.inventory_incomplete", 503)
        for item in names:
            object_path = directory / (str(item["name"]) + ".aesgcm")
            if object_path.is_symlink():
                raise ManualError("capture.custody_unavailable", 503)
            object_path.unlink(missing_ok=True)
        fsync_directory(directory)
        return {
            "backup_id": identity,
            "manifest_digest": digest(canonical(manifest)),
            "expires_at": manifest["expires_at"],
            "known_encrypted_objects_unlinked": True,
            "physical_erasure_proven": False,
        }

    def inspect(self, backup_id: str) -> dict[str, object]:
        identity = str(UUID(backup_id))
        manifest = self._manifest(identity)
        self._decrypt(identity, manifest)
        return self._view(manifest)

    @staticmethod
    def _view(manifest: dict[str, object]) -> dict[str, object]:
        result: dict[str, object] = {
            "id": manifest["id"],
            "manifest_digest": digest(canonical(manifest)),
            "capture_at": manifest["capture_at"],
            "expires_at": manifest["expires_at"],
            "schema_version": manifest["schema_version"],
            "journal_barrier": manifest["journal_barrier"],
            "audit_digest": manifest["audit_digest"],
            "state": "verified",
        }
        validate_contract("BackupView", result)
        return result

    def restore_quarantine(
        self, backup_id: str, target: Path, current_journal: JournalState
    ) -> QuarantineRestore:
        """Stage verified bytes only; never run SQL or acquire serving authority."""
        identity = str(UUID(backup_id))
        manifest = self._manifest(identity)
        if (
            current_journal.journal_id != manifest["journal_id"]
            or str(current_journal.generation) != manifest["journal_generation"]
            or current_journal.tip < int(str(manifest["journal_tip"]))
            or current_journal.restriction_barrier < int(str(manifest["journal_barrier"]))
            or (
                current_journal.tip == int(str(manifest["journal_tip"]))
                and current_journal.tip_digest != manifest["journal_digest"]
            )
        ):
            raise ManualError("capture.current_journal_required", 503)
        objects = self._decrypt(identity, manifest)
        target_id = str(uuid4())
        target.mkdir(mode=0o700, parents=False, exist_ok=False)
        marker: dict[str, object] = {
            "format_version": "care.quarantine.v1",
            "target_id": target_id,
            "backup_id": identity,
            "manifest_digest": digest(canonical(manifest)),
            "state": "quarantined_unvalidated",
            "serving_allowed": False,
            "must_disable_restored_credentials": True,
            "must_reconcile_current_restrictions": True,
            "must_suspend_positive_grants": True,
            "journal_tip": str(current_journal.tip),
            "journal_digest": current_journal.tip_digest,
        }
        write_new(target / "quarantine.json", canonical(signed(marker, self.signer)))
        for name, value in objects.items():
            write_new(target / name, value)
        fsync_directory(target)
        fsync_directory(target.parent)
        return QuarantineRestore(
            backup_id=identity,
            target_id=target_id,
            path=target,
            manifest_digest=digest(canonical(manifest)),
            journal=current_journal,
        )
