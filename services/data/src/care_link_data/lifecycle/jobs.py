"""Narrow authenticated workload jobs for follow-up delivery and active-copy minimization."""

from datetime import timedelta
from typing import Protocol, cast
from uuid import UUID, uuid4

from care_link_contracts import validate_contract
from care_link_domain import DutyActor, DutyAuthorityPort, DutyScope, ManualError

from ..control import ManualService
from ..duties import DutyCommands
from ..store import Record, Transaction, instant, number, text
from ..values import object_value
from .purge import CopyPurger


class LifecycleDutyAuthority(DutyAuthorityPort, Protocol):
    def authorize_batch(
        self, actor: DutyActor, action: str, request_digest: str, scope: DutyScope, count: int
    ) -> DutyActor: ...


class LifecycleJobs(DutyCommands):
    def __init__(self, service: ManualService, authority: LifecycleDutyAuthority) -> None:
        super().__init__(service, authority)
        self.batch_authority = authority

    @staticmethod
    def _scope(action: str, snapshot: Record) -> DutyScope:
        return DutyScope(None, None, text(snapshot, "purpose"))

    def _snapshot(self, tx: Transaction, action: str, data: Record) -> Record:
        control = tx.get("control", "demo")
        if control is None:
            raise ManualError("manual.bootstrap_missing", 503)
        return {
            "control": control,
            "target": None,
            "subject": None,
            "guard": None,
            "session": None,
            "assignment": None,
            "job": None,
            "purpose": "rights",
        }

    def lifecycle_due(self, actor: DutyActor, key: str, data: Record) -> Record:
        validate_contract("LifecycleDueRequest", data)
        if str(UUID(key)) != key:
            raise ManualError("manual.invalid_operation", 400)
        action = "lifecycle_due"
        binding = self.binding(action, key, data)
        self.batch_authority.authorize_batch(
            actor, action, binding, actor.scope, cast(int, data["batch_limit"])
        )
        with self.service.store.transaction(actor, None, locked=False) as tx:
            snapshot = self._snapshot(tx, action, data)
            scope = self._scope(action, snapshot)
            current = self.authority.current(actor, action, binding, scope)
            request = self._policy(current, action, key, binding, snapshot)
            validate_contract("PolicyInput", request)
        decision = self.service.policy.evaluate(request)
        self.service.check_policy_decision(decision, request)
        with self.service.store.transaction(actor, None) as tx:
            latest = self._snapshot(tx, action, data)
            if (
                self.authority.current(actor, action, binding, scope) != current
                or self._versions(actor, latest) != request["versions"]
            ):
                raise ManualError("manual.stale_authority", 409)
            self.batch_authority.authorize_batch(
                actor, action, binding, scope, cast(int, data["batch_limit"])
            )
            self.service.assert_journal_current(latest)
            old = self._record(
                tx.connection.execute(
                    "SELECT * FROM durable.duty_operation WHERE operation_id=%s FOR UPDATE", (key,)
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
            delivered: list[str] = []
            if old:
                if (
                    old["actor_id"] != actor.actor_id
                    or old["workload_id"] != actor.workload_id
                    or old["action"] != action
                    or old["payload_digest"] != binding
                ):
                    raise ManualError("manual.idempotency_conflict", 409)
                result: Record = {
                    "operation_id": key,
                    "state": old["state"],
                    "resource_id": old["resource_id"],
                    "revision": str(number(old, "revision")),
                    "audit_ref": old["canonical_audit_id"],
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
                )
            else:
                count, delivered = self._work(tx, data)
                audit_id = str(uuid4())
                result = {
                    "operation_id": key,
                    "state": "committed",
                    "resource_id": None,
                    "revision": str(count),
                    "audit_ref": audit_id,
                }
                tx.connection.execute(
                    "INSERT INTO durable.duty_operation "
                    "(operation_id,actor_id,workload_id,action,payload_digest,resource_id,"
                    "revision,canonical_audit_id,created_at) "
                    "VALUES(%s,%s,%s,%s,%s,NULL,%s,%s,%s)",
                    (
                        key,
                        actor.actor_id,
                        actor.workload_id,
                        action,
                        binding,
                        count,
                        audit_id,
                        self.clock(),
                    ),
                )
                self._recheck_deliveries(tx, delivered)
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
            if not old:
                self._recheck_deliveries(tx, delivered)
            if nonce is None:
                tx.connection.execute(
                    "INSERT INTO durable.duty_nonce VALUES(%s,%s,%s,%s)",
                    (actor.nonce, actor.actor_id, key, binding),
                )
            self.service.check_policy_decision(decision, request)
            self.batch_authority.authorize_batch(
                actor, action, binding, scope, cast(int, data["batch_limit"])
            )
            self.service.assert_journal_current(latest)
            if (
                actor.expires_at <= self.clock()
                or actor.request_deadline
                and actor.request_deadline <= self.clock()
            ):
                raise ManualError("manual.deadline", 503)
            validate_contract("CommandResult", result)
        return result

    def _work(self, tx: Transaction, data: Record) -> tuple[int, list[str]]:
        limit = cast(int, data["batch_limit"])
        count = 0
        delivered: list[str] = []
        if data["class"] == "session":
            rows = tx.connection.execute(
                "SELECT id,session_id FROM care.follow_up WHERE state IN "
                "('scheduled','claimed','unknown','reconciliation_needed') "
                "AND due_at<=%s ORDER BY due_at,id LIMIT %s",
                (self.clock(), limit),
            ).fetchall()
            for value in rows:
                sid = str(value["session_id"])
                tx.scope(sid)
                row = tx.get("followup", str(value["id"]))
                if row is None:
                    continue
                subject = tx.get("subject", text(row, "subject_id"))
                inbox = tx.rows("inbox", effect_key=row["effect_key"], limit=2)
                if inbox:
                    row["state"] = "sent"
                    row["inbox_message_id"] = inbox[0]["id"]
                elif row["cancel_requested"]:
                    row["state"] = "cancelled"
                    row["fence"] = number(row, "fence") + 1
                elif instant(row, "expires_at") <= self.clock():
                    row["state"] = "expired"
                elif subject is None or subject["delete_state"] != "active":
                    row["state"] = "cancelled"
                else:
                    try:
                        self.service.contact_grant(tx, row, self.clock())
                    except ManualError:
                        row["state"] = "cancelled"
                    else:
                        # All senders acquire this same global guard and followup
                        # row; absence plus fence increment invalidates old sends.
                        row["fence"] = number(row, "fence") + 1
                        row["state"] = "authorized"
                        message_id = str(uuid4())
                        session = tx.get("session", sid)
                        if session is None:
                            raise ManualError("manual.not_found", 404)
                        message: Record = {
                            "id": message_id,
                            "session_id": sid,
                            "subject_id": row["subject_id"],
                            "recipient_account_id": row["recipient_account_id"],
                            "followup_id": row["id"],
                            "effect_key": row["effect_key"],
                            "text_ciphertext": self.service.cipher.encrypt(
                                "Comment allez-vous depuis notre dernier échange? "
                                "Vous pouvez choisir de demander du soutien."
                                if session["locale"] == "fr-CA"
                                else "How have you been since our last conversation? "
                                "You can choose to ask for support."
                            ),
                            "sources": [],
                            "created_at": self.clock(),
                            "expires_at": self.clock() + timedelta(days=7),
                            "read_at": None,
                        }
                        tx.put("inbox", message)
                        self.service.register_lifecycle_copy(
                            tx, session, "inbox", message_id, expiry=message["expires_at"]
                        )
                        row["state"] = "sent"
                        row["inbox_message_id"] = message_id
                        delivered.append(text(row, "id"))
                row["revision"] = number(row, "revision") + 1
                tx.put("followup", row)
                count += 1
        count += CopyPurger(self.service, self.clock).run(tx, data, limit - count)
        return count, delivered

    def _recheck_deliveries(self, tx: Transaction, delivered: list[str]) -> None:
        for followup_id in delivered:
            row = tx.peek("followup", followup_id)
            if row is None or instant(row, "expires_at") <= self.clock():
                raise ManualError("manual.followup_expired", 409)
            tx.scope(text(row, "session_id"))
            self.service.contact_grant(tx, row, self.clock())
            subject = tx.get("subject", text(row, "subject_id"))
            if subject is None or subject["delete_state"] != "active":
                raise ManualError("manual.subject_restricted", 409)
