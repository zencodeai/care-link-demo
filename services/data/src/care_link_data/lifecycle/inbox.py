"""Participant-owned internal inbox, independent of ended support transports."""

from care_link_domain import Actor, ManualError

from ..engine import Engine
from ..store import Record, Transaction, instant, text
from ..values import Outcome, stamp


class Inbox(Engine):
    def inbox_projection(self, tx: Transaction, actor: Actor, row: Record) -> Record:
        subject = tx.get("subject", text(row, "subject_id"))
        if (
            row["recipient_account_id"] != actor.account_id
            or subject is None
            or subject["delete_state"] != "active"
            or instant(row, "expires_at") <= self.clock()
        ):
            raise ManualError("manual.not_found", 404)
        return {
            "id": row["id"],
            "recipient_account_id": row["recipient_account_id"],
            "followup_id": row["followup_id"],
            "source_session_id": row["session_id"],
            "text": self.cipher.decrypt(text(row, "text_ciphertext")),
            "sources": row["sources"],
            "created_at": stamp(instant(row, "created_at")),
            "expires_at": stamp(instant(row, "expires_at")),
            "read_at": stamp(instant(row, "read_at")) if row["read_at"] else None,
        }

    def participant_inbox(
        self, actor: Actor, *, limit: int = 50, cursor: str | None = None
    ) -> Record:
        def read(
            tx: Transaction, current: Actor, _b: Record, _s: Record | None, _g: Record | None
        ) -> Outcome:
            if cursor is not None or not 1 <= limit <= 50:
                raise ManualError("manual.invalid_query", 422)
            tx.locked = False
            rows = tx.rows("inbox", recipient_account_id=current.account_id, limit=100)
            tx.locked = True
            if len(rows) == 100:
                raise ManualError("manual.page_limit", 503)
            selected: list[Record] = []
            for row in rows:
                try:
                    selected.append(self.inbox_projection(tx, current, row))
                except ManualError as error:
                    if error.status != 404:
                        raise
            if len(selected) > limit:
                raise ManualError("manual.page_limit", 503)
            return Outcome("InboxPage", {"items": selected, "next_cursor": None})

        return self._run(
            actor, "participant_inbox", None, {"limit": limit, "cursor": cursor}, None, read
        )

    def inbox_message_read(self, actor: Actor, message_id: str) -> Record:
        def read(
            tx: Transaction, current: Actor, _b: Record, _s: Record | None, _g: Record | None
        ) -> Outcome:
            metadata = tx.peek("inbox", message_id)
            if metadata is not None:
                tx.scope(text(metadata, "session_id"))
            row = tx.get("inbox", message_id)
            if row is None:
                raise ManualError("manual.not_found", 404)
            view = self.inbox_projection(tx, current, row)
            tx.scope(text(row, "session_id"))
            if row["read_at"] is None:
                row["read_at"] = self.clock()
                tx.put("inbox", row)
                view["read_at"] = stamp(instant(row, "read_at"))
            return Outcome("InboxMessageView", view)

        return self._run(actor, "inbox_message_read", None, {"message_id": message_id}, None, read)
