"""Narrow workload-duty commands, isolated from human service authority.

No content projection, generic job dispatcher, synthesized human actor, or default
admission exists here. Each invocation performs at most one durable transition.
"""

import base64
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from uuid import UUID, uuid4

from care_link_contracts import ContractError, validate_contract
from care_link_domain import DutyActor, DutyAuthorityPort, DutyScope, ManualError
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from psycopg.types.json import Jsonb

from .control import ManualService
from .store import Record, Transaction, instant, number, text
from .values import canonical, digest, dt, object_value, stamp


@dataclass(frozen=True)
class SignalSource:
    audience: str
    key: Ed25519PublicKey


class DutyCommands:
    def __init__(
        self,
        service: ManualService,
        authority: DutyAuthorityPort,
        *,
        signal_sources: Mapping[str, SignalSource] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.service = service
        self.authority = authority
        self.signal_sources = MappingProxyType(dict(signal_sources or {}))
        self.clock = clock

    @staticmethod
    def binding(action: str, key: str, payload: Record) -> str:
        return digest(
            {
                "contract_version": "care.v1",
                "action": action,
                "operation_id": key,
                "payload": payload,
            }
        )

    @staticmethod
    def _record(row: Record | None) -> Record | None:
        return (
            {key: str(value) if isinstance(value, UUID) else value for key, value in row.items()}
            if row
            else None
        )

    def _job(self, tx: Transaction, data: Record, *, lock: bool = False) -> Record:
        row = tx.connection.execute(
            (
                "SELECT * FROM durable.due_job WHERE job_id=%s FOR UPDATE"
                if lock
                else "SELECT * FROM durable.due_job WHERE job_id=%s"
            ),
            (data["job_id"],),
        ).fetchone()
        job = self._record(row)
        if job is None:
            raise ManualError("manual.job_not_found", 404)
        expected = {
            "kind": job["kind"],
            "aggregate_id": job["aggregate_id"],
            "expected_revision": str(number(job, "expected_revision")),
            "fence": str(number(job, "fence")),
            "original_operation_id": job["original_operation_id"],
            "deadline": stamp(instant(job, "deadline")),
        }
        supplied = {key: value for key, value in data.items() if key != "job_id"}
        supplied["deadline"] = stamp(dt(supplied["deadline"]))
        if supplied != expected or self.clock() >= instant(job, "deadline"):
            raise ManualError("manual.job_stale", 409)
        return job

    def _snapshot(self, tx: Transaction, action: str, data: Record) -> Record:
        control = tx.get("control", "demo")
        if control is None:
            raise ManualError("manual.bootstrap_missing", 503)
        session = None
        assignment = None
        target = None
        subject = None
        guard = None
        job = None
        if action == "identity_revoke":
            target = tx.get("principal", text(data, "subject_id"))
            if target is None:
                raise ManualError("manual.signal_subject_unmapped", 404)
        else:
            job = self._job(tx, data)
            tx.scope(text(job, "session_id"))
            preliminary = tx.peek("session", text(job, "session_id"))
            if preliminary is None:
                raise ManualError("manual.job_session_missing", 503)
            # Control is already held; metadata discovery precedes sorted guards.
            old_lock = tx.locked
            tx.locked = False
            try:
                before_assignment = tx.get("assignment", text(job, "aggregate_id"))
            finally:
                tx.locked = old_lock
            if before_assignment is None:
                raise ManualError("manual.job_assignment_missing", 503)
            for principal in sorted(
                {text(preliminary, "participant_account_id"), text(before_assignment, "worker_id")}
            ):
                if tx.get("principal", principal) is None:
                    raise ManualError("manual.job_principal_missing", 503)
            subject = tx.get("subject", text(preliminary, "persona_id"))
            guard = tx.get("guard", text(job, "session_id"))
            session = tx.get("session", text(job, "session_id"))
            assignment = tx.get("assignment", text(job, "aggregate_id"))
            if subject is None or guard is None or session is None or assignment is None:
                raise ManualError("manual.job_guard_missing", 503)
        return {
            "control": control,
            "target": target,
            "subject": subject,
            "guard": guard,
            "session": session,
            "assignment": assignment,
            "job": job,
        }

    @staticmethod
    def _scope(action: str, snapshot: Record) -> DutyScope:
        if action == "identity_revoke":
            return DutyScope(None, None, "security")
        session = object_value(snapshot["session"])
        return DutyScope(text(session, "id"), text(session, "persona_id"), "support")

    @staticmethod
    def _versions(actor: DutyActor, snapshot: Record) -> Record:
        control = object_value(snapshot["control"])
        target = object_value(snapshot["target"]) if snapshot["target"] else None
        subject = object_value(snapshot["subject"]) if snapshot["subject"] else None
        guard = object_value(snapshot["guard"]) if snapshot["guard"] else None
        assignment = object_value(snapshot["assignment"]) if snapshot["assignment"] else None
        session = object_value(snapshot["session"]) if snapshot["session"] else None
        return {
            "identity": str(actor.workload_revision),
            "roles": str(actor.duty_revision),
            "subject": str(number(subject, "authority_revision")) if subject else "0",
            "session_access": str(number(guard, "access_revision")) if guard else "0",
            "assignment": str(number(assignment, "revision")) if assignment else "0",
            "resource": str(number(target, "identity_revision"))
            if target
            else str(number(session, "revision"))
            if session
            else "0",
            "directory": "0",
            "policy_epoch": str(number(control, "epoch")),
            "control_epoch": str(number(guard, "control_epoch")) if guard else "0",
            "serving_generation": str(number(control, "serving_generation")),
            "restriction_barrier": str(number(control, "restriction_barrier")),
        }

    def _policy(
        self, actor: DutyActor, action: str, key: str, binding: str, snapshot: Record
    ) -> Record:
        control = object_value(snapshot["control"])
        return {
            "operation_id": key,
            "actor": actor.wire(),
            "action": action,
            "scope": self._scope(action, snapshot).wire(),
            "tags": {"environment": "demo", "population": "synthetic"},
            "jurisdiction": None,
            "versions": self._versions(actor, snapshot),
            "payload_digest": binding,
            "consent_id": None,
            "review_id": None,
            "bundle_digest": control["bundle_digest"],
            "artifact_digests": [actor.duty_artifact_digest],
            "mode": control["mode"],
            "audit_ready": True,
            "authority_complete": True,
            "authority_facts": {
                "actor_role_allowed": True,
                "resource_owned_or_assigned": True,
                "field_scope_allowed": True,
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

    def _audit(
        self,
        tx: Transaction,
        actor: DutyActor,
        action: str,
        key: str,
        binding: str,
        output: Record,
        versions: Record,
        audit_id: str,
        *,
        decision: str = "PERMIT",
    ) -> None:
        head = tx.peek("audit_head", "demo")
        if head is None:
            raise ManualError("manual.audit_unavailable", 503)
        context: Record = {
            "actor": actor.wire(),
            "evidence": actor.evidence(),
            "workload_revision": str(actor.workload_revision),
            "duty_revision": str(actor.duty_revision),
        }
        created = self.clock()
        encoded: Record = {
            "event_id": audit_id,
            "operation_id": key,
            "principal_id": actor.actor_id,
            "action": action,
            "decision": decision,
            "input_digest": binding,
            "output_digest": digest(output),
            "versions": versions,
            "previous_hash": head["digest"],
            "created_at": stamp(created),
            "encoding": "care.audit.v1",
            "stream_id": "demo",
            "sequence": str(number(head, "next_sequence")),
            "actor_context": context,
        }
        tx.connection.execute(
            "SELECT audit.append_event(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                audit_id,
                key,
                actor.actor_id,
                action,
                decision,
                binding,
                digest(output),
                Jsonb(versions),
                created,
                head["digest"],
                digest(encoded),
                Jsonb(context),
            ),
        )

    def _run(self, actor: DutyActor, key: str, data: Record, action: str) -> Record:
        started = time.monotonic()
        if str(UUID(key)) != key:
            raise ManualError("manual.invalid_operation", 400)
        data = object_value(json.loads(canonical(data)))
        validate_contract("Signal" if action == "identity_revoke" else "DueJob", data)
        binding = self.binding(action, key, data)
        # Authenticate the immutable exact attempt before any domain lookup. An
        # invalid/unregistered proof never supplies a trusted canonical actor slot.
        authenticated = self.authority.current(actor, action, binding, actor.scope)
        try:
            if action == "job_execute" and actor.job_id != data.get("job_id"):
                raise ManualError("manual.job_binding_denied")
            if action == "job_execute" and data["kind"] != "reservation_expiry":
                raise ManualError("manual.job_kind_not_admitted", 503)
            if action == "identity_revoke":
                self._verify_signal(data)
            with self.service.store.transaction(actor, None, locked=False) as prepare:
                snapshot = self._snapshot(prepare, action, data)
                scope = self._scope(action, snapshot)
                current = self.authority.current(actor, action, binding, scope)
                request = self._policy(current, action, key, binding, snapshot)
                validate_contract("PolicyInput", request)
            decision = self.service.policy.evaluate(request)
            self.service.check_policy_decision(decision, request)
            with self.service.store.transaction(actor, scope.session_id) as tx:
                latest = self._snapshot(tx, action, data)
                if (
                    self.authority.current(actor, action, binding, self._scope(action, latest))
                    != current
                ):
                    raise ManualError("manual.duty_changed")
                if self._versions(current, latest) != request["versions"]:
                    raise ManualError("manual.stale_authority", 409)
                self.service.check_policy_decision(decision, request)
                self.service.assert_journal_current(latest)
                prior = self._record(
                    tx.connection.execute(
                        "SELECT * FROM durable.duty_operation WHERE operation_id=%s FOR UPDATE",
                        (key,),
                    ).fetchone()
                )
                nonce = self._record(
                    tx.connection.execute(
                        "SELECT * FROM durable.duty_nonce WHERE nonce=%s FOR UPDATE", (actor.nonce,)
                    ).fetchone()
                )
                if nonce and (
                    nonce["operation_id"] != key
                    or nonce["actor_id"] != actor.actor_id
                    or nonce["request_digest"] != binding
                ):
                    raise ManualError("manual.duty_nonce_used", 409)
                if prior:
                    if (
                        prior["actor_id"] != actor.actor_id
                        or prior["workload_id"] != actor.workload_id
                        or prior["action"] != action
                        or prior["payload_digest"] != binding
                    ):
                        raise ManualError("manual.idempotency_conflict", 409)
                    result: Record = {
                        "operation_id": key,
                        "state": prior["state"],
                        "resource_id": prior["resource_id"],
                        "revision": str(number(prior, "revision")),
                        "audit_ref": prior["canonical_audit_id"],
                    }
                    self._audit(
                        tx,
                        current,
                        action + ".replay",
                        str(uuid4()),
                        binding,
                        result,
                        object_value(request["versions"]),
                        str(uuid4()),
                        decision="DENY" if prior["state"] == "rejected" else "PERMIT",
                    )
                else:
                    if action == "identity_revoke":
                        resource, revision = self._revoke(tx, key, data, latest)
                    else:
                        resource, revision = self._expire(tx, key, data, latest)
                    audit_id = str(uuid4())
                    result = {
                        "operation_id": key,
                        "state": "committed",
                        "resource_id": resource,
                        "revision": str(revision),
                        "audit_ref": audit_id,
                    }
                    tx.connection.execute(
                        "INSERT INTO durable.duty_operation "
                        "(operation_id,actor_id,workload_id,action,payload_digest,resource_id,"
                        "revision,canonical_audit_id,created_at) "
                        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (
                            key,
                            actor.actor_id,
                            actor.workload_id,
                            action,
                            binding,
                            resource,
                            revision,
                            audit_id,
                            self.clock(),
                        ),
                    )
                    self._audit(
                        tx,
                        current,
                        action,
                        key,
                        binding,
                        result,
                        object_value(request["versions"]),
                        audit_id,
                    )
                if nonce is None:
                    tx.connection.execute(
                        "INSERT INTO durable.duty_nonce VALUES(%s,%s,%s,%s)",
                        (actor.nonce, actor.actor_id, key, binding),
                    )
                validate_contract("CommandResult", result)
                self.service.check_policy_decision(decision, request)
                if (
                    time.monotonic() - started >= 1
                    or actor.expires_at <= self.clock()
                    or (
                        actor.request_deadline is not None
                        and actor.request_deadline <= self.clock()
                    )
                ):
                    raise ManualError("manual.deadline", 503)
            return result
        except (ManualError, ContractError) as cause:
            error = (
                cause
                if isinstance(cause, ManualError)
                else ManualError("manual.policy_contract_unavailable", 503)
            )
            # A lost commit acknowledgment must reconcile the original key. It
            # cannot be converted into a terminal denial or a second logical effect.
            if error.code != "manual.commit_unknown":
                self._record_denial(authenticated, action, key, binding, error)
            if isinstance(cause, ManualError):
                raise
            raise error from cause

    def _record_denial(
        self, actor: DutyActor, action: str, key: str, binding: str, error: ManualError
    ) -> None:
        """Record a known rolled-back authenticated attempt in a separate transaction.

        Denial logging grants no authority and deliberately does not depend on a
        live PDP/journal. If the audit/store is down, no central commit is claimed.
        """
        with self.service.store.transaction(actor, None) as tx:
            control = tx.get("control", "demo")
            if control is None:
                raise ManualError("manual.audit_unavailable", 503)
            prior = self._record(
                tx.connection.execute(
                    "SELECT * FROM durable.duty_operation WHERE operation_id=%s FOR UPDATE", (key,)
                ).fetchone()
            )
            terminal = 400 <= error.status < 500 and prior is None
            audit_operation = key if terminal else str(uuid4())
            audit_id = str(uuid4())
            versions = self._versions(
                actor,
                {
                    "control": control,
                    "target": None,
                    "subject": None,
                    "guard": None,
                    "assignment": None,
                    "session": None,
                },
            )
            safe: Record = {"operation_id": key, "state": "rejected", "safe_reason": error.code}
            if terminal:
                tx.connection.execute(
                    "INSERT INTO durable.duty_operation "
                    "(operation_id,actor_id,workload_id,action,payload_digest,resource_id,"
                    "revision,canonical_audit_id,created_at,state,safe_reason) "
                    "VALUES(%s,%s,%s,%s,%s,NULL,0,%s,%s,'rejected',%s)",
                    (
                        key,
                        actor.actor_id,
                        actor.workload_id,
                        action,
                        binding,
                        audit_id,
                        self.clock(),
                        error.code,
                    ),
                )
            self._audit(
                tx,
                actor,
                action + ".denied",
                audit_operation,
                binding,
                safe,
                versions,
                audit_id,
                decision="DENY",
            )

    def _verify_signal(self, data: Record) -> None:
        source = self.signal_sources.get(text(data, "issuer_id"))
        if source is None or source.audience != data["audience"]:
            raise ManualError("manual.signal_source_not_admitted", 503)
        if data["event_type"] == "workload_compromised":
            raise ManualError("manual.workload_signal_not_admitted", 503)
        unsigned = {key: value for key, value in data.items() if key != "signature"}
        content = {key: value for key, value in unsigned.items() if key != "digest"}
        if digest(content) != data["digest"]:
            raise ManualError("manual.signal_digest_denied")
        try:
            signature = text(data, "signature")
            raw = base64.b64decode(
                signature + "=" * (-len(signature) % 4), altchars=b"-_", validate=True
            )
            if base64.urlsafe_b64encode(raw).rstrip(b"=").decode() != signature:
                raise ValueError("Noncanonical signature")
            source.key.verify(raw, canonical(unsigned).encode())
        except (ValueError, InvalidSignature) as error:
            raise ManualError("manual.signal_signature_denied") from error

    def _revoke(self, tx: Transaction, key: str, data: Record, snapshot: Record) -> tuple[str, int]:
        target = object_value(snapshot["target"])
        control = object_value(snapshot["control"])
        issuer, subject = text(data, "issuer_id"), text(data, "subject_id")
        source = tx.connection.execute(
            "SELECT quarantined FROM control.signal_source WHERE issuer_id=%s FOR UPDATE", (issuer,)
        ).fetchone()
        if source and source["quarantined"]:
            raise ManualError("manual.signal_source_quarantined", 503)
        prior = self._record(
            tx.connection.execute(
                "SELECT * FROM control.signal_receipt WHERE issuer_id=%s AND jti=%s FOR UPDATE",
                (issuer, data["jti"]),
            ).fetchone()
        )
        head = self._record(
            tx.connection.execute(
                "SELECT * FROM control.signal_head WHERE issuer_id=%s AND subject_id=%s FOR UPDATE",
                (issuer, subject),
            ).fetchone()
        )
        if prior and prior["digest"] == data["digest"] and prior["subject_id"] == subject:
            return subject, number(target, "identity_revision")
        sequence = number(head, "source_sequence") if head else 0
        previous = head["digest"] if head else "0" * 64
        age = (self.clock() - dt(data["event_at"])).total_seconds()
        suspicious = (
            prior is not None
            or not -5 <= age <= 60
            or data["source_sequence"] != str(sequence + 1)
            or data["previous_digest"] != previous
        )
        target["identity_revision"] = number(target, "identity_revision") + 1
        restriction: Record = {
            "kind": "identity_revoke",
            "principal_id": subject,
            "identity_revision": str(number(target, "identity_revision")),
            "disabled": True,
        }
        if suspicious:
            control["epoch"] = number(control, "epoch") + 1
            restriction = {
                "kind": "kill",
                "mode": "restricted",
                "epoch": str(number(control, "epoch")),
                "bundle_digest": control["bundle_digest"],
            }
        self.service.append_restriction(
            tx, key, control, restriction, DutyScope(None, None, "security").wire()
        )
        target["revoked"] = True
        if not suspicious:
            target["source_sequence"] = int(text(data, "source_sequence"))
        tx.put("principal", target)
        tx.connection.execute(
            "INSERT INTO control.signal_source VALUES(%s,%s) ON CONFLICT(issuer_id) "
            "DO UPDATE SET quarantined=excluded.quarantined",
            (issuer, suspicious),
        )
        if suspicious:
            control["mode"] = "restricted"
            tx.put("control", control)
        else:
            tx.connection.execute(
                "INSERT INTO control.signal_head VALUES(%s,%s,%s,%s) "
                "ON CONFLICT(issuer_id,subject_id) DO UPDATE SET "
                "source_sequence=excluded.source_sequence,digest=excluded.digest",
                (issuer, subject, int(text(data, "source_sequence")), data["digest"]),
            )
        if prior is None:
            tx.connection.execute(
                "INSERT INTO control.signal_receipt VALUES(%s,%s,%s,%s,%s)",
                (issuer, data["jti"], subject, data["digest"], key),
            )
        return subject, number(target, "identity_revision")

    def _expire(self, tx: Transaction, key: str, data: Record, snapshot: Record) -> tuple[str, int]:
        job = self._job(tx, data, lock=True)
        assignment = object_value(snapshot["assignment"])
        session = object_value(snapshot["session"])
        guard = object_value(snapshot["guard"])
        if job["state"] != "pending":
            raise ManualError("manual.job_already_processed", 409)
        if (
            self.clock() < instant(job, "due_at")
            or instant(assignment, "expires_at") > self.clock()
        ):
            raise ManualError("manual.job_not_due", 409)
        if (
            assignment["status"] != "reserved"
            or number(assignment, "revision") != number(job, "expected_revision")
            or number(assignment, "control_epoch") != number(job, "fence")
            or number(guard, "control_epoch") != number(job, "fence")
        ):
            raise ManualError("manual.job_fenced", 409)
        if session["service_phase"] == "ended":
            raise ManualError("manual.job_session_ended", 410)
        assignment["status"] = "expired"
        assignment["revision"] = number(assignment, "revision") + 1
        assignment["updated_at"] = self.clock()
        tx.put("assignment", assignment)
        queue = self.service.active_queue(tx, text(session, "id"))
        if queue is None or queue["status"] != "reserved":
            raise ManualError("manual.job_queue_changed", 409)
        queue["status"] = "pending"
        queue["revision"] = number(queue, "revision") + 1
        queue["next_review_at"] = self.clock() + timedelta(seconds=60)
        queue["updated_at"] = self.clock()
        tx.put("queue", queue)
        session["service_phase"] = "queued"
        self.service.bump(
            tx,
            session,
            guard,
            event_type="queue_changed",
            resource_id=text(queue, "id"),
            resource_revision=number(queue, "revision"),
        )
        tx.connection.execute(
            "UPDATE durable.due_job SET state='completed',completed_operation_id=%s "
            "WHERE job_id=%s",
            (key, data["job_id"]),
        )
        return text(assignment, "id"), number(assignment, "revision")

    def identity_revoke(self, actor: DutyActor, key: str, data: Record) -> Record:
        return self._run(actor, key, data, "identity_revoke")

    def job_execute(self, actor: DutyActor, key: str, data: Record) -> Record:
        return self._run(actor, key, data, "job_execute")
