"""Single-host transactional opaque spool; local audit is not business audit."""

import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import cast
from uuid import UUID

from care_link_contracts import validate_contract

from .audit import append_event
from .intents import INTENT_SCHEMA, CreateIntents
from .lifecycle import HelpLifecycle
from .lifecycle_schema import (
    LIFECYCLE_SCHEMA,
    anchor_nonce,
    anchor_operation,
    anchor_request,
    deny_retired,
)
from .model import Action, BrowserContext, Clock, Decision, HelpError, Wire, now_utc, timestamp

PARTICIPANTS = frozenset({"pid", "carer", "professional_participant"})
WORKFORCE = frozenset({"worker", "supervisor"})
SCHEMA = """
CREATE TABLE IF NOT EXISTS request (
 id TEXT PRIMARY KEY, owner_account TEXT NOT NULL, created_at TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('recorded','accepted_unconnected','cancelled')),
 accepted_by TEXT, revision INTEGER NOT NULL CHECK(revision>=1),
 authority_evidence_digest TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS operation (
 id TEXT PRIMARY KEY, principal TEXT NOT NULL, action TEXT NOT NULL,
 help_id TEXT NOT NULL REFERENCES request(id), digest TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decision_nonce (nonce TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS local_event (
 sequence INTEGER PRIMARY KEY, previous_hash TEXT NOT NULL, hash TEXT NOT NULL,
 action TEXT NOT NULL, reference TEXT NOT NULL, time TEXT NOT NULL,
 authority_evidence_digest TEXT NOT NULL
);
"""


