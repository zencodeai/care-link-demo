"""Append/verify a local chain continuing from its minimal pruned-prefix checkpoint."""

import hashlib
import sqlite3

from .model import Decision, HelpError, canonical


def _tail(connection: sqlite3.Connection) -> tuple[int, str]:
    previous = connection.execute(
        "SELECT sequence,hash FROM local_event ORDER BY sequence DESC LIMIT 1"
    ).fetchone()
    if previous is not None:
        return previous["sequence"], previous["hash"]
    checkpoint = connection.execute(
        "SELECT last_deleted_sequence,last_deleted_hash FROM "
        "help_audit_checkpoint WHERE singleton=1"
    ).fetchone()
    if checkpoint is None:
        raise HelpError("help.audit_checkpoint_missing", 503)
    return checkpoint["last_deleted_sequence"], checkpoint["last_deleted_hash"]


def verify_history(connection: sqlite3.Connection) -> None:
    checkpoint = connection.execute(
        "SELECT last_deleted_sequence,last_deleted_hash FROM "
        "help_audit_checkpoint WHERE singleton=1"
    ).fetchone()
    if checkpoint is None:
        raise HelpError("help.audit_checkpoint_missing", 503)
    sequence, previous = checkpoint["last_deleted_sequence"], checkpoint["last_deleted_hash"]
    if (
        type(sequence) is not int
        or sequence < 0
        or len(previous) != 64
        or any(char not in "0123456789abcdef" for char in previous)
    ):
        raise HelpError("help.audit_checkpoint_invalid", 503)
    for row in connection.execute("SELECT * FROM local_event ORDER BY sequence").fetchall():
        event = {
            "sequence": row["sequence"],
            "previous_hash": row["previous_hash"],
            "action": row["action"],
            "reference": row["reference"],
            "time": row["time"],
            "authority_evidence_digest": row["authority_evidence_digest"],
        }
        if (
            row["sequence"] != sequence + 1
            or row["previous_hash"] != previous
            or hashlib.sha256(canonical(event)).hexdigest() != row["hash"]
        ):
            raise HelpError("help.audit_chain_invalid", 503)
        sequence, previous = row["sequence"], row["hash"]


def append_event(
    connection: sqlite3.Connection, action: str, help_id: str, at: str, decision: Decision
) -> None:
    # Checkpoint anchors retain no account/request reference. They acknowledge
    # only the removed prefix position, never reconstruct deleted history.
    verify_history(connection)
    previous_sequence, previous_hash = _tail(connection)
    sequence = previous_sequence + 1
    event = {
        "sequence": sequence,
        "previous_hash": previous_hash,
        "action": action,
        "reference": help_id,
        "time": at,
        "authority_evidence_digest": decision.evidence_digest,
    }
    event_hash = hashlib.sha256(canonical(event)).hexdigest()
    connection.execute(
        "INSERT INTO local_event VALUES (?,?,?,?,?,?,?)",
        (sequence, previous_hash, event_hash, action, help_id, at, decision.evidence_digest),
    )
