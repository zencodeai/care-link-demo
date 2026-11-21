"""Explicit post-crisis anchors and separately consented internal follow-up."""

from datetime import timedelta
from typing import cast
from uuid import uuid4

from care_link_contracts import validate_contract
from care_link_domain import Actor, ManualError

from ..consent import grant_current
from ..engine import Engine
from ..store import Record, Transaction, instant, number, text
from ..values import Outcome, dt, integer, stamp
from .views import followup_view, outcome_view


class Followup(Engine):
    def _life_session(self, actor: Actor, repository: str, target: str) -> str:
        with self.store.transaction(actor, None, locked=False) as tx:
            row = tx.peek(repository, target)
            if row is None:
                raise ManualError("manual.not_found", 404)
            return text(row, "session_id")

    @staticmethod
    def contact_grant(tx: Transaction, row: Record, now: object) -> Record:
        from datetime import datetime

        grant = tx.get("consent", text(row, "contact_grant_id"))
        if not (
            grant
            and grant["session_id"] == row["session_id"]
            and grant["subject_id"] == row["subject_id"]
            and grant["purpose"] == "follow_up"
            and grant["recipient_kind"] == "account"
            and grant["recipient_id"] == row["recipient_account_id"]
            and "summary" in cast(list[str], grant["fields"])
            and grant_current(tx, grant, cast(datetime, now))
        ):
            raise ManualError("manual.contact_consent_required", 409)
        return grant

    def _anchor(self, tx: Transaction, followup: Record, body: Record) -> None:
        event = tx.get("post_crisis", text(body, "post_crisis_event_id"))
        if event is None or event["session_id"] != followup["session_id"]:
            raise ManualError("manual.anchor_required", 409)
        anchor, due = instant(event, "occurred_at"), dt(body["due_at"])
        if not anchor + timedelta(hours=24) <= due <= anchor + timedelta(hours=72):
            raise ManualError("manual.followup_window", 422)
        if self.clock() >= anchor + timedelta(hours=72):
            raise ManualError("manual.followup_expired", 409)
        followup.update(
            post_crisis_event_id=event["id"],
            due_at=due,
            expires_at=anchor + timedelta(hours=72),
            state="scheduled",
            contact_grant_id=body["contact_grant_id"],
        )
        grant = self.contact_grant(tx, followup, self.clock())
        if instant(grant, "expires_at") <= due:
            raise ManualError("manual.contact_consent_interval", 409)

    def post_crisis_record(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        def apply(
            tx: Transaction,
            current: Actor,
            body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, g = self.require_session(session, guard)
            self.expected(body, row)
            occurred = dt(body["occurred_at"])
            if occurred > self.clock():
                raise ManualError("manual.invalid_anchor_time", 422)
            # A source event must actually belong to this session, not an invented UUID.
            source = tx.connection.execute(
                "SELECT 1 FROM durable.event WHERE session_id=%s AND event_id=%s",
                (session_id, body["source_event_id"]),
            ).fetchone()
            if source is None:
                raise ManualError("manual.source_event_required", 422)
            event: Record = {
                "id": str(uuid4()),
                "session_id": session_id,
                "actor_id": current.account_id,
                "source_event_id": body["source_event_id"],
                "occurred_at": occurred,
                "created_at": self.clock(),
                "revision": 1,
            }
            tx.put("post_crisis", event)
            self.bump(tx, row, g)
            return Outcome(
                "PostCrisisView",
                {k: v for k, v in event.items() if k in {"id", "session_id"}}
                | {"occurred_at": stamp(occurred), "revision": "1"},
                text(event, "id"),
                session_id,
            )

        return self._run(
            actor, "post_crisis_record", key, data, session_id, apply, contract="PostCrisisRecord"
        )

    def followup_create(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        def apply(
            tx: Transaction,
            _actor: Actor,
            body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, g = self.require_session(session, guard)
            self.expected(body, row)
            if body["subject_id"] != row["persona_id"]:
                raise ManualError("manual.subject_mismatch", 422)
            value: Record = {
                "id": str(uuid4()),
                "session_id": session_id,
                "subject_id": body["subject_id"],
                "recipient_account_id": body["recipient_account_id"],
                "contact_grant_id": body["contact_grant_id"],
                "post_crisis_event_id": None,
                "due_at": None,
                "expires_at": None,
                "revision": 1,
                "state": "anchor_pending",
                "inbox_message_id": None,
                "effect_key": str(uuid4()),
                "fence": 0,
                "created_at": self.clock(),
            }
            self.contact_grant(tx, value, self.clock())
            if body["kind"] == "scheduled":
                self._anchor(tx, value, body)
            tx.put("followup", value)
            self.register_lifecycle_copy(tx, row, "followup", text(value, "id"))
            self.bump(tx, row, g)
            return Outcome("FollowUpView", followup_view(value), text(value, "id"), session_id)

        return self._run(
            actor, "followup_create", key, data, session_id, apply, contract="FollowUpCreate"
        )

    def _followup_change(
        self, actor: Actor, key: str, data: Record, target: str, *, cancel: bool
    ) -> Record:
        sid = self._life_session(actor, "followup", target)

        def apply(
            tx: Transaction,
            _actor: Actor,
            body: Record,
            _session: Record | None,
            _guard: Record | None,
        ) -> Outcome:
            row = tx.get("followup", target)
            if row is None or row["session_id"] != sid:
                raise ManualError("manual.not_found", 404)
            if integer(body["expected_revision"]) != number(row, "revision"):
                raise ManualError("manual.stale_revision", 409)
            if cancel:
                row["cancel_requested"] = True
                if row["state"] in {"anchor_pending", "scheduled", "claimed"}:
                    row["state"] = "cancelled"
                    row["fence"] = number(row, "fence") + 1
                elif row["state"] in {"unknown", "reconciliation_needed"}:
                    row["state"] = "reconciliation_needed"
                # Sent/authorized is truthfully too late; never claim recall.
            else:
                if row["state"] != "anchor_pending":
                    raise ManualError("manual.anchor_already_bound", 409)
                self._anchor(tx, row, body)
            row["revision"] = number(row, "revision") + 1
            tx.put("followup", row)
            return Outcome("FollowUpView", followup_view(row), target, sid)

        validate_contract("RevisionCommand" if cancel else "FollowUpBindAnchor", data)
        return self._run(
            actor,
            "followup_cancel" if cancel else "followup_bind_anchor",
            key,
            {**data, "followup_id": target},
            sid,
            apply,
            replay=lambda tx, _a, _b, _s, _g: Outcome(
                "FollowUpView", followup_view(cast(Record, tx.get("followup", target)))
            ),
        )

    def followup_bind_anchor(
        self, actor: Actor, key: str, data: Record, followup_id: str
    ) -> Record:
        return self._followup_change(actor, key, data, followup_id, cancel=False)

    def followup_cancel(self, actor: Actor, key: str, data: Record, followup_id: str) -> Record:
        return self._followup_change(actor, key, data, followup_id, cancel=True)

    def followup_read(self, actor: Actor, followup_id: str) -> Record:
        sid = self._life_session(actor, "followup", followup_id)

        def read(
            tx: Transaction, _a: Actor, _b: Record, _s: Record | None, _g: Record | None
        ) -> Outcome:
            row = tx.get("followup", followup_id)
            if row is None:
                raise ManualError("manual.not_found", 404)
            return Outcome("FollowUpView", followup_view(row))

        return self._run(actor, "followup_read", None, {"followup_id": followup_id}, sid, read)

    def outcome_append(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        def apply(
            tx: Transaction,
            current: Actor,
            body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, g = self.require_session(session, guard)
            self.expected(body, row)
            observed = dt(body["observed_at"])
            if not instant(row, "created_at") <= observed <= self.clock():
                raise ManualError("manual.outcome_time", 422)
            if body["carer_support"] and current.role != "carer":
                raise ManualError("manual.carer_attribution_required", 422)
            outcome: Record = {
                "id": str(uuid4()),
                "session_id": session_id,
                "subject_id": row["persona_id"],
                "actor_id": current.account_id,
                "pathway_id": body["pathway_id"],
                "state": body["state"],
                "carer_support": body["carer_support"],
                "source": body["source"],
                "observed_at": observed,
                "created_at": self.clock(),
                "revision": 1,
            }
            tx.put("outcome", outcome)
            self.bump(tx, row, g)
            self.register_lifecycle_copy(tx, row, "outcome", text(outcome, "id"))
            return Outcome(
                "CommandResult",
                {
                    "operation_id": key,
                    "state": "committed",
                    "resource_id": outcome["id"],
                    "revision": "1",
                    "audit_ref": str(uuid4()),
                },
                text(outcome, "id"),
                session_id,
            )

        return self._run(
            actor, "outcome_append", key, data, session_id, apply, contract="OutcomeCreate"
        )

    def outcomes_read(
        self, actor: Actor, session_id: str, *, limit: int = 50, cursor: str | None = None
    ) -> Record:
        def read(
            tx: Transaction, current: Actor, _b: Record, _s: Record | None, _g: Record | None
        ) -> Outcome:
            if cursor is not None or not 1 <= limit <= 50:
                raise ManualError("manual.invalid_query", 422)
            rows = tx.rows("outcome", session_id=session_id, limit=100)
            # Private attributed reports are visible only to their actual author.
            own = [r for r in rows if r["actor_id"] == current.account_id]
            if len(rows) == 100 or len(own) > limit:
                raise ManualError("manual.page_limit", 503)
            return Outcome(
                "OutcomePage", {"items": [outcome_view(r) for r in own], "next_cursor": None}
            )

        return self._run(
            actor, "outcomes_read", None, {"limit": limit, "cursor": cursor}, session_id, read
        )

    def register_lifecycle_copy(
        self, tx: Transaction, session: Record, kind: str, target: str, *, expiry: object = None
    ) -> None:
        closed = instant(session, "closed_at") if session.get("closed_at") else None
        tx.put(
            "copy",
            {
                "copy_id": str(uuid4()),
                "subject_id": session["persona_id"],
                "session_id": session["id"],
                "purpose": "rights" if kind == "export" else "follow_up",
                "aggregate_type": kind,
                "aggregate_id": target,
                "content_ref": kind + ":" + target,
                "classification": "synthetic_content",
                "encryption_key_ref": self.content_key_ref or "unavailable",
                "anchor_kind": "capture" if expiry else "last_parent_closed",
                "anchor_at": self.clock() if expiry else closed,
                "expires_at": expiry if expiry else closed + timedelta(days=7) if closed else None,
                "state": "retained" if expiry or closed else "anchor_pending",
                "created_at": self.clock(),
            },
        )
