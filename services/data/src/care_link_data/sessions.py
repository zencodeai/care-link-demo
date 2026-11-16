"""Participant-led manual intake, attributed records and protected projections."""

import hashlib
import hmac
import json
from datetime import timedelta
from typing import cast
from uuid import uuid4

from care_link_domain import Actor, ManualError

from . import projections
from .engine import Engine
from .store import Record, Transaction, instant, number, text
from .values import PARTICIPANTS, Outcome, canonical, digest, dt, integer, stamp


class SessionService(Engine):
    def session_create(self, actor: Actor, key: str, data: Record) -> Record:
        return self._run(
            actor, "session_create", key, data, None, self._create, contract="SessionCreate"
        )

    def _create(
        self,
        tx: Transaction,
        actor: Actor,
        data: Record,
        _session: Record | None,
        _guard: Record | None,
    ) -> Outcome:
        if data["participant_kind"] != actor.role:
            raise ManualError("manual.participant_role")
        fixture_id = data["fixture_id"]
        if fixture_id is not None and (
            not isinstance(fixture_id, str)
            or fixture_id not in self.fixtures
            or self.scenario_bindings.get(actor.account_id) != fixture_id
        ):
            raise ManualError("manual.fixture_not_assigned")
        persona_id = data["persona_id"]
        now = self.clock()
        if persona_id is None:
            persona_id = str(uuid4())
            tx.put(
                "persona",
                {
                    "id": persona_id,
                    "environment": "demo",
                    "population": "synthetic",
                    "revision": 1,
                    "kind": actor.role,
                    "account_id": actor.account_id,
                    "display_alias": "Fictional participant",
                    "created_at": now,
                    "updated_at": now,
                },
            )
            tx.put(
                "subject",
                {"subject_id": persona_id, "authority_revision": 1, "delete_state": "active"},
            )
        elif isinstance(persona_id, str):
            subject = tx.get("subject", persona_id)
            persona = tx.get("persona", persona_id)
            if (
                persona is None
                or subject is None
                or persona["account_id"] != actor.account_id
                or persona["kind"] != actor.role
                or subject["delete_state"] != "active"
            ):
                raise ManualError("manual.persona_unavailable", 404)
        else:
            raise ManualError("manual.persona_unavailable", 404)
        sid = str(uuid4())
        tx.scope(sid)
        session: Record = {
            "id": sid,
            "environment": "demo",
            "population": "synthetic",
            "revision": 0,
            "created_at": now,
            "updated_at": now,
            "persona_id": persona_id,
            "participant_account_id": actor.account_id,
            "participant_kind": data["participant_kind"],
            "jurisdiction": data["jurisdiction"],
            "locale": data["locale"],
            "channel": data["channel"],
            "service_phase": "active",
            "transport": "connected",
            "owner_id": None,
            "fixture_id": fixture_id,
            "tier": None,
            "unresolved": True,
            "disclosure_acknowledged": False,
            "assessment_turns": 0,
            "closed_at": None,
        }
        guard: Record = {
            "session_id": sid,
            "access_revision": 1,
            "control_epoch": 0,
            "next_event_seq": 1,
        }
        tx.put("session", session)
        run_id = getattr(actor, "review_run_id", None)
        if run_id is not None:
            tx.connection.execute(
                "INSERT INTO core.review_member(session_id,run_id) VALUES(%s,%s)", (sid, run_id)
            )
        tx.put("guard", guard)
        tx.put(
            "acl",
            {
                "session_id": sid,
                "principal_id": actor.account_id,
                "purpose": "support",
                "fields": [
                    "needs",
                    "preferences",
                    "observations",
                    "rationale",
                    "summary",
                    "outcome",
                ],
                "valid_until": None,
                "revoked_at": None,
                "revision": 1,
            },
        )
        self.register_copy(tx, session, "session", sid)
        self.bump(tx, session, guard)
        return Outcome("SessionView", self.session_projection(tx, session, guard), sid, sid)

    def session_read(self, actor: Actor, session_id: str) -> Record:
        def read(
            tx: Transaction,
            _actor: Actor,
            _data: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, current = self.require_session(session, guard)
            return Outcome("SessionView", self.session_projection(tx, row, current))

        return self._run(actor, "session_read", None, {}, session_id, read)

    def session_disclosure(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        def acknowledge(
            tx: Transaction,
            _actor: Actor,
            body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, current = self.require_session(session, guard)
            self.active(row)
            self.expected(body, row)
            template = self.disclosure_templates.get(text(row, "locale"))
            if (
                template is None
                or body["template_id"] != template["id"]
                or body["template_digest"] != template["digest"]
                or body["locale"] != row["locale"]
            ):
                raise ManualError("manual.disclosure_changed", 409)
            row["disclosure_acknowledged"] = True
            self.bump(tx, row, current)
            return self.command(row)

        return self._run(
            actor,
            "session_disclosure",
            key,
            data,
            session_id,
            acknowledge,
            contract="DisclosureAck",
        )

    @staticmethod
    def command(session: Record, resource_id: str | None = None) -> Outcome:
        return Outcome(
            "CommandResult",
            {
                "operation_id": str(uuid4()),
                "state": "committed",
                "resource_id": resource_id or session["id"],
                "revision": str(number(session, "revision")),
                "audit_ref": str(uuid4()),
            },
            resource_id or text(session, "id"),
            text(session, "id"),
        )

    def session_turns(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        return self._run(
            actor, "session_turns", key, data, session_id, self._turn, contract="TurnSubmit"
        )

    def _turn(
        self,
        tx: Transaction,
        actor: Actor,
        data: Record,
        session: Record | None,
        guard: Record | None,
    ) -> Outcome:
        row, current = self.require_session(session, guard)
        self.active(row)
        self.expected(data, row)
        if row["disclosure_acknowledged"] is not True:
            raise ManualError("manual.disclosure_required", 409)
        if data["locale"] != row["locale"]:
            raise ManualError("manual.locale_mismatch", 422)
        if tx.rows("turn", session_id=row["id"], client_turn_id=data["client_turn_id"], limit=1):
            raise ManualError("manual.turn_id_conflict", 409)
        fixture = self.fixtures.get(str(row["fixture_id"]), {})
        tier = fixture.get("tier", "T0")
        if tier not in {"T0", "T1", "T2", "T3", "T4"}:
            raise ManualError("manual.fixture_invalid", 503)
        reasons: list[str] = []
        if fixture.get("hazard") is True:
            reasons.append("fixture_hazard")
        if fixture.get("critical_unknown", True) is True:
            reasons.append("critical_unknown")
        if fixture.get("age_uncertain") is True:
            reasons.append("age_uncertain")
        if tier in {"T2", "T3", "T4"}:
            reasons.append("fixture_tier")
        row["assessment_turns"] = number(row, "assessment_turns") + 1
        if row["assessment_turns"] >= 10:
            reasons.append("assessment_limit")
        row["tier"] = tier
        assessment_id, turn_id, message_id = str(uuid4()), str(uuid4()), str(uuid4())
        revision = number(row, "revision") + 1
        now = self.clock()
        tx.put(
            "turn",
            {
                "id": turn_id,
                "session_id": row["id"],
                "client_turn_id": data["client_turn_id"],
                "event_seq": number(current, "next_event_seq"),
                "author_id": actor.account_id,
                "text_ciphertext": self.cipher.encrypt(text(data, "text")),
                "locale": data["locale"],
                "assessment_revision": revision,
                "created_at": now,
            },
        )
        tx.put(
            "message",
            {
                "id": message_id,
                "session_id": row["id"],
                "revision": 1,
                "sender_id": actor.account_id,
                "kind": "participant",
                "text_ciphertext": self.cipher.encrypt(text(data, "text")),
                "control_epoch": number(current, "control_epoch"),
                "created_at": now,
            },
        )
        assessment: Record = {
            "id": assessment_id,
            "session_id": row["id"],
            "revision": revision,
            "fixture_id": row["fixture_id"],
            "field_states": [{"field": "needs", "state": "captured", "assertion_ids": []}],
            "tier_set_digest": fixture.get(
                "tier_set_digest", digest({"class": "stub", "rules": "manual-fixture-v1"})
            ),
            "tier": tier,
            "hazard_fixture": fixture.get("hazard", False),
            "human_reasons": reasons,
            "created_at": now,
        }
        self.register_copy(tx, row, "turn", turn_id)
        self.register_copy(tx, row, "message", message_id)
        tx.put("assessment", assessment)
        if reasons:
            self.enqueue(tx, row, current)
        self.bump(
            tx,
            row,
            current,
            event_type="message_available",
            resource_id=message_id,
            resource_revision=1,
        )
        return Outcome(
            "AssessmentView",
            projections.assessment_view(assessment),
            assessment_id,
            text(row, "id"),
        )

    def session_assertions(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        def append(
            tx: Transaction,
            current_actor: Actor,
            body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, current = self.require_session(session, guard)
            self.active(row)
            self.expected(body, row)
            if body["subject_id"] != row["persona_id"]:
                raise ManualError("manual.subject_scope", 404)
            previous = body["supersedes_id"]
            if isinstance(previous, str):
                old = tx.get("assertion", previous)
                if (
                    old is None
                    or old["session_id"] != row["id"]
                    or old["author_id"] != current_actor.account_id
                ):
                    raise ManualError("manual.assertion_scope", 404)
            assertion: Record = {
                "id": str(uuid4()),
                "session_id": row["id"],
                "subject_id": row["persona_id"],
                "revision": 1,
                "field_key": body["field"],
                "value_ciphertext": self.cipher.encrypt(canonical(body["value"])),
                "author_id": current_actor.account_id,
                "verification": "unverified",
                "supersedes_id": previous,
                "effective_at": dt(body["effective_at"]),
                "created_at": self.clock(),
            }
            tx.put("assertion", assertion)
            self.register_copy(tx, row, "assertion", text(assertion, "id"))
            self.bump(tx, row, current)
            return Outcome(
                "AssertionView",
                projections.assertion_view(assertion, self.cipher, json.loads),
                text(assertion, "id"),
                text(row, "id"),
            )

        return self._run(
            actor, "session_assertions", key, data, session_id, append, contract="AssertionCreate"
        )

    def session_choices(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        def append(
            tx: Transaction,
            current_actor: Actor,
            body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, current = self.require_session(session, guard)
            self.active(row)
            self.expected(body, row)
            # Directory admission is IMP-04; no fabricated selectable destination.
            if body["service_id"] is not None:
                raise ManualError("manual.directory_unavailable", 503)
            tx.put(
                "choice",
                {
                    "id": str(uuid4()),
                    "session_id": row["id"],
                    "author_id": current_actor.account_id,
                    "action": body["action"],
                    "service_id": None,
                    "rationale_version": body["rationale_version"],
                    "created_at": self.clock(),
                },
            )
            self.bump(tx, row, current)
            return self.command(row)

        return self._run(
            actor, "session_choices", key, data, session_id, append, contract="ChoiceCommand"
        )

    def enqueue(self, tx: Transaction, session: Record, guard: Record) -> Record:
        old = self.active_queue(tx, text(session, "id"))
        if old is not None:
            return old
        now = self.clock()
        fixture = self.fixtures.get(str(session["fixture_id"]), {})
        queue: Record = {
            "id": str(uuid4()),
            "session_id": session["id"],
            "revision": 1,
            "requested_at": now,
            "mode": "regional_outage"
            if fixture.get("regional_outage")
            else "partner_unavailable"
            if fixture.get("partner_unavailable")
            else "normal",
            "fixture_priority": {"T4": 0, "T3": 1, "T2": 2, "T1": 3, "T0": 4}.get(
                str(session["tier"]), 4
            ),
            "next_review_at": now + timedelta(seconds=60),
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        }
        tx.put("queue", queue)
        if session["service_phase"] in {"active", "human_requested"}:
            # The in-process queue scheduler commits its actual durable admission.
            session["service_phase"] = "queued"
        del guard
        return queue

    def session_human_request(
        self, actor: Actor, key: str, data: Record, session_id: str
    ) -> Record:
        def request(
            tx: Transaction,
            _actor: Actor,
            body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, current = self.require_session(session, guard)
            self.active(row)
            old = self.active_queue(tx, text(row, "id"))
            if old is None:
                self.expected(body, row)
            queue = self.enqueue(tx, row, current)
            self.bump(
                tx,
                row,
                current,
                event_type="queue_changed",
                resource_id=text(queue, "id"),
                resource_revision=number(queue, "revision"),
            )
            return Outcome(
                "QueueView", self.queue_projection(tx, queue), text(queue, "id"), text(row, "id")
            )

        return self._run(
            actor, "session_human_request", key, data, session_id, request, contract="HumanRequest"
        )

    def session_end(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        def end(
            tx: Transaction,
            _actor: Actor,
            body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, current = self.require_session(session, guard)
            self.active(row)
            self.expected(body, row)
            if body["reason"] != "user_choice":
                raise ManualError("manual.explicit_end_required", 422)
            row["service_phase"] = "ended"
            row["closed_at"] = self.clock()
            row["owner_id"] = None
            tx.close_copies(text(row, "id"), instant(row, "closed_at"))
            current["control_epoch"] = number(current, "control_epoch") + 1
            queue = self.active_queue(tx, text(row, "id"))
            if queue:
                queue["status"] = "cancelled"
                queue["revision"] = number(queue, "revision") + 1
                tx.put("queue", queue)
            assignment = self.active_assignment(tx, text(row, "id"))
            if assignment:
                assignment["status"] = "released"
                assignment["revision"] = number(assignment, "revision") + 1
                tx.put("assignment", assignment)
            for family in tx.rows("family", session_id=row["id"], status="active"):
                family["status"] = "revoked"
                family["revision"] = number(family, "revision") + 1
                tx.put("family", family)
            self.bump(tx, row, current)
            return self.command(row)

        return self._run(actor, "session_end", key, data, session_id, end, contract="ReasonCommand")

    def message_send(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        def send(
            tx: Transaction,
            current_actor: Actor,
            body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, current = self.require_session(session, guard)
            self.active(row)
            self.expected(body, row)
            if integer(body["expected_control_epoch"]) != number(current, "control_epoch"):
                raise ManualError("manual.owner_changed", 409)
            if body["accepted_draft_id"] is not None:
                raise ManualError("manual.ai_disabled", 503)
            if current_actor.role not in PARTICIPANTS and (
                row["owner_id"] != current_actor.account_id
                or row["service_phase"] != "human_controlled"
            ):
                raise ManualError("manual.current_owner_required", 409)
            message: Record = {
                "id": str(uuid4()),
                "session_id": row["id"],
                "revision": 1,
                "sender_id": current_actor.account_id,
                "kind": "participant" if current_actor.role in PARTICIPANTS else "human_authored",
                "text_ciphertext": self.cipher.encrypt(text(body, "text")),
                "control_epoch": number(current, "control_epoch"),
                "created_at": self.clock(),
            }
            tx.put("message", message)
            self.register_copy(tx, row, "message", text(message, "id"))
            self.bump(
                tx,
                row,
                current,
                event_type="message_available",
                resource_id=text(message, "id"),
                resource_revision=1,
            )
            return Outcome(
                "MessageView",
                projections.message_view(message, self.cipher),
                text(message, "id"),
                text(row, "id"),
            )

        return self._run(
            actor, "message_send", key, data, session_id, send, contract="MessageSubmit"
        )

    def messages_read(
        self, actor: Actor, session_id: str, *, limit: int = 50, cursor: str | None = None
    ) -> Record:
        if not 1 <= limit <= 50:
            raise ManualError("manual.invalid_page", 422)

        def read(
            tx: Transaction,
            current_actor: Actor,
            _body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            _row, _current = self.require_session(session, guard)
            position = self._cursor_position(current_actor, "messages:" + session_id, cursor)
            after = (dt(position[0]), position[1]) if position else None
            rows = tx.message_page(session_id, after, limit + 1)
            items = rows[:limit]
            next_cursor = (
                self._issue_cursor(
                    current_actor,
                    "messages:" + session_id,
                    [stamp(instant(items[-1], "created_at")), text(items[-1], "id")],
                )
                if len(rows) > limit
                else None
            )
            return Outcome(
                "MessagePage",
                {
                    "items": [projections.message_view(item, self.cipher) for item in items],
                    "next_cursor": next_cursor,
                },
            )

        return self._run(
            actor, "messages_read", None, {"limit": limit, "cursor": cursor}, session_id, read
        )

    def _issue_cursor(self, actor: Actor, kind: str, position: list[str]) -> str:
        if not self.cursor_key:
            raise ManualError("manual.pagination_unconfigured", 503)
        payload = (
            canonical(
                {
                    "principal": actor.account_id,
                    "kind": kind,
                    "position": position,
                    "expires": stamp(self.clock() + timedelta(minutes=5)),
                }
            )
            .encode()
            .hex()
        )
        signature = hmac.new(self.cursor_key, payload.encode(), hashlib.sha256).hexdigest()
        return payload + "." + signature

    def _cursor_position(self, actor: Actor, kind: str, cursor: str | None) -> list[str] | None:
        if cursor is None:
            return None
        if not self.cursor_key or len(cursor) > 1024:
            raise ManualError("manual.cursor_invalid", 422)
        try:
            payload, signature = cursor.split(".")
            expected = hmac.new(self.cursor_key, payload.encode(), hashlib.sha256).hexdigest()
            value = json.loads(bytes.fromhex(payload))
            if (
                not hmac.compare_digest(signature, expected)
                or value["principal"] != actor.account_id
                or value["kind"] != kind
                or dt(value["expires"]) <= self.clock()
            ):
                raise ValueError("Invalid cursor")
            position: object = value["position"]
            if (
                not isinstance(position, list)
                or not all(isinstance(item, str) for item in cast(list[object], position))
                or len(cast(list[object], position)) != (3 if kind == "queue" else 2)
            ):
                raise ValueError("Invalid cursor position")
            return cast(list[str], position)
        except (ValueError, KeyError, TypeError) as error:
            raise ManualError("manual.cursor_invalid", 422) from error

    def session_events(self, actor: Actor, session_id: str, last_event_id: int = 0) -> list[Record]:
        if not 0 <= last_event_id <= 9223372036854775807:
            raise ManualError("manual.event_position", 422)

        # Each call releases at most one freshly authorized reference. The BFF
        # calls again before every write; there is no prefetched private queue.
        def read(
            tx: Transaction,
            _actor: Actor,
            _body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, current = self.require_session(session, guard)
            pending = tx.events_after(session_id, last_event_id)
            if (
                len(pending) > 32
                or (pending and number(pending[0], "sequence") != last_event_id + 1)
                or last_event_id >= number(current, "next_event_seq")
            ):
                return Outcome(
                    "EventView",
                    {
                        "event_id": str(uuid4()),
                        "sequence": str(last_event_id),
                        "occurred_at": stamp(self.clock()),
                        "type": "resync_required",
                        "resource_id": row["id"],
                        "resource_revision": str(number(row, "revision")),
                    },
                )
            if pending:
                return Outcome("EventView", projections.event_view(pending[0]))
            # Empty private event batches are represented by a public heartbeat
            # sentinel at the adapter boundary; never invent an aggregate event.
            raise ManualError("manual.no_event", 204)

        try:
            return [
                self._run(
                    actor,
                    "session_events",
                    None,
                    {"last_event_id": str(last_event_id)},
                    session_id,
                    read,
                )
            ]
        except ManualError as error:
            if error.status == 204:
                return []
            raise
