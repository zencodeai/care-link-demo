"""Explicit custody-only administration of review namespaces, never business rows.

The operator adapter supplies an owned verify-full admin connection and exact
DB/journal binding. No runtime/browser transport exposes this class.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import LiteralString, cast
from uuid import UUID

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from .store import Record
from .values import digest


def apply_review_migration(connection: psycopg.Connection[Record]) -> None:
    """Named additive migration; never invoked by application startup."""
    path = Path(__file__).resolve().parents[2] / "migrations/002_review_recovery.sql"
    migration = path.read_text()
    expected = hashlib.sha256(migration.encode()).hexdigest()
    with connection.cursor(row_factory=dict_row) as cursor:
        exists = cursor.execute(
            "SELECT to_regclass('core.review_run') AS run, "
            "to_regclass('core.review_schema_version') AS version"
        ).fetchone()
        if exists and exists["run"] is not None:
            if exists["version"] is None:
                raise ValueError("Partial/unbound review migration; inspect before applying")
            version = cursor.execute(
                "SELECT migration_digest FROM core.review_schema_version "
                "WHERE version='review-recovery-1'"
            ).fetchone()
            if version is None or version["migration_digest"] != expected:
                raise ValueError("Review migration digest mismatch")
            return
        cursor.execute(cast(LiteralString, migration))
        cursor.execute(
            "INSERT INTO core.review_schema_version VALUES('review-recovery-1',%s)", (expected,)
        )


def _uuid(value: str) -> str:
    if str(UUID(value)) != value:
        raise ValueError("Canonical review UUID required")
    return value


@dataclass(frozen=True)
class ReviewRunAdmin:
    dsn: str = field(repr=False)
    environment_id: str
    expected_database: str
    expected_journal_id: str

    def __post_init__(self) -> None:
        fields = conninfo_to_dict(self.dsn)
        if fields.get("sslmode") != "verify-full" or not fields.get("sslrootcert"):
            raise ValueError("Review administration requires verify-full TLS")
        if (
            fields.get("dbname") != self.expected_database
            or not 1 <= len(self.environment_id) <= 96
        ):
            raise ValueError("Exact owned review database/environment required")
        _uuid(self.expected_journal_id)

    def _connect(self) -> psycopg.Connection[Record]:
        connection = psycopg.Connection[Record].connect(
            self.dsn, connect_timeout=2, row_factory=dict_row
        )
        connection.execute("SET LOCAL lock_timeout='2s'")
        connection.execute("SET LOCAL statement_timeout='3s'")
        # Same first lock as actor gateway: closure cannot race a guarded write.
        head = connection.execute(
            "SELECT journal_id FROM control.guard WHERE key='demo' FOR UPDATE"
        ).fetchone()
        if head is None or str(head["journal_id"]) != self.expected_journal_id:
            connection.close()
            raise ValueError("Review journal ownership mismatch")
        return connection

    @staticmethod
    def _view(row: Record) -> Record:
        return {
            "environment_id": row["environment_id"],
            "run_id": str(row["id"]),
            "scenario": row["scenario"],
            "scenario_version": row["scenario_version"],
            "state": row["state"],
            "revision": str(row["revision"]),
        }

    def inspect(self, run_id: str) -> Record:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM core.review_run WHERE id=%s AND environment_id=%s",
                (_uuid(run_id), self.environment_id),
            ).fetchone()
            if row is None:
                raise ValueError("Owned review run not found")
            return self._view(row)

    def create(
        self, run_id: str, scenario: str, operation_id: str, scenario_version: str = "1"
    ) -> Record:
        _uuid(run_id)
        _uuid(operation_id)
        if scenario != "manual-service" or scenario_version != "1":
            raise ValueError("Unsupported review scenario/version")
        payload = digest(
            {
                "run_id": run_id,
                "environment_id": self.environment_id,
                "scenario": scenario,
                "scenario_version": scenario_version,
            }
        )
        with self._connect() as connection:
            prior = connection.execute(
                "SELECT * FROM core.review_admin_operation WHERE operation_id=%s", (operation_id,)
            ).fetchone()
            if prior and (
                str(prior["run_id"]) != run_id
                or prior["command"] != "create"
                or prior["payload_digest"] != payload
            ):
                raise ValueError("Review admin operation identity conflict")
            row = connection.execute(
                "SELECT * FROM core.review_run WHERE id=%s FOR UPDATE", (run_id,)
            ).fetchone()
            if row:
                if not prior or row["environment_id"] != self.environment_id:
                    raise ValueError("Review run already exists under a different operation")
                return self._view(row)
            occupied = connection.execute(
                "SELECT id FROM core.review_run WHERE environment_id=%s "
                "AND state IN ('active','closing')",
                (self.environment_id,),
            ).fetchone()
            if occupied:
                raise ValueError("Environment already has an active review run")
            now = datetime.now(UTC)
            row = connection.execute(
                "INSERT INTO core.review_run VALUES(%s,%s,%s,%s,'active',1,%s,NULL) RETURNING *",
                (run_id, self.environment_id, scenario, scenario_version, now),
            ).fetchone()
            connection.execute(
                "INSERT INTO core.review_admin_operation VALUES(%s,%s,'create',%s,%s)",
                (operation_id, run_id, payload, now),
            )
            if row is None:
                raise ValueError("Review run update did not return a row")
            return self._view(row)

    def close(self, run_id: str, operation_id: str) -> Record:
        _uuid(run_id)
        _uuid(operation_id)
        payload = digest({"run_id": run_id, "environment_id": self.environment_id})
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM core.review_run WHERE id=%s AND environment_id=%s FOR UPDATE",
                (run_id, self.environment_id),
            ).fetchone()
            if row is None:
                raise ValueError("Owned review run not found")
            prior = connection.execute(
                "SELECT * FROM core.review_admin_operation WHERE operation_id=%s", (operation_id,)
            ).fetchone()
            if prior and (
                str(prior["run_id"]) != run_id
                or prior["command"] != "close"
                or prior["payload_digest"] != payload
            ):
                raise ValueError("Review admin operation identity conflict")
            if row["state"] != "closed":
                row = connection.execute(
                    "UPDATE core.review_run SET state='closed',revision=revision+1,closed_at=%s "
                    "WHERE id=%s RETURNING *",
                    (datetime.now(UTC), run_id),
                ).fetchone()
            if not prior:
                connection.execute(
                    "INSERT INTO core.review_admin_operation VALUES(%s,%s,'close',%s,%s)",
                    (operation_id, run_id, payload, datetime.now(UTC)),
                )
            if row is None:
                raise ValueError("Review run update did not return a row")
            return self._view(row)
