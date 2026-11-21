"""Real PostgreSQL quarantine transformation, independent of host/router custody.

Only an exact separately provisioned quarantine database may be transformed.
The owner supplies authenticated, fully verified live-journal records; records
must span the entire current head. A copied signature is not continuing custody.
"""

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import psycopg
from care_link_contracts import validate_contract
from care_link_domain import Actor, CipherPort, JournalState, ManualError
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from ..audit import verify_audit_chain
from ..values import digest
from .assistance import suspend_assistance
from .restrictions import apply

Record = dict[str, object]
HEX = re.compile(r"^[0-9a-f]{64}$")
DATABASE = re.compile(r"^(?:imp03_quarantine_|imp09_quarantine_|care_link_restore_)[0-9a-f]{32}$")
SCHEMAS = (
    "control",
    "core",
    "workforce",
    "durable",
    "audit",
    "access",
    "recovery",
    "lifecycle",
    "plans",
    "consent",
    "knowledge",
    "referral",
    "assistance",
    "care",
    "rights",
    "governance",
    "quality",
)


class PostgresQuarantineValidator:
    def __init__(
        self,
        dsn: str,
        expected_database: str,
        target_id: str,
        schema_digest: str,
        artifact_digest: str,
        audit_checkpoint: str,
        recovery_actor_id: str,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        current_principals: Callable[[], tuple[Actor, ...]] | None = None,
        content_cipher: CipherPort | None = None,
    ) -> None:
        if (
            not DATABASE.fullmatch(expected_database)
            or conninfo_to_dict(dsn).get("dbname") != expected_database
        ):
            raise ValueError("exact separately provisioned quarantine database required")
        if not all(
            HEX.fullmatch(value) for value in (schema_digest, artifact_digest, audit_checkpoint)
        ):
            raise ValueError("exact capture digests required")
        self.dsn = dsn
        self.database = expected_database
        self.target_id = str(UUID(target_id))
        self.actor_id = str(UUID(recovery_actor_id))
        self.schema_digest = schema_digest
        self.artifact_digest = artifact_digest
        self.audit_checkpoint = audit_checkpoint
        self.clock = clock
        self.current_principals = current_principals
        self.content_cipher = content_cipher

    def _connection(self) -> psycopg.Connection[Record]:
        return psycopg.Connection[Record].connect(self.dsn, row_factory=dict_row)

    def _assert_quarantine(self, connection: psycopg.Connection[Record]) -> Record:
        current = connection.execute("SELECT current_database() AS name").fetchone()
        guard = connection.execute(
            "SELECT * FROM control.guard WHERE key='demo' FOR UPDATE"
        ).fetchone()
        if current is None or current["name"] != self.database or guard is None:
            raise ManualError("recovery.target_mismatch", 409)
        if guard["mode"] != "quarantine" or guard["serving_generation"] != 0:
            raise ManualError("recovery.target_not_quarantined", 409)
        return guard

    def _audit(self, connection: psycopg.Connection[Record]) -> str:
        events = [
            {key: str(value) if isinstance(value, UUID) else value for key, value in row.items()}
            for row in connection.execute("SELECT * FROM audit.event ORDER BY sequence")
        ]
        result = verify_audit_chain(events)
        head = connection.execute("SELECT * FROM audit.head WHERE stream_id='demo'").fetchone()
        if (
            head is None
            or head["digest"] != result
            or head["next_sequence"] != len(events) + 1
            or result != self.audit_checkpoint
        ):
            raise ManualError("recovery.audit_checkpoint_mismatch", 409)
        return result

    @staticmethod
    def _digest(connection: psycopg.Connection[Record]) -> str:
        # PostgreSQL JSON has stable scalar encoding; sort complete row encodings
        # and table identities. Exclude only expected gate transition fields.
        tables = connection.execute(
            "SELECT schemaname,tablename FROM pg_tables WHERE schemaname=ANY(%s) ORDER BY 1,2",
            (list(SCHEMAS),),
        ).fetchall()
        inventory: Record = {}
        for table in tables:
            schema, name = str(table["schemaname"]), str(table["tablename"])
            if schema == "recovery" and name == "target_validation":
                continue
            expression = (
                sql.SQL("to_jsonb(t)-'mode'-'serving_generation'")
                if (schema, name) == ("control", "guard")
                else sql.SQL("to_jsonb(t)")
            )
            rows = connection.execute(
                sql.SQL("SELECT ({})::text AS value FROM {} t ORDER BY 1").format(
                    expression, sql.Identifier(schema, name)
                )
            )
            inventory[schema + "." + name] = [row["value"] for row in rows]
        return digest(inventory)

    def inspect(self) -> str:
        with self._connection() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            return self._digest(connection)

    def reconcile(self, head: JournalState, records: tuple[Record, ...]) -> Record:
        if (
            head.observed_at.tzinfo is None
            or not 0 <= (self.clock() - head.observed_at).total_seconds() <= 1
        ):
            raise ManualError("recovery.current_head_required", 409)
        if len(records) != head.tip:
            raise ManualError("recovery.journal_incomplete", 409)
        for index, entry in enumerate(records, start=1):
            validate_contract("JournalRecord", entry)
            if (
                entry["journal_id"] != head.journal_id
                or entry["generation"] != str(head.generation)
                or entry["sequence"] != str(index)
            ):
                raise ManualError("recovery.journal_discontinuous", 409)
        if records and records[-1]["hash"] != head.tip_digest:
            raise ManualError("recovery.journal_head_mismatch", 409)
        with self._connection() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            guard = self._assert_quarantine(connection)
            if (
                str(guard["journal_id"]) != head.journal_id
                or guard["journal_generation"] != head.generation
                or int(str(guard["restriction_barrier"])) > head.restriction_barrier
            ):
                raise ManualError("recovery.journal_identity_mismatch", 409)
            audit_digest = self._audit(connection)
            existing = connection.execute(
                "SELECT * FROM recovery.target_validation WHERE target_id=%s", (self.target_id,)
            ).fetchone()
            if existing is not None and (
                int(str(existing["journal_tip"])) > head.tip
                or (
                    existing["journal_tip"] == head.tip
                    and existing["journal_digest"] != head.tip_digest
                )
            ):
                raise ManualError("recovery.journal_rollback", 409)
            original_principals = {
                str(row["principal_id"]): row
                for row in connection.execute("SELECT * FROM control.principal_guard")
            }
            self._suspend(connection)
            uncertainties: list[str] = []
            for entry in records:
                command = cast(Record, entry["command"])
                if command["kind"] in {"restrict_intent", "serving_fence"} and not apply(
                    connection, entry, self.actor_id
                ):
                    uncertainties.append(str(command["command_id"]))
            self._admit_current_principals(connection, original_principals)
            connection.execute(
                "UPDATE control.guard SET restriction_barrier=%s,journal_tip_seen=%s",
                (head.restriction_barrier, head.tip),
            )
            rights_digest = digest(
                [
                    row["value"]
                    for row in connection.execute(
                        "SELECT to_jsonb(r)::text AS value FROM recovery.restriction r "
                        "ORDER BY sequence"
                    )
                ]
            )
            connection.execute(
                "INSERT INTO recovery.target_validation VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                " ON CONFLICT(target_id) DO UPDATE SET journal_tip=EXCLUDED.journal_tip,"
                "journal_digest=EXCLUDED.journal_digest,restriction_barrier=EXCLUDED.res"
                "triction_barrier,"
                "rights_digest=EXCLUDED.rights_digest,validated_at=EXCLUDED.validated_at",
                (
                    self.target_id,
                    head.journal_id,
                    head.generation,
                    head.tip,
                    head.tip_digest,
                    head.restriction_barrier,
                    audit_digest,
                    rights_digest,
                    self.schema_digest,
                    self.artifact_digest,
                    self.clock(),
                ),
            )
            target_digest = self._digest(connection)
        return {
            "target_id": self.target_id,
            "target_digest": target_digest,
            "audit_digest": audit_digest,
            "rights_digest": rights_digest,
            "uncertainties": uncertainties,
            "schema_digest": self.schema_digest,
            "artifact_digest": self.artifact_digest,
        }

    def _admit_current_principals(
        self, connection: psycopg.Connection[Record], original: dict[str, Record]
    ) -> None:
        # This callback is a fresh external identity authority adapter. Snapshot
        # account rows, bearer bytes and caller body fields never supply it.
        if self.current_principals is None:
            return
        for actor in self.current_principals():
            now = self.clock()
            if actor.expires_at <= now or not 0 <= (now - actor.auth_time).total_seconds() <= 300:
                raise ManualError("recovery.fresh_identity_required", 403)
            fenced = connection.execute(
                "SELECT 1 FROM recovery.restriction WHERE kind IN ('identity_revoke','role_revoke')"
                " AND payload->>'principal_id'=%s LIMIT 1",
                (actor.account_id,),
            ).fetchone()
            if fenced is not None:
                raise ManualError("recovery.principal_fenced", 403)
            existing = connection.execute(
                "SELECT p.principal_id,n.target_id FROM control.principal_guard p LEFT JOIN"
                " recovery.new_principal n ON n.principal_id=p.principal_id AND n.target_id=%s"
                " WHERE p.principal_id=%s",
                (self.target_id, actor.account_id),
            ).fetchone()
            prior = original.get(actor.account_id)
            if prior is not None and (
                actor.identity_revision < int(str(prior["identity_revision"]))
                or actor.role_revision < int(str(prior["role_revision"]))
                or (
                    actor.role != prior["role"]
                    and actor.role_revision <= int(str(prior["role_revision"]))
                )
                or (
                    prior["revoked"] is True
                    and existing is not None
                    and existing["target_id"] is None
                    and actor.identity_revision <= int(str(prior["identity_revision"]))
                )
            ):
                raise ManualError("recovery.stronger_current_identity_required", 403)
            connection.execute(
                "INSERT INTO control.principal_guard VALUES(%s,%s,%s,%s,false,0)"
                " ON CONFLICT(principal_id) DO UPDATE"
                " SET identity_revision=EXCLUDED.identity_revision,"
                "role_revision=EXCLUDED.role_revision,role=EXCLUDED.role,revoked=false",
                (actor.account_id, actor.identity_revision, actor.role_revision, actor.role),
            )
            connection.execute(
                "INSERT INTO recovery.new_principal VALUES(%s,%s,%s)"
                " ON CONFLICT(target_id,principal_id)"
                " DO UPDATE SET identity_evidence_id=EXCLUDED.identity_evidence_id",
                (self.target_id, actor.account_id, actor.identity_evidence_id),
            )

    def _suspend(self, connection: psycopg.Connection[Record]) -> None:
        now = self.clock()
        statements = (
            "UPDATE control.principal_guard SET revoked=true WHERE NOT revoked",
            (
                "UPDATE core.session_acl SET revoked_at=%s,revision=revision+1 WHERE "
                "revoked_at IS NULL"
            ),
            (
                "UPDATE access.continuation_family SET "
                "status='revoked',revision=revision+1 WHERE status='active'"
            ),
            "UPDATE access.continuation_token SET consumed_at=%s WHERE consumed_at IS NULL",
            (
                "UPDATE consent.current_grant SET revoked_at=%s,revision=revision+1 WHERE "
                "revoked_at IS NULL"
            ),
            "UPDATE consent.delegation SET revoked_at=%s WHERE revoked_at IS NULL",
            "UPDATE access.audit_grant SET revoked=true WHERE NOT revoked",
            "UPDATE governance.approval SET active=false WHERE active",
            "UPDATE governance.instance SET healthy=false WHERE healthy",
            (
                "UPDATE governance.activation SET state='superseded' WHERE state IN "
                "('proposed','staged','ready')"
            ),
            (
                "UPDATE workforce.assignment SET status='released',revision=revision+1 "
                "WHERE status IN ('reserved','accepted','connected')"
            ),
            "UPDATE workforce.channel_challenge SET revoked=true WHERE NOT revoked",
            (
                "UPDATE workforce.queue_entry SET status='pending',revision=revision+1 "
                "WHERE status IN ('reserved','accepted')"
            ),
            (
                "UPDATE core.session SET owner_id=NULL,transport='disconnected' WHERE "
                "owner_id IS NOT NULL OR transport<>'disconnected'"
            ),
            (
                "UPDATE core.session_guard SET "
                "control_epoch=control_epoch+1,access_revision=access_revision+1"
            ),
            "UPDATE durable.due_job SET state='superseded' WHERE state='pending'",
            "UPDATE referral.authorization SET consumed_at=%s WHERE consumed_at IS NULL",
            "UPDATE referral.review SET expires_at=LEAST(expires_at,%s)",
            (
                "UPDATE referral.dispatch SET "
                "state='reconciliation_needed',fence=fence+1,revision=revision+1 WHERE "
                "state IN ('pending','authorized','attempted','unknown','partial')"
            ),
            (
                "UPDATE care.follow_up SET "
                "state='reconciliation_needed',fence=fence+1,revision=revision+1 WHERE "
                "state IN ('anchor_pending','scheduled','claimed','authorized','unknown')"
            ),
            (
                "UPDATE assistance.inference_job SET "
                "state='fenced',fence=fence+1,revision=revision+1 WHERE state IN "
                "('running','compute_unknown')"
            ),
            "UPDATE assistance.compute_slot SET state='compute_unknown' WHERE state='occupied'",
        )
        for statement in statements:
            connection.execute(statement, (now,) if "%s" in statement else ())
        suspend_assistance(connection, now, self.content_cipher)
        # Optional reviewer recovery namespace may be absent from older backups.
        optional = connection.execute("SELECT to_regclass('core.review_intent') AS name").fetchone()
        if optional is not None and optional["name"] is not None:
            connection.execute(
                (
                    "UPDATE core.review_intent SET cancelled_at=GREATEST(created_at,%s) "
                    "WHERE cancelled_at IS NULL"
                ),
                (now,),
            )
            connection.execute(
                "UPDATE core.review_draft SET expires_at=LEAST(expires_at,%s)", (now,)
            )
