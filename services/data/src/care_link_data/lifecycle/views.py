"""Closed actor-facing lifecycle projections."""

from ..store import Record, instant, number
from ..values import stamp


def followup_view(row: Record) -> Record:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "revision": str(number(row, "revision")),
        "state": row["state"],
        "due_at": stamp(instant(row, "due_at")) if row["due_at"] else None,
        "inbox_message_id": row["inbox_message_id"],
    }


def rights_view(row: Record) -> Record:
    return {
        "id": row["id"],
        "revision": str(number(row, "revision")),
        "kind": row["kind"],
        "state": row["state"],
        "exceptions": row["exceptions"],
        "download_id": row["download_id"],
        "deadline": stamp(instant(row, "deadline")),
    }


def outcome_view(row: Record) -> Record:
    return {
        "id": row["id"],
        "revision": str(number(row, "revision")),
        "session_id": row["session_id"],
        "state": row["state"],
        "carer_support": row["carer_support"],
        "observed_at": stamp(instant(row, "observed_at")),
    }
