"""Final lifecycle disclosure reauthorization after materialization and canonical audit."""

from typing import cast

from care_link_domain import Actor, ManualError

from ..engine import Engine
from ..store import Record, Transaction, instant, text


def check_lifecycle_output(
    service: Engine, tx: Transaction, actor: Actor, action: str, result: Record
) -> None:
    current = service.current_actor(actor)
    if action == "export_download":
        rows = tx.rows(
            "rights", download_id=result["export_id"], requester_id=current.account_id, limit=2
        )
        if len(rows) != 1:
            raise ManualError("manual.export_unavailable", 404)
        row = rows[0]
        subject = tx.get("subject", text(row, "subject_id"))
        if (
            subject is None
            or subject["delete_state"] != "active"
            or instant(row, "export_expires_at") <= service.clock()
        ):
            raise ManualError("manual.export_unavailable", 404)
        service.authority.rights_download_proof(
            current, text(row, "ceremony_id"), text(row, "subject_id")
        )
    elif action in {"participant_inbox", "inbox_message_read"}:
        items = cast(list[Record], result["items"]) if action == "participant_inbox" else [result]
        for item in items:
            row = tx.peek("inbox", text(item, "id"))
            if (
                row is None
                or row["recipient_account_id"] != current.account_id
                or instant(row, "expires_at") <= service.clock()
            ):
                raise ManualError("manual.inbox_unavailable", 404)
            subject = tx.peek("subject", text(row, "subject_id"))
            if subject is None or subject["delete_state"] != "active":
                raise ManualError("manual.inbox_unavailable", 404)
    elif action in {"followup_create", "followup_bind_anchor"}:
        row = tx.get("followup", text(result, "id"))
        if row is None:
            raise ManualError("manual.not_found", 404)
        from .followup import Followup

        Followup.contact_grant(tx, row, service.clock())

    # Own restrictive transitions may have advanced this row and the host head.
    # Compare the fresh locked control state, then deny any external intent that
    # arrived during materialization/audit before releasing protected output.
    control = tx.get("control", "demo")
    if control is None:
        raise ManualError("manual.bootstrap_missing", 503)
    service.assert_journal_current({"control": control})
