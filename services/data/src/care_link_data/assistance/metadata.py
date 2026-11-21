"""Identifier-only scope lookup for signed gateway metadata preflight."""

from care_link_domain import Actor, ManualError

from ..engine import Engine
from ..store import Record, text
from ..values import object_value


def metadata_scope(engine: Engine, actor: Actor, action: str, arguments: Record) -> str | None:
    if action == "assistance_status":
        return None
    if action == "task_create":
        binding = object_value(arguments["binding"])
        if binding["kind"] != "session":
            raise ManualError("assistance.binding_unavailable", 409)
        return text(binding, "session_id")
    kind = "task" if action.startswith("task_") or action == "assistance_task_context" else "draft"
    identifier = text(arguments, kind + "_id")
    with engine.store.transaction(actor, None, locked=False) as tx:
        row = tx.connection.execute(
            "SELECT session_id FROM assistance.locator WHERE kind=%s AND id=%s",
            (kind, identifier),
        ).fetchone()
        if row is None:
            raise ManualError("assistance.not_found", 404)
        return str(row["session_id"])
