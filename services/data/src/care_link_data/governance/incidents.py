"""Bounded incident containment and receipt-bound recovery, never telemetry permission."""

from datetime import timedelta
from typing import cast

from care_link_contracts import validate_contract
from care_link_domain import Actor, ManualError

from ..engine import Engine
from ..store import Record, Transaction, instant, number, text
from ..values import Outcome, digest, dt, integer, object_value
from .authority import approval, current_human
from .projections import command, incident_view, required


class Incidents(Engine):
    def incident_create(self, actor: Actor, key: str, data: Record) -> Record:
        def create(
            tx: Transaction, current: Actor, body: Record, _s: Record | None, _g: Record | None
        ) -> Outcome:
            current_human(tx, current, self.clock())
            old = tx.get("gov_incident", key)
            if old:
                return Outcome("IncidentView", incident_view(old), key)
            row: Record = {
                "id": key,
                "kind": body["kind"],
                "severity": body["severity"],
                "scope": body["scope"],
                "evidence_refs": body["evidence_refs"],
                "revision": 1,
                "state": "open",
                "creator_id": current.account_id,
                "created_at": self.clock(),
                "review_due_at": self.clock()
                + timedelta(minutes=15 if body["severity"] == "critical" else 60),
                "recovery_approval_id": None,
                "containment_epoch": None,
            }
            tx.put("gov_incident", row)
            return Outcome("IncidentView", incident_view(row), key)

        return self._run(
            actor,
            "incident_create",
            key,
            data,
            None,
            create,
            contract="IncidentCreate",
            replay=create,
        )

    def incident_read(self, actor: Actor, incident_id: str) -> Record:
        def read(
            tx: Transaction, current: Actor, _b: Record, _s: Record | None, _g: Record | None
        ) -> Outcome:
            current_human(tx, current, self.clock())
            return Outcome("IncidentView", incident_view(required(tx, "gov_incident", incident_id)))

        return self._run(actor, "incident_read", None, {"incident_id": incident_id}, None, read)

    def incident_transition(self, actor: Actor, key: str, data: Record, incident_id: str) -> Record:
        validate_contract("IncidentTransition", data)

        def transition(
            tx: Transaction, current: Actor, body: Record, _s: Record | None, _g: Record | None
        ) -> Outcome:
            current_human(tx, current, self.clock())
            row = required(tx, "gov_incident", incident_id)
            if integer(body["expected_revision"]) != number(row, "revision"):
                raise ManualError("governance.stale_revision", 409)
            allowed = {
                "open": "contained",
                "contained": "reviewing",
                "reviewing": "remediated",
                "remediated": "closed",
            }
            if allowed.get(text(row, "state")) != body["target_state"]:
                raise ManualError("governance.incident_transition_denied", 409)
            if body["target_state"] in {"remediated", "closed"}:
                if not isinstance(body["recovery_approval_id"], str):
                    raise ManualError("governance.recovery_approval_required")
                approval(
                    tx,
                    current,
                    text(body, "recovery_approval_id"),
                    "incident_transition",
                    digest({k: v for k, v in body.items() if k != "recovery_approval_id"}),
                    self.clock(),
                )
                row["recovery_approval_id"] = body["recovery_approval_id"]
            if body["target_state"] == "contained":
                # Scoped incidents are durable review records. Subject/session
                # data remains fenced by existing inline subject controls; a
                # service-wide critical incident restricts the global capability.
                scope = object_value(row["scope"])
                if scope["session_id"] is not None or scope["subject_id"] is not None:
                    raise ManualError("governance.scoped_containment_requires_explicit_fence", 409)
                if scope["fields"]:
                    raise ManualError("governance.field_containment_not_supported", 409)
                control = required(tx, "control", "demo")
                if isinstance(scope["recipient_id"], str):
                    principal = required(tx, "principal", text(scope, "recipient_id"))
                    principal["identity_revision"] = number(principal, "identity_revision") + 1
                    principal["revoked"] = True
                    restriction = {
                        "kind": "identity_revoke",
                        "principal_id": principal["principal_id"],
                        "identity_revision": str(number(principal, "identity_revision")),
                        "disabled": True,
                    }
                    self.append_restriction(tx, key, control, restriction, scope)
                    tx.put("principal", principal)
                else:
                    control["epoch"] = number(control, "epoch") + 1
                    mode = "quarantine" if row["kind"] == "contamination" else "restricted"
                    if control["mode"] == "quarantine":
                        mode = "quarantine"
                    control["mode"] = mode
                    self.append_restriction(
                        tx,
                        key,
                        control,
                        {
                            "kind": "kill",
                            "mode": mode,
                            "epoch": str(number(control, "epoch")),
                            "bundle_digest": control["bundle_digest"],
                        },
                        scope,
                    )
                    tx.put("control", control)
                row["containment_epoch"] = control["epoch"]
            # Closing an incident never clears restrictions. Recovery requires
            # a separate exact approved activation with new ACKs and epoch.
            row["state"] = body["target_state"]
            row["revision"] = number(row, "revision") + 1
            row["evidence_refs"] = [
                *cast(list[str], row["evidence_refs"]),
                text(body, "evidence_digest"),
            ]
            tx.put("gov_incident", row)
            return Outcome("IncidentView", incident_view(row), incident_id)

        def replay(
            tx: Transaction, current: Actor, _b: Record, _s: Record | None, _g: Record | None
        ) -> Outcome:
            current_human(tx, current, self.clock())
            return Outcome(
                "IncidentView",
                incident_view(required(tx, "gov_incident", incident_id)),
                incident_id,
            )

        return self._run(
            actor,
            "incident_transition",
            key,
            {**data, "incident_id": incident_id},
            None,
            transition,
            replay=replay,
        )

    def exception_create(self, actor: Actor, key: str, data: Record) -> Record:
        def create(
            tx: Transaction, current: Actor, body: Record, _s: Record | None, _g: Record | None
        ) -> Outcome:
            current_human(tx, current, self.clock())
            control = required(tx, "control", "demo")
            if integer(body["expected_revision"]) != number(control, "epoch"):
                raise ManualError("governance.stale_epoch", 409)
            rule = required(tx, "gov_exception_rule", text(body, "policy_rule_id"))
            if rule["policy_rule_id"] not in {"demo.review_frequency"}:
                raise ManualError("governance.rule_not_overridable")
            if (
                rule["active"] is not True
                or rule["artifact_digest"] != control["bundle_digest"]
                or rule["scope"] != body["scope"]
                or rule["compensating_control_digest"] != body["compensating_control_digest"]
            ):
                raise ManualError("governance.exception_binding_denied")
            expiry = dt(body["expires_at"])
            if not self.clock() < expiry <= self.clock() + timedelta(minutes=15):
                raise ManualError("governance.exception_expiry_denied", 422)
            receipt = approval(
                tx,
                current,
                text(body, "approver_receipt_id"),
                "exception_create",
                digest({k: v for k, v in body.items() if k != "approver_receipt_id"}),
                self.clock(),
            )
            if expiry > instant(receipt, "expires_at"):
                raise ManualError("governance.exception_expiry_denied", 422)
            row: Record = {
                "id": key,
                "policy_rule_id": body["policy_rule_id"],
                "artifact_digest": control["bundle_digest"],
                "epoch": control["epoch"],
                "scope": body["scope"],
                "approver_receipt_id": body["approver_receipt_id"],
                "expires_at": expiry,
                "compensating_control_digest": body["compensating_control_digest"],
                "created_at": self.clock(),
            }
            if tx.get("gov_exception", key) is None:
                tx.put("gov_exception", row)
            return Outcome("CommandResult", command(key, key), key)

        return self._run(
            actor,
            "exception_create",
            key,
            data,
            None,
            create,
            contract="ExceptionCreate",
            replay=create,
        )
