"""Durable create-intent registry; a lost browser response cannot mint duplicates."""

import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from uuid import UUID, uuid4, uuid5

from .audit import append_event
from .lifecycle_schema import anchor_intent, anchor_nonce, deny_retired
from .model import BrowserContext, Clock, Decision, HelpError, timestamp

INTENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS create_intent (
 owner_account TEXT PRIMARY KEY, operation_id TEXT UNIQUE NOT NULL,
 help_id TEXT UNIQUE NOT NULL, body_digest TEXT NOT NULL,
 authority_evidence_digest TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class CreateIntent:
    operation_id: str
    help_id: str


def _current(connection: sqlite3.Connection, owner: str) -> sqlite3.Row | None:
    row = connection.execute(
        "SELECT i.*,r.status FROM create_intent i LEFT JOIN request r ON r.id=i.help_id "
        "WHERE i.owner_account=?",
        (owner,),
    ).fetchone()
    return None if row is not None and row["status"] == "cancelled" else row


class CreateIntents:
    def __init__(
        self,
        connect: Callable[[], sqlite3.Connection],
        restrict_files: Callable[[], None],
        clock: Clock,
    ) -> None:
        self.connect, self.restrict_files, self.clock = connect, restrict_files, clock

    def candidate(self, owner: str) -> CreateIntent:
        try:
            with closing(self.connect()) as connection:
                row = _current(connection, owner)
                if row is not None:
                    return CreateIntent(row["operation_id"], row["help_id"])
        except sqlite3.Error as error:
            raise HelpError("help.spool_unavailable", 503) from error
        operation_id = str(uuid4())
        return CreateIntent(operation_id, str(uuid5(UUID(operation_id), "care-link-help")))

    def save(
        self, candidate: CreateIntent, body_digest: str, context: BrowserContext, decision: Decision
    ) -> str:
        if context.account_id != decision.principal_id or context.role not in {
            "pid",
            "carer",
            "professional_participant",
        }:
            raise HelpError("help.role_denied")
        with closing(self.connect()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                if not self.clock() < decision.expires_at:
                    raise HelpError("help.authority_expired")
                row = _current(connection, context.account_id)
                if row is None:
                    old = connection.execute(
                        "SELECT operation_id FROM create_intent WHERE owner_account=?",
                        (context.account_id,),
                    ).fetchone()
                    if old is not None and old["operation_id"] == candidate.operation_id:
                        raise HelpError("help.intent_race", 409)
                if row is not None:
                    if row["operation_id"] != candidate.operation_id:
                        # The losing caller must acquire fresh authority for the
                        # winner's exact target before returning that private key.
                        raise HelpError("help.intent_race", 409)
                    if row["body_digest"] != body_digest:
                        raise HelpError("help.intent_body_conflict", 409)
                deny_retired(connection, "operation", candidate.operation_id)
                deny_retired(connection, "help", candidate.help_id)
                connection.execute("INSERT INTO decision_nonce VALUES (?)", (decision.nonce,))
                anchor_nonce(connection, decision, self.clock())
                if row is None:
                    connection.execute(
                        "INSERT INTO create_intent VALUES (?,?,?,?,?) "
                        "ON CONFLICT(owner_account) DO UPDATE SET "
                        "operation_id=excluded.operation_id,help_id=excluded.help_id,"
                        "body_digest=excluded.body_digest,"
                        "authority_evidence_digest=excluded.authority_evidence_digest",
                        (
                            context.account_id,
                            candidate.operation_id,
                            candidate.help_id,
                            body_digest,
                            decision.evidence_digest,
                        ),
                    )
                    anchor_intent(
                        connection, candidate.operation_id, candidate.help_id, self.clock()
                    )
                append_event(
                    connection,
                    "create_intent",
                    candidate.help_id,
                    timestamp(self.clock()),
                    decision,
                )
                if not self.clock() < decision.expires_at:
                    raise HelpError("help.authority_expired")
                connection.commit()
                return candidate.operation_id
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
                self.restrict_files()
