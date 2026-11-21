"""Invalidate restored AI leases/proposals/reviews in their durable JSON state."""

import json
from datetime import datetime
from typing import cast

import psycopg
from care_link_domain import CipherPort, ManualError
from psycopg.types.json import Jsonb

from ..values import integer, stamp

Record = dict[str, object]


def _read(row: Record, cipher: CipherPort | None) -> Record | None:
    if row["purged"]:
        return None
    envelope = row["body"]
    if not isinstance(envelope, dict):
        raise ManualError("recovery.assistance_body_invalid", 409)
    ciphertext = cast(Record, envelope).get("ciphertext")
    if not isinstance(ciphertext, str):
        raise ManualError("recovery.assistance_body_invalid", 409)
    if cipher is None:
        raise ManualError("recovery.content_key_required", 503)
    value = json.loads(cipher.decrypt(ciphertext))
    if not isinstance(value, dict):
        raise ManualError("recovery.assistance_body_invalid", 409)
    return dict(cast(Record, value))


def _write(body: Record, cipher: CipherPort | None) -> Jsonb:
    if cipher is None:
        raise ManualError("recovery.content_key_required", 503)
    return Jsonb({"ciphertext": cipher.encrypt(json.dumps(body, sort_keys=True))})


def suspend_assistance(
    connection: psycopg.Connection[Record], now: datetime, cipher: CipherPort | None
) -> None:
    for row in connection.execute("SELECT id,body FROM assistance.task FOR UPDATE").fetchall():
        row["purged"] = (
            connection.execute(
                "SELECT 1 FROM lifecycle.copy WHERE aggregate_id=%s AND state='purged' LIMIT 1",
                (row["id"],),
            ).fetchone()
            is not None
        )
        body = _read(row, cipher)
        if body is None:
            continue
        if body.get("state") != "cancelled" or any(
            body.get(key) is not None for key in ("lease", "proposal_reservation", "draft_id")
        ):
            body.update(
                state="cancelled",
                fence=integer(integer(body.get("fence")) + 1),
                revision=str(integer(integer(body.get("revision")) + 1)),
                lease=None,
                proposal_reservation=None,
                draft_id=None,
                safe_reason="assistance.restored_authority_fenced",
            )
            connection.execute(
                "UPDATE assistance.task SET body=%s WHERE id=%s", (_write(body, cipher), row["id"])
            )
    for row in connection.execute("SELECT id,body FROM assistance.draft FOR UPDATE").fetchall():
        row["purged"] = (
            connection.execute(
                "SELECT 1 FROM lifecycle.copy WHERE aggregate_id=%s AND state='purged' LIMIT 1",
                (row["id"],),
            ).fetchone()
            is not None
        )
        body = _read(row, cipher)
        if body is None:
            continue
        if body.get("state") != "stale" or body.get("review") is not None:
            body.update(
                state="stale",
                revision=str(integer(integer(body.get("revision")) + 1)),
                review=None,
                expires_at=stamp(now),
            )
            connection.execute(
                "UPDATE assistance.draft SET body=%s WHERE id=%s", (_write(body, cipher), row["id"])
            )
