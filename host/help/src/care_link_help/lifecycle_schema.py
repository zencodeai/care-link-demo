"""Additive lifecycle anchors. Existing rows get no invented event timestamps."""

import hashlib
import sqlite3
from datetime import datetime

from .model import Decision, HelpError, timestamp

LIFECYCLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS request_lifecycle (
 help_id TEXT PRIMARY KEY REFERENCES request(id) ON DELETE CASCADE,
 created_at TEXT NOT NULL, cancelled_at TEXT,
 active_reviewed_at TEXT, active_review_due_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS operation_lifecycle (
 operation_id TEXT PRIMARY KEY REFERENCES operation(id) ON DELETE CASCADE,
 event_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS intent_lifecycle (
 operation_id TEXT PRIMARY KEY, help_id TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS nonce_lifecycle (
 nonce TEXT PRIMARY KEY REFERENCES decision_nonce(nonce) ON DELETE CASCADE,
 accepted_at TEXT NOT NULL, authority_expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS help_dependency_review (
 help_id TEXT PRIMARY KEY, reviewed_at TEXT NOT NULL, review_due_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS help_retention_hold (
 id TEXT PRIMARY KEY, help_id TEXT NOT NULL, owner TEXT NOT NULL CHECK(owner='main'),
 reason TEXT NOT NULL, review_date TEXT NOT NULL, released_at TEXT
);
CREATE TABLE IF NOT EXISTS retired_help_key (
 key_digest TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('operation','help')),
 retired_at TEXT NOT NULL, owner TEXT NOT NULL CHECK(owner='main'),
 reason TEXT NOT NULL, review_date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS help_audit_checkpoint (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 last_deleted_sequence INTEGER NOT NULL CHECK(last_deleted_sequence>=0),
 last_deleted_hash TEXT NOT NULL, pruned_at TEXT
);
INSERT OR IGNORE INTO help_audit_checkpoint VALUES (1,0,
 '0000000000000000000000000000000000000000000000000000000000000000',NULL);
CREATE TABLE IF NOT EXISTS help_managed_copy_cleanup (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 state TEXT NOT NULL CHECK(state IN ('not_run','pending','pending_busy_or_reader',
 'pending_error','complete')), checked_at TEXT
);
INSERT OR IGNORE INTO help_managed_copy_cleanup VALUES (1,'not_run',NULL);
"""


def key_digest(kind: str, value: str) -> str:
    return hashlib.sha256((kind + "\0" + value).encode()).hexdigest()


def deny_retired(connection: sqlite3.Connection, kind: str, value: str) -> None:
    row = connection.execute(
        "SELECT 1 FROM retired_help_key WHERE key_digest=?", (key_digest(kind, value),)
    ).fetchone()
    if row is not None:
        raise HelpError("help.operation_retired", 410)


def anchor_nonce(connection: sqlite3.Connection, decision: Decision, now: datetime) -> None:
    connection.execute(
        "INSERT INTO nonce_lifecycle VALUES (?,?,?)",
        (decision.nonce, timestamp(now), timestamp(decision.expires_at)),
    )


def anchor_request(connection: sqlite3.Connection, help_id: str, now: datetime) -> None:
    from datetime import timedelta

    connection.execute(
        "INSERT INTO request_lifecycle VALUES (?,?,NULL,NULL,?)",
        (help_id, timestamp(now), timestamp(now + timedelta(days=30))),
    )


def anchor_operation(connection: sqlite3.Connection, operation_id: str, now: datetime) -> None:
    connection.execute(
        "INSERT INTO operation_lifecycle VALUES (?,?)", (operation_id, timestamp(now))
    )


def anchor_intent(
    connection: sqlite3.Connection, operation_id: str, help_id: str, now: datetime
) -> None:
    connection.execute(
        "INSERT INTO intent_lifecycle VALUES (?,?,?)", (operation_id, help_id, timestamp(now))
    )
