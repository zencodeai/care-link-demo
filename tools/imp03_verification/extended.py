"""Receipt-bound observation and quarantine capture for the continuation target.

These are privileged operator helpers, never serving endpoints. Public results
contain counts/digests and bounded audit action names, not rows, DSNs or dumps.
The retained generation1 target and IMP-02 are outside this fixed lease.
"""

import hashlib
import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID, uuid4

import psycopg
from care_link_data import verify_audit_chain
from care_link_domain import JournalState
from care_link_recovery_control import CaptureMetadata, EncryptedCaptures, QuarantineRestore
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from tools.imp03_shared import docker as owned_docker

from .capture import docker

Record = dict[str, object]
DATABASE = "imp03_runtime_002"
LOGIN = "imp03_data_runtime_002"
PORT = "25435"
SCHEMAS = ("core", "workforce", "access", "lifecycle", "control", "durable", "recovery", "audit")
QUARANTINE = re.compile(r"^imp03_cont1_quarantine_[0-9a-f]{32}$")
HEX = re.compile(r"^[0-9a-f]{64}$")


class JournalReader(Protocol):
    def head(self) -> JournalState: ...


def _record(value: object) -> Record:
    if not isinstance(value, dict):
        raise ValueError("Expected operator metadata object")
    return cast(Record, value)


def _rows(value: object) -> list[Record]:
    if not isinstance(value, list):
        raise ValueError("Expected operator metadata rows")
    return [_record(item) for item in cast(list[object], value)]


def _text(value: Record, key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str):
        raise ValueError("Missing operator metadata field: " + key)
    return item


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


@dataclass(frozen=True)
class TargetLease:
    """Actual host publication and receipt, supplied from private operator state."""

    container_name: str
    container_id: str
    admin_dsn: str = field(repr=False)
    journal_id: str
    policy_digest: str

    def __post_init__(self) -> None:
        if self.container_name not in {
            "care-link-imp03-003-cont1-postgres",
            "care-link-imp03-003-cont1-postgres-ingress",
        }:
            raise ValueError("Only the fresh continuation PostgreSQL target is allowed")
        if not HEX.fullmatch(self.container_id) or not HEX.fullmatch(self.policy_digest):
            raise ValueError("Exact container and policy digests required")
        if str(UUID(self.journal_id)) != self.journal_id:
            raise ValueError("Canonical current journal identity required")
        settings = conninfo_to_dict(self.admin_dsn)
        if (
            settings.get("sslmode") != "verify-full"
            or not settings.get("host")
            or settings.get("hostaddr") != "127.0.0.1"
            or settings.get("port") != PORT
            or settings.get("user") != "postgres"
            or settings.get("dbname") not in {"postgres", DATABASE}
            or not settings.get("sslrootcert")
        ):
            raise ValueError("Exact continuation host verify-full admin endpoint required")

    def dsn(self, database: str = DATABASE) -> str:
        if database not in {DATABASE, "postgres"} and not QUARANTINE.fullmatch(database):
            raise ValueError("Only source, maintenance or named quarantine databases allowed")
        return make_conninfo(
            "",
            **{
                key: str(value)
                for key, value in {
                    **conninfo_to_dict(self.admin_dsn),
                    "dbname": database,
                }.items()
            },
        )

    def inspect(self) -> None:
        metadata = owned_docker.inspect_container(self.container_name)
        config = _record(metadata["HostConfig"])
        ports = _record(config["PortBindings"])
        if metadata.get("Id") != self.container_id or ports.get("5432/tcp") != [
            {"HostIp": "127.0.0.1", "HostPort": PORT}
        ]:
            raise ValueError("Continuation PostgreSQL identity/publication changed")


def _connection(lease: TargetLease, database: str = DATABASE) -> psycopg.Connection[Record]:
    return psycopg.Connection[Record].connect(
        lease.dsn(database), row_factory=dict_row, connect_timeout=2
    )


