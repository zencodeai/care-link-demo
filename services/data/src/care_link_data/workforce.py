"""Queue, exclusive assignment, endpoint handshake and explicit ownership."""

import secrets
from datetime import timedelta
from uuid import uuid4

from care_link_domain import Actor, ManualError

from . import projections
from .sessions import SessionService
from .store import Record, Transaction, instant, number, text
from .values import WORKFORCE, Outcome, dt, integer, stamp, token_digest


class WorkforceService(SessionService):
    def queue_list(self, actor: Actor, *, limit: int = 50, cursor: str | None = None) -> Record:
        if not 1 <= limit <= 50:
            raise ManualError("manual.invalid_page", 422)

        def read(
            tx: Transaction,
            current_actor: Actor,
            _body: Record,
            _session: Record | None,
            _guard: Record | None,
        ) -> Outcome:
            position = self._cursor_position(current_actor, "queue", cursor)
            after = (integer(position[0]), dt(position[1]), position[2]) if position else None
            rows = tx.queue_page(
                after, limit + 1, review_run_id=getattr(current_actor, "review_run_id", None)
            )
            selected = rows[:limit]
            next_cursor = (
                self._issue_cursor(
                    current_actor,
                    "queue",
                    [
                        str(number(selected[-1], "fixture_priority")),
                        stamp(instant(selected[-1], "requested_at")),
                        text(selected[-1], "id"),
                    ],
                )
                if len(rows) > limit
                else None
            )
            return Outcome(
                "QueuePage",
                {
                    "items": [self.queue_projection(tx, row) for row in selected],
                    "next_cursor": next_cursor,
                },
            )

        return self._run(
            actor, "queue_list", None, {"limit": limit, "cursor": cursor}, None, read, queue=True
        )

    def workforce_reserve(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        def reserve(
            tx: Transaction,
            current_actor: Actor,
            body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, current = self.require_session(session, guard)
            self.active(row)
            if body["worker_id"] != current_actor.account_id:
                raise ManualError("manual.reserve_self_required")
            queue = self.active_queue(tx, text(row, "id"))
            if queue is None or queue["status"] != "pending":
                raise ManualError("manual.queue_unavailable", 409)
            self.expected(body, queue)
            assignment = self.active_assignment(tx, text(row, "id"))
            if assignment:
                raise ManualError("manual.already_reserved", 409)
            now = self.clock()
            assignment = {
                "id": str(uuid4()),
                "session_id": row["id"],
                "worker_id": current_actor.account_id,
                "revision": 1,
                "reservation_id": str(uuid4()),
                "expires_at": now + timedelta(seconds=60),
                "status": "reserved",
                "control_epoch": number(current, "control_epoch"),
                "accepted_at": None,
                "connected_at": None,
                "created_at": now,
                "updated_at": now,
            }
            tx.put("assignment", assignment)
            # The eventual job is exact persisted metadata, never caller-selected work.
            tx.connection.execute(
                "INSERT INTO durable.due_job VALUES("
                "%s,'reservation_expiry',%s,%s,%s,%s,%s,%s,%s,'pending',NULL)",
                (
                    str(uuid4()),
                    assignment["id"],
                    row["id"],
                    assignment["revision"],
                    assignment["control_epoch"],
                    key,
                    assignment["expires_at"],
                    instant(assignment, "expires_at") + timedelta(minutes=5),
                ),
            )
            queue["status"] = "reserved"
            queue["revision"] = number(queue, "revision") + 1
            tx.put("queue", queue)
            self.bump(
                tx,
                row,
                current,
                event_type="queue_changed",
                resource_id=text(queue, "id"),
                resource_revision=number(queue, "revision"),
            )
            return Outcome(
                "AssignmentView",
                projections.assignment_view(assignment),
                text(assignment, "id"),
                text(row, "id"),
            )

        return self._run(
            actor, "workforce_reserve", key, data, session_id, reserve, contract="AssignmentCommand"
        )

    def _own_assignment(self, tx: Transaction, actor: Actor, session: Record) -> Record:
        assignment = self.active_assignment(tx, text(session, "id"))
        if assignment is None or assignment["worker_id"] != actor.account_id:
            raise ManualError("manual.assignment_scope", 404)
        if assignment["status"] == "reserved" and instant(assignment, "expires_at") <= self.clock():
            raise ManualError("manual.reservation_expired", 410)
        return assignment

    def workforce_accept(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        def accept(
            tx: Transaction,
            current_actor: Actor,
            body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, current = self.require_session(session, guard)
            self.active(row)
            assignment = self._own_assignment(tx, current_actor, row)
            self.expected(body, assignment)
            if assignment["status"] != "reserved":
                raise ManualError("manual.reservation_required", 409)
            assignment["status"] = "accepted"
            assignment["accepted_at"] = self.clock()
            assignment["updated_at"] = self.clock()
            assignment["revision"] = number(assignment, "revision") + 1
            tx.put("assignment", assignment)
            row["service_phase"] = "worker_assigned"
            queue = self.active_queue(tx, text(row, "id"))
            if queue:
                queue["status"] = "accepted"
                queue["revision"] = number(queue, "revision") + 1
                tx.put("queue", queue)
            self.bump(tx, row, current)
            return Outcome(
                "AssignmentView",
                projections.assignment_view(assignment),
                text(assignment, "id"),
                text(row, "id"),
            )

        return self._run(
            actor, "workforce_accept", key, data, session_id, accept, contract="RevisionCommand"
        )

    def workforce_prepare_transfer(
        self, actor: Actor, key: str, data: Record, session_id: str
    ) -> Record:
        def prepare(
            tx: Transaction,
            current_actor: Actor,
            body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, current = self.require_session(session, guard)
            self.active(row)
            assignment = self._own_assignment(tx, current_actor, row)
            self.expected(body, assignment)
            if assignment["status"] not in {"accepted", "connected"}:
                raise ManualError("manual.acceptance_required", 409)
            if assignment["status"] == "connected":
                # Explicit same-owner reconnection invalidates old channel
                # evidence without requeueing or rewinding accountable ownership.
                assignment["status"] = "accepted"
                assignment["channel_challenge_id"] = None
                assignment["revision"] = number(assignment, "revision") + 1
                assignment["updated_at"] = self.clock()
                tx.put("assignment", assignment)
            for old in tx.rows("challenge", session_id=row["id"], revoked=False):
                old["revoked"] = True
                tx.put("challenge", old)
            now = self.clock()
            challenge: Record = {
                "id": str(uuid4()),
                "session_id": row["id"],
                "assignment_id": assignment["id"],
                "control_epoch": number(current, "control_epoch"),
                "expires_at": now + timedelta(seconds=30),
                "revoked": False,
                "participant_nonce_hash": None,
                "worker_nonce_hash": None,
                "participant_binding": None,
                "worker_binding": None,
                "participant_generation": None,
                "worker_generation": None,
                "evidence_id": None,
                "created_at": now,
            }
            tx.put("challenge", challenge)
            row["service_phase"] = "handoff_pending"
            self.bump(tx, row, current)
            return Outcome(
                "TransferPreparation",
                {
                    "assignment": projections.assignment_view(assignment),
                    "challenge_id": challenge["id"],
                    "expires_at": stamp(instant(challenge, "expires_at")),
                },
                text(challenge, "id"),
                text(row, "id"),
            )

        return self._run(
            actor,
            "workforce_prepare_transfer",
            key,
            data,
            session_id,
            prepare,
            contract="RevisionCommand",
        )

    def _challenge(self, tx: Transaction, session: Record, guard: Record) -> Record:
        rows = tx.rows("challenge", session_id=session["id"], revoked=False, limit=2)
        if not rows or instant(rows[0], "expires_at") <= self.clock():
            raise ManualError("manual.challenge_expired", 410)
        row = rows[0]
        assignment = self.active_assignment(tx, text(session, "id"))
        if (
            assignment is None
            or row["assignment_id"] != assignment["id"]
            or row["control_epoch"] != guard["control_epoch"]
            or assignment["status"] != "accepted"
        ):
            raise ManualError("manual.challenge_stale", 409)
        return row

    @staticmethod
    def _party(actor: Actor, session: Record, assignment: Record) -> str:
        if session["participant_account_id"] == actor.account_id:
            return "participant"
        if assignment["worker_id"] == actor.account_id:
            return "worker"
        raise ManualError("manual.endpoint_scope", 404)

    def channel_challenge_read(self, actor: Actor, session_id: str) -> Record:
        def read(
            tx: Transaction,
            current_actor: Actor,
            _body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, current = self.require_session(session, guard)
            self.active(row)
            challenge = self._challenge(tx, row, current)
            assignment = (
                self._own_assignment(tx, current_actor, row)
                if row["participant_account_id"] != current_actor.account_id
                else self.active_assignment(tx, text(row, "id"))
            )
            if assignment is None:
                raise ManualError("manual.assignment_scope", 404)
            party = self._party(current_actor, row, assignment)
            if challenge[party + "_nonce_hash"] is not None:
                raise ManualError("manual.challenge_replacement_required", 409)
            if not self.channel.current(
                current_actor.account_id,
                current_actor.browser_session_digest,
                current_actor.transport_generation,
            ):
                raise ManualError("manual.channel_not_live", 409)
            nonce = secrets.token_urlsafe(32)
            challenge[party + "_nonce_hash"] = token_digest(nonce)
            challenge[party + "_binding"] = current_actor.browser_session_digest
            challenge[party + "_generation"] = current_actor.transport_generation
            tx.put("challenge", challenge)
            return Outcome(
                "ChannelChallengeView",
                {
                    "challenge_id": challenge["id"],
                    "assignment_id": assignment["id"],
                    "session_id": row["id"],
                    "party": party,
                    "nonce": nonce,
                    "transport_generation": str(current_actor.transport_generation),
                    "control_epoch": str(number(current, "control_epoch")),
                    "expires_at": stamp(instant(challenge, "expires_at")),
                },
            )

        return self._run(actor, "channel_challenge_read", None, {}, session_id, read)

    def channel_ack(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        def acknowledge(
            tx: Transaction,
            current_actor: Actor,
            body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, current = self.require_session(session, guard)
            self.active(row)
            self.expected(body, row)
            challenge = self._challenge(tx, row, current)
            assignment = self.active_assignment(tx, text(row, "id"))
            if assignment is None:
                raise ManualError("manual.assignment_scope", 404)
            party = self._party(current_actor, row, assignment)
            expected_hash = challenge[party + "_nonce_hash"]
            if (
                body["challenge_id"] != challenge["id"]
                or not isinstance(expected_hash, str)
                or not secrets.compare_digest(token_digest(text(body, "nonce")), expected_hash)
                or integer(body["expected_control_epoch"]) != number(current, "control_epoch")
                or integer(body["transport_generation"]) != current_actor.transport_generation
                or challenge[party + "_binding"] != current_actor.browser_session_digest
                or challenge[party + "_generation"] != current_actor.transport_generation
                or not self.channel.current(
                    current_actor.account_id,
                    current_actor.browser_session_digest,
                    current_actor.transport_generation,
                )
            ):
                raise ManualError("manual.channel_proof_invalid")
            if tx.rows("ack", challenge_id=challenge["id"], party=party, limit=1):
                raise ManualError("manual.nonce_consumed", 409)
            ack: Record = {
                "id": str(uuid4()),
                "challenge_id": challenge["id"],
                "session_id": row["id"],
                "party": party,
                "principal_id": current_actor.account_id,
                "browser_binding": current_actor.browser_session_digest,
                "transport_generation": current_actor.transport_generation,
                "identity_revision": current_actor.identity_revision,
                "role_revision": current_actor.role_revision,
                "session_access_revision": number(current, "access_revision"),
                "created_at": self.clock(),
            }
            tx.put("ack", ack)
            acks = tx.rows("ack", challenge_id=challenge["id"], limit=2)
            if (
                len(acks) == 2
                and self._current_ack_principals(tx, acks)
                and all(
                    self.channel.current(
                        text(item, "principal_id"),
                        text(item, "browser_binding"),
                        number(item, "transport_generation"),
                    )
                    for item in acks
                )
            ):
                challenge["evidence_id"] = str(uuid4())
                tx.put("challenge", challenge)
            # ACK is handshake metadata, not an aggregate revision transition;
            # concurrent parties can acknowledge the same exact session revision.
            return Outcome(
                "ChannelAckView",
                self._ack_projection(tx, current_actor, ack),
                text(ack, "id"),
                text(row, "id"),
            )

        return self._run(
            actor, "channel_ack", key, data, session_id, acknowledge, contract="ChannelAckSubmit"
        )

    def _ack_projection(self, tx: Transaction, actor: Actor, ack: Record) -> Record:
        view = super()._ack_projection(tx, actor, ack)
        if view["evidence_id"]:
            acks = tx.rows("ack", challenge_id=ack["challenge_id"], limit=2)
            if not self._current_ack_principals(tx, acks) or not all(
                self.channel.current(
                    text(item, "principal_id"),
                    text(item, "browser_binding"),
                    number(item, "transport_generation"),
                )
                for item in acks
            ):
                view["evidence_id"] = None
                view["state"] = "one_party_acknowledged"
        return view

    def _current_ack_principals(self, tx: Transaction, acks: list[Record]) -> bool:
        for ack in sorted(acks, key=lambda item: text(item, "principal_id")):
            principal = tx.get("principal", text(ack, "principal_id"))
            guard = tx.get("guard", text(ack, "session_id"))
            if guard is None or guard["access_revision"] != ack["session_access_revision"]:
                return False
            if ack["party"] == "participant":
                grants = tx.rows(
                    "acl",
                    session_id=ack["session_id"],
                    principal_id=ack["principal_id"],
                    purpose="support",
                )
                if not any(
                    grant["revoked_at"] is None
                    and (
                        grant["valid_until"] is None or instant(grant, "valid_until") > self.clock()
                    )
                    for grant in grants
                ):
                    return False
            if (
                principal is None
                or principal["revoked"] is not False
                or principal["identity_revision"] != ack["identity_revision"]
                or principal["role_revision"] != ack["role_revision"]
            ):
                return False
        return True

    def workforce_confirm_transfer(
        self, actor: Actor, key: str, data: Record, session_id: str
    ) -> Record:
        def confirm(
            tx: Transaction,
            current_actor: Actor,
            body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, current = self.require_session(session, guard)
            self.active(row)
            self.expected(body, row)
            assignment = self._own_assignment(tx, current_actor, row)
            challenge = self._challenge(tx, row, current)
            acks = tx.rows("ack", challenge_id=challenge["id"], limit=2)
            worker_ack = next((ack for ack in acks if ack["party"] == "worker"), None)
            if (
                row["service_phase"] != "handoff_pending"
                or body["assignment_id"] != assignment["id"]
                or integer(body["expected_control_epoch"]) != number(current, "control_epoch")
                or challenge["evidence_id"] is None
                or body["channel_evidence_id"] != challenge["evidence_id"]
                or worker_ack is None
                or body["worker_ack_id"] != worker_ack["id"]
                or len(acks) != 2
                or not self._current_ack_principals(tx, acks)
                or not all(
                    self.channel.current(
                        text(item, "principal_id"),
                        text(item, "browser_binding"),
                        number(item, "transport_generation"),
                    )
                    for item in acks
                )
            ):
                raise ManualError("manual.two_party_channel_required", 409)
            row["owner_id"] = current_actor.account_id
            row["service_phase"] = "human_controlled"
            current["control_epoch"] = number(current, "control_epoch") + 1
            assignment["status"] = "connected"
            assignment["connected_at"] = self.clock()
            assignment["channel_challenge_id"] = challenge["id"]
            assignment["control_epoch"] = number(current, "control_epoch")
            assignment["revision"] = number(assignment, "revision") + 1
            tx.put("assignment", assignment)
            challenge["revoked"] = True
            tx.put("challenge", challenge)
            self.bump(tx, row, current)
            return Outcome(
                "SessionView",
                self.session_projection(tx, row, current),
                text(row, "id"),
                text(row, "id"),
            )

        return self._run(
            actor,
            "workforce_confirm_transfer",
            key,
            data,
            session_id,
            confirm,
            contract="TransferConfirm",
        )

    def workforce_transfer_failed(
        self, actor: Actor, key: str, data: Record, session_id: str
    ) -> Record:
        def failed(
            tx: Transaction,
            current_actor: Actor,
            body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, current = self.require_session(session, guard)
            self.active(row)
            self.expected(body, row)
            assignment = self._own_assignment(tx, current_actor, row)
            assignment["status"] = "released"
            assignment["revision"] = number(assignment, "revision") + 1
            tx.put("assignment", assignment)
            for challenge in tx.rows("challenge", session_id=row["id"], revoked=False):
                challenge["revoked"] = True
                tx.put("challenge", challenge)
            queue = self.active_queue(tx, text(row, "id"))
            if queue is None:
                queue = self.enqueue(tx, row, current)
            queue["status"] = "pending"
            queue["revision"] = number(queue, "revision") + 1
            queue["next_review_at"] = self.clock() + timedelta(seconds=60)
            tx.put("queue", queue)
            row["service_phase"] = "queued"
            row["owner_id"] = None
            current["control_epoch"] = number(current, "control_epoch") + 1
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
            actor,
            "workforce_transfer_failed",
            key,
            data,
            session_id,
            failed,
            contract="ReasonCommand",
        )

    def workforce_observe(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        def observe(
            tx: Transaction,
            current_actor: Actor,
            body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, current = self.require_session(session, guard)
            queue = self.active_queue(tx, text(row, "id"))
            if queue is None:
                raise ManualError("manual.queue_unavailable", 404)
            self.expected(body, queue)
            expires = dt(body["expires_at"])
            if not self.clock() < expires <= self.clock() + timedelta(minutes=15):
                raise ManualError("manual.observe_expiry", 422)
            tx.put(
                "acl",
                {
                    "session_id": row["id"],
                    "principal_id": current_actor.account_id,
                    "purpose": body["scope"],
                    "fields": [
                        "needs",
                        "preferences",
                        "observations",
                        "rationale",
                        "summary",
                        "outcome",
                    ],
                    "valid_until": expires,
                    "revoked_at": None,
                    "revision": 1,
                },
            )
            current["access_revision"] = number(current, "access_revision") + 1
            self.bump(tx, row, current)
            return self.command(row)

        return self._run(
            actor, "workforce_observe", key, data, session_id, observe, contract="ObserveCommand"
        )

    def workforce_takeover(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        def takeover(
            tx: Transaction,
            _actor: Actor,
            body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, current = self.require_session(session, guard)
            self.active(row)
            self.expected(body, row)
            target = tx.get("principal", text(body, "worker_id"))
            if target is None or target["revoked"] is not False or target["role"] not in WORKFORCE:
                raise ManualError("manual.target_worker_unavailable", 404)
            old = self.active_assignment(tx, text(row, "id"))
            if old:
                old["status"] = "released"
                old["revision"] = number(old, "revision") + 1
                tx.put("assignment", old)
            for challenge in tx.rows("challenge", session_id=row["id"], revoked=False):
                challenge["revoked"] = True
                tx.put("challenge", challenge)
            current["control_epoch"] = number(current, "control_epoch") + 1
            row["owner_id"] = body["worker_id"]
            row["service_phase"] = "worker_assigned"
            now = self.clock()
            assignment: Record = {
                "id": str(uuid4()),
                "session_id": row["id"],
                "worker_id": body["worker_id"],
                "revision": number(row, "revision") + 1,
                "reservation_id": str(uuid4()),
                "expires_at": now + timedelta(seconds=60),
                "status": "accepted",
                "control_epoch": number(current, "control_epoch"),
                "accepted_at": now,
                "connected_at": None,
                "created_at": now,
                "updated_at": now,
            }
            tx.put("assignment", assignment)
            self.bump(tx, row, current)
            return Outcome(
                "SessionView",
                self.session_projection(tx, row, current),
                text(row, "id"),
                text(row, "id"),
            )

        return self._run(
            actor,
            "workforce_takeover",
            key,
            data,
            session_id,
            takeover,
            contract="AssignmentCommand",
        )
