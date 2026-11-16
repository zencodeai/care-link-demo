"""Restrictive inline controls and bounded manual queue maintenance."""

import time
from datetime import timedelta
from uuid import uuid4

from care_link_contracts import validate_contract
from care_link_domain import Actor, ManualError

from .review import ReviewService
from .store import Record, Transaction, instant, number, text
from .values import Outcome, digest, integer, object_value


class ManualService(ReviewService):
    def authority_metadata(self, actor: Actor, request: Record) -> Record:
        """Exact metadata preflight, after transport verifies signed delegation.

        It contains no content and supplies no positive permission cache; final
        commands evaluate policy and recheck all current guards independently.
        """
        started = time.monotonic()
        validate_contract("MetadataRequest", request)
        scope = object_value(request["scope"])
        session_id = scope["session_id"] if isinstance(scope["session_id"], str) else None
        action = text(request, "action")
        current = self._fresh_actor(actor)
        with self.store.transaction(current, session_id, queue=action == "queue_list") as tx:
            snapshot = self._snapshot(tx, current, session_id)
            current = self._fresh_actor(current)
            self.assert_journal_current(snapshot)
            policy_input = self._policy_input(
                tx, current, action, str(uuid4()), text(request, "payload_digest"), snapshot
            )
            control = object_value(snapshot["control"])
            facts = object_value(policy_input["authority_facts"])
            session = snapshot["session"]
            complete = facts["resource_owned_or_assigned"] is True
            if scope["subject_id"] is not None and (
                session is None or object_value(session)["persona_id"] != scope["subject_id"]
            ):
                complete = False
            versions = self._versions(current, snapshot)
            if not complete:
                facts["resource_owned_or_assigned"] = False
                facts["field_scope_allowed"] = False
                for name in [
                    "subject",
                    "session_access",
                    "assignment",
                    "resource",
                    "control_epoch",
                ]:
                    versions[name] = "0"
            result: Record = {
                "versions": versions,
                "authority_facts": facts,
                "bundle_digest": control["bundle_digest"],
                "mode": control["mode"],
                "complete": complete,
            }
            validate_contract("MetadataResult", result)
            self._audit(
                tx,
                current,
                "authority_metadata",
                str(uuid4()),
                digest(request),
                result,
                versions,
                decision="PERMIT" if complete else "DENY",
            )
            if time.monotonic() - started >= 1 or (
                actor.request_deadline is not None and actor.request_deadline <= self.clock()
            ):
                raise ManualError("manual.deadline_exceeded", 503)
        return result

    def operation_status(self, actor: Actor, operation_id: str) -> Record:
        def status(
            tx: Transaction,
            current_actor: Actor,
            _body: Record,
            _session: Record | None,
            _guard: Record | None,
        ) -> Outcome:
            operation = tx.get("operation", operation_id)
            if operation is None or operation["principal_id"] != current_actor.account_id:
                raise ManualError("manual.not_found", 404)
            from .review_scope import scope_allowed

            sid = operation["session_id"]
            run = (
                tx.peek("review_run", current_actor.review_run_id)
                if current_actor.review_run_id
                else None
            )
            if isinstance(sid, str) and not scope_allowed(
                tx, current_actor, "operation_status", sid, run
            ):
                raise ManualError("manual.not_found", 404)
            return Outcome(
                "OperationStatus",
                {
                    "operation_id": operation_id,
                    "state": operation["state"],
                    "safe_reason": "manual.fresh_recovery_required"
                    if operation["state"] == "replacement_unavailable"
                    else None,
                },
            )

        return self._run(
            actor, "operation_status", None, {"operation_id": operation_id}, None, status
        )

    def append_restriction(
        self,
        tx: Transaction,
        key: str,
        control: Record,
        restriction: Record,
        scope: Record,
    ) -> None:
        before = self.journal.head()
        request: Record = {
            "command_id": key,
            "expected_tip": str(before.tip),
            "kind": "restrict_intent",
            "scope": scope,
            "restriction": restriction,
            "binding_digest": digest(restriction),
            "db_operation_id": key,
            "relaxation_evidence_digest": None,
        }
        after = self.journal.append(request)
        if (
            after.journal_id != before.journal_id
            or after.generation != before.generation
            or after.restriction_barrier <= before.restriction_barrier
        ):
            raise ManualError("manual.journal_append_invalid", 503)
        control["restriction_barrier"] = after.restriction_barrier
        control["journal_tip_seen"] = after.tip
        tx.put("control", control)
        tx.put(
            "recovery",
            {
                "command_id": key,
                "intent_seq": after.tip,
                "barrier_seq": after.restriction_barrier,
                "payload_digest": digest(request),
                "state": "applied",
                "db_operation_id": key,
                "applied_at": self.clock(),
            },
        )

    def control_change(self, actor: Actor, key: str, data: Record) -> Record:
        def change(
            tx: Transaction,
            _actor: Actor,
            body: Record,
            _session: Record | None,
            _guard: Record | None,
        ) -> Outcome:
            control = tx.get("control", "demo")
            if control is None:
                raise ManualError("manual.bootstrap_missing", 503)
            if integer(body["expected_revision"]) != number(control, "epoch"):
                raise ManualError("manual.stale_revision", 409)
            if body["mode"] == "normal" or (
                control["mode"] in {"restricted", "quarantine"} and body["mode"] == "ai_disabled"
            ):
                raise ManualError("manual.relaxation_not_admitted")
            control["epoch"] = number(control, "epoch") + 1
            self.append_restriction(
                tx,
                key,
                control,
                {
                    "kind": "kill",
                    "mode": body["mode"],
                    "epoch": str(number(control, "epoch")),
                    "bundle_digest": control["bundle_digest"],
                },
                {
                    "session_id": None,
                    "subject_id": None,
                    "purpose": "service_operations",
                    "fields": [],
                    "recipient_id": None,
                },
            )
            control["mode"] = body["mode"]
            tx.put("control", control)
            return Outcome(
                "CommandResult",
                {
                    "operation_id": key,
                    "state": "committed",
                    "resource_id": None,
                    "revision": str(number(control, "epoch")),
                    "audit_ref": str(uuid4()),
                },
            )

        return self._run(actor, "control_change", key, data, None, change, contract="ControlChange")

    def restrict_principal(self, actor: Actor, key: str, data: Record) -> Record:
        """Named internal current-authority revocation; operator/security only.

        The caller adapter verifies the exact service delegation. It supplies
        principal_id and expected_identity_revision, never a new role/permission.
        """
        if set(data) != {"principal_id", "expected_identity_revision"}:
            raise ManualError("manual.invalid_revoke", 422)

        def revoke(
            tx: Transaction,
            _actor: Actor,
            body: Record,
            _session: Record | None,
            _guard: Record | None,
        ) -> Outcome:
            target = tx.get("principal", text(body, "principal_id"))
            control = tx.get("control", "demo")
            if target is None or control is None:
                raise ManualError("manual.not_found", 404)
            if integer(body["expected_identity_revision"]) != number(target, "identity_revision"):
                raise ManualError("manual.identity_changed", 409)
            target["identity_revision"] = number(target, "identity_revision") + 1
            self.append_restriction(
                tx,
                key,
                control,
                {
                    "kind": "identity_revoke",
                    "principal_id": target["principal_id"],
                    "identity_revision": str(number(target, "identity_revision")),
                    "disabled": True,
                },
                {
                    "session_id": None,
                    "subject_id": None,
                    "purpose": "service_operations",
                    "fields": [],
                    "recipient_id": None,
                },
            )
            target["revoked"] = True
            tx.put("principal", target)
            return Outcome(
                "CommandResult",
                {
                    "operation_id": key,
                    "state": "committed",
                    "resource_id": target["principal_id"],
                    "revision": str(number(target, "identity_revision")),
                    "audit_ref": str(uuid4()),
                },
            )

        return self._run(actor, "manual_identity_restrict", key, data, None, revoke)

    def review_queue(self, actor: Actor, key: str, data: Record) -> Record:
        """Bounded explicit queue review; no silent session end or fake staffing."""
        if set(data) != {"session_id", "expected_revision"}:
            raise ManualError("manual.invalid_job", 422)

        def review(
            tx: Transaction,
            _actor: Actor,
            body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, current = self.require_session(session, guard)
            self.active(row)
            self.expected(body, row)
            assignment = self.active_assignment(tx, text(row, "id"))
            queue = self.active_queue(tx, text(row, "id"))
            if queue is None:
                raise ManualError("manual.queue_unavailable", 404)
            if (
                assignment
                and assignment["status"] == "reserved"
                and instant(assignment, "expires_at") <= self.clock()
            ):
                assignment["status"] = "expired"
                assignment["revision"] = number(assignment, "revision") + 1
                tx.put("assignment", assignment)
                queue["status"] = "pending"
                row["service_phase"] = "queued"
            # Load mode is measured from actual pending entries, with deterministic
            # configured outage precedence. ETA remains unknown.
            pending = tx.rows("queue", status="pending", limit=100)
            fixture = self.fixtures.get(str(row["fixture_id"]), {})
            queue["mode"] = (
                "regional_outage"
                if fixture.get("regional_outage")
                else "partner_unavailable"
                if fixture.get("partner_unavailable")
                else "severe"
                if len(pending) >= 6
                else "elevated"
                if len(pending) >= 3
                else "normal"
            )
            queue["next_review_at"] = self.clock() + timedelta(seconds=60)
            queue["revision"] = number(queue, "revision") + 1
            queue["updated_at"] = self.clock()
            tx.put("queue", queue)
            self.bump(
                tx,
                row,
                current,
                event_type="queue_changed",
                resource_id=text(queue, "id"),
                resource_revision=number(queue, "revision"),
            )
            return self.command(row)

        return self._run(
            actor, "manual_queue_review", key, data, text(data, "session_id"), review, queue=True
        )