def _guard(connection: psycopg.Connection[Record], lease: TargetLease) -> Record:
    row = connection.execute(
        "SELECT current_database() AS database, journal_id,journal_generation,bundle_digest "
        "FROM control.guard WHERE key='demo'"
    ).fetchone()
    tls = connection.execute(
        "SELECT ssl,version FROM pg_stat_ssl WHERE pid=pg_backend_pid()"
    ).fetchone()
    if (
        row is None
        or row.get("database") != DATABASE
        or str(row.get("journal_id")) != lease.journal_id
        or row.get("bundle_digest") != lease.policy_digest
        or tls != {"ssl": True, "version": "TLSv1.3"}
    ):
        raise ValueError("Source database, receipt or TLS binding differs from lease")
    return row


def _audit(connection: psycopg.Connection[Record]) -> Record:
    rows = connection.execute("SELECT * FROM audit.event ORDER BY sequence LIMIT 100001").fetchall()
    if len(rows) > 100000:
        raise ValueError("Qualification audit inventory exceeds bounded observation")
    normalized = [
        {key: str(value) if isinstance(value, UUID) else value for key, value in row.items()}
        for row in rows
    ]
    digest = verify_audit_chain(normalized)
    head = connection.execute(
        "SELECT next_sequence,digest FROM audit.head WHERE stream_id='demo'"
    ).fetchone()
    if head != {"next_sequence": len(rows) + 1, "digest": digest}:
        raise ValueError("Audit head differs from validated full chain")
    return {
        "valid": True,
        "event_count": len(rows),
        "head_digest": digest,
        "events": [{key: row[key] for key in ("hash", "action", "decision")} for row in normalized],
    }


def snapshot_connection(connection: psycopg.Connection[Record], lease: TargetLease) -> Record:
    """Read within the caller's repeatable-read read-only transaction."""
    _guard(connection, lease)
    catalog = connection.execute(
        "SELECT schemaname AS schema,tablename AS name FROM pg_tables "
        "WHERE schemaname=ANY(%s) ORDER BY schemaname,tablename",
        (list(SCHEMAS),),
    ).fetchall()
    tables: Record = {}
    for item in catalog:
        schema, name = _text(item, "schema"), _text(item, "name")
        if schema not in SCHEMAS:
            raise ValueError("Unexpected database schema")
        rows = connection.execute(
            sql.SQL("SELECT row_to_json(t)::text AS row FROM {} t").format(
                sql.Identifier(schema, name)
            )
        ).fetchall()
        encoded = sorted(_text(row, "row") for row in rows)
        tables[schema + "." + name] = {"count": len(rows), "sha256": _digest(encoded)}
    committed: Record = {}
    effectful: Record = {}
    rejected: Record = {}
    for table in ("operation", "duty_operation"):
        rows = connection.execute(
            sql.SQL("SELECT row_to_json(t)::text AS row FROM {} t WHERE state='committed'").format(
                sql.Identifier("durable", table)
            )
        ).fetchall()
        committed[table] = {
            "count": len(rows),
            "sha256": _digest(sorted(_text(row, "row") for row in rows)),
        }
        rows = connection.execute(
            sql.SQL("SELECT row_to_json(t)::text AS row FROM {} t WHERE state<>'rejected'").format(
                sql.Identifier("durable", table)
            )
        ).fetchall()
        effectful[table] = {
            "count": len(rows),
            "sha256": _digest(sorted(_text(row, "row") for row in rows)),
        }
        rows = connection.execute(
            sql.SQL("SELECT row_to_json(t)::text AS row FROM {} t WHERE state='rejected'").format(
                sql.Identifier("durable", table)
            )
        ).fetchall()
        rejected[table] = sorted(_digest(_text(row, "row")) for row in rows)
    return {
        "database": DATABASE,
        "journal_id": lease.journal_id,
        "policy_digest": lease.policy_digest,
        "tables": tables,
        "committed_operations": committed,
        "non_rejected_operations": effectful,
        "rejected_operation_hashes": rejected,
        "audit": _audit(connection),
        "postgres_tls": "TLSv1.3 verify-full",
    }


