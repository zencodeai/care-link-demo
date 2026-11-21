"""Authenticated retention holds; journal before active-copy restriction changes."""

from uuid import uuid4

from care_link_contracts import validate_contract
from care_link_domain import Actor, ManualError

from ..engine import Engine
from ..store import Record, Transaction, instant, number, text
from ..values import Outcome, dt, integer, object_value, stamp


class Holds(Engine):
    def hold_create(self, actor: Actor, key: str, data: Record) -> Record:
        def apply(
            tx: Transaction, current: Actor, body: Record, _s: Record | None, _g: Record | None
        ) -> Outcome:
            control = tx.get("control", "demo")
            if control is None:
                raise ManualError("manual.bootstrap_missing", 503)
            if integer(body["expected_revision"]) != number(control, "epoch"):
                raise ManualError("manual.stale_revision", 409)
            scope = object_value(body["scope"])
            if scope["subject_id"] is None and scope["session_id"] is None:
                raise ManualError("manual.hold_scope_required", 422)
            expiry = dt(body["expires_at"]) if body["expires_at"] else None
            if expiry and expiry <= self.clock():
                raise ManualError("manual.hold_expired", 422)
            value: Record = {
                "id": str(uuid4()),
                "revision": 1,
                "scope": scope,
                "reason": body["reason"],
                "authority_ref": body["authority_ref"],
                "actor_id": current.account_id,
                "created_at": self.clock(),
                "expires_at": expiry,
                "released_at": None,
            }
            self.append_restriction(
                tx,
                key,
                control,
                {
                    "kind": "hold",
                    "hold_id": value["id"],
                    "scope": scope,
                    "authority_ref": body["authority_ref"],
                    "starts_at": stamp(instant(value, "created_at")),
                    "expires_at": body["expires_at"],
                },
                scope,
            )
            tx.put("hold", value)
            control["epoch"] = number(control, "epoch") + 1
            tx.put("control", control)
            return Outcome(
                "CommandResult",
                {
                    "operation_id": key,
                    "state": "committed",
                    "resource_id": value["id"],
                    "revision": "1",
                    "audit_ref": str(uuid4()),
                },
                text(value, "id"),
            )

        return self._run(actor, "hold_create", key, data, None, apply, contract="HoldCommand")

    def hold_release(self, actor: Actor, key: str, data: Record, hold_id: str) -> Record:
        validate_contract("RevisionCommand", data)

        def apply(
            tx: Transaction, _a: Actor, body: Record, _s: Record | None, _g: Record | None
        ) -> Outcome:
            row = tx.get("hold", hold_id)
            control = tx.get("control", "demo")
            if row is None or control is None:
                raise ManualError("manual.not_found", 404)
            if integer(body["expected_revision"]) != number(row, "revision"):
                raise ManualError("manual.stale_revision", 409)
            if row["released_at"] is None:
                # Reassert the original external restriction before recording a DB
                # release. Recovery must verify this committed release+audit;
                # an intent ahead of DB never weakens the original hold.
                self.append_restriction(
                    tx,
                    key,
                    control,
                    {
                        "kind": "hold",
                        "hold_id": hold_id,
                        "scope": row["scope"],
                        "authority_ref": row["authority_ref"],
                        "starts_at": stamp(instant(row, "created_at")),
                        "expires_at": stamp(instant(row, "expires_at"))
                        if row["expires_at"]
                        else None,
                    },
                    object_value(row["scope"]),
                )
                row["released_at"] = self.clock()
                row["revision"] = number(row, "revision") + 1
                tx.put("hold", row)
                control["epoch"] = number(control, "epoch") + 1
                tx.put("control", control)
            return Outcome(
                "CommandResult",
                {
                    "operation_id": key,
                    "state": "committed",
                    "resource_id": hold_id,
                    "revision": str(number(row, "revision")),
                    "audit_ref": str(uuid4()),
                },
                hold_id,
            )

        return self._run(actor, "hold_release", key, {**data, "hold_id": hold_id}, None, apply)
