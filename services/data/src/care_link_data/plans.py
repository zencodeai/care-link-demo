"""Attributed append-only plan snapshots with current account field filtering."""

import json
from datetime import timedelta
from uuid import uuid4

from care_link_contracts import validate_contract
from care_link_domain import Actor, ManualError

from .consent import current_fields, owns_subject
from .engine import Engine
from .store import Record, Transaction, instant, number, text
from .values import Outcome, canonical, integer, object_value, stamp

PLAN_FIELDS = frozenset(
    {
        "plan.warning_signs",
        "plan.strategies",
        "plan.responders",
        "plan.medication_report",
        "plan.advance_wishes",
        "plan.contacts",
        "plan.substitute_decision_maker",
    }
)


class Plans(Engine):
    def _plan_session(self, actor: Actor, plan_id: str) -> str:
        with self.store.transaction(actor, None, locked=False, queue=True) as tx:
            plan = tx.get("plan", plan_id)
            if plan is None:
                raise ManualError("manual.not_found", 404)
            return text(plan, "session_id")

    def _subject_session(self, actor: Actor, subject_id: str, key: str | None = None) -> str:
        with self.store.transaction(actor, None, locked=False, queue=True) as tx:
            prior = tx.get("operation", key) if key else None
            if (
                prior is not None
                and prior["principal_id"] == actor.account_id
                and prior["operation_name"] == "plan_create"
                and isinstance(prior["session_id"], str)
            ):
                # The same logical command retains its original anchor even
                # after another support session is created for this subject.
                return text(prior, "session_id")
            persona = tx.get("persona", subject_id)
            if persona is None or persona["account_id"] != actor.account_id or actor.role != "pid":
                raise ManualError("manual.not_found", 404)
            sessions = tx.rows(
                "session", persona_id=subject_id, participant_account_id=actor.account_id, limit=100
            )
            if len(sessions) == 100:
                raise ManualError("manual.session_lookup_limit", 503)
            if not sessions:
                raise ManualError("manual.not_found", 404)
            # One stable anchor; a plan's independent lifecycle never expires by
            # session age. Multiple active sessions do not create hidden authority.
            return text(
                max(sessions, key=lambda row: (instant(row, "created_at"), text(row, "id"))), "id"
            )

    def plan_projection(self, tx: Transaction, actor: Actor, plan: Record) -> Record:
        session = tx.get("session", text(plan, "session_id"))
        if session is None:
            raise ManualError("manual.not_found", 404)
        owner = owns_subject(tx, actor, session)
        allowed: set[str] = current_fields(tx, actor, session, self.clock()) if not owner else set()
        if not owner and not allowed:
            raise ManualError("manual.not_found", 404)
        # Latest per author, not last writer wins across different people.
        latest: dict[tuple[str, str], Record] = {}
        rows = tx.rows("plan_field", plan_id=plan["id"], limit=100)
        if len(rows) == 100:
            raise ManualError("manual.plan_history_limit", 503)
        for field in rows:
            if not owner and field["field_key"] not in allowed:
                continue
            key = (text(field, "field_key"), text(field, "author_id"))
            if key not in latest or number(field, "revision") > number(latest[key], "revision"):
                latest[key] = field
        if len(latest) > 32:
            raise ManualError("manual.plan_projection_limit", 503)
        views: list[Record] = []
        for key in sorted(latest):
            field = latest[key]
            views.append(
                {
                    "id": field["id"],
                    "revision": str(number(field, "revision")),
                    "subject_id": plan["subject_id"],
                    "field": field["field_key"],
                    "value": object_value(
                        json.loads(self.cipher.decrypt(text(field, "value_ciphertext")))
                    ),
                    "author_id": field["author_id"],
                    "source": field["source"],
                    "verification": "disputed"
                    if any(
                        other["field_key"] == field["field_key"]
                        and other["author_id"] != field["author_id"]
                        and self.cipher.decrypt(text(other, "value_ciphertext"))
                        != self.cipher.decrypt(text(field, "value_ciphertext"))
                        for other in latest.values()
                    )
                    else field["verification"],
                    "supersedes_id": field["supersedes_id"],
                    "effective_at": stamp(instant(field, "effective_at")),
                }
            )
        return {
            "id": plan["id"],
            "subject_id": plan["subject_id"],
            "revision": str(number(plan, "revision")),
            "state": plan["state"],
            "fields": views,
            "retired_at": stamp(instant(plan, "retired_at")) if plan["retired_at"] else None,
        }

    def _plan_copy(self, tx: Transaction, plan: Record, kind: str, aggregate_id: str) -> None:
        if not self.content_key_ref:
            raise ManualError("manual.content_custody_unregistered", 503)
        tx.put(
            "copy",
            {
                "copy_id": str(uuid4()),
                "subject_id": plan["subject_id"],
                "session_id": plan["session_id"],
                "purpose": "plan",
                "aggregate_type": kind,
                "aggregate_id": aggregate_id,
                "content_ref": "postgres:" + kind + ":" + aggregate_id,
                "classification": "synthetic_content",
                "encryption_key_ref": self.content_key_ref,
                "anchor_kind": "plan_retired",
                "anchor_at": None,
                "expires_at": None,
                "state": "anchor_pending",
                "created_at": self.clock(),
            },
        )

    def plan_create(self, actor: Actor, key: str, data: Record) -> Record:
        def create(
            tx: Transaction,
            current: Actor,
            body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, current_guard = self.require_session(session, guard)
            if not owns_subject(tx, current, row) or not current.mfa:
                raise ManualError("manual.plan_owner_required")
            self.expected(body, row)
            if body["subject_id"] != row["persona_id"]:
                raise ManualError("manual.subject_scope", 404)
            if tx.rows("plan", subject_id=row["persona_id"], state="active", limit=1):
                raise ManualError("manual.active_plan_exists", 409)
            plan: Record = {
                "id": str(uuid4()),
                "subject_id": row["persona_id"],
                "session_id": row["id"],
                "revision": 1,
                "state": "active",
                "created_at": self.clock(),
                "updated_at": self.clock(),
                "retired_at": None,
            }
            tx.put("plan", plan)
            self._plan_copy(tx, plan, "plan", text(plan, "id"))
            self._plan_bump_subject(tx, row)
            self.bump(tx, row, current_guard)
            return Outcome(
                "PlanView",
                self.plan_projection(tx, current, plan),
                text(plan, "id"),
                text(row, "id"),
            )

        return self._run(
            actor,
            "plan_create",
            key,
            data,
            self._subject_session(actor, text(data, "subject_id"), key),
            create,
            contract="PlanCreate",
        )

    @staticmethod
    def _plan_bump_subject(tx: Transaction, session: Record) -> None:
        subject = tx.get("subject", text(session, "persona_id"))
        if subject is None:
            raise ManualError("manual.subject_scope", 404)
        subject["authority_revision"] = number(subject, "authority_revision") + 1
        tx.put("subject", subject)

    def plan_read(self, actor: Actor, plan_id: str) -> Record:
        def read(
            tx: Transaction,
            current: Actor,
            _body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, _ = self.require_session(session, guard)
            plan = tx.get("plan", plan_id)
            if plan is None or plan["session_id"] != row["id"]:
                raise ManualError("manual.not_found", 404)
            return Outcome("PlanView", self.plan_projection(tx, current, plan))

        return self._run(
            actor, "plan_read", None, {"plan_id": plan_id}, self._plan_session(actor, plan_id), read
        )

    def plan_field_append(self, actor: Actor, key: str, data: Record, plan_id: str) -> Record:
        def append(
            tx: Transaction,
            current: Actor,
            body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, current_guard = self.require_session(session, guard)
            plan = tx.get("plan", plan_id)
            if plan is None or plan["session_id"] != row["id"]:
                raise ManualError("manual.not_found", 404)
            if plan["state"] != "active":
                raise ManualError("manual.plan_retired", 409)
            if body["field"] not in PLAN_FIELDS:
                raise ManualError("manual.plan_field_required", 422)
            if not current.mfa:
                raise ManualError("manual.assurance_required")
            if not owns_subject(tx, current, row) and body["field"] not in current_fields(
                tx, current, row, self.clock()
            ):
                raise ManualError("manual.field_scope_denied")
            if integer(body["expected_revision"]) != number(plan, "revision"):
                raise ManualError("manual.stale_revision", 409)
            history = tx.rows("plan_field", plan_id=plan_id, field_key=body["field"], limit=100)
            if len(history) >= 99:
                raise ManualError("manual.plan_history_limit", 409)
            own = [field for field in history if field["author_id"] == current.account_id]
            previous = max(own, key=lambda field: number(field, "revision")) if own else None
            # An assigned worker adds their report rather than replacing wishes
            # authored by the PID. Conflicting current reports remain disputed.
            conflicting = any(
                field["author_id"] != current.account_id
                and self.cipher.decrypt(text(field, "value_ciphertext")) != canonical(body["value"])
                for field in history
            )
            field: Record = {
                "id": str(uuid4()),
                "plan_id": plan_id,
                "subject_id": plan["subject_id"],
                "session_id": row["id"],
                "field_key": body["field"],
                "revision": number(plan, "revision") + 1,
                "value_ciphertext": self.cipher.encrypt(canonical(body["value"])),
                "author_id": current.account_id,
                "source": body["source"],
                "verification": "disputed" if conflicting else "unverified",
                "supersedes_id": previous["id"] if previous else None,
                "effective_at": self.clock(),
                "safety_relevant": body["safety_relevant"],
            }
            tx.put("plan_field", field)
            self._plan_copy(tx, plan, "plan_field", text(field, "id"))
            if conflicting and (
                body["safety_relevant"] or any(old["safety_relevant"] for old in history)
            ):
                tx.put(
                    "plan_review",
                    {
                        "id": str(uuid4()),
                        "plan_id": plan_id,
                        "field_id": field["id"],
                        "state": "pending",
                        "created_at": self.clock(),
                    },
                )
            plan["revision"] = number(plan, "revision") + 1
            plan["updated_at"] = self.clock()
            tx.put("plan", plan)
            self._plan_bump_subject(tx, row)
            self.bump(tx, row, current_guard)
            return Outcome(
                "PlanView", self.plan_projection(tx, current, plan), plan_id, text(row, "id")
            )

        validate_contract("PlanFieldCreate", data)
        return self._run(
            actor,
            "plan_field_append",
            key,
            {**data, "plan_id": plan_id},
            self._plan_session(actor, plan_id),
            append,
        )

    def plan_retire(self, actor: Actor, key: str, data: Record, plan_id: str) -> Record:
        def retire(
            tx: Transaction,
            current: Actor,
            body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, current_guard = self.require_session(session, guard)
            plan = tx.get("plan", plan_id)
            if (
                plan is None
                or plan["session_id"] != row["id"]
                or not owns_subject(tx, current, row)
                or not current.mfa
            ):
                raise ManualError("manual.not_found", 404)
            if integer(body["expected_revision"]) != number(plan, "revision"):
                raise ManualError("manual.stale_revision", 409)
            if plan["state"] == "active":
                retired_at = self.clock()
                plan["state"], plan["retired_at"] = "retired", retired_at
                plan["revision"] = number(plan, "revision") + 1
                plan["updated_at"] = retired_at
                tx.put("plan", plan)
                # Independent plan cleanup begins here, never on session close.
                # The accepted demo schedule is explicit retirement +30 days.
                # Purge and backup completion remain separate obligations.
                fields = tx.rows("plan_field", plan_id=plan_id, limit=100)
                if len(fields) == 100:
                    raise ManualError("manual.plan_history_limit", 503)
                aggregates = [plan_id, *(text(field, "id") for field in fields)]
                for aggregate_id in aggregates:
                    copies = tx.rows("copy", aggregate_id=aggregate_id, purpose="plan", limit=1)
                    if not copies:
                        raise ManualError("manual.plan_copy_missing", 503)
                    copy = copies[0]
                    if copy["anchor_at"] is None:
                        copy["anchor_at"] = retired_at
                        copy["expires_at"] = retired_at + timedelta(days=30)
                        copy["state"] = "retained"
                        tx.put("copy", copy)
                self._plan_bump_subject(tx, row)
                self.bump(tx, row, current_guard)
            return Outcome(
                "PlanView", self.plan_projection(tx, current, plan), plan_id, text(row, "id")
            )

        validate_contract("RevisionCommand", data)
        return self._run(
            actor,
            "plan_retire",
            key,
            {**data, "plan_id": plan_id},
            self._plan_session(actor, plan_id),
            retire,
        )
