"""Exact per-boot enforcer ACK under current workload duty authority."""

import time
from typing import cast
from uuid import UUID, uuid4

from care_link_contracts import ContractError, validate_contract
from care_link_domain import DutyActor, DutyScope, ManualError

from ..activation_fence import activation_effective
from ..duties import DutyCommands
from ..store import Record, Transaction, instant, number, text
from ..values import object_value
from .artifacts import reviews_current
from .projections import activation_view, required


class EnforcerAcknowledgements(DutyCommands):
    @staticmethod
    def _scope(action: str, snapshot: Record) -> DutyScope:
        del action, snapshot
        return DutyScope(None, None, "governance")

    def _ack_snapshot(self, tx: Transaction, data: Record) -> Record:
        control = required(tx, "control", "demo")
        activation = required(tx, "gov_activation", text(data, "activation_id"))
        instance = required(tx, "gov_instance", text(data, "instance_id"))
        return {
            "control": control,
            "activation": activation,
            "instance": instance,
            "target": None,
            "subject": None,
            "guard": None,
            "assignment": None,
            "session": None,
        }

    def activation_ack(self, actor: DutyActor, key: str, data: Record) -> Record:
        validate_contract("ActivationAck", data)
        binding = self.binding("activation_ack", key, data)
        authenticated = self.authority.current(
            actor, "activation_ack", binding, DutyScope(None, None, "governance")
        )
        try:
            return self._activation_ack(actor, key, data)
        except (ManualError, ContractError) as cause:
            error = (
                cause
                if isinstance(cause, ManualError)
                else ManualError("manual.policy_contract_unavailable", 503)
            )
            if error.code != "manual.commit_unknown":
                self._record_denial(authenticated, "activation_ack", key, binding, error)
            if isinstance(cause, ManualError):
                raise
            raise error from cause

    def _activation_ack(self, actor: DutyActor, key: str, data: Record) -> Record:
        started = time.monotonic()
        if str(UUID(key)) != key:
            raise ManualError("manual.invalid_operation", 400)
        validate_contract("ActivationAck", data)
        action = "activation_ack"
        binding = self.binding(action, key, data)
        scope = DutyScope(None, None, "governance")
        current = self.authority.current(actor, action, binding, scope)
        with self.service.store.transaction(current, None, locked=False) as tx:
            snapshot = self._ack_snapshot(tx, data)
            request = self._policy(current, action, key, binding, snapshot)
            validate_contract("PolicyInput", request)
        decision = self.service.policy.evaluate(request)
        self.service.check_policy_decision(decision, request)
        with self.service.store.transaction(current, None) as tx:
            latest = self._ack_snapshot(tx, data)
            if (
                self.authority.current(actor, action, binding, scope) != current
                or self._versions(current, latest) != request["versions"]
            ):
                raise ManualError("governance.enforcer_authority_changed", 409)
            self.service.assert_journal_current(latest)
            row = object_value(latest["activation"])
            instance = object_value(latest["instance"])
            if (
                instance["workload_id"] != actor.workload_id
                or instance["actor_id"] != actor.actor_id
                or instance["boot_id"] != data["boot_id"]
                or instance["healthy"] is not True
                or not 0 <= (self.clock() - instant(instance, "observed_at")).total_seconds() <= 30
                or data["instance_id"] not in cast(list[str], row["required_instances"])
                or data["epoch"] != str(number(row, "epoch"))
                or data["bundle_digest"] != row["bundle_digest"]
                or row["state"] not in {"staged", "ready", "active"}
                or row["state"] == "active"
                and not activation_effective(tx, object_value(latest["control"]), row)
            ):
                raise ManualError("governance.exact_current_boot_ack_required")
            prior = tx.connection.execute(
                "SELECT * FROM durable.duty_operation WHERE operation_id=%s FOR UPDATE", (key,)
            ).fetchone()
            nonce = tx.connection.execute(
                "SELECT * FROM durable.duty_nonce WHERE nonce=%s FOR UPDATE", (actor.nonce,)
            ).fetchone()
            if nonce and (
                str(nonce["operation_id"]) != key
                or str(nonce["actor_id"]) != actor.actor_id
                or nonce["request_digest"] != binding
            ):
                raise ManualError("manual.duty_nonce_used", 409)
            if prior and (
                prior["payload_digest"] != binding or str(prior["actor_id"]) != actor.actor_id
            ):
                raise ManualError("manual.idempotency_conflict", 409)
            if prior and prior["state"] == "rejected":
                raise ManualError("manual.operation_rejected", 409)
            if prior is None:
                old = tx.rows(
                    "gov_ack", activation_id=row["id"], instance_id=data["instance_id"], limit=1
                )
                ack: Record = {
                    "id": old[0]["id"] if old else key,
                    "activation_id": row["id"],
                    "instance_id": data["instance_id"],
                    "boot_id": data["boot_id"],
                    "epoch": number(row, "epoch"),
                    "bundle_digest": data["bundle_digest"],
                    "status": data["status"],
                    "created_at": self.clock(),
                }
                tx.put("gov_ack", ack)
                row["revision"] = number(row, "revision") + 1
                was_active = row["state"] == "active"
                row["state"] = "active" if was_active else "staged"
                if data["status"] == "rejected" and not was_active:
                    row["state"] = "rejected"
                elif not was_active and not activation_view(tx, row)["missing_instances"]:
                    try:
                        reviews_current(
                            tx,
                            required(tx, "gov_artifact", text(row, "bundle_digest")),
                            self.clock(),
                        )
                    except ManualError:
                        pass  # ACK is readiness evidence, never review authority.
                    else:
                        row["state"] = "ready"
                tx.put("gov_activation", row)
            result = activation_view(tx, row)
            audit_id = str(uuid4())
            if prior is None:
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
                        row["id"],
                        row["revision"],
                        audit_id,
                        self.clock(),
                    ),
                )
            if nonce is None:
                tx.connection.execute(
                    "INSERT INTO durable.duty_nonce VALUES(%s,%s,%s,%s)",
                    (actor.nonce, actor.actor_id, key, binding),
                )
            self._audit(
                tx,
                current,
                action + ".replay" if prior else action,
                str(uuid4()) if prior else key,
                binding,
                result,
                object_value(request["versions"]),
                audit_id,
            )
            self.service.check_policy_decision(decision, request)
            if (
                self.authority.current(actor, action, binding, scope) != current
                or time.monotonic() - started >= 1
                or actor.expires_at <= self.clock()
            ):
                raise ManualError("governance.enforcer_authority_changed", 409)
            if activation_view(tx, row) != result:
                raise ManualError("governance.enforcer_state_changed", 409)
            validate_contract("ActivationView", result)
        return result
