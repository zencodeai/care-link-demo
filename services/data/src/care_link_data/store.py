"""PostgreSQL adapter. Only this deployable receives business credentials.

The application sees named bounded repositories; identifiers are fixed here and
never come from HTTP. Runtime never creates schemas, guards or account grants.
"""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

import psycopg
from care_link_domain import Actor, JournalState, ManualError
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

Record = dict[str, object]
ConnectionFactory = Callable[[str], AbstractContextManager[psycopg.Connection[Record]]]


class StorageActor(Protocol):
    @property
    def account_id(self) -> str: ...


# Fixed repository mapping. DTO JSON columns are content/state values, never a
# caller-supplied operation name or SQL expression.
TABLES: dict[str, tuple[str, tuple[str, ...]]] = {
    "gov_human": ("governance.human_registry", ("account_id",)),
    "gov_approval": ("governance.approval", ("id",)),
    "gov_candidate": ("governance.candidate", ("digest",)),
    "gov_signer": ("governance.signer", ("id",)),
    "gov_instance": ("governance.instance", ("instance_id",)),
    "gov_exception_rule": ("governance.exception_rule", ("policy_rule_id",)),
    "gov_artifact": ("governance.artifact", ("digest",)),
    "gov_review": ("governance.review", ("id",)),
    "gov_activation": ("governance.activation", ("id",)),
    "gov_ack": ("governance.ack", ("id",)),
    "gov_exception": ("governance.exception", ("id",)),
    "gov_incident": ("governance.incident", ("id",)),
    "gov_scope_grant": ("access.audit_grant", ("id",)),
    "gov_audit_export": ("audit.export_request", ("id",)),
    "gov_metric_release": ("quality.metric_release", ("id",)),
    "post_crisis": ("care.post_crisis_event", ("id",)),
    "followup": ("care.follow_up", ("id",)),
    "inbox": ("care.inbox_message", ("id",)),
    "outcome": ("care.outcome", ("id",)),
    "hold": ("lifecycle.hold", ("id",)),
    "rights": ("rights.request", ("id",)),
    "control": ("control.guard", ("key",)),
    "principal": ("control.principal_guard", ("principal_id",)),
    "persona": ("core.persona", ("id",)),
    "subject": ("core.subject_guard", ("subject_id",)),
    "session": ("core.session", ("id",)),
    "guard": ("core.session_guard", ("session_id",)),
    "acl": ("core.session_acl", ("session_id", "principal_id", "purpose")),
    "turn": ("core.turn", ("id",)),
    "assertion": ("core.assertion", ("id",)),
    "assessment": ("core.assessment", ("id",)),
    "message": ("core.message", ("id",)),
    "choice": ("core.choice", ("id",)),
    "queue": ("workforce.queue_entry", ("id",)),
    "assignment": ("workforce.assignment", ("id",)),
    "challenge": ("workforce.channel_challenge", ("id",)),
    "ack": ("workforce.channel_ack", ("id",)),
    "operation": ("durable.operation", ("operation_id",)),
    "event": ("durable.event", ("session_id", "sequence")),
    "family": ("access.continuation_family", ("id",)),
    "token": ("access.continuation_token", ("family_id", "generation")),
    "recovery": ("recovery.command", ("command_id",)),
    "audit_head": ("audit.head", ("stream_id",)),
    "copy": ("lifecycle.copy", ("copy_id",)),
    "dependency": ("lifecycle.dependency", ("parent_copy_id", "child_copy_id")),
    "review_run": ("core.review_run", ("id",)),
    "review_member": ("core.review_member", ("session_id",)),
    "review_draft": ("core.review_draft", ("id",)),
    "review_intent": ("core.review_intent", ("operation_id",)),
    "plan": ("plans.plan", ("id",)),
    "plan_field": ("plans.field", ("id",)),
    "plan_review": ("plans.review_work", ("id",)),
    "consent": ("consent.current_grant", ("grant_id",)),
    "consent_event": ("consent.event", ("id",)),
    "delegation": ("consent.delegation", ("id",)),
    "directory": ("knowledge.service_version", ("id",)),
    "service_guard": ("knowledge.service_guard", ("service_id",)),
    "referral": ("referral.generation", ("id",)),
    "referral_review": ("referral.review", ("id",)),
    "dispatch": ("referral.dispatch", ("id",)),
    "authorization": ("referral.authorization", ("id",)),
    "dispatch_observation": ("referral.observation", ("id",)),
    "dispatch_attempt": ("referral.attempt", ("id",)),
    "directory_quarantine": ("knowledge.quarantine", ("id",)),
}
JSON_COLUMNS = {
    "metadata",
    "manifest",
    "request",
    "query",
    "cells",
    "selected",
    "source_vector",
    "receipt",
    "field_states",
    "versions",
    "source",
    "scope",
    "recipient",
    "facts",
    "sources",
}
APPEND_ONLY = frozenset(
    {
        "gov_review",
        "gov_exception",
        "post_crisis",
        "outcome",
        "referral_review",
        "dispatch_observation",
        "dispatch_attempt",
        "plan_field",
        "consent_event",
        "directory",
        "directory_quarantine",
    }
)
GOV_CUSTODY = frozenset(
    {
        "gov_human",
        "gov_approval",
        "gov_candidate",
        "gov_signer",
        "gov_instance",
        "gov_exception_rule",
        "gov_metric_release",
    }
)
READ_ONLY = APPEND_ONLY | {"delegation"} | GOV_CUSTODY


