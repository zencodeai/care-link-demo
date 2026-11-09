"""Offline same-custodian Option B maintenance for the opaque help spool.

This module has no browser endpoint or request-time identity dependency. It
removes only terminal cancelled linkage after90days, retaining minimal negative
replay markers. Active support is never inferred closed by age or silence.
"""

import os
import re
import sqlite3
import stat
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from .audit import verify_history
from .lifecycle_schema import key_digest
from .managed_copies import cleanup_managed_copies
from .model import Clock, HelpError, Wire, timestamp


def _instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("missing timezone")
        return parsed.astimezone(UTC)
    except ValueError as error:
        raise HelpError("help.lifecycle_anchor_invalid", 503) from error


class HelpLifecycle:
    def __init__(
        self,
        path: Path,
        connect: Callable[[], sqlite3.Connection],
        restrict: Callable[[], None],
        clock: Clock,
        *,
        owner_uid: int,
        max_retired_keys: int = 10000,
    ) -> None:
        if owner_uid < 0 or not 1 <= max_retired_keys <= 100000:
            raise ValueError("exact custodian UID and bounded retirement capacity required")
        self.path, self.connect, self.restrict, self.clock, self.owner_uid = (
            path,
            connect,
            restrict,
            clock,
            owner_uid,
        )
        self.max_retired_keys = max_retired_keys

    def _custody(self) -> None:
        if (
            os.geteuid() != self.owner_uid
            or self.path.parent.is_symlink()
            or self.path.is_symlink()
        ):
            raise HelpError("help.lifecycle_custody_denied", 503)
        for path, mode in ((self.path.parent, 0o700), (self.path, 0o600)):
            data = path.stat(follow_symlinks=False)
            if data.st_uid != self.owner_uid or stat.S_IMODE(data.st_mode) != mode:
                raise HelpError("help.lifecycle_custody_denied", 503)

    @staticmethod
    def _held(connection: sqlite3.Connection, help_id: str) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM help_retention_hold WHERE help_id=? AND released_at IS NULL LIMIT 1",
                (help_id,),
            ).fetchone()
            is not None
        )

    def hold(self, help_id: str, reason: str, review_at: datetime) -> str:
        self._custody()
        now = self.clock()
        if re.fullmatch(
            r"[a-z][a-z0-9_.-]{1,127}", reason
        ) is None or not now < review_at <= now + timedelta(days=30):
            raise HelpError("help.lifecycle_hold_invalid")
        hold_id = str(uuid4())
        with closing(self.connect()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                exists = connection.execute(
                    "SELECT 1 FROM request WHERE id=? UNION ALL SELECT 1 FROM "
                    "create_intent WHERE help_id=? LIMIT 1",
                    (help_id, help_id),
                ).fetchone()
                if exists is None:
                    raise HelpError("help.not_found", 404)
                connection.execute(
                    "INSERT INTO help_retention_hold VALUES (?,?, 'main',?,?,NULL)",
                    (hold_id, help_id, reason, timestamp(review_at)),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                self.restrict()
        return hold_id

    def release_hold(self, hold_id: str) -> None:
        self._custody()
        with closing(self.connect()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                hold = connection.execute(
                    "SELECT help_id FROM help_retention_hold WHERE id=? AND released_at IS NULL",
                    (hold_id,),
                ).fetchone()
                if hold is None:
                    raise HelpError("help.lifecycle_hold_missing", 404)
                # Release changes only this scoped exception. Active support and
                # terminal/anchor/replay guards still control all disposal.
                connection.execute(
                    "UPDATE help_retention_hold SET released_at=? WHERE id=?",
                    (timestamp(self.clock()), hold_id),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                self.restrict()

    def review_active(self, help_id: str) -> None:
        self._custody()
        now = self.clock()
        with closing(self.connect()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT r.status,l.help_id FROM request r LEFT JOIN "
                    "request_lifecycle l ON l.help_id=r.id WHERE r.id=?",
                    (help_id,),
                ).fetchone()
                if row is not None and row["status"] == "cancelled":
                    raise HelpError("help.lifecycle_active_missing", 404)
                if row is None:
                    intent = connection.execute(
                        "SELECT l.created_at FROM create_intent i LEFT JOIN intent_lifecycle l "
                        "ON l.operation_id=i.operation_id WHERE i.help_id=?",
                        (help_id,),
                    ).fetchone()
                    if intent is None:
                        raise HelpError("help.lifecycle_active_missing", 404)
                    if intent["created_at"] is None:
                        raise HelpError("help.lifecycle_migration_pending", 409)
                elif row["help_id"] is None:
                    raise HelpError("help.lifecycle_migration_pending", 409)
                connection.execute(
                    "INSERT INTO help_dependency_review VALUES (?,?,?) "
                    "ON CONFLICT(help_id) DO UPDATE SET reviewed_at=excluded.reviewed_at,"
                    "review_due_at=excluded.review_due_at",
                    (help_id, timestamp(now), timestamp(now + timedelta(days=30))),
                )
                connection.execute(
                    "UPDATE request_lifecycle SET active_reviewed_at=?,"
                    "active_review_due_at=? WHERE help_id=?",
                    (timestamp(now), timestamp(now + timedelta(days=30)), help_id),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                self.restrict()

    def status(self) -> Wire:
        self._custody()
        now = self.clock()
        with closing(self.connect()) as connection:
            verify_history(connection)
            rows = connection.execute(
                "SELECT r.id,r.status,l.created_at,l.cancelled_at,"
                "COALESCE(d.review_due_at,l.active_review_due_at) AS active_review_due_at "
                "FROM request r LEFT JOIN request_lifecycle l ON l.help_id=r.id "
                "LEFT JOIN help_dependency_review d ON d.help_id=r.id"
            ).fetchall()
            migration = sum(
                row["created_at"] is None
                or (row["status"] == "cancelled" and row["cancelled_at"] is None)
                for row in rows
            )
            overdue = sum(
                row["status"] != "cancelled"
                and row["active_review_due_at"] is not None
                and _instant(row["active_review_due_at"]) <= now
                for row in rows
            )
            legacy_operations = connection.execute(
                "SELECT count(*) FROM operation o LEFT JOIN operation_lifecycle l "
                "ON l.operation_id=o.id WHERE l.event_at IS NULL"
            ).fetchone()[0]
            legacy_intents = connection.execute(
                "SELECT count(*) FROM create_intent i LEFT JOIN intent_lifecycle "
                "l ON l.operation_id=i.operation_id WHERE l.created_at IS NULL"
            ).fetchone()[0]
            legacy_nonces = connection.execute(
                "SELECT count(*) FROM decision_nonce n LEFT JOIN nonce_lifecycle "
                "l ON l.nonce=n.nonce WHERE l.accepted_at IS NULL"
            ).fetchone()[0]
            overdue_holds = connection.execute(
                "SELECT review_date FROM help_retention_hold WHERE released_at IS NULL"
            ).fetchall()
            retired_rows = connection.execute("SELECT review_date FROM retired_help_key").fetchall()
            unresolved_intents = connection.execute(
                "SELECT i.help_id,l.created_at,d.review_due_at FROM create_intent i LEFT "
                "JOIN request r ON r.id=i.help_id "
                "LEFT JOIN intent_lifecycle l ON l.operation_id=i.operation_id "
                "LEFT JOIN help_dependency_review d ON d.help_id=i.help_id WHERE r.id IS NULL"
            ).fetchall()
            checkpoint = connection.execute(
                "SELECT last_deleted_sequence FROM help_audit_checkpoint WHERE singleton=1"
            ).fetchone()
            copies = connection.execute(
                "SELECT state FROM help_managed_copy_cleanup WHERE singleton=1"
            ).fetchone()[0]
            return {
                "owner": "main",
                "active_dependency": "unresolved_help_ownership",
                "active_requests": sum(row["status"] != "cancelled" for row in rows),
                "active_review_overdue": overdue,
                "unmaterialized_create_dependencies": len(unresolved_intents),
                "unmaterialized_review_overdue": sum(
                    row["created_at"] is not None
                    and (
                        _instant(row["review_due_at"])
                        if row["review_due_at"] is not None
                        else _instant(row["created_at"]) + timedelta(days=30)
                    )
                    <= now
                    for row in unresolved_intents
                ),
                "retired_marker_review_overdue": sum(
                    _instant(row["review_date"]) <= now for row in retired_rows
                ),
                "retired_marker_capacity": self.max_retired_keys,
                "migration_pending": migration + legacy_operations + legacy_intents + legacy_nonces,
                "overdue_holds": sum(_instant(row["review_date"]) <= now for row in overdue_holds),
                "audit_scope": "checkpoint_to_current_only"
                if checkpoint[0]
                else "stored_chain_only",
                "backup_cleanup": "pending_separate_spool_copy_inventory",
                "managed_copy_cleanup": copies,
                "managed_copy_reader_pending": copies == "pending_busy_or_reader",
                "physical_erasure_claim": False,
            }

    def _retire(self, connection: sqlite3.Connection, kind: str, value: str, now: datetime) -> None:
        digest = key_digest(kind, value)
        if connection.execute(
            "SELECT 1 FROM retired_help_key WHERE key_digest=?", (digest,)
        ).fetchone():
            return
        count = connection.execute("SELECT count(*) FROM retired_help_key").fetchone()[0]
        if count >= self.max_retired_keys:
            raise HelpError("help.lifecycle_retirement_capacity", 503)
        connection.execute(
            "INSERT INTO retired_help_key VALUES (?, ?, ?, 'main', 'retired_replay_key', ?)",
            (digest, kind, timestamp(now), timestamp(now + timedelta(days=30))),
        )

    def run(self) -> Wire:
        self._custody()
        now = self.clock()
        cutoff = now - timedelta(days=90)
        deleted, nonces, pruned = 0, 0, 0
        with closing(self.connect()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                verify_history(connection)
                rows = connection.execute(
                    "SELECT r.id,l.cancelled_at FROM request r JOIN request_lifecycle "
                    "l ON l.help_id=r.id WHERE r.status='cancelled'"
                ).fetchall()
                for row in rows:
                    help_id = row["id"]
                    if (
                        row["cancelled_at"] is None
                        or _instant(row["cancelled_at"]) > cutoff
                        or self._held(connection, help_id)
                    ):
                        continue
                    unknown_operations = connection.execute(
                        "SELECT 1 FROM operation o LEFT JOIN operation_lifecycle l "
                        "ON l.operation_id=o.id "
                        "WHERE o.help_id=? AND l.event_at IS NULL LIMIT 1",
                        (help_id,),
                    ).fetchone()
                    unknown_intents = connection.execute(
                        "SELECT 1 FROM create_intent i LEFT JOIN intent_lifecycle l "
                        "ON l.operation_id=i.operation_id "
                        "WHERE i.help_id=? AND l.created_at IS NULL LIMIT 1",
                        (help_id,),
                    ).fetchone()
                    if unknown_operations is not None or unknown_intents is not None:
                        continue  # explicit migration_pending; never invent anchors
                    event_times = connection.execute(
                        "SELECT l.event_at FROM operation o JOIN operation_lifecycle l "
                        "ON l.operation_id=o.id WHERE o.help_id=? "
                        "UNION ALL SELECT time AS event_at FROM local_event WHERE reference=?",
                        (help_id, help_id),
                    ).fetchall()
                    # A later status/retry attribution has its own90day audit
                    # window; cancellation does not shorten that event's life.
                    if any(_instant(event["event_at"]) > cutoff for event in event_times):
                        continue
                    operations = connection.execute(
                        "SELECT id FROM operation WHERE help_id=?", (help_id,)
                    ).fetchall()
                    for operation in operations:
                        self._retire(connection, "operation", operation["id"], now)
                    intents = connection.execute(
                        "SELECT operation_id FROM create_intent WHERE help_id=?", (help_id,)
                    ).fetchall()
                    for intent in intents:
                        self._retire(connection, "operation", intent["operation_id"], now)
                    self._retire(connection, "help", help_id, now)
                    connection.execute("DELETE FROM create_intent WHERE help_id=?", (help_id,))
                    connection.execute("DELETE FROM intent_lifecycle WHERE help_id=?", (help_id,))
                    connection.execute("DELETE FROM operation WHERE help_id=?", (help_id,))
                    connection.execute(
                        "DELETE FROM help_dependency_review WHERE help_id=?", (help_id,)
                    )
                    connection.execute(
                        "DELETE FROM help_retention_hold WHERE help_id=? "
                        "AND released_at IS NOT NULL",
                        (help_id,),
                    )
                    connection.execute("DELETE FROM request WHERE id=?", (help_id,))
                    deleted += 1
                for row in connection.execute(
                    "SELECT nonce,authority_expires_at FROM nonce_lifecycle"
                ).fetchall():
                    if _instant(row["authority_expires_at"]) <= cutoff:
                        connection.execute(
                            "DELETE FROM decision_nonce WHERE nonce=?", (row["nonce"],)
                        )
                        nonces += 1
                # A prefix may be pruned only while it does not cross an active,
                # held or legacy-unanchored dependency. No holes in the chain.
                events = connection.execute(
                    "SELECT sequence,hash,reference,time FROM local_event ORDER BY sequence"
                ).fetchall()
                for event in events:
                    reference = event["reference"]
                    current = connection.execute(
                        "SELECT status FROM request WHERE id=?", (reference,)
                    ).fetchone()
                    intent = connection.execute(
                        "SELECT 1 FROM create_intent WHERE help_id=?", (reference,)
                    ).fetchone()
                    if (
                        _instant(event["time"]) > cutoff
                        or self._held(connection, reference)
                        or current is not None
                        or intent is not None
                    ):
                        break
                    connection.execute(
                        "UPDATE help_audit_checkpoint SET "
                        "last_deleted_sequence=?,last_deleted_hash=?,pruned_at=? WHERE singleton=1",
                        (event["sequence"], event["hash"], timestamp(now)),
                    )
                    connection.execute(
                        "DELETE FROM local_event WHERE sequence=?", (event["sequence"],)
                    )
                    pruned += 1
                verify_history(connection)
                # Persist before unlinkage ACK. Interrupted or blocked physical
                # managed-file cleanup cannot accidentally appear completed.
                connection.execute(
                    "UPDATE help_managed_copy_cleanup SET state='pending' WHERE singleton=1"
                )
                connection.commit()
            except sqlite3.Error as error:
                connection.rollback()
                raise HelpError("help.lifecycle_unavailable", 503) from error
            except BaseException:
                connection.rollback()
                raise
            finally:
                self.restrict()
        self._custody()
        copies = cleanup_managed_copies(self.connect, self.restrict, self.clock())
        return {
            "owner": "main",
            "terminal_linkages_removed": deleted,
            "expired_nonces_removed": nonces,
            "audit_prefix_pruned": pruned,
            "backup_cleanup": "pending_separate_spool_copy_inventory",
            "managed_copy_cleanup": copies,
            "managed_copy_reader_pending": copies == "pending_busy_or_reader",
            "physical_erasure_claim": False,
        }
