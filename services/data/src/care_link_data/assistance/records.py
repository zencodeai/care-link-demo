"""Fixed PostgreSQL repositories; no caller controls a SQL identifier."""

import json
from typing import Literal, cast

from care_link_domain import CipherPort, ManualError
from psycopg import sql
from psycopg.types.json import Jsonb

from ..store import Record, Transaction
from ..values import object_value

Kind = Literal["task", "draft", "invocation", "operation"]


def read(
    tx: Transaction, kind: Kind, identifier: str, cipher: CipherPort, *, lock: bool = True
) -> Record:
    row = tx.connection.execute(
        sql.SQL("SELECT body FROM assistance.{} WHERE id=%s{}").format(
            sql.Identifier(kind), sql.SQL(" FOR UPDATE") if lock else sql.SQL("")
        ),
        (identifier,),
    ).fetchone()
    if row is None:
        raise ManualError("assistance.not_found", 404)
    return cast(
        Record, json.loads(cipher.decrypt(cast(str, object_value(row["body"])["ciphertext"])))
    )


def save(
    tx: Transaction, kind: Kind, value: Record, principal: str, session: str, cipher: CipherPort
) -> None:
    if kind not in {"task", "draft", "invocation"}:
        raise ValueError("Invalid mutable repository")
    columns: Record = {"id": value["id"], "principal_id": principal, "session_id": session}
    if kind != "task":
        columns["task_id"] = value["task_id"]
    if kind == "invocation":
        columns["request_digest"] = value["request_digest"]
    columns["body"] = Jsonb({"ciphertext": cipher.encrypt(json.dumps(value, sort_keys=True))})
    tx.connection.execute(
        sql.SQL("INSERT INTO assistance.{} ({}) VALUES ({}) {}").format(
            sql.Identifier(kind),
            sql.SQL(",").join(map(sql.Identifier, columns)),
            sql.SQL(",").join(sql.Placeholder() for _ in columns),
            sql.SQL("ON CONFLICT(id) DO UPDATE SET body=EXCLUDED.body")
            if kind in {"task", "draft"}
            else sql.SQL(""),
        ),
        tuple(columns.values()),
    )

    if kind in {"task", "draft"}:
        tx.connection.execute(
            "INSERT INTO assistance.locator VALUES(%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",
            (value["id"], kind, principal, session),
        )