def _record(value: Record) -> Record:
    return {key: str(item) if isinstance(item, UUID) else item for key, item in value.items()}


class Transaction:
    def __init__(self, connection: psycopg.Connection[Record], *, locked: bool) -> None:
        self.connection = connection
        self.locked = locked

    def scope(self, session_id: str | None, *, queue: bool = False) -> None:
        self.connection.execute(
            "SELECT set_config('care_link.session',%s,true),set_config('care_link.queue',%s,true)",
            (session_id or "", "true" if queue else "false"),
        )

    def rows(self, repository: str, *, limit: int = 100, **where: object) -> list[Record]:
        if not 1 <= limit <= 100:
            raise ValueError("Bounded repository query required")
        table, _keys = TABLES[repository]
        conditions = sql.SQL(" AND ").join(
            sql.SQL("{} IS NOT DISTINCT FROM %s").format(sql.Identifier(column)) for column in where
        )
        query = sql.SQL("SELECT * FROM {}{} ORDER BY {} LIMIT %s{}").format(
            sql.Identifier(*table.split(".")),
            sql.SQL(" WHERE ") + conditions if where else sql.SQL(""),
            sql.SQL(",").join(sql.Identifier(key) for key in TABLES[repository][1]),
            sql.SQL(" FOR UPDATE") if self.locked and repository not in READ_ONLY else sql.SQL(""),
        )
        return [_record(row) for row in self.connection.execute(query, (*where.values(), limit))]

    def peek(self, repository: str, key: str) -> Record | None:
        locked = self.locked
        try:
            self.locked = False
            return self.get(repository, key)
        finally:
            self.locked = locked

    def get(self, repository: str, key: str) -> Record | None:
        table, keys = TABLES[repository]
        if len(keys) != 1:
            raise ValueError("Composite repository requires named filters")
        del table
        rows = self.rows(repository, limit=1, **{keys[0]: key})
        return rows[0] if rows else None

    def put(self, repository: str, record: Record) -> None:
        table, keys = TABLES[repository]
        columns = tuple(record)
        nonkeys = [column for column in columns if column not in keys]
        if repository in READ_ONLY:
            if repository == "delegation" or repository in GOV_CUSTODY:
                raise ValueError("Delegations require separate provisioning custody")
            self.connection.execute(
                sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                    sql.Identifier(*table.split(".")),
                    sql.SQL(",").join(map(sql.Identifier, columns)),
                    sql.SQL(",").join(sql.Placeholder() for _ in columns),
                ),
                tuple(
                    Jsonb(value) if key in JSON_COLUMNS else value for key, value in record.items()
                ),
            )
            return
        if repository in {"control", "principal"}:
            # Runtime may update preprovisioned authority guards, never insert or
            # recreate one. PostgreSQL UPSERT requires INSERT even on conflict.
            query = sql.SQL("UPDATE {} SET {} WHERE {}").format(
                sql.Identifier(*table.split(".")),
                sql.SQL(",").join(
                    sql.SQL("{}=%s").format(sql.Identifier(column)) for column in nonkeys
                ),
                sql.SQL(" AND ").join(
                    sql.SQL("{}=%s").format(sql.Identifier(column)) for column in keys
                ),
            )
            result = self.connection.execute(
                query, tuple(record[column] for column in [*nonkeys, *keys])
            )
            if result.rowcount != 1:
                raise ManualError("manual.authority_guard_missing", 503)
            return
        query = sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) DO UPDATE SET {}").format(
            sql.Identifier(*table.split(".")),
            sql.SQL(",").join(map(sql.Identifier, columns)),
            sql.SQL(",").join(sql.Placeholder() for _ in columns),
            sql.SQL(",").join(map(sql.Identifier, keys)),
            sql.SQL(",").join(
                sql.SQL("{}=EXCLUDED.{}").format(sql.Identifier(column), sql.Identifier(column))
                for column in nonkeys
            ),
        )
        values = tuple(
            Jsonb(value) if key in JSON_COLUMNS else value for key, value in record.items()
        )
        self.connection.execute(query, values)

    def message_page(
        self, session_id: str, position: tuple[datetime, str] | None, limit: int
    ) -> list[Record]:
        if not 1 <= limit <= 51:
            raise ValueError("Invalid message page size")
        after_time, after_id = (
            position
            if position
            else (datetime.min.replace(tzinfo=UTC), "00000000-0000-0000-0000-000000000000")
        )
        rows = self.connection.execute(
            "SELECT * FROM core.message WHERE session_id=%s AND (created_at,id)>(%s,%s) "
            "ORDER BY created_at,id LIMIT %s",
            (session_id, after_time, after_id, limit),
        ).fetchall()
        return [_record(row) for row in rows]

    def queue_page(
        self,
        position: tuple[int, datetime, str] | None,
        limit: int,
        *,
        review_run_id: str | None = None,
    ) -> list[Record]:
        if not 1 <= limit <= 51:
            raise ValueError("Invalid queue page size")
        priority, after_time, after_id = (
            position
            if position
            else (-1, datetime.min.replace(tzinfo=UTC), "00000000-0000-0000-0000-000000000000")
        )
        if self.review_available():
            rows = self.connection.execute(
                "SELECT q.* FROM workforce.queue_entry q LEFT JOIN core.review_member m "
                "ON m.session_id=q.session_id WHERE q.status IN ('pending','reserved','accepted') "
                "AND ((%s::uuid IS NULL AND m.session_id IS NULL) OR m.run_id=%s::uuid) "
                "AND (q.fixture_priority,q.requested_at,q.id)>(%s,%s,%s) "
                "ORDER BY q.fixture_priority,q.requested_at,q.id LIMIT %s",
                (review_run_id, review_run_id, priority, after_time, after_id, limit),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM workforce.queue_entry "
                "WHERE status IN ('pending','reserved','accepted') "
                "AND (fixture_priority,requested_at,id)>(%s,%s,%s) "
                "ORDER BY fixture_priority,requested_at,id LIMIT %s",
                (priority, after_time, after_id, limit),
            ).fetchall()
        return [_record(row) for row in rows]

    def review_available(self) -> bool:
        row = self.connection.execute("SELECT to_regclass('core.review_run') AS name").fetchone()
        return row is not None and row["name"] is not None

    def directory_page(self, after: str | None, limit: int) -> list[Record]:
        if not 1 <= limit <= 51:
            raise ValueError("Invalid directory page size")
        rows = self.connection.execute(
            "SELECT * FROM knowledge.service_guard WHERE service_id>%s::uuid "
            "ORDER BY service_id LIMIT %s",
            (after or "00000000-0000-0000-0000-000000000000", limit),
        ).fetchall()
        return [_record(row) for row in rows]

    def review_sessions(self, run_id: str | None) -> list[Record]:
        rows = self.connection.execute(
            "SELECT s.* FROM core.session s LEFT JOIN core.review_member m ON m.session_id=s.id "
            "WHERE ((%s::uuid IS NULL AND m.session_id IS NULL) OR m.run_id=%s::uuid) "
            "ORDER BY s.updated_at DESC,s.id DESC LIMIT 50",
            (run_id, run_id),
        ).fetchall()
        return [_record(row) for row in rows]

    def review_recovery_intents(self, principal_id: str, run_id: str | None) -> list[Record]:
        rows = self.connection.execute(
            "SELECT i.* FROM core.review_intent i LEFT JOIN core.review_member m "
            "ON m.session_id=i.session_id WHERE i.principal_id=%s "
            "AND ((%s::uuid IS NULL AND m.session_id IS NULL) OR m.run_id=%s::uuid) "
            "ORDER BY i.created_at DESC,i.operation_id DESC LIMIT 10",
            (principal_id, run_id, run_id),
        ).fetchall()
        return [_record(row) for row in rows]

    def review_has_unresolved_intent(self, principal_id: str, session_id: str, kind: str) -> bool:
        return (
            self.connection.execute(
                "SELECT 1 FROM core.review_intent i WHERE i.principal_id=%s AND i.session_id=%s "
                "AND i.kind=%s AND i.cancelled_at IS NULL AND NOT EXISTS "
                "(SELECT 1 FROM durable.operation o WHERE o.operation_id=i.operation_id) LIMIT 1",
                (principal_id, session_id, kind),
            ).fetchone()
            is not None
        )

    def review_records(self, repository: str, *, limit: int = 100, **where: object) -> list[Record]:
        # Global control guard serializes these append-only projections; no row
        # update grant is needed merely to inspect an intent or membership.
        locked = self.locked
        try:
            self.locked = False
            return self.rows(repository, limit=limit, **where)
        finally:
            self.locked = locked

    def events_after(self, session_id: str, sequence: int) -> list[Record]:
        rows = self.connection.execute(
            "SELECT * FROM durable.event WHERE session_id=%s AND sequence>%s "
            "ORDER BY sequence LIMIT 33",
            (session_id, sequence),
        ).fetchall()
        return [_record(row) for row in rows]

    def close_copies(self, session_id: str, anchor: datetime) -> None:
        self.connection.execute(
            "UPDATE lifecycle.copy SET anchor_at=%s,"
            "expires_at=%s+interval '7 days',state='retained' "
            "WHERE session_id=%s AND state='anchor_pending' AND purpose IN ('support','follow_up')",
            (anchor, anchor, session_id),
        )

    def audit_append(self, event: Record) -> None:
        self.connection.execute(
            "SELECT audit.append_event(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                event["event_id"],
                event["operation_id"],
                event["principal_id"],
                event["action"],
                event["decision"],
                event["input_digest"],
                event["output_digest"],
                Jsonb(event["versions"]),
                event["created_at"],
                event["previous_hash"],
                event["hash"],
            ),
        )


