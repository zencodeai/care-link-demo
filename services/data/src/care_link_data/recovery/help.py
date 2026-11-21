"""Fresh-authority, minimal host-spool import without recreating connection."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

import psycopg
from care_link_contracts import validate_contract
from care_link_domain import JournalPort, ManualError
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..values import digest, stamp

Record = dict[str, object]


@dataclass(frozen=True)
class HelpSnapshot:
    help_id: str
    revision: int
    status: str
    local_created_at: datetime
    local_event_digest: str


class HelpImportAuthority(Protocol):
    def current(self, request: Record) -> HelpSnapshot:
        """Authenticate current workload, authorize and obtain exact spool snapshot."""
        ...


class PostgresHelpReconciler:
    def __init__(
        self,
        dsn: str,
        authority: HelpImportAuthority,
        recovery_actor_id: str,
        *,
        journal: JournalPort,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.dsn, self.authority, self.clock = dsn, authority, clock
        self.actor_id = str(UUID(recovery_actor_id))
        self.journal = journal

    def reconcile(self, request: Record, command_id: str) -> Record:
        validate_contract("HelpReconcile", request)
        operation = str(UUID(command_id))
        snapshot = self.authority.current(request)
        if (
            snapshot.help_id != request["help_id"]
            or str(snapshot.revision) != request["spool_revision"]
            or snapshot.local_event_digest != request["local_event_digest"]
            or snapshot.status not in {"requested", "accepted_unconnected", "cancelled", "closed"}
            or snapshot.local_created_at.tzinfo is None
            or snapshot.local_created_at > self.clock()
        ):
            raise ManualError("recovery.help_snapshot_mismatch", 409)
        identity = str(UUID(snapshot.help_id))
        with psycopg.Connection[Record].connect(self.dsn, row_factory=dict_row) as connection:
            # Canonical lock order: control guard, business/import row, audit head.
            control = connection.execute("SELECT * FROM control.guard FOR UPDATE").fetchone()
            if control is None or control["mode"] in {"restricted", "quarantine"}:
                raise ManualError("recovery.help_central_unavailable", 503)
            self._current_gate(control)
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (identity,))
            previous = connection.execute(
                "SELECT * FROM recovery.help_operation WHERE command_id=%s", (operation,)
            ).fetchone()
            if previous is not None:
                if (
                    previous["request_digest"] != digest(request)
                    or str(previous["help_id"]) != identity
                ):
                    raise ManualError("recovery.help_idempotency_conflict", 409)
                self._current_gate(control)
                return self._result(operation, identity, previous)
            old = connection.execute(
                "SELECT * FROM recovery.help_import WHERE help_id=%s FOR UPDATE", (identity,)
            ).fetchone()
            expected = 0 if old is None else int(str(old["revision"]))
            if (
                old is not None
                and old["spool_revision"] == snapshot.revision
                and old["local_event_digest"] == snapshot.local_event_digest
            ):
                row = old
            else:
                if int(str(request["expected_revision"])) != expected or (
                    old is not None and int(str(old["spool_revision"])) >= snapshot.revision
                ):
                    raise ManualError("recovery.help_stale_revision", 409)
                row = connection.execute(
                    "INSERT INTO recovery.help_import VALUES(%s,%s,%s,%s,%s,%s,%s,false)"
                    " ON CONFLICT(help_id) DO UPDATE SET spool_revision=EXCLUDED.spool_revision,"
                    "local_event_digest=EXCLUDED.local_event_digest,revision=EXCLUDED.revision,"
                    "status=EXCLUDED.status,central_reconciled_at=EXCLUDED.central_reconciled_at"
                    " RETURNING *",
                    (
                        identity,
                        snapshot.revision,
                        snapshot.local_event_digest,
                        expected + 1,
                        snapshot.status,
                        snapshot.local_created_at,
                        self.clock(),
                    ),
                ).fetchone()
            if row is None:
                raise ManualError("recovery.help_import_failed", 503)
            self._current_gate(control)
            audit_ref = self._audit(connection, operation, request, self._view(row))
            connection.execute(
                "INSERT INTO recovery.help_operation VALUES(%s,%s,%s,%s,%s)",
                (operation, identity, digest(request), row["revision"], audit_ref),
            )
            self._current_gate(control)
            return self._result(
                operation, identity, {"revision": row["revision"], "audit_ref": audit_ref}
            )

    def _current_gate(self, control: Record) -> None:
        head = self.journal.head()
        if (
            not 0 <= (self.clock() - head.observed_at).total_seconds() <= 1
            or str(control["journal_id"]) != head.journal_id
            or control["journal_generation"] != head.generation
            or control["restriction_barrier"] != head.restriction_barrier
            or control["serving_generation"] != head.serving_generation
            or head.serving_generation == 0
        ):
            raise ManualError("recovery.help_current_gate_required", 503)

    def _audit(
        self,
        connection: psycopg.Connection[Record],
        operation: str,
        request: Record,
        output: Record,
    ) -> str:
        head = connection.execute("SELECT * FROM audit.head WHERE stream_id='demo'").fetchone()
        if head is None:
            raise ManualError("recovery.help_audit_unavailable", 503)
        event_id, now = str(uuid4()), self.clock()
        event: Record = {
            "event_id": event_id,
            "operation_id": operation,
            "principal_id": self.actor_id,
            "action": "help_reconcile",
            "decision": "PERMIT",
            "input_digest": digest(request),
            "output_digest": digest(output),
            "versions": {},
            "previous_hash": head["digest"],
            "created_at": stamp(now),
            "encoding": "care.audit.v1",
            "stream_id": "demo",
            "sequence": str(head["next_sequence"]),
        }
        connection.execute("SELECT set_config('care_link.principal',%s,true)", (self.actor_id,))
        connection.execute(
            "SELECT audit.append_event(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                event_id,
                operation,
                self.actor_id,
                "help_reconcile",
                "PERMIT",
                event["input_digest"],
                event["output_digest"],
                Jsonb({}),
                now,
                head["digest"],
                digest(event),
            ),
        )
        return event_id

    @staticmethod
    def _result(operation: str, identity: str, record: Record) -> Record:
        result: Record = {
            "operation_id": operation,
            "state": "committed",
            "resource_id": identity,
            "revision": str(record["revision"]),
            "audit_ref": str(record["audit_ref"]),
        }
        validate_contract("CommandResult", result)
        return result

    @staticmethod
    def _view(row: Record) -> Record:
        created = row["central_reconciled_at"]
        if not isinstance(created, datetime):
            raise ManualError("recovery.help_import_corrupt", 503)
        return {
            "help_id": str(row["help_id"]),
            "revision": str(row["revision"]),
            "spool_revision": str(row["spool_revision"]),
            "status": row["status"],
            "connection_confirmed": False,
            "reconciled_at": stamp(created),
            "evidence_digest": digest(
                {"help_id": str(row["help_id"]), "digest": row["local_event_digest"]}
            ),
        }