class Spool:
    def __init__(self, path: Path, *, clock: Clock = now_utc) -> None:
        """Create only the explicitly selected spool, with private file modes.

        Caller owns a dedicated existing private directory. Symlinks and a shared
        world/group-accessible directory are rejected. Filesystem fsync behavior
        and separate OS identity still require host qualification.
        """
        if path.is_symlink() or not path.parent.is_dir() or path.parent.stat().st_mode & 0o077:
            raise ValueError("spool requires a dedicated 0700 directory")
        if path.parent.stat().st_uid != os.geteuid():
            raise ValueError("spool directory must belong to the effective custodian UID")
        self.path = path
        self.clock = clock
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        if path.stat().st_mode & 0o077 or path.stat().st_uid != os.geteuid():
            raise ValueError("spool file must be private")
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(SCHEMA + INTENT_SCHEMA + LIFECYCLE_SCHEMA)
        self._restrict_files()
        self.intents = CreateIntents(self._connect, self._restrict_files, self.clock)
        self.lifecycle = HelpLifecycle(
            self.path, self._connect, self._restrict_files, self.clock, owner_uid=os.geteuid()
        )

    def _restrict_files(self) -> None:
        for path in (self.path, Path(str(self.path) + "-wal"), Path(str(self.path) + "-shm")):
            if path.exists():
                path.chmod(0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=1, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        # Erase deleted cell content in the managed SQLite pages. Offline
        # lifecycle maintenance separately rebuilds legacy free pages and
        # truncates WAL frames; this is not a storage-device erasure claim.
        if connection.execute("PRAGMA secure_delete=ON").fetchone()[0] != 1:
            connection.close()
            raise HelpError("help.secure_delete_unavailable", 503)
        return connection

    @staticmethod
    def _view(row: sqlite3.Row) -> Wire:
        view: Wire = {
            "id": row["id"],
            "revision": str(row["revision"]),
            "state": row["status"],
            "created_at": row["created_at"],
            "connection_confirmed": False,
        }
        validate_contract("HelpView", view)
        return view

    def apply(
        self,
        *,
        action: Action,
        help_id: str,
        operation_id: str,
        body_digest: str,
        context: BrowserContext,
        decision: Decision,
        expected_revision: str | None,
    ) -> Wire:
        UUID(help_id)
        UUID(operation_id)
        if context.account_id != decision.principal_id:
            raise HelpError("help.authority_denied")
        with closing(self._connect()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                if not self.clock() < decision.expires_at:
                    raise HelpError("help.authority_expired")
                deny_retired(connection, "operation", operation_id)
                deny_retired(connection, "help", help_id)
                connection.execute("INSERT INTO decision_nonce VALUES (?)", (decision.nonce,))
                anchor_nonce(connection, decision, self.clock())
                row = connection.execute("SELECT * FROM request WHERE id=?", (help_id,)).fetchone()
                prior = connection.execute(
                    "SELECT * FROM operation WHERE id=?", (operation_id,)
                ).fetchone()
                if prior is not None and (
                    prior["principal"] != context.account_id
                    or prior["action"] != action
                    or prior["help_id"] != help_id
                    or prior["digest"] != body_digest
                ):
                    raise HelpError("help.idempotency_conflict", 409)
                if action == "create":
                    if context.role not in PARTICIPANTS:
                        raise HelpError("help.role_denied")
                    if row is not None and row["owner_account"] != context.account_id:
                        raise HelpError("help.not_found", 404)
                elif row is None:
                    raise HelpError("help.not_found", 404)
                else:
                    owner = row["owner_account"] == context.account_id
                    if action == "accept":
                        if context.role not in WORKFORCE or owner:
                            raise HelpError("help.role_denied")
                    elif not owner and not (action == "status" and context.role in WORKFORCE):
                        raise HelpError("help.not_found", 404)
                    if action == "cancel" and context.role not in PARTICIPANTS:
                        raise HelpError("help.role_denied")
                if prior is None and action == "create":
                    connection.execute(
                        "INSERT INTO request VALUES (?,?,?,'recorded',NULL,1,?)",
                        (
                            help_id,
                            context.account_id,
                            self.clock().isoformat().replace("+00:00", "Z"),
                            decision.evidence_digest,
                        ),
                    )
                    anchor_request(connection, help_id, self.clock())
                elif prior is None and action in {"accept", "cancel"}:
                    if row is None:
                        raise HelpError("help.not_found", 404)
                    if str(row["revision"]) != expected_revision:
                        raise HelpError("help.revision_conflict", 409)
                    if row["status"] == "cancelled" or (
                        action == "accept" and row["status"] != "recorded"
                    ):
                        raise HelpError("help.state_conflict", 409)
                    if row["revision"] >= 9223372036854775807:
                        raise HelpError("help.revision_conflict", 409)
                    connection.execute(
                        "UPDATE request SET status=?,accepted_by=?,revision=revision+1,"
                        "authority_evidence_digest=? WHERE id=? AND revision=?",
                        (
                            "accepted_unconnected" if action == "accept" else "cancelled",
                            context.account_id if action == "accept" else row["accepted_by"],
                            decision.evidence_digest,
                            help_id,
                            int(cast(str, expected_revision)),
                        ),
                    )
                    if action == "cancel":
                        connection.execute(
                            "UPDATE request_lifecycle SET cancelled_at=? WHERE help_id=?",
                            (timestamp(self.clock()), help_id),
                        )
                if prior is None:
                    connection.execute(
                        "INSERT INTO operation VALUES (?,?,?,?,?)",
                        (operation_id, context.account_id, action, help_id, body_digest),
                    )
                    anchor_operation(connection, operation_id, self.clock())
                append_event(
                    connection,
                    action,
                    help_id,
                    self.clock().isoformat().replace("+00:00", "Z"),
                    decision,
                )
                current = connection.execute(
                    "SELECT * FROM request WHERE id=?", (help_id,)
                ).fetchone()
                if current is None:
                    raise HelpError("help.spool_unavailable", 503)
                view = self._view(current)
                if not self.clock() < decision.expires_at:
                    raise HelpError("help.authority_expired")
                connection.commit()
                return view
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise HelpError("help.replayed_decision", 409) from error
            except sqlite3.Error as error:
                connection.rollback()
                raise HelpError("help.spool_unavailable", 503) from error
            except HelpError:
                connection.rollback()
                raise
            finally:
                self._restrict_files()

    def reconciliation_snapshot(self, help_id: str) -> Wire:
        """Maintenance-only minimal snapshot; caller supplies fresh workload authority.

        This is absent from browser routes. It never exports owner/worker IDs or
        private history, and a retired request is not reconstructed from audit.
        """
        from .audit import verify_history

        if str(UUID(help_id)) != help_id:
            raise HelpError("help.invalid_request", 400)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN")
            verify_history(connection)
            deny_retired(connection, "help", help_id)
            row = connection.execute("SELECT * FROM request WHERE id=?", (help_id,)).fetchone()
            event = connection.execute(
                "SELECT hash FROM local_event WHERE reference=? ORDER BY sequence DESC LIMIT 1",
                (help_id,),
            ).fetchone()
            if row is None or event is None:
                raise HelpError("help.reconciliation_unavailable", 503)
            return {
                "help_id": help_id,
                "revision": str(row["revision"]),
                "status": "requested" if row["status"] == "recorded" else row["status"],
                "local_created_at": row["created_at"],
                "local_event_digest": event["hash"],
            }
