"""Guarded application transaction boundary for named manual commands.

Policy is evaluated over metadata before locks, then its complete binding and
all current guard values are compared under the final ordered lock set.
"""

import json
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from care_link_contracts import validate_contract
from care_link_domain import (
    Actor,
    AuthorityPort,
    ChannelPort,
    CipherPort,
    JournalPort,
    ManualError,
    PolicyPort,
)

from . import projections, review_projection, review_scope
from .directory_admission import VerifiedDirectoryAdmission
from .store import PostgresStore, Record, Transaction, instant, number, text
from .values import (
    PARTICIPANTS,
    ROLES,
    WORKFORCE,
    Outcome,
    canonical,
    digest,
    dt,
    integer,
    object_value,
    stamp,
)

Handler = Callable[[Transaction, Actor, Record, Record | None, Record | None], Outcome]


class Engine:
    def __init__(
        self,
        store: PostgresStore,
        authority: AuthorityPort,
        policy: PolicyPort,
        journal: JournalPort,
        cipher: CipherPort,
        *,
        channel: ChannelPort,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        disclosure_templates: dict[str, Record] | None = None,
        fixtures: dict[str, Record] | None = None,
        cursor_key: bytes | None = None,
        scenario_bindings: dict[str, str] | None = None,
        content_key_ref: str | None = None,
        directory_admission: VerifiedDirectoryAdmission | None = None,
    ) -> None:
        self.store, self.authority, self.policy, self.journal, self.cipher = (
            store,
            authority,
            policy,
            journal,
            cipher,
        )
        self.channel, self.clock = channel, clock
        self.disclosure_templates = disclosure_templates or {}
        self.fixtures = fixtures or {}
        self.cursor_key = cursor_key
        self.scenario_bindings = scenario_bindings or {}
        self.content_key_ref = content_key_ref or getattr(cipher, "key_ref", None)
        # Admission manifests are deployment inputs, never directory feed fields.
        self.directory_artifacts = directory_admission.manifests if directory_admission else {}

    @staticmethod
    def active_assignment(tx: Transaction, session_id: str) -> Record | None:
        for status in ("connected", "accepted", "reserved"):
            rows = tx.rows("assignment", session_id=session_id, status=status, limit=2)
            if rows:
                return rows[0]
        return None

    @staticmethod
    def active_queue(tx: Transaction, session_id: str) -> Record | None:
        for status in ("pending", "reserved", "accepted"):
            rows = tx.rows("queue", session_id=session_id, status=status, limit=2)
            if rows:
                return rows[0]
        return None

    def _snapshot(
        self,
        tx: Transaction,
        actor: Actor,
        session_id: str | None,
        extra_principals: tuple[str, ...] = (),
    ) -> Record:
        control = tx.get("control", "demo")
        if control is None:
            raise ManualError("manual.bootstrap_missing", 503)
        session = tx.peek("session", session_id) if session_id else None
        assignment = None
        if session_id:
            # Metadata-only discovery; all are re-read after ordered guards.
            locked = tx.locked
            tx.locked = False
            try:
                assignment = self.active_assignment(tx, session_id)
            finally:
                tx.locked = locked
        principals = {actor.account_id, *extra_principals}
        if session:
            principals.add(text(session, "participant_account_id"))
        if assignment:
            principals.add(text(assignment, "worker_id"))
        current_principal: Record | None = None
        for principal in sorted(principals):
            record = tx.get("principal", principal)
            if principal == actor.account_id:
                current_principal = record
        if current_principal is None or current_principal["revoked"] is not False:
            raise ManualError("manual.principal_unavailable")
        if (
            number(current_principal, "identity_revision") != actor.identity_revision
            or number(current_principal, "role_revision") != actor.role_revision
            or current_principal["role"] != actor.role
        ):
            raise ManualError("manual.principal_changed")
        subject = tx.get("subject", text(session, "persona_id")) if session else None
        guard = tx.get("guard", session_id) if session_id else None
        if session and (subject is None or guard is None or subject["delete_state"] != "active"):
            raise ManualError("manual.session_unavailable", 404)
        if session_id:
            session = tx.get("session", session_id)
            assignment = self.active_assignment(tx, session_id)
        return {
            "control": control,
            "principal": current_principal,
            "subject": subject,
            "session": session,
            "guard": guard,
            "assignment": assignment,
            "review_run": review_scope.run_snapshot(tx, actor),
        }

    def _accessible(self, tx: Transaction, actor: Actor, action: str, snapshot: Record) -> bool:
        if actor.role not in ROLES.get(action, frozenset()):
            return False
        if actor.role not in PARTICIPANTS and not actor.mfa:
            return False
        session = snapshot["session"]
        if not review_scope.scope_allowed(
            tx,
            actor,
            action,
            text(object_value(session), "id") if session else None,
            object_value(snapshot["review_run"]) if snapshot.get("review_run") else None,
        ):
            return False
        if action.startswith(("plan_", "consent_")):
            if session is None:
                # Preflight contains no target content. Resource discovery and
                # exact current field authorization occur in the final command.
                return True
            from .consent import capability_access

            return capability_access(tx, actor, action, object_value(session), self.clock())
        if action.startswith("directory_"):
            return True
        if session is None:
            return action in {
                "review_workspace",
                "session_create",
                "queue_list",
                "control_change",
                "operation_status",
                "manual_identity_restrict",
            }
        row = object_value(session)
        if row["participant_account_id"] == actor.account_id:
            grants = tx.rows(
                "acl",
                session_id=row["id"],
                principal_id=actor.account_id,
                purpose="support",
                limit=1,
            )
            return (
                actor.role in PARTICIPANTS
                and bool(grants)
                and grants[0]["revoked_at"] is None
                and (
                    grants[0]["valid_until"] is None
                    or instant(grants[0], "valid_until") > self.clock()
                )
            )
        assignment = snapshot["assignment"]
        if assignment:
            current = object_value(assignment)
            if current["worker_id"] == actor.account_id and current["status"] in {
                "accepted",
                "connected",
            }:
                return actor.role in WORKFORCE
            if current["worker_id"] == actor.account_id and action in {
                "workforce_accept",
                "workforce_reserve",
                "workforce_transfer_failed",
            }:
                return actor.role in WORKFORCE
        if action == "manual_queue_review":
            return actor.role == "operator"
        if action in {"workforce_reserve", "workforce_observe"}:
            return actor.role in WORKFORCE
        if actor.role == "supervisor":
            grants = tx.rows("acl", session_id=row["id"], principal_id=actor.account_id, limit=10)
            for grant in grants:
                if (
                    grant["revoked_at"] is None
                    and grant["valid_until"] is not None
                    and instant(grant, "valid_until") > self.clock()
                ):
                    if action == "workforce_takeover":
                        return grant["purpose"] == "interrupt"
                    return action in {"session_read", "messages_read", "session_events"}
        return False

    def _versions(self, actor: Actor, snapshot: Record) -> Record:
        control = object_value(snapshot["control"])
        session = object_value(snapshot["session"]) if snapshot["session"] else None
        guard = object_value(snapshot["guard"]) if snapshot["guard"] else None
        subject = object_value(snapshot["subject"]) if snapshot["subject"] else None
        assignment = object_value(snapshot["assignment"]) if snapshot["assignment"] else None
        versions: Record = {
            "identity": str(actor.identity_revision),
            "roles": str(actor.role_revision),
            "subject": str(number(subject, "authority_revision")) if subject else "0",
            "session_access": str(number(guard, "access_revision")) if guard else "0",
            "assignment": str(number(assignment, "revision")) if assignment else "0",
            "resource": str(number(session, "revision")) if session else "0",
            "directory": "0",
            "policy_epoch": str(number(control, "epoch")),
            "control_epoch": str(number(guard, "control_epoch")) if guard else "0",
            "serving_generation": str(number(control, "serving_generation")),
            "restriction_barrier": str(number(control, "restriction_barrier")),
        }
        if snapshot.get("review_run"):
            versions["review_run"] = str(number(object_value(snapshot["review_run"]), "revision"))
        return versions

    def _policy_input(
        self,
        tx: Transaction,
        actor: Actor,
        action: str,
        operation_id: str,
        payload_digest: str,
        snapshot: Record,
        *,
        arguments: Record | None = None,
    ) -> Record:
        session = object_value(snapshot["session"]) if snapshot["session"] else None
        control = object_value(snapshot["control"])
        allowed = self._accessible(tx, actor, action, snapshot)
        purpose = (
            "service_operations"
            if action.startswith("workforce_")
            or action
            in {"queue_list", "control_change", "manual_identity_restrict", "manual_queue_review"}
            else "plan"
            if action.startswith("plan_")
            else "governance"
            if action == "directory_ingest"
            else "security"
            if action == "directory_suspend"
            else "support"
        )
        request: Record = {
            "operation_id": operation_id,
            "actor": {
                "kind": "human",
                "principal_id": actor.account_id,
                "workload_id": "spiffe://care-link.demo/demo/data",
                "role": actor.role,
                "assurance": "AL2" if actor.mfa else "AL1",
                "identity_evidence_id": actor.identity_evidence_id,
                "task_id": None,
                "job_id": None,
            },
            "action": action,
            "scope": {
                "session_id": session["id"] if session else None,
                "subject_id": session["persona_id"] if session else None,
                "purpose": purpose,
                "fields": [],
                "recipient_id": None,
            },
            "tags": {"environment": "demo", "population": "synthetic"},
            "jurisdiction": session["jurisdiction"] if session else None,
            "versions": self._versions(actor, snapshot),
            "payload_digest": payload_digest,
            "consent_id": None,
            "review_id": None,
            "bundle_digest": control["bundle_digest"],
            "artifact_digests": [],
            "mode": control["mode"],
            "audit_ready": True,
            "authority_complete": True,
            "authority_facts": {
                "actor_role_allowed": actor.role in ROLES.get(action, frozenset()),
                "resource_owned_or_assigned": allowed,
                "field_scope_allowed": allowed,
                "source_current": True,
                "artifact_admitted": True,
                "jurisdiction_allowed": True,
                "workload_unfenced": True,
                "consent": {
                    "required": False,
                    "valid": False,
                    "grant_id": None,
                    "subject_revision": "0",
                    "scope_digest": None,
                    "effective_at": None,
                    "expires_at": None,
                    "recipient_id": None,
                    "fields": [],
                },
                "review": {
                    "required": False,
                    "valid": False,
                    "review_id": None,
                    "payload_digest": None,
                    "reviewer_id": None,
                    "expires_at": None,
                },
                "exception_id": None,
                "exception_expires_at": None,
            },
        }

        if arguments is not None and action.startswith(("plan_", "consent_", "directory_")):
            from .planning_policy import enrich_planning_policy

            enrich_planning_policy(
                tx,
                actor,
                action,
                arguments,
                snapshot,
                request,
                self.clock(),
                self.directory_artifacts,
            )
        return request

    def _fresh_actor(self, actor: Actor) -> Actor:
        if actor.request_deadline is not None and actor.request_deadline <= self.clock():
            raise ManualError("manual.deadline_exceeded", 503)
        fresh = self.authority.current(actor)
        # Provider lookup can consume the remaining immutable request budget.
        # A timed-out request does not invalidate an otherwise valid identity.
        if actor.request_deadline is not None and actor.request_deadline <= self.clock():
            raise ManualError("manual.deadline_exceeded", 503)
        if (
            fresh.account_id != actor.account_id
            or fresh.role != actor.role
            or fresh.identity_revision != actor.identity_revision
            or fresh.role_revision != actor.role_revision
            or fresh.browser_session_digest != actor.browser_session_digest
            or fresh.transport_generation != actor.transport_generation
            or (fresh.review_run_id, fresh.review_slot_id, fresh.review_origin)
            != (actor.review_run_id, actor.review_slot_id, actor.review_origin)
            or fresh.expires_at <= self.clock()
            or fresh.auth_time > self.clock() + timedelta(seconds=1)
            or (
                fresh.role not in PARTICIPANTS
                and (not fresh.mfa or fresh.auth_time + timedelta(minutes=5) <= self.clock())
            )
        ):
            raise ManualError("manual.identity_changed")
        return replace(fresh, request_deadline=actor.request_deadline)

    def check_policy_decision(self, decision: Record, request: Record) -> None:
        validate_contract("PolicyDecision", decision)
        if (
            decision["decision"] != "PERMIT"
            or decision["binding_digest"] != digest(request)
            or decision["versions"] != request["versions"]
            or decision["bundle_digest"] != request["bundle_digest"]
            or dt(decision["expires_at"]) <= self.clock()
        ):
            raise ManualError(
                "manual.policy_denied", 503 if decision["decision"] == "PERMIT" else 403
            )
        obligations = decision["obligations"]
        if not isinstance(obligations, list) or obligations != [{"kind": "audit_before_effect"}]:
            raise ManualError("manual.unsupported_obligation")

    def assert_journal_current(self, snapshot: Record) -> None:
        control = object_value(snapshot["control"])
        head = self.journal.head()
        if (
            head.journal_id != control["journal_id"]
            or head.generation != control["journal_generation"]
            or head.restriction_barrier != control["restriction_barrier"]
            or head.serving_generation != control["serving_generation"]
            or head.serving_generation == 0
            or not self.clock() - timedelta(seconds=1)
            <= head.observed_at
            <= self.clock() + timedelta(seconds=1)
        ):
            raise ManualError("manual.journal_barrier", 503)

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

    def _audit(
        self,
        tx: Transaction,
        actor: Actor,
        action: str,
        operation_id: str,
        payload_digest: str,
        output: object,
        versions: Record,
        *,
        decision: str = "PERMIT",
        audit_id: str | None = None,
    ) -> str:
        head = tx.peek("audit_head", "demo")
        if head is None:
            raise ManualError("manual.audit_unavailable", 503)
        event: Record = {
            "event_id": audit_id or str(uuid4()),
            "operation_id": operation_id,
            "principal_id": actor.account_id,
            "action": action,
            "decision": decision,
            "input_digest": payload_digest,
            "output_digest": digest(output),
            "versions": versions,
            "previous_hash": head["digest"],
            "created_at": self.clock(),
        }
        encoded = {
            **event,
            "created_at": stamp(self.clock()),
            "encoding": "care.audit.v1",
            "stream_id": "demo",
            "sequence": str(number(head, "next_sequence")),
        }
        event["created_at"] = dt(encoded["created_at"])
        event["hash"] = digest(encoded)
        tx.audit_append(event)
        return text(event, "event_id")

    def _run(
        self,
        actor: Actor,
        action: str,
        key: str | None,
        data: Record,
        session_id: str | None,
        handler: Handler,
        *,
        contract: str | None = None,
        queue: bool = False,
        replay: Handler | None = None,
    ) -> Record:
        started = time.monotonic()
        data = cast(Record, json.loads(canonical(data)))
        operation_id = str(UUID(key)) if key else str(uuid4())
        if key and operation_id != key:
            raise ManualError("manual.invalid_operation", 400)
        if contract:
            validate_contract(contract, data)
        payload_digest = digest(
            {
                "contract_version": "care.v1",
                "action": action,
                "session_id": session_id,
                "payload": data,
            }
        )
        current = self._fresh_actor(actor)
        target = (
            data.get("worker_id")
            if action == "workforce_takeover"
            else data.get("principal_id")
            if action == "manual_identity_restrict"
            else None
        )
        extra_principals = (target,) if isinstance(target, str) else ()
        with self.store.transaction(current, session_id, locked=False, queue=queue) as prepare:
            snapshot = self._snapshot(prepare, current, session_id, extra_principals)
            request = self._policy_input(
                prepare, current, action, operation_id, payload_digest, snapshot, arguments=data
            )
            validate_contract("PolicyInput", request)
        try:
            decision = self.policy.evaluate(request)
            self.check_policy_decision(decision, request)
        except ManualError as error:
            self._record_denial(
                current,
                action,
                operation_id,
                key,
                payload_digest,
                session_id,
                error,
                extra_principals,
            )
            raise
        try:
            with self.store.transaction(current, session_id, queue=queue) as tx:
                latest = self._snapshot(tx, current, session_id, extra_principals)
                final_actor = self._fresh_actor(current)
                # A fresh identity receipt ID is evidence of this revalidation;
                # policy binding retains the original receipt and guard vector.
                final_request = self._policy_input(
                    tx, final_actor, action, operation_id, payload_digest, latest, arguments=data
                )
                if final_request != request:
                    raise ManualError("manual.stale_authority", 409)
                if not self._accessible(tx, final_actor, action, latest):
                    raise ManualError("manual.not_found", 404)
                self.check_policy_decision(decision, request)
                self.assert_journal_current(latest)
                if key or action == "channel_challenge_read":
                    review_scope.assert_channel_current(final_actor, self.channel)
                old = tx.get("operation", operation_id) if key else None
                if old is not None:
                    if (
                        old["principal_id"] != final_actor.account_id
                        or old["operation_name"] != action
                        or old["payload_digest"] != payload_digest
                    ):
                        raise ManualError("manual.idempotency_conflict", 409)
                    result = (
                        replay(
                            tx,
                            final_actor,
                            data,
                            cast(Record | None, latest["session"]),
                            cast(Record | None, latest["guard"]),
                        ).value
                        if replay is not None and old["state"] == "committed"
                        else self._replay(tx, final_actor, old, latest)
                    )
                    self._audit(
                        tx,
                        final_actor,
                        action + ".replay",
                        str(uuid4()),
                        payload_digest,
                        result,
                        object_value(request["versions"]),
                    )
                else:
                    review_scope.assert_submission_intent(
                        tx,
                        final_actor,
                        action,
                        operation_id,
                        session_id,
                        data,
                        self.cipher,
                        self.clock(),
                    )
                    result = handler(
                        tx,
                        final_actor,
                        data,
                        cast(Record | None, latest["session"]),
                        cast(Record | None, latest["guard"]),
                    )
                    audit_id = str(uuid4())
                    if result.contract == "CommandResult":
                        result.value["operation_id"] = operation_id
                        result.value["audit_ref"] = audit_id
                    validate_contract(result.contract, result.value)
                    if key:
                        tx.put(
                            "operation",
                            {
                                "operation_id": operation_id,
                                "principal_id": final_actor.account_id,
                                "operation_name": action,
                                "key": operation_id,
                                "payload_digest": payload_digest,
                                "state": "replacement_unavailable"
                                if result.sensitive_once
                                else "committed",
                                "session_id": result.session_id or session_id,
                                "resource_id": result.resource_id,
                                "result_type": result.contract,
                                "canonical_audit_id": audit_id,
                                "created_at": self.clock(),
                            },
                        )
                    self._audit(
                        tx,
                        final_actor,
                        action,
                        operation_id,
                        payload_digest,
                        result.value,
                        object_value(request["versions"]),
                        audit_id=audit_id,
                    )
                    result = result.value
                if key or action == "channel_challenge_read":
                    review_scope.assert_channel_current(final_actor, self.channel)
                self._check_output_authority(
                    tx, final_actor, action, result, latest, object_value(request["scope"])
                )
                if (
                    time.monotonic() - started >= 1
                    or dt(decision["expires_at"]) <= self.clock()
                    or (
                        actor.request_deadline is not None
                        and actor.request_deadline <= self.clock()
                    )
                ):
                    raise ManualError("manual.deadline", 503)
            return result
        except ManualError as error:
            if error.code == "manual.commit_unknown":
                raise
            self._record_denial(
                current,
                action,
                operation_id,
                key,
                payload_digest,
                session_id,
                error,
                extra_principals,
            )
            raise

    def _check_output_authority(
        self,
        tx: Transaction,
        actor: Actor,
        action: str,
        result: Record,
        snapshot: Record,
        policy_scope: Record,
    ) -> None:
        """Recheck the exact selected disclosure after content work and audit.

        A narrower surviving grant cannot authorize fields selected under an
        expired grant. This is the final guarded disclosure authorization; no
        bytes are released if the check rolls back the transaction.
        """
        if action.startswith("plan_"):
            from .consent import current_fields, owns_subject

            session = object_value(snapshot["session"])
            emitted = {
                text(object_value(field), "field") for field in cast(list[object], result["fields"])
            }
            if not emitted.issubset(cast(list[str], policy_scope["fields"])):
                raise ManualError("manual.field_scope_denied")
            if action != "plan_read" and (
                not actor.mfa or not 0 <= (self.clock() - actor.auth_time).total_seconds() < 300
            ):
                raise ManualError("manual.assurance_required")
            if not owns_subject(tx, actor, session):
                allowed = current_fields(tx, actor, session, self.clock())
                fields = result.get("fields")
                if not allowed or not isinstance(fields, list):
                    raise ManualError("manual.field_scope_denied")
                for raw in cast(list[object], fields):
                    field = object_value(raw)
                    if field["field"] not in allowed:
                        raise ManualError("manual.field_scope_denied")
        elif action == "consent_grant" and dt(result["expires_at"]) <= self.clock():
            raise ManualError("manual.consent_interval", 409)
        elif action.startswith("directory_") and action != "directory_suspend":
            candidates = result.get("items", [result])
            if isinstance(candidates, list):
                for raw in cast(list[object], candidates):
                    view = object_value(raw)
                    if view.get("state") == "verified" and dt(view["expires_at"]) <= self.clock():
                        raise ManualError("manual.directory_projection_expired", 409)

    def _record_denial(
        self,
        actor: Actor,
        action: str,
        operation_id: str,
        key: str | None,
        payload_digest: str,
        session_id: str | None,
        error: ManualError,
        extra_principals: tuple[str, ...],
    ) -> None:
        if error.status == 204:
            return
        # Domain rollback precedes a distinct durable denial. A terminal rejected
        # key cannot later become successful after an authority/input change.
        with self.store.transaction(actor, session_id) as denied:
            failed = self._snapshot(denied, actor, session_id, extra_principals)
            old = denied.get("operation", operation_id) if key else None
            audit_id = str(uuid4())
            canonical_operation = str(uuid4())
            if key and old is None and error.status < 500:
                canonical_operation = operation_id
                denied.put(
                    "operation",
                    {
                        "operation_id": operation_id,
                        "principal_id": actor.account_id,
                        "operation_name": action,
                        "key": operation_id,
                        "payload_digest": payload_digest,
                        "state": "rejected",
                        "session_id": session_id,
                        "resource_id": None,
                        "result_type": "OperationStatus",
                        "canonical_audit_id": audit_id,
                        "created_at": self.clock(),
                    },
                )
            self._audit(
                denied,
                actor,
                action + ".denied",
                canonical_operation,
                payload_digest,
                {"safe_reason": error.code},
                self._versions(actor, failed),
                decision="DENY",
                audit_id=audit_id,
            )

    def current_connection(self, tx: Transaction, session_id: str) -> bool:
        # Current metadata is read under the already-held global guard, without
        # acquiring out-of-order locks while projecting a queue page.
        locked = tx.locked
        tx.locked = False
        try:
            session = tx.get("session", session_id)
            assignment = self.active_assignment(tx, session_id)
            if session is None or assignment is None or assignment["status"] != "connected":
                return False
            challenge_id = assignment.get("channel_challenge_id")
            if not isinstance(challenge_id, str):
                return False
            challenge = tx.get("challenge", challenge_id)
            guard = tx.get("guard", session_id)
            if (
                challenge is None
                or guard is None
                or guard["control_epoch"] != assignment["control_epoch"]
            ):
                return False
            acks = tx.rows("ack", challenge_id=challenge_id, limit=2)
            if len(acks) != 2:
                return False
            for ack in acks:
                principal = tx.get("principal", text(ack, "principal_id"))
                if (
                    principal is None
                    or principal["revoked"] is not False
                    or principal["identity_revision"] != ack["identity_revision"]
                    or principal["role_revision"] != ack["role_revision"]
                    or guard["access_revision"] != ack["session_access_revision"]
                    or not self.channel.current(
                        text(ack, "principal_id"),
                        text(ack, "browser_binding"),
                        number(ack, "transport_generation"),
                    )
                ):
                    return False
                if ack["party"] == "participant":
                    grants = tx.rows(
                        "acl",
                        session_id=session_id,
                        principal_id=ack["principal_id"],
                        purpose="support",
                    )
                    if not any(
                        item["revoked_at"] is None
                        and (
                            item["valid_until"] is None
                            or instant(item, "valid_until") > self.clock()
                        )
                        for item in grants
                    ):
                        return False
            return True
        finally:
            tx.locked = locked

    def session_projection(self, tx: Transaction, session: Record, guard: Record) -> Record:
        view = projections.session_view(tx, session, guard)
        if session["service_phase"] == "human_controlled":
            connected = self.current_connection(tx, text(session, "id"))
            view["transport"] = "connected" if connected else "disconnected"
            reasons = cast(list[str], view["degraded_reasons"])
            if not connected and "channel_disconnected" not in reasons:
                reasons.append("channel_disconnected")
        return view

    def queue_projection(self, tx: Transaction, queue: Record) -> Record:
        view = projections.queue_view(tx, queue)
        view["connection_confirmed"] = bool(
            view["connection_confirmed"]
        ) and self.current_connection(tx, text(queue, "session_id"))
        return view

    def _replay(self, tx: Transaction, actor: Actor, old: Record, snapshot: Record) -> Record:
        sid = old["session_id"]
        if isinstance(sid, str) and snapshot["session"] is None:
            tx.scope(sid)
            snapshot = self._snapshot(tx, actor, sid)
            if not self._accessible(tx, actor, "session_read", snapshot):
                raise ManualError("manual.not_found", 404)
        if old["state"] == "replacement_unavailable":
            return {
                "operation_id": old["operation_id"],
                "state": "replacement_unavailable",
                "safe_reason": "manual.fresh_recovery_required",
            }
        if old["state"] == "rejected":
            raise ManualError("manual.operation_rejected", 409)
        session = cast(Record | None, snapshot["session"])
        guard = cast(Record | None, snapshot["guard"])
        kind = old["result_type"]
        resource = old["resource_id"]
        if kind in {"ReviewDraftView", "ReviewIntentView"} and isinstance(resource, str):
            row = tx.peek(
                "review_draft" if kind == "ReviewDraftView" else "review_intent", resource
            )
            if row is None or row["principal_id"] != actor.account_id:
                raise ManualError("manual.not_found", 404)
            return (
                review_projection.draft_view(row, self.cipher)
                if kind == "ReviewDraftView"
                else review_projection.intent_view(tx, row, actor, self.cipher, self.clock())
            )
        if kind == "SessionView" and session and guard:
            return self.session_projection(tx, session, guard)
        if kind == "CommandResult":
            return {
                "operation_id": old["operation_id"],
                "state": "committed",
                "resource_id": resource,
                "revision": str(number(session, "revision")) if session else "0",
                "audit_ref": old["canonical_audit_id"],
            }
        if kind == "TransferPreparation" and isinstance(resource, str):
            challenge = tx.get("challenge", resource)
            if (
                challenge
                and not challenge["revoked"]
                and instant(challenge, "expires_at") > self.clock()
            ):
                assignment = tx.get("assignment", text(challenge, "assignment_id"))
                if assignment:
                    return {
                        "assignment": projections.assignment_view(assignment),
                        "challenge_id": challenge["id"],
                        "expires_at": stamp(instant(challenge, "expires_at")),
                    }
            raise ManualError("manual.challenge_expired", 410)
        table = {
            "QueueView": "queue",
            "AssignmentView": "assignment",
            "AssessmentView": "assessment",
            "MessageView": "message",
            "AssertionView": "assertion",
            "ChannelAckView": "ack",
        }.get(str(kind))
        if not table or not isinstance(resource, str):
            raise ManualError("manual.operation_requires_current_view", 409)
        row = tx.get(table, resource)
        if row is None:
            raise ManualError("manual.not_found", 404)
        if kind == "QueueView":
            return self.queue_projection(tx, row)
        if kind == "AssignmentView":
            return projections.assignment_view(row)
        if kind == "AssessmentView":
            return projections.assessment_view(row)
        if kind == "MessageView":
            return projections.message_view(row, self.cipher)
        if kind == "AssertionView":
            return projections.assertion_view(row, self.cipher, json.loads)
        return self._ack_projection(tx, actor, row)

    def _ack_projection(self, tx: Transaction, actor: Actor, ack: Record) -> Record:
        challenge = tx.get("challenge", text(ack, "challenge_id"))
        if (
            challenge is None
            or challenge["revoked"] is not False
            or instant(challenge, "expires_at") <= self.clock()
            or ack["principal_id"] != actor.account_id
            or ack["browser_binding"] != actor.browser_session_digest
            or ack["transport_generation"] != actor.transport_generation
        ):
            raise ManualError("manual.challenge_expired", 410)
        return {
            "ack_id": ack["id"],
            "challenge_id": challenge["id"],
            "evidence_id": challenge["evidence_id"],
            "state": "two_party_confirmed"
            if challenge["evidence_id"]
            else "one_party_acknowledged",
            "expires_at": stamp(instant(challenge, "expires_at")),
        }

    def register_copy(self, tx: Transaction, session: Record, kind: str, aggregate_id: str) -> None:
        if not isinstance(self.content_key_ref, str) or not self.content_key_ref:
            raise ManualError("manual.content_custody_unregistered", 503)
        copy_id = str(uuid4())
        tx.put(
            "copy",
            {
                "copy_id": copy_id,
                "subject_id": session["persona_id"],
                "session_id": session["id"],
                "purpose": "support",
                "aggregate_type": kind,
                "aggregate_id": aggregate_id,
                "content_ref": "postgres:" + kind + ":" + aggregate_id,
                "classification": "synthetic_content",
                "encryption_key_ref": self.content_key_ref,
                "anchor_kind": "last_parent_closed",
                "anchor_at": None,
                "expires_at": None,
                "state": "anchor_pending",
                "created_at": self.clock(),
            },
        )
        if kind != "session":
            parents = tx.rows("copy", session_id=session["id"], aggregate_type="session", limit=1)
            if not parents:
                raise ManualError("manual.copy_parent_missing", 503)
            tx.put(
                "dependency",
                {
                    "parent_copy_id": parents[0]["copy_id"],
                    "child_copy_id": copy_id,
                    "reason": "session_parent",
                },
            )

    def bump(
        self,
        tx: Transaction,
        session: Record,
        guard: Record,
        *,
        event_type: str = "session_changed",
        resource_id: str | None = None,
        resource_revision: int | None = None,
    ) -> None:
        session["revision"] = number(session, "revision") + 1
        session["updated_at"] = self.clock()
        sequence = number(guard, "next_event_seq")
        guard["next_event_seq"] = sequence + 1
        tx.put("session", session)
        tx.put("guard", guard)
        tx.put(
            "event",
            {
                "session_id": session["id"],
                "sequence": sequence,
                "event_id": str(uuid4()),
                "type": event_type,
                "resource_id": resource_id or session["id"],
                "resource_revision": resource_revision
                if resource_revision is not None
                else session["revision"],
                "occurred_at": self.clock(),
            },
        )

    @staticmethod
    def require_session(session: Record | None, guard: Record | None) -> tuple[Record, Record]:
        if session is None or guard is None:
            raise ManualError("manual.not_found", 404)
        return session, guard

    @staticmethod
    def expected(data: Record, row: Record) -> None:
        if integer(data["expected_revision"]) != number(row, "revision"):
            raise ManualError("manual.stale_revision", 409)

    @staticmethod
    def active(session: Record) -> None:
        if session["service_phase"] == "ended":
            raise ManualError("manual.session_ended", 410)
