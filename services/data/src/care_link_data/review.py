"""Authoritative actor workspace, encrypted drafts and durable submission identities."""

from datetime import timedelta
from uuid import uuid4

from care_link_domain import Actor, ManualError

from . import projections, review_projection
from .continuations import ContinuationService
from .review_scope import scope_allowed
from .store import Record, Transaction, instant, number, text
from .values import PARTICIPANTS, Outcome, canonical, integer, object_value, stamp


class ReviewService(ContinuationService):
    def review_workspace(self, actor: Actor, session_id: str | None = None) -> Record:
        def read(
            tx: Transaction,
            current: Actor,
            _body: Record,
            _session: Record | None,
            _guard: Record | None,
        ) -> Outcome:
            run = tx.peek("review_run", current.review_run_id) if current.review_run_id else None
            active = run is None or run["state"] == "active"
            candidates = tx.review_sessions(current.review_run_id)
            if session_id and all(row["id"] != session_id for row in candidates):
                requested = tx.peek("session", session_id)
                if requested is not None:
                    candidates = [requested, *candidates[:49]]
            views: list[Record] = []
            selected: Record | None = None
            selected_guard: Record | None = None
            own_assignment: Record | None = None
            for row in candidates:
                sid = text(row, "id")
                if not scope_allowed(
                    tx, current, "session_read" if active else "operation_status", sid, run
                ):
                    continue
                candidate_assignment = self.active_assignment(tx, sid)
                if (
                    active
                    and candidate_assignment
                    and candidate_assignment["worker_id"] == current.account_id
                    and (session_id is None or session_id == sid)
                    and own_assignment is None
                ):
                    own_assignment = candidate_assignment
                if not active:
                    continue
                snapshot = self._snapshot(tx, current, sid)
                if not self._accessible(tx, current, "session_read", snapshot):
                    continue
                guard = object_value(snapshot["guard"])
                views.append(self.session_projection(tx, row, guard))
                if selected is None and (session_id is None or session_id == sid):
                    selected, selected_guard = row, guard
            if (
                active
                and session_id
                and selected is None
                and not (own_assignment and own_assignment["session_id"] == session_id)
            ):
                raise ManualError("manual.not_found", 404)
            if selected is not None:
                assignment = self.active_assignment(tx, text(selected, "id"))
                own_assignment = (
                    assignment
                    if assignment and assignment["worker_id"] == current.account_id
                    else None
                )
            accessible_ids = {str(view["id"]) for view in views}
            intents = self._review_intents(tx, current, accessible_ids, expose_payload=active)
            drafts: list[Record] = []
            if selected is not None:
                for row in tx.review_records(
                    "review_draft",
                    session_id=selected["id"],
                    principal_id=current.account_id,
                    limit=3,
                ):
                    expired = instant(row, "expires_at") <= self.clock()
                    prepared = tx.review_records(
                        "review_intent",
                        session_id=row["session_id"],
                        principal_id=current.account_id,
                        kind=row["kind"],
                        draft_revision=row["revision"],
                        limit=1,
                    )
                    operation = (
                        tx.peek("operation", text(prepared[0], "operation_id"))
                        if prepared
                        else None
                    )
                    committed = operation is not None and operation["state"] == "committed"
                    # Retain the exact optimistic revision without decrypting
                    # or redisplaying consumed/expired content.
                    drafts.append(
                        review_projection.draft_view(
                            row, self.cipher, expose_text=not (committed or expired)
                        )
                    )
            handshake = (
                self._review_handshake(tx, current, selected, selected_guard) if selected else None
            )
            interrupt_expires_at: str | None = None
            if active and selected is not None and current.role == "supervisor":
                grants = tx.review_records(
                    "acl",
                    session_id=selected["id"],
                    principal_id=current.account_id,
                    purpose="interrupt",
                    limit=1,
                )
                if (
                    grants
                    and grants[0]["revoked_at"] is None
                    and grants[0]["valid_until"] is not None
                    and instant(grants[0], "valid_until") > self.clock()
                ):
                    interrupt_expires_at = stamp(instant(grants[0], "valid_until"))
            result: Record = {
                "interrupt_expires_at": interrupt_expires_at,
                "run_id": current.review_run_id,
                "run_state": run["state"] if run else None,
                "conversations": views,
                "conversation": self.session_projection(tx, selected, selected_guard)
                if selected and selected_guard
                else None,
                "assignment": projections.assignment_view(own_assignment)
                if own_assignment
                else None,
                "drafts": drafts,
                "pending_intents": intents,
                "handshake": handshake,
                "disclosure_acknowledged": selected["disclosure_acknowledged"] is True
                if selected
                else False,
                "intake_submitted": number(selected, "assessment_turns") > 0 if selected else False,
            }
            return Outcome("ReviewWorkspace", result)

        return self._run(
            actor,
            "review_workspace",
            None,
            {"session_id": session_id},
            None,
            read,
            contract="ReviewWorkspaceQuery",
            queue=True,
        )

    def _review_intents(
        self, tx: Transaction, actor: Actor, accessible_ids: set[str], *, expose_payload: bool
    ) -> list[Record]:
        rows = tx.review_recovery_intents(actor.account_id, actor.review_run_id)
        return [
            review_projection.intent_view(
                tx,
                row,
                actor,
                self.cipher,
                self.clock(),
                expose_payload=expose_payload and row["session_id"] in accessible_ids,
            )
            for row in rows
        ]

    def _review_handshake(
        self, tx: Transaction, actor: Actor, session: Record, guard: Record | None
    ) -> Record | None:
        if guard is None:
            return None
        challenges = tx.review_records(
            "challenge", session_id=session["id"], revoked=False, limit=10
        )
        challenges.sort(key=lambda row: instant(row, "created_at"), reverse=True)
        if not challenges:
            return None
        challenge = challenges[0]
        valid = (
            instant(challenge, "expires_at") > self.clock()
            and challenge["control_epoch"] == guard["control_epoch"]
        )
        participant = False
        worker = False
        worker_ack_id = None
        for ack in tx.review_records("ack", challenge_id=challenge["id"], limit=2):
            principal = tx.peek("principal", text(ack, "principal_id"))
            current = (
                valid
                and principal is not None
                and principal["revoked"] is False
                and principal["identity_revision"] == ack["identity_revision"]
                and principal["role_revision"] == ack["role_revision"]
                and guard["access_revision"] == ack["session_access_revision"]
                and self.channel.current(
                    text(ack, "principal_id"),
                    text(ack, "browser_binding"),
                    number(ack, "transport_generation"),
                )
            )
            if ack["party"] == "participant":
                grants = tx.review_records(
                    "acl",
                    session_id=session["id"],
                    principal_id=ack["principal_id"],
                    purpose="support",
                    limit=1,
                )
                current = (
                    current
                    and bool(grants)
                    and grants[0]["revoked_at"] is None
                    and (
                        grants[0]["valid_until"] is None
                        or instant(grants[0], "valid_until") > self.clock()
                    )
                )
                participant = bool(current)
            else:
                worker = bool(current)
                if current and ack["principal_id"] == actor.account_id:
                    worker_ack_id = ack["id"]
        return {
            "expires_at": stamp(instant(challenge, "expires_at")),
            "challenge_id": challenge["id"],
            "assignment_id": challenge["assignment_id"],
            "participant_acknowledged": participant,
            "worker_acknowledged": worker,
            "evidence_id": challenge["evidence_id"] if participant and worker else None,
            "worker_ack_id": worker_ack_id,
        }

    def review_draft_save(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        def save(
            tx: Transaction,
            current: Actor,
            body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, _current = self.require_session(session, guard)
            self.active(row)
            kind = text(body, "kind")
            if kind == "plan":
                run = (
                    tx.peek("review_run", current.review_run_id) if current.review_run_id else None
                )
                if run is None or run.get("scenario") != "plans-consent-directory":
                    raise ManualError("manual.review_context_required")
            if kind == "intake" and current.role not in PARTICIPANTS:
                raise ManualError("manual.participant_role")
            existing = tx.rows(
                "review_draft",
                session_id=session_id,
                principal_id=current.account_id,
                kind=kind,
                limit=1,
            )
            draft = existing[0] if existing else None
            if integer(body["expected_revision"]) != (number(draft, "revision") if draft else 0):
                raise ManualError("manual.stale_revision", 409)
            now = self.clock()
            result: Record = {
                "id": draft["id"] if draft else str(uuid4()),
                "session_id": session_id,
                "principal_id": current.account_id,
                "kind": kind,
                "revision": number(draft, "revision") + 1 if draft else 1,
                "text_ciphertext": self.cipher.encrypt(text(body, "text")),
                "expires_at": now + timedelta(days=1),
                "updated_at": now,
            }
            tx.put("review_draft", result)
            copies = tx.rows("copy", aggregate_id=result["id"], limit=2)
            if copies:
                copy = copies[0]
                copy["anchor_at"] = now
                copy["expires_at"] = result["expires_at"]
                tx.put("copy", copy)
            else:
                self.register_copy(
                    tx,
                    row,
                    "review_draft",
                    text(result, "id"),
                    captured_at=now,
                    expires_at=instant(result, "expires_at"),
                )
            return Outcome(
                "ReviewDraftView",
                review_projection.draft_view(result, self.cipher),
                text(result, "id"),
                session_id,
            )

        return self._run(
            actor, "review_draft_save", key, data, session_id, save, contract="ReviewDraftSave"
        )

    def review_intent_prepare(
        self, actor: Actor, key: str, data: Record, session_id: str
    ) -> Record:
        def prepare(
            tx: Transaction,
            current: Actor,
            body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, current_guard = self.require_session(session, guard)
            self.active(row)
            kind = text(body, "kind")
            if kind not in {"intake", "message"}:
                raise ManualError("manual.invalid_review_intent", 422)
            drafts = tx.rows(
                "review_draft",
                session_id=session_id,
                principal_id=current.account_id,
                kind=kind,
                limit=1,
            )
            if not drafts or number(drafts[0], "revision") != integer(body["draft_revision"]):
                raise ManualError("manual.draft_changed", 409)
            draft = drafts[0]
            if instant(draft, "expires_at") <= self.clock():
                raise ManualError("manual.draft_expired", 410)
            existing = tx.review_records(
                "review_intent",
                session_id=session_id,
                principal_id=current.account_id,
                kind=kind,
                draft_revision=body["draft_revision"],
                limit=1,
            )
            if existing:
                return Outcome(
                    "ReviewIntentView",
                    review_projection.intent_view(
                        tx, existing[0], current, self.cipher, self.clock()
                    ),
                    text(existing[0], "operation_id"),
                    session_id,
                )
            # A different draft cannot silently replace an uncertain prior send.
            if tx.review_has_unresolved_intent(current.account_id, session_id, kind):
                raise ManualError("manual.pending_operation", 409)
            self.expected(body, row)
            if integer(body["expected_control_epoch"]) != number(current_guard, "control_epoch"):
                raise ManualError("manual.owner_changed", 409)
            value = self.cipher.decrypt(text(draft, "text_ciphertext"))
            if not value.strip():
                raise ManualError("manual.empty_draft", 422)
            if kind == "intake":
                if current.role not in PARTICIPANTS or row["disclosure_acknowledged"] is not True:
                    raise ManualError("manual.disclosure_required", 409)
                if body["locale"] != row["locale"]:
                    raise ManualError("manual.locale_mismatch", 422)
                action = "session_turns"
                payload: Record = {
                    "expected_revision": body["expected_revision"],
                    "client_turn_id": str(uuid4()),
                    "text": value,
                    "locale": body["locale"],
                }
            else:
                if current.role not in PARTICIPANTS and (
                    row["owner_id"] != current.account_id
                    or row["service_phase"] != "human_controlled"
                ):
                    raise ManualError("manual.current_owner_required", 409)
                action = "message_send"
                payload = {
                    "expected_revision": body["expected_revision"],
                    "expected_control_epoch": body["expected_control_epoch"],
                    "text": value,
                    "accepted_draft_id": None,
                }
            intent: Record = {
                "operation_id": str(uuid4()),
                "session_id": session_id,
                "principal_id": current.account_id,
                "kind": kind,
                "draft_revision": number(draft, "revision"),
                "action": action,
                "payload_ciphertext": self.cipher.encrypt(canonical(payload)),
                "created_at": self.clock(),
                "cancelled_at": None,
            }
            tx.connection.execute(
                "INSERT INTO core.review_intent(operation_id,session_id,principal_id,kind,"
                "draft_revision,action,payload_ciphertext,created_at) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                tuple(
                    intent[name]
                    for name in (
                        "operation_id",
                        "session_id",
                        "principal_id",
                        "kind",
                        "draft_revision",
                        "action",
                        "payload_ciphertext",
                        "created_at",
                    )
                ),
            )
            self.register_copy(
                tx,
                row,
                "review_intent",
                text(intent, "operation_id"),
                captured_at=instant(intent, "created_at"),
                expires_at=instant(intent, "created_at") + timedelta(days=1),
            )
            return Outcome(
                "ReviewIntentView",
                review_projection.intent_view(tx, intent, current, self.cipher, self.clock()),
                text(intent, "operation_id"),
                session_id,
            )

        return self._run(
            actor,
            "review_intent_prepare",
            key,
            data,
            session_id,
            prepare,
            contract="ReviewIntentPrepare",
        )

    def review_intent_cancel(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        def cancel(
            tx: Transaction,
            current: Actor,
            body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            self.require_session(session, guard)
            intent = tx.peek("review_intent", text(body, "operation_id"))
            if (
                intent is None
                or intent["session_id"] != session_id
                or intent["principal_id"] != current.account_id
            ):
                raise ManualError("manual.not_found", 404)
            operation = tx.peek("operation", text(intent, "operation_id"))
            if operation is not None and operation["state"] != "rejected":
                # A canonical commit/pending/unknown outcome must be reconciled;
                # cancellation cannot erase an effect or pretend it did not occur.
                raise ManualError("manual.operation_not_cancellable", 409)
            if intent.get("cancelled_at") is None:
                now = self.clock()
                tx.connection.execute(
                    "UPDATE core.review_intent SET cancelled_at=%s WHERE operation_id=%s",
                    (now, intent["operation_id"]),
                )
                intent["cancelled_at"] = now
                drafts = tx.rows(
                    "review_draft",
                    session_id=session_id,
                    principal_id=current.account_id,
                    kind=intent["kind"],
                    limit=1,
                )
                if drafts and drafts[0]["revision"] == intent["draft_revision"]:
                    draft = drafts[0]
                    draft["revision"] = number(draft, "revision") + 1
                    draft["updated_at"] = now
                    tx.put("review_draft", draft)
            return Outcome(
                "ReviewIntentView",
                review_projection.intent_view(tx, intent, current, self.cipher, self.clock()),
                text(intent, "operation_id"),
                session_id,
            )

        return self._run(
            actor,
            "review_intent_cancel",
            key,
            data,
            session_id,
            cancel,
            contract="ReviewIntentCancel",
        )