def snapshot_target(lease: TargetLease) -> Record:
    lease.inspect()
    try:
        with _connection(lease) as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            connection.execute("SET LOCAL TIME ZONE 'UTC'")
            return snapshot_connection(connection, lease)
    except psycopg.Error:
        raise RuntimeError("Continuation database observation failed; details suppressed") from None


def compare_snapshots(before: Record, after: Record) -> Record:
    """Permit only rejected-operation records and append-only denial/preflight audit.

    Full hashes remain available for inspection even for those permitted changes.
    This does not itself observe bytes already delivered to a browser/channel.
    """
    for key in ("database", "journal_id", "policy_digest"):
        if before.get(key) != after.get(key):
            raise ValueError("Cannot compare snapshots from different target bindings")
    old, new = _record(before["tables"]), _record(after["tables"])
    changed = sorted(key for key in old.keys() | new.keys() if old.get(key) != new.get(key))
    separately_checked = {
        "audit.event",
        "audit.head",
        "durable.operation",
        "durable.duty_operation",
    }
    prohibited = [key for key in changed if key not in separately_checked]
    audit_before, audit_after = _record(before["audit"]), _record(after["audit"])
    prior, current = _rows(audit_before["events"]), _rows(audit_after["events"])
    append_only = (
        audit_before.get("valid") is True
        and audit_after.get("valid") is True
        and current[: len(prior)] == prior
        and len(current) >= len(prior)
    )
    audit_permitted = append_only and all(
        event.get("decision") == "DENY"
        or (event.get("decision") == "PERMIT" and event.get("action") == "authority_metadata")
        for event in current[len(prior) :]
    )
    committed_same = before["committed_operations"] == after["committed_operations"]
    effectful_same = before["non_rejected_operations"] == after["non_rejected_operations"]
    old_rejected = _record(before["rejected_operation_hashes"])
    new_rejected = _record(after["rejected_operation_hashes"])
    rejected_append_only = all(
        isinstance(old_rejected.get(table), list)
        and isinstance(new_rejected.get(table), list)
        and set(cast(list[str], old_rejected[table])) <= set(cast(list[str], new_rejected[table]))
        for table in ("operation", "duty_operation")
    )
    return {
        "changed_tables": changed,
        "prohibited_changed_tables": prohibited,
        "committed_operation_rows_unchanged": committed_same,
        "non_rejected_operation_rows_unchanged": effectful_same,
        "rejected_operation_rows_append_only": rejected_append_only,
        "audit_chain_append_only": append_only,
        "new_audit_events_permitted": audit_permitted,
        "no_prohibited_observed_effect": (
            not prohibited
            and committed_same
            and effectful_same
            and rejected_append_only
            and audit_permitted
        ),
        "output_scope": "Database only; client buffered/delivered bytes require separate evidence",
    }


def _dump(lease: TargetLease, snapshot: str) -> bytes:
    lease.inspect()
    result = subprocess.run(  # noqa: S603 - inspected exact owned container, fixed pg_dump argv
        [
            docker(),
            "exec",
            lease.container_id,
            "pg_dump",
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            "--snapshot=" + snapshot,
            "--username=postgres",
            "--dbname=" + DATABASE,
        ],
        capture_output=True,
        check=False,
        timeout=60,
    )
    if result.returncode:
        raise RuntimeError("Continuation consistent dump failed; details suppressed")
    return result.stdout


