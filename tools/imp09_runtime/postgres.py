"""Concrete recovery binding limited to the named disposable synthetic database.

The database has no application listener; only this maintenance adapter receives
its private DSN. pg_restore never executes against the running demo database.
"""

import hashlib
import json
import os
import secrets
import shutil
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import psycopg
from care_link_data.recovery import PostgresQuarantineValidator
from care_link_domain import Actor, CipherPort, JournalState, ManualError
from care_link_recovery_control import CaptureInput, CaptureMetadata, QuarantineRestore
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

Record = dict[str, object]
NAME = "care-link-imp09-001-postgres"


def run_database(
    command: str, database: str, *, data: bytes | None = None, extra: tuple[str, ...] = ()
) -> bytes:
    binary = shutil.which("docker")
    if binary is None:
        raise ManualError("recovery.fixture_unavailable", 503)
    result = subprocess.run(  # noqa: S603
        [
            binary,
            "exec",
            "-i",
            NAME,
            command,
            "--username=postgres",
            "--dbname=" + database,
            *extra,
        ],
        input=data,
        capture_output=True,
        check=False,
    )  # noqa: S603
    if result.returncode:
        raise ManualError("recovery.database_command_failed", 503)
    return result.stdout


def source_settings(dsn: str) -> dict[str, str]:
    settings = conninfo_to_dict(dsn)
    if (
        settings.get("host") != "localhost"
        or settings.get("hostaddr") != "127.0.0.1"
        or settings.get("port") != "35439"
        or settings.get("dbname") != "imp03_manual"
        or settings.get("sslmode") != "verify-full"
    ):
        raise ValueError("Only owned IMP09 disposable verified-TLS fixture allowed")
    return {key: str(value) for key, value in settings.items()}


class PostgresCaptureSource:
    def __init__(self, dsn: str, schema_digest: str, artifact_digest: str) -> None:
        self.settings = source_settings(dsn)
        self.dsn = dsn
        self.schema_digest, self.artifact_digest = schema_digest, artifact_digest

    def capture(self) -> CaptureInput:
        with psycopg.connect(self.dsn) as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            checkpoint = connection.execute(
                "SELECT pg_export_snapshot(),pg_current_wal_lsn()::text,clock_timestamp()"
            ).fetchone()
            audit = connection.execute(
                "SELECT digest FROM audit.head WHERE stream_id='demo'"
            ).fetchone()
            if checkpoint is None or audit is None:
                raise ManualError("recovery.capture_checkpoint_missing", 503)
            dump = run_database(
                "pg_dump",
                "imp03_manual",
                extra=(
                    "--format=custom",
                    "--no-owner",
                    "--snapshot=" + str(checkpoint[0]),
                ),
            )
            metadata = CaptureMetadata(
                "imp09-012",
                self.schema_digest,
                self.artifact_digest,
                str(audit[0]),
                str(checkpoint[1]),
            )
            return CaptureInput({"database.dump": dump}, metadata, cast(datetime, checkpoint[2]))