class PostgresStore:
    """Connections are scoped per transaction, never shared across requests."""

    def __init__(self, dsn: str, *, connection_factory: ConnectionFactory | None = None) -> None:
        settings = conninfo_to_dict(dsn)
        if settings.get("sslmode") != "verify-full" or not settings.get("sslrootcert"):
            raise ValueError("Business PostgreSQL requires pinned CA and verify-full TLS")
        self._dsn = dsn
        self._connection_factory = connection_factory

    @contextmanager
    def transaction(
        self,
        actor: StorageActor,
        session_id: str | None,
        *,
        locked: bool = True,
        queue: bool = False,
    ) -> Iterator[Transaction]:
        try:
            manager = (
                self._connection_factory(self._dsn)
                if self._connection_factory is not None
                else psycopg.Connection[Record].connect(
                    self._dsn, connect_timeout=1, row_factory=dict_row
                )
            )
            with manager as connection:
                connection.execute("SET LOCAL lock_timeout='900ms'")
                connection.execute("SET LOCAL statement_timeout='900ms'")
                connection.execute(
                    "SELECT set_config('care_link.principal',%s,true), "
                    "set_config('care_link.review_run',%s,true)",
                    (actor.account_id, getattr(actor, "review_run_id", None) or ""),
                )
                tx = Transaction(connection, locked=locked)
                tx.scope(session_id, queue=queue)
                yield tx
        except psycopg.Error as error:
            # Do not expose driver messages/credentials/SQL. A lost commit ACK is
            # indistinguishable here; clients reconcile the existing operation.
            raise ManualError("manual.commit_unknown", 503) from error

    def bootstrap(
        self, head: JournalState, bundle_digest: str, *, mode: str = "ai_disabled"
    ) -> None:
        """Offline migrator-only bootstrap; absent from every service transport."""
        if mode != "ai_disabled":
            raise ValueError("Initial manual service starts AI-disabled")
        with psycopg.connect(self._dsn) as connection:
            connection.execute(
                "INSERT INTO control.guard VALUES('demo',1,%s,%s,%s,%s,%s,%s,%s)",
                (
                    bundle_digest,
                    head.serving_generation,
                    mode,
                    head.restriction_barrier,
                    head.tip,
                    head.journal_id,
                    head.generation,
                ),
            )

    def provision_principal(self, actor: Actor) -> None:
        """Offline migrator-only exact local role binding, no claim-derived role."""
        with psycopg.connect(self._dsn) as connection:
            connection.execute(
                "INSERT INTO control.principal_guard "
                "(principal_id,identity_revision,role_revision,role) "
                "VALUES(%s,%s,%s,%s)",
                (actor.account_id, actor.identity_revision, actor.role_revision, actor.role),
            )


def text(record: Record, key: str) -> str:
    value = record[key]
    if not isinstance(value, str):
        raise ManualError("manual.corrupt_state", 503)
    return value


def number(record: Record, key: str) -> int:
    value = record[key]
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 <= value <= 9223372036854775807
    ):
        raise ManualError("manual.corrupt_state", 503)
    return value


def instant(record: Record, key: str) -> datetime:
    value = record[key]
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ManualError("manual.corrupt_state", 503)
    return value