def capture_target(
    lease: TargetLease,
    captures: EncryptedCaptures,
    journal: JournalReader,
    schema: Path,
    artifact_digest: str,
    *,
    dump: Callable[[str], bytes] | None = None,
) -> Record:
    """Keep the exported source snapshot open until pg_dump consumes it."""
    lease.inspect()
    with _connection(lease) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        guard = _guard(connection, lease)
        checkpoint = connection.execute(
            "SELECT pg_export_snapshot() AS snapshot,pg_current_wal_lsn()::text AS wal,"
            "clock_timestamp() AS captured_at"
        ).fetchone()
        if checkpoint is None or not isinstance(checkpoint.get("captured_at"), datetime):
            raise ValueError("Consistent source checkpoint unavailable")
        head = _audit(connection)
        journal_head = journal.head()
        if journal_head.journal_id != lease.journal_id or journal_head.generation != guard.get(
            "journal_generation"
        ):
            raise ValueError("Current capture journal differs from source lease")
        token = _text(checkpoint, "snapshot")
        content = dump(token) if dump is not None else _dump(lease, token)
        if not content.startswith(b"PGDMP") or len(content) > 256 * 1024 * 1024:
            raise ValueError("Bounded custom-format PostgreSQL dump required")
        metadata = CaptureMetadata(
            "001_manual",
            hashlib.sha256(schema.read_bytes()).hexdigest(),
            artifact_digest,
            _text(head, "head_digest"),
            _text(checkpoint, "wal"),
        )
        return captures.capture(
            str(uuid4()),
            {"database.dump": content},
            metadata,
            journal_head,
            capture_at=cast(datetime, checkpoint["captured_at"]),
        )


def restore_target(
    lease: TargetLease, staged: QuarantineRestore, *, expected_audit_digest: str
) -> Record:
    """Import only into a fresh database with no runtime CONNECT/serving grants.

    Failed/partial targets are retained for inspection; no DROP/reset is supplied.
    """
    if staged.serving_allowed or staged.state != "quarantined_unvalidated":
        raise ValueError("Only verified unvalidated quarantine staging may be imported")
    if staged.journal.journal_id != lease.journal_id:
        raise ValueError("Quarantine stage belongs to another source journal")
    if not HEX.fullmatch(expected_audit_digest):
        raise ValueError("Exact verified capture audit digest required")
    lease.inspect()
    target = "imp03_cont1_quarantine_" + uuid4().hex
    with _connection(lease, "postgres") as connection:
        connection.autocommit = True
        connection.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(target))
        )
        connection.execute(
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(target))
        )
    result = subprocess.run(  # noqa: S603 - fixed import into new UUID database in owned container
        [
            docker(),
            "exec",
            "-i",
            lease.container_id,
            "pg_restore",
            "--exit-on-error",
            "--no-owner",
            "--no-privileges",
            "--username=postgres",
            "--dbname=" + target,
        ],
        input=(staged.path / "database.dump").read_bytes(),
        capture_output=True,
        check=False,
        timeout=60,
    )
    if result.returncode:
        raise RuntimeError("Quarantine import failed; partial target retained: " + target)
    with _connection(lease, target) as connection:
        connection.execute("UPDATE control.guard SET mode='quarantine',serving_generation=0")
        connection.execute("UPDATE control.principal_guard SET revoked=true")
        connection.execute("UPDATE core.session_acl SET revoked_at=clock_timestamp()")
        connection.execute("UPDATE access.continuation_family SET status='revoked'")
        connection.execute(
            "UPDATE workforce.channel_challenge "
            "SET expires_at=clock_timestamp()-interval '1 second'"
        )
        observation = connection.execute(
            "SELECT (SELECT mode='quarantine' AND serving_generation=0 FROM control.guard "
            "WHERE key='demo') AS quarantine,"
            "(SELECT count(*)=0 FROM control.principal_guard WHERE NOT revoked) "
            "AS principals_disabled,"
            "(SELECT count(*)=0 FROM access.continuation_family WHERE status='active') "
            "AS tokens_disabled,"
            "NOT has_database_privilege(%s,current_database(),'CONNECT') AS runtime_connect_denied",
            (LOGIN,),
        ).fetchone()
        if observation is None or not all(value is True for value in observation.values()):
            raise ValueError("Quarantine restrictions could not be confirmed")
        audit = _audit(connection)
        if audit["head_digest"] != expected_audit_digest:
            raise ValueError("Imported audit chain differs from verified capture checkpoint")
    return {
        "target_database": target,
        "state": "quarantined_unvalidated",
        "serving_allowed": False,
        "observed": observation,
        "audit_chain_valid": audit["valid"],
        "source_database": DATABASE,
        "source_reset": False,
    }
