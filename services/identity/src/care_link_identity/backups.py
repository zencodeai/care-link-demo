"""Owned encrypted identity metadata snapshots with immutable seven-day expiry.

The protected directory and DB inventory are one declared custody scope. Capture,
reconciliation, expiry and clearance serialize through the same local OS lock.
No export/copy/restore promotion or physical-erasure claim is exposed here.
"""

import fcntl
import hashlib
import json
import os
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID

from .crypto import Custody, digest
from .domain import IdentityError, Store, instant, stamp, text
from .retention import PROFILE_FIELDS, RetentionService
from .retention_ports import BackupClearance, RetentionAuthority, validate_grant


class EncryptedIdentityBackups:
    def __init__(
        self,
        store: Store,
        custody: Custody,
        directory: Path,
        owner_uid: int,
        authority: RetentionAuthority | None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store, self.custody, self.directory, self.owner_uid, self.authority, self.clock = (
            store,
            custody,
            directory,
            owner_uid,
            authority,
            clock,
        )
        self.custody_id = digest(str(directory.resolve()) + "\0" + str(owner_uid))

    @contextmanager
    def _locked_directory(self) -> Iterator[int]:
        directory, lock = -1, -1
        try:
            directory = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            metadata = os.fstat(directory)
            if metadata.st_uid != self.owner_uid or stat.S_IMODE(metadata.st_mode) != 0o700:
                raise IdentityError("identity.backup_custody_denied", 503)
            lock = os.open(
                ".identity-backup.lock",
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory,
            )
            information = os.fstat(lock)
            if (
                information.st_uid != self.owner_uid
                or stat.S_IMODE(information.st_mode) != 0o600
                or not stat.S_ISREG(information.st_mode)
            ):
                raise IdentityError("identity.backup_lock_denied", 503)
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield directory
        except OSError as error:
            raise IdentityError("identity.backup_custody_unavailable", 503) from error
        finally:
            if lock >= 0:
                os.close(lock)
            if directory >= 0:
                os.close(directory)

    @staticmethod
    def _write(fd: int, payload: bytes) -> None:
        written = 0
        while written < len(payload):
            count = os.write(fd, payload[written:])
            if count <= 0:
                raise IdentityError("identity.backup_write_incomplete", 503)
            written += count

    def _ciphertext(self, directory: int, record: dict[str, object]) -> bytes:
        if record.get("custody_id") != self.custody_id:
            raise IdentityError("identity.backup_custody_mismatch", 503)
        capture_id = text(record, "capture_id")
        if str(UUID(capture_id)) != capture_id or record.get("filename") != capture_id + ".enc":
            raise IdentityError("identity.backup_filename_denied", 503)
        fd = os.open(text(record, "filename"), os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != self.owner_uid
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_size > 16 * 1024 * 1024
            ):
                raise IdentityError("identity.backup_file_denied", 503)
            value = bytearray()
            while len(value) < info.st_size:
                chunk = os.read(fd, min(65536, info.st_size - len(value)))
                if not chunk:
                    raise IdentityError("identity.backup_file_incomplete", 503)
                value.extend(chunk)
            if hashlib.sha256(value).hexdigest() != record["ciphertext_digest"]:
                raise IdentityError("identity.backup_integrity_denied", 503)
            os.fsync(fd)
            return bytes(value)
        finally:
            os.close(fd)

    def capture(self, capture_id: str, actor_proof: str) -> dict[str, object]:
        if str(UUID(capture_id)) != capture_id:
            raise IdentityError("identity.backup_capture_id_denied")
        if self.authority is None:
            raise IdentityError("identity.backup_authority_unavailable", 503)
        grant = self.authority.authorize(
            actor_proof, "capture_identity_backup", "00000000-0000-0000-0000-000000000000"
        )
        if (
            grant.action != "capture_identity_backup"
            or grant.target_account_id != "00000000-0000-0000-0000-000000000000"
        ):
            raise IdentityError("identity.backup_grant_scope_denied")
        with self._locked_directory() as directory:
            with self.store.transaction() as tx:
                validate_grant(tx, grant, self.clock())
                old = tx.get("backup_capture", capture_id)
            if old is not None:
                return self._reconcile_locked(directory, capture_id, old)
            with self.store.transaction() as tx:
                validate_grant(tx, grant, self.clock())
                now = self.clock()
                kinds = (
                    "account",
                    "account_marker",
                    "retention_record",
                    "retention_hold",
                    "head",
                    "issuer",
                    "workload_state",
                )
                rows = [(kind, key, payload) for kind in kinds for key, payload in tx.items(kind)]
                accounts = sorted(
                    {
                        text(payload, "account_id")
                        for kind, _key, payload in rows
                        if kind == "account"
                    }
                )
                profile_accounts = sorted(
                    {
                        text(payload, "account_id")
                        for kind, _key, payload in rows
                        if kind == "account" and bool(PROFILE_FIELDS & payload.keys())
                    }
                )
                capture_at, expires = stamp(now), stamp(now + timedelta(days=7))
                envelope = {
                    "capture_id": capture_id,
                    "immutable_capture_at": capture_at,
                    "expires_at": expires,
                    "records": rows,
                }
                encrypted = self.custody.encrypt(
                    json.dumps(envelope, separators=(",", ":"), ensure_ascii=False)
                ).encode("ascii")
                if len(encrypted) > 16 * 1024 * 1024:
                    raise IdentityError("identity.backup_capacity_exceeded", 503)
                record: dict[str, object] = {
                    "capture_id": capture_id,
                    "custody_id": self.custody_id,
                    "immutable_capture_at": capture_at,
                    "expires_at": expires,
                    "account_ids": accounts,
                    "profile_account_ids": profile_accounts,
                    "filename": capture_id + ".enc",
                    "ciphertext_digest": hashlib.sha256(encrypted).hexdigest(),
                    "state": "pending",
                    "owner": "main",
                }
                tx.put("backup_capture", capture_id, record)
            fd = os.open(
                text(record, "filename"),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory,
            )
            try:
                self._write(fd, encrypted)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(directory)
            return self._reconcile_locked(directory, capture_id, record)

    def _reconcile_locked(
        self, directory: int, capture_id: str, record: dict[str, object]
    ) -> dict[str, object]:
        if record["state"] == "expired_unlinked":
            return dict(record)
        raw = self._ciphertext(directory, record)
        envelope = cast(dict[str, object], json.loads(self.custody.decrypt(raw.decode("ascii"))))
        if (
            envelope.get("capture_id") != capture_id
            or envelope.get("immutable_capture_at") != record["immutable_capture_at"]
            or envelope.get("expires_at") != record["expires_at"]
            or instant(record["expires_at"])
            != instant(record["immutable_capture_at"]) + timedelta(days=7)
        ):
            raise IdentityError("identity.backup_manifest_denied", 503)
        os.fsync(directory)
        with self.store.transaction() as tx:
            latest = tx.get("backup_capture", capture_id)
            if latest is None or latest.get("ciphertext_digest") != record["ciphertext_digest"]:
                raise IdentityError("identity.backup_inventory_changed", 503)
            latest["state"] = "durable"
            tx.put("backup_capture", capture_id, latest)
        return latest

    def reconcile_capture(self, capture_id: str) -> dict[str, object]:
        with self._locked_directory() as directory:
            with self.store.transaction() as tx:
                record = tx.get("backup_capture", capture_id)
            if record is None:
                raise IdentityError("identity.backup_missing", 404)
            return self._reconcile_locked(directory, capture_id, record)

    def expire(self) -> int:
        count = 0
        with self._locked_directory() as directory:
            with self.store.transaction() as tx:
                rows = list(tx.items("backup_capture"))
            for capture_id, record in rows:
                if record.get("custody_id") != self.custody_id:
                    continue
                if (
                    instant(record["expires_at"]) > self.clock()
                    or record.get("state") == "expired_unlinked"
                ):
                    continue
                # Expiry never moves. A pending writer cannot run behind this
                # unlink because every capture/expiry uses the same OS lock.
                try:
                    os.unlink(text(record, "filename"), dir_fd=directory)
                except FileNotFoundError:
                    pass
                os.fsync(directory)
                with self.store.transaction() as tx:
                    latest = tx.get("backup_capture", capture_id)
                    if latest is None:
                        raise IdentityError("identity.backup_inventory_missing", 503)
                    latest.update({"state": "expired_unlinked", "unlinked_at": stamp(self.clock())})
                    tx.put("backup_capture", capture_id, latest)
                count += 1
        self.minimize_terminal_inventory()
        return count

    def minimize_terminal_inventory(self) -> int:
        """Drop terminal account links after the accepted90day audit window.

        The immutable capture/filename/digest remains a restrictive replay marker.
        Unknown files, outstanding copies, holds or reconciliation dependencies
        prevent minimization; missing historical unlink anchors are not invented.
        This is managed inventory minimization, not physical-device erasure.
        """
        removed = 0
        with self._locked_directory() as directory, self.store.transaction() as tx:
            now = self.clock()
            rows = list(tx.items("backup_capture"))
            actual = set(os.listdir(directory)) - {".identity-backup.lock"}
            local = [row for _key, row in rows if row.get("custody_id") == self.custody_id]
            filenames = {text(row, "filename") for row in local}
            if not actual <= filenames or any(
                row.get("state") == "expired_unlinked" and text(row, "filename") in actual
                for row in local
            ):
                return 0
            holds = list(tx.items("retention_hold"))
            dependencies = list(tx.items("retention_record"))
            operations = list(tx.items("retention_operation"))
            markers = list(tx.items("account_marker"))
            for capture_id, row in rows:
                if (
                    row.get("custody_id") != self.custody_id
                    or row.get("state") != "expired_unlinked"
                    or row.get("inventory_account_links_removed_at") is not None
                    or row.get("unlinked_at") is None
                ):
                    continue
                if (
                    instant(row["expires_at"])
                    != instant(row["immutable_capture_at"]) + timedelta(days=7)
                    or instant(row["unlinked_at"]) < instant(row["expires_at"])
                    or now < instant(row["unlinked_at"]) + timedelta(days=90)
                ):
                    continue
                accounts = set(cast(list[str], row["account_ids"])) | set(
                    cast(list[str], row["profile_account_ids"])
                )
                if (
                    any(
                        hold.get("account_id") in accounts and hold.get("released") is not True
                        for _key, hold in holds
                    )
                    or any(
                        record.get("account_id") in accounts and record.get("dependencies")
                        for _key, record in dependencies
                    )
                    or any(
                        marker.get("account_id") in accounts and marker.get("profile_dependencies")
                        for _key, marker in markers
                    )
                    or any(
                        operation.get("account_id") in accounts
                        and (
                            operation.get("provider_state") != "confirmed"
                            or operation.get("subject_ciphertext")
                            or (
                                operation.get("action") == "profile_purge"
                                and operation.get("backup_state") != "known_copies_accounted"
                            )
                        )
                        for _key, operation in operations
                    )
                    or any(
                        other_id != capture_id
                        and (
                            other.get("state") != "expired_unlinked"
                            or other.get("unlinked_at") is None
                        )
                        and accounts
                        & (
                            set(cast(list[str], other["account_ids"]))
                            | set(cast(list[str], other["profile_account_ids"]))
                        )
                        for other_id, other in rows
                    )
                ):
                    continue
                row.update(
                    {
                        "account_ids": [],
                        "profile_account_ids": [],
                        "inventory_account_links_removed_at": stamp(now),
                        "reason": "expired_capture_replay_restriction",
                        "review_date": stamp(now + timedelta(days=30)),
                    }
                )
                tx.put("backup_capture", capture_id, row)
                removed += 1
        return removed

    def clearance(self, account_id: str) -> BackupClearance:
        with self._locked_directory() as directory:
            with self.store.transaction() as tx:
                rows = list(tx.items("backup_capture"))
            filenames = {
                text(row, "filename")
                for _id, row in rows
                if row.get("custody_id") == self.custody_id
            }
            actual = set(os.listdir(directory)) - {".identity-backup.lock"}
            # A terminal filename returning is an unexpected copy for every
            # account, including after terminal inventory links are minimized.
            known = actual <= filenames and not any(
                row.get("custody_id") == self.custody_id
                and row.get("state") == "expired_unlinked"
                and text(row, "filename") in actual
                for _id, row in rows
            )
            copies = 0
            immutable = True
            for _id, row in rows:
                if account_id not in cast(list[str], row["profile_account_ids"]):
                    continue
                immutable &= instant(row["expires_at"]) == instant(
                    row["immutable_capture_at"]
                ) + timedelta(days=7)
                if row["state"] == "expired_unlinked":
                    if text(row, "filename") in actual:
                        known = False
                    continue
                copies += 1
                if row.get("custody_id") != self.custody_id:
                    known = False
                    continue
                if row["state"] != "durable":
                    known = False
                try:
                    self._ciphertext(directory, row)
                except (OSError, IdentityError):
                    known = False
            return BackupClearance(account_id, known, copies, self.clock(), immutable)

    def restore_to_quarantine(
        self, capture_id: str, retention: RetentionService
    ) -> list[tuple[str, str, dict[str, object]]]:
        with self._locked_directory() as directory:
            with self.store.transaction() as tx:
                record = tx.get("backup_capture", capture_id)
            if (
                record is None
                or record.get("state") != "durable"
                or self.clock() >= instant(record["expires_at"])
            ):
                raise IdentityError("identity.backup_not_restorable")
            raw = self._ciphertext(directory, record)
            envelope = cast(
                dict[str, object], json.loads(self.custody.decrypt(raw.decode("ascii")))
            )
            if (
                envelope.get("immutable_capture_at") != record["immutable_capture_at"]
                or envelope.get("expires_at") != record["expires_at"]
            ):
                raise IdentityError("identity.backup_manifest_denied", 503)
            values = envelope.get("records")
            if not isinstance(values, list):
                raise IdentityError("identity.backup_records_denied", 503)
            rows: list[tuple[str, str, dict[str, object]]] = []
            for value in cast(list[object], values):
                if not isinstance(value, list):
                    raise IdentityError("identity.backup_records_denied", 503)
                parts = cast(list[object], value)
                if (
                    len(parts) != 3
                    or not isinstance(parts[0], str)
                    or not isinstance(parts[1], str)
                    or not isinstance(parts[2], dict)
                ):
                    raise IdentityError("identity.backup_records_denied", 503)
                rows.append((parts[0], parts[1], cast(dict[str, object], parts[2])))
            return retention.quarantine_restore(rows, instant(record["immutable_capture_at"]))
