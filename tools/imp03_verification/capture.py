"""Consistent logical capture and role-quarantined PostgreSQL restore test harness.

This only operates in the named disposable IMP-03 PostgreSQL container. It does
not validate trusted serving recovery, live rights reconciliation or PITR/RPO.
"""

import hashlib
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import psycopg
from care_link_domain import JournalPort
from care_link_recovery_control import CaptureMetadata, EncryptedCaptures, QuarantineRestore
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from .database import NAME


def docker() -> str:
    executable = shutil.which("docker")
    if executable is None:
        raise ValueError("Docker unavailable")
    return executable


def capture_database(
    admin_dsn: str,
    captures: EncryptedCaptures,
    journal: JournalPort,
    schema: Path,
    artifact_digest: str,
) -> tuple[dict[str, object], bytes]:
    settings = conninfo_to_dict(admin_dsn)
    if settings.get("dbname") != "imp03_manual" or settings.get("port") != "25433":
        raise ValueError("Only disposable IMP-03 source database is allowed")
    with psycopg.connect(admin_dsn) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        snapshot = connection.execute(
            "SELECT pg_export_snapshot(),pg_current_wal_lsn()::text,clock_timestamp()"
        ).fetchone()
        audit = connection.execute(
            "SELECT digest FROM audit.head WHERE stream_id='demo'"
        ).fetchone()
        if snapshot is None or audit is None:
            raise ValueError("Capture checkpoint unavailable")
        result = subprocess.run(  # noqa: S603
            [
                docker(),
                "exec",
                NAME,
                "pg_dump",
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--snapshot=" + str(snapshot[0]),
                "--username=postgres",
                "--dbname=imp03_manual",
            ],
            check=True,
            capture_output=True,
        )
        dump = result.stdout
        metadata = CaptureMetadata(
            "001_manual",
            hashlib.sha256(schema.read_bytes()).hexdigest(),
            artifact_digest,
            str(audit[0]),
            str(snapshot[1]),
        )
        view = captures.capture(
            str(uuid4()), {"database.dump": dump}, metadata, journal.head(), capture_at=snapshot[2]
        )
    return view, dump


def restore_database(
    admin_dsn: str,
    staged: QuarantineRestore,
) -> str:
    if staged.serving_allowed or staged.state != "quarantined_unvalidated":
        raise ValueError("Only unvalidated quarantine staging can be imported")
    settings = conninfo_to_dict(admin_dsn)
    if settings.get("dbname") != "imp03_manual" or settings.get("port") != "25433":
        raise ValueError("Only disposable IMP-03 fixture is allowed")
    target = "imp03_quarantine_" + uuid4().hex
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(target))
        )
        connection.execute(
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(target))
        )
    try:
        result = subprocess.run(  # noqa: S603
            [
                docker(),
                "exec",
                "-i",
                NAME,
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
        )
        if result.returncode:
            raise ValueError("Quarantine database import failed")
        target_dsn = make_conninfo(**{**settings, "dbname": target})
        with psycopg.connect(target_dsn) as connection:
            connection.execute("UPDATE control.guard SET mode='quarantine',serving_generation=0")
            connection.execute("UPDATE control.principal_guard SET revoked=true")
            connection.execute("UPDATE core.session_acl SET revoked_at=clock_timestamp()")
            connection.execute("UPDATE access.continuation_family SET status='revoked'")
            connection.execute(
                "UPDATE workforce.channel_challenge "
                "SET expires_at=clock_timestamp()-interval '1 second'"
            )
        return target
    except BaseException:
        drop_target(admin_dsn, target)
        raise


def drop_target(admin_dsn: str, target: str) -> None:
    suffix = target.removeprefix("imp03_quarantine_")
    if (
        not target.startswith("imp03_quarantine_")
        or len(suffix) != 32
        or any(c not in "0123456789abcdef" for c in suffix)
    ):
        raise ValueError("Refusing cleanup of unowned target")
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(target)))
