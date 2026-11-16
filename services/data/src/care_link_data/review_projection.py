"""Explicit recovery views; encrypted rows and operator metadata remain private."""

import json
from datetime import datetime, timedelta

from care_link_domain import Actor, CipherPort, ManualError

from .store import Record, Transaction, instant, number, text
from .values import object_value, stamp


def draft_view(row: Record, cipher: CipherPort, *, expose_text: bool = True) -> Record:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "kind": row["kind"],
        "revision": str(number(row, "revision")),
        "text": cipher.decrypt(text(row, "text_ciphertext")) if expose_text else "",
        "expires_at": stamp(instant(row, "expires_at")),
    }


def intent_view(
    tx: Transaction,
    row: Record,
    actor: Actor,
    cipher: CipherPort,
    now: datetime,
    *,
    expose_payload: bool = True,
) -> Record:
    if row["principal_id"] != actor.account_id:
        raise ManualError("manual.not_found", 404)
    operation = tx.peek("operation", text(row, "operation_id"))
    state = (
        "cancelled"
        if row.get("cancelled_at") is not None
        else operation["state"]
        if operation
        else "prepared"
    )
    payload = None
    if (
        expose_payload
        and state != "cancelled"
        and instant(row, "created_at") + timedelta(days=1) > now
    ):
        payload = object_value(json.loads(cipher.decrypt(text(row, "payload_ciphertext"))))
    return {
        "operation_id": row["operation_id"],
        "session_id": row["session_id"],
        "kind": row["kind"],
        "draft_revision": str(number(row, "draft_revision")),
        "state": state,
        "action": row["action"],
        "payload": payload,
        "created_at": stamp(instant(row, "created_at")),
    }