class PostgresRecoveryTargets:
    def __init__(
        self,
        source_dsn: str,
        path: Path,
        recovery_actor_id: str,
        smoke: Callable[[str, int], bool],
        schema_digest: str,
        artifact_digest: str,
        current_principals: Callable[[], tuple[Actor, ...]] = tuple,
        content_cipher: CipherPort | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.settings = source_settings(source_dsn)
        self.source_dsn = source_dsn
        if path.is_symlink() or not path.is_dir() or path.stat().st_mode & 0o077:
            raise ValueError("Private pre-provisioned target registry required")
        self.path = path
        self.schema_digest = schema_digest
        self.artifact_digest = artifact_digest
        self.current_principals = current_principals
        self.content_cipher = content_cipher
        self.clock = clock
        self.actor_id = str(UUID(recovery_actor_id))
        self.smoke_probe = smoke
        self.access_path = path / "credentials"
        self.access_path.mkdir(mode=0o700, exist_ok=True)
        if self.access_path.is_symlink() or self.access_path.stat().st_mode & 0o077:
            raise ValueError("Separate private target credential custody required")

    def _file(self, target_id: str) -> Path:
        return self.path / (str(UUID(target_id)) + ".json")

    def _write(self, path: Path, value: Record) -> None:
        temporary = path.parent / (uuid4().hex + ".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            json.dump(value, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def _row(self, target_id: str) -> Record:
        path = self._file(target_id)
        if path.is_symlink():
            raise ManualError("recovery.target_custody_denied", 503)
        value = json.loads(path.read_text())
        if not isinstance(value, dict):
            raise ManualError("recovery.target_metadata_invalid", 503)
        row = cast(Record, value)
        if (
            row.get("schema_digest") != self.schema_digest
            or row.get("artifact_digest") != self.artifact_digest
        ):
            raise ManualError("recovery.incompatible_target", 409)
        return row

    def dsn(self, target_id: str) -> str:
        row = self._row(target_id)
        expected = "imp09_quarantine_" + UUID(target_id).hex
        if row["database"] != expected:
            raise ManualError("recovery.target_mismatch", 503)
        return make_conninfo(**{**self.settings, "dbname": expected})

    def runtime_dsn(self, target_id: str) -> str:
        """Unique non-superuser data identity; never export this into evidence."""
        path = self.access_path / (str(UUID(target_id)) + ".json")
        if path.is_symlink():
            raise ManualError("recovery.target_credential_denied", 503)
        value = json.loads(path.read_text())
        role = "imp09_target_" + UUID(target_id).hex
        if value["user"] != role:
            raise ManualError("recovery.target_credential_denied", 503)
        return make_conninfo(
            **{
                **self.settings,
                "dbname": "imp09_quarantine_" + UUID(target_id).hex,
                "user": role,
                "password": value["password"],
            }
        )

    def _validator(self, target_id: str) -> PostgresQuarantineValidator:
        row = self._row(target_id)
        return PostgresQuarantineValidator(
            self.dsn(target_id),
            str(row["database"]),
            target_id,
            str(row["schema_digest"]),
            str(row["artifact_digest"]),
            str(row["audit_digest"]),
            self.actor_id,
            current_principals=self.current_principals,
            content_cipher=self.content_cipher,
        )

    def create(self, staged: QuarantineRestore, metadata: Record) -> None:
        if (
            metadata.get("schema_digest") != self.schema_digest
            or metadata.get("artifact_digest") != self.artifact_digest
        ):
            raise ManualError("recovery.incompatible_capture", 409)
        identity = str(UUID(staged.target_id))
        database = "imp09_quarantine_" + UUID(identity).hex
        if staged.serving_allowed or staged.state != "quarantined_unvalidated":
            raise ManualError("recovery.quarantine_required", 409)
        with psycopg.connect(self.source_dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(database))
            )
            connection.execute(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database))
            )
        # Register the copy before import, so interrupted restores remain in the
        # immutable-expiry inventory. Metadata contains no DSN or plaintext.
        copy_record: Record = {
            "database": database,
            "schema_digest": metadata["schema_digest"],
            "artifact_digest": metadata["artifact_digest"],
            "audit_digest": metadata["audit_digest"],
            "capture_at": metadata["capture_at"],
            "expires_at": metadata["expires_at"],
            "staging_path": str(staged.path),
            "state": "importing",
        }
        self._write(self._file(identity), copy_record)
        role = "imp09_target_" + UUID(identity).hex
        password = secrets.token_urlsafe(32)
        with psycopg.connect(self.source_dsn) as connection:
            connection.execute(
                sql.SQL(
                    "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}"
                ).format(sql.Identifier(role), sql.Literal(password))
            )
            connection.execute(
                sql.SQL("GRANT care_link_data_runtime TO {}").format(sql.Identifier(role))
            )
        self._write(self.access_path / (identity + ".json"), {"user": role, "password": password})
        # An interrupted import remains unservable. Never adopt it.
        run_database(
            "pg_restore",
            database,
            data=(staged.path / "database.dump").read_bytes(),
            extra=("--exit-on-error", "--no-owner"),
        )
        target_dsn = make_conninfo(**{**self.settings, "dbname": database})
        with psycopg.connect(target_dsn) as connection:
            connection.execute("UPDATE control.guard SET mode='quarantine',serving_generation=0")
        # Plaintext staging is no longer needed once import has completed.
        staged_dump = staged.path / "database.dump"
        staged_dump.unlink()
        descriptor = os.open(staged.path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        copy_record["state"] = "quarantined"
        self._write(self._file(identity), copy_record)

    def reconcile(self, target_id: str, head: JournalState, records: tuple[Record, ...]) -> Record:
        return self._validator(target_id).reconcile(head, records)

    def inspect(self, target_id: str) -> str:
        return self._validator(target_id).inspect()

    def fence_all(self) -> None:
        # Fence the source DB even if an old process still uses the raw journal.
        # A routing change alone must never leave that generation able to write.
        with psycopg.connect(self.source_dsn) as connection:
            connection.execute("UPDATE control.guard SET mode='quarantine',serving_generation=0")
            connection.execute("REVOKE CONNECT ON DATABASE imp03_manual FROM PUBLIC")
        for path in self.path.glob("*.json"):
            if path.name == "route.json":
                continue
            target = str(UUID(path.stem))
            if self._row(target).get("state") == "expired_unlinked":
                continue
            with psycopg.connect(self.dsn(target)) as connection:
                connection.execute(
                    "UPDATE control.guard SET mode='quarantine',serving_generation=0"
                )

    def route(self, target_id: str) -> None:
        self.dsn(target_id)
        self._write(self.path / "route.json", {"target_id": target_id})

    def enable(self, target_id: str, generation: int) -> None:
        if self.state() != (target_id, 0) or generation <= 0:
            raise ManualError("recovery.route_not_restricted", 503)
        with psycopg.connect(self.dsn(target_id)) as connection:
            blocked = connection.execute(
                "SELECT 1 FROM recovery.restriction WHERE disposition='unresolved' LIMIT 1"
            ).fetchone()
            if blocked is not None:
                raise ManualError("recovery.operational_restriction_unresolved", 409)
            connection.execute(
                "UPDATE control.guard SET mode='ai_disabled',serving_generation=%s", (generation,)
            )
            connection.execute(
                sql.SQL("ALTER ROLE {} LOGIN").format(
                    sql.Identifier("imp09_target_" + UUID(target_id).hex)
                )
            )
            connection.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier("imp09_quarantine_" + UUID(target_id).hex),
                    sql.Identifier("imp09_target_" + UUID(target_id).hex),
                )
            )

    def smoke(self, target_id: str, generation: int) -> bool:
        return self.state() == (target_id, generation) and self.smoke_probe(
            self.dsn(target_id), generation
        )

    def state(self) -> tuple[str | None, int]:
        path = self.path / "route.json"
        if not path.exists():
            return None, 0
        if path.is_symlink():
            raise ManualError("recovery.router_custody_denied", 503)
        row = json.loads(path.read_text())
        if row.get("expired") is True:
            return None, 0
        target = str(UUID(row["target_id"]))
        with psycopg.connect(self.dsn(target)) as connection:
            result = connection.execute(
                "SELECT serving_generation,mode FROM control.guard WHERE key='demo'"
            ).fetchone()
        if result is None:
            return target, 0
        return target, int(result[0]) if result[1] == "ai_disabled" else 0

    def inventory(self) -> tuple[Record, ...]:
        """Account for imported copies and staging without renewing capture expiry."""
        rows: list[Record] = []
        known: set[str] = set()
        for path in sorted(self.path.glob("*.json")):
            if path.name == "route.json":
                continue
            identity = str(UUID(path.stem))
            row = self._row(identity)
            known.add(str(row["database"]))
            rows.append({"target_id": identity, **row})
        with psycopg.connect(self.source_dsn) as connection:
            actual = {
                str(row[0])
                for row in connection.execute(
                    "SELECT datname FROM pg_database "
                    "WHERE starts_with(datname, 'imp09_quarantine_')"
                )
            }
        if not actual <= known:
            raise ManualError("recovery.unaccounted_database_copy", 503)
        return tuple(rows)

    def expire_target(self, target_id: str, current_hold: Callable[[str], bool]) -> Record:
        """Maintenance-only removal of an expired non-serving known copy.

        Current hold authority is mandatory; active serving storage has its own
        lifecycle and cannot be dropped as backup cleanup. No physical-device
        erasure certificate is produced.
        """
        row = self._row(target_id)
        if self.clock() < datetime.fromisoformat(str(row["expires_at"])) or current_hold(target_id):
            raise ManualError("recovery.copy_expiry_or_hold_denied", 409)
        if self.state() == (target_id, 0):
            self._write(self.path / "route.json", {"target_id": target_id, "expired": True})
        elif self.state()[0] == target_id:
            raise ManualError("recovery.active_target_retained", 409)
        name = "imp09_quarantine_" + UUID(target_id).hex
        if row["database"] != name:
            raise ManualError("recovery.target_mismatch", 503)
        with psycopg.connect(self.source_dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )
        staged = Path(str(row["staging_path"])) / "database.dump"
        if staged.is_symlink():
            raise ManualError("recovery.target_custody_denied", 503)
        staged.unlink(missing_ok=True)
        role = "imp09_target_" + UUID(target_id).hex
        with psycopg.connect(self.source_dsn) as connection:
            connection.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
        credential = self.access_path / (str(UUID(target_id)) + ".json")
        credential.unlink(missing_ok=True)
        row["state"] = "expired_unlinked"
        self._write(self._file(target_id), row)
        return {
            "target_id": target_id,
            "expires_at": row["expires_at"],
            "known_copy_unlinked": True,
            "physical_erasure_proven": False,
        }


def schema_digest(root: Path) -> str:
    return hashlib.sha256(
        b"".join(p.read_bytes() for p in sorted((root / "services/data/migrations").glob("*.sql")))
    ).hexdigest()
