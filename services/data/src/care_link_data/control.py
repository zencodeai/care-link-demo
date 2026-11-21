"""Restrictive inline controls and bounded manual queue maintenance."""

import time
from datetime import timedelta
from uuid import uuid4

from care_link_contracts import validate_contract
from care_link_domain import Actor, ManualError

from .consent import Consent
from .directory import Directory
from .dispatches import Dispatches
from .plans import Plans
from .review import ReviewService
from .store import Record, Transaction, instant, number, text
from .values import Outcome, digest, integer, object_value


class ManualService(Dispatches, Plans, Consent, Directory, ReviewService):
    def own_reports_read(self, actor: Actor, session_id: str) -> Record:
        import json

        from .projections import assertion_view

        def read(
            tx: Transaction,
            current: Actor,
            _data: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, _ = self.require_session(session, guard)
            if row["participant_account_id"] != current.account_id:
                raise ManualError("manual.not_found", 404)
            reports = tx.rows(
                "assertion", session_id=session_id, author_id=current.account_id, limit=100
            )
            if len(reports) == 100:
                raise ManualError("manual.report_history_limit", 503)
            values = [
                assertion_view(report, self.cipher, json.loads)
                for report in reports
                if report["subject_id"] == row["persona_id"]
            ]
            return Outcome("OwnReportPage", {"items": values, "next_cursor": None})

        return self._run(actor, "own_reports_read", None, {}, session_id, read)

    def _replay(self, tx: Transaction, actor: Actor, old: Record, snapshot: Record) -> Record:
        from .consent import consent_view, grant_current, owns_subject

        if old["state"] != "committed":
            return super()._replay(tx, actor, old, snapshot)
        resource = old["resource_id"]
        if not isinstance(resource, str):
            return super()._replay(tx, actor, old, snapshot)
        if old["result_type"] in {"ReferralView", "DispatchView", "ReviewView"}:
            repository = {
                "ReferralView": "referral",
                "DispatchView": "dispatch",
                "ReviewView": "referral_review",
            }[text(old, "result_type")]
            value = tx.get(repository, resource)
            if value is None:
                raise ManualError("manual.not_found", 404)
            if old["result_type"] == "ReferralView":
                return self.referral_projection(tx, actor, value)
            if old["result_type"] == "DispatchView":
                return self.dispatch_projection(value)
            return self.review_projection(value)
        if old["result_type"] == "PlanView":
            plan = tx.get("plan", resource)
            if plan is None:
                raise ManualError("manual.not_found", 404)
            return self.plan_projection(tx, actor, plan)
        if old["result_type"] == "ConsentView":
            grant = tx.get("consent", resource)
            session = snapshot["session"]
            if (
                grant is None
                or session is None
                or not (
                    owns_subject(tx, actor, object_value(session))
                    or grant["grantor_id"] == actor.account_id
                    or grant["recipient_kind"] == "account"
                    and grant["recipient_id"] == actor.account_id
                    and grant_current(tx, grant, self.clock())
                )
            ):
                raise ManualError("manual.not_found", 404)
            return consent_view(grant)
        if old["result_type"] == "DirectoryView":
            return self.directory_projection(tx, self.lookup_directory(tx, resource))
        if old["operation_name"] == "consent_revoke":
            grant = tx.get("consent", resource)
            if grant is None:
                raise ManualError("manual.not_found", 404)
            return {
                "operation_id": old["operation_id"],
                "state": "committed",
                "resource_id": resource,
                "revision": str(number(grant, "revision")),
                "audit_ref": old["canonical_audit_id"],
            }
        if old["operation_name"] == "directory_suspend":
            guard = tx.get("service_guard", resource)
            if guard is None:
                raise ManualError("manual.not_found", 404)
            return {
                "operation_id": old["operation_id"],
                "state": "committed",
                "resource_id": resource,
                "revision": str(number(guard, "current_revision")),
                "audit_ref": old["canonical_audit_id"],
            }
        return super()._replay(tx, actor, old, snapshot)

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
        planning = object_value(request["planning"]) if request.get("planning") else None
        arguments: Record | None = None
        if action.startswith(
            (
                "plan_",
                "consent_",
                "directory_",
                "referral_",
                "dispatch_",
                "dispatcher_",
                "receipt_",
                "task_",
                "draft_",
                "assistance_",
            )
        ):
            if planning is None or planning["action"] != action:
                raise ManualError("manual.planning_target_required", 422)
            arguments = {
                **object_value(planning["arguments"]),
                **object_value(planning["path_arguments"]),
            }
            if action.startswith(("task_", "draft_", "assistance_")):
                from .assistance.metadata import metadata_scope

                session_id = metadata_scope(self, current, action, arguments)
            elif action in {"referral_draft", "referral_sources"}:
                session_id = text(arguments, "session_id")
            elif action.startswith("referral_"):
                session_id = self._referral_session(current, text(arguments, "referral_id"))
            elif action.startswith(("dispatch_", "dispatcher_", "receipt_")):
                session_id = self._referral_session(
                    current, text(arguments, "dispatch_id"), "dispatch"
                )
            elif action == "plan_create":
                session_id = self._subject_session(
                    current, text(arguments, "subject_id"), text(planning, "operation_id")
                )
            elif action.startswith("plan_"):
                session_id = self._plan_session(current, text(arguments, "plan_id"))
            elif action == "consent_grant":
                session_id = text(arguments, "session_id")
            elif action.startswith("consent_"):
                session_id = self._consent_session(current, text(arguments, "grant_id"))
            else:
                session_id = None
        with self.store.transaction(current, session_id, queue=action == "queue_list") as tx:
            snapshot = self._snapshot(tx, current, session_id)
            current = self._fresh_actor(current)
            self.assert_journal_current(snapshot)
            policy_input = self._policy_input(
                tx,
                current,
                action,
                text(planning, "operation_id") if planning else str(uuid4()),
                text(request, "payload_digest"),
                snapshot,
                arguments=arguments,
            )
            control = object_value(snapshot["control"])
            facts = object_value(policy_input["authority_facts"])
            session = snapshot["session"]
            complete = facts["resource_owned_or_assigned"] is True
            if scope["subject_id"] is not None and (
                session is None or object_value(session)["persona_id"] != scope["subject_id"]
            ):
                complete = False
            versions = object_value(policy_input["versions"])
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
            if planning is not None:
                result.update(
                    {
                        "resolved_scope": policy_input["scope"],
                        "consent_id": policy_input["consent_id"],
                        **(
                            {
                                "review_id": policy_input["review_id"],
                                "referral_payload_digest": policy_input["referral_payload_digest"],
                            }
                            if "referral_payload_digest" in policy_input
                            else {}
                        ),
                        "disclosure_grants": policy_input.get("disclosure_grants", []),
                        "artifact_digests": policy_input["artifact_digests"],
                        "directory_bindings": policy_input.get("directory_bindings", []),
                    }
                )
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
