"""Guarded desired/current activation, per-boot ACKs and higher-epoch rollback."""

from typing import cast

from care_link_contracts import validate_contract
from care_link_domain import Actor, ManualError

from ..engine import Engine
from ..store import Record, Transaction, instant, number, text
from ..values import Outcome, digest, dt, integer, object_value, stamp
from .artifacts import reviews_current, verified_candidate
from .authority import current_human
from .projections import activation_view, required

MODE_ORDER = {"normal": 0, "ai_disabled": 1, "restricted": 2, "quarantine": 3}
SCOPE: Record = {
    "session_id": None,
    "subject_id": None,
    "purpose": "governance",
    "fields": [],
    "recipient_id": None,
}


def instances_current(tx: Transaction) -> list[str]:
    rows = tx.rows("gov_instance", required=True, limit=33)
    if not rows or len(rows) > 32:
        raise ManualError("governance.required_instances_unknown", 503)
    return sorted(text(r, "instance_id") for r in rows)


def stage_ready(tx: Transaction, row: Record) -> None:
    if sorted(cast(list[str], row["required_instances"])) != instances_current(tx):
        raise ManualError("governance.instance_set_changed", 409)
    if activation_view(tx, row)["missing_instances"]:
        raise ManualError("governance.current_boot_ack_required", 409)


def activation_evidence(tx: Transaction, row: Record) -> Record:
    reviews = tx.rows("gov_review", artifact_digest=row["bundle_digest"], limit=100)
    acknowledgements = tx.rows("gov_ack", activation_id=row["id"], limit=33)
    if len(reviews) == 100 or len(acknowledgements) > 32:
        raise ManualError("governance.activation_evidence_limit", 503)
    return {
        "activation_id": row["id"],
        "epoch": str(number(row, "epoch")),
        "bundle_digest": row["bundle_digest"],
        "required_instances": row["required_instances"],
        "reviews": [
            {
                "id": r["id"],
                "reviewer_human_id": r["reviewer_human_id"],
                "authority_class": r["authority_class"],
                "decision": r["decision"],
                "evidence_digest": r["evidence_digest"],
                "expires_at": stamp(instant(r, "expires_at")),
            }
            for r in reviews
        ],
        "acks": [
            {k: a[k] for k in ("instance_id", "boot_id", "bundle_digest", "epoch", "status")}
            for a in acknowledgements
        ],
    }


class Activations(Engine):
    def activation_create(self, actor: Actor, key: str, data: Record) -> Record:
        def create(
            tx: Transaction, current: Actor, body: Record, _s: Record | None, _g: Record | None
        ) -> Outcome:
            current_human(tx, current, self.clock(), "operations")
            old = tx.get("gov_activation", key)
            if old:
                return Outcome("ActivationView", activation_view(tx, old), key)
            control = required(tx, "control", "demo")
            if integer(body["expected_epoch"]) != number(control, "epoch"):
                raise ManualError("governance.stale_epoch", 409)
            artifact = required(tx, "gov_artifact", text(body, "artifact_digest"))
            if artifact["kind"] != "policy":
                raise ManualError("governance.non_policy_activation_not_supported", 422)
            manifest, _classification = verified_candidate(tx, object_value(artifact["metadata"]))
            if integer(manifest["compatible_serving_generation"]) != number(
                control, "serving_generation"
            ):
                raise ManualError("governance.incompatible_serving_generation", 409)
            names = cast(list[str], body["required_instances"])
            if sorted(names) != instances_current(tx):
                raise ManualError("governance.required_instances_mismatch", 422)
            epoch = number(control, "epoch") + 1
            integer(epoch)
            restrictive = MODE_ORDER[text(manifest, "mode")] > MODE_ORDER[text(control, "mode")]
            row: Record = {
                "id": key,
                "epoch": epoch,
                "base_epoch": number(control, "epoch"),
                "bundle_digest": artifact["digest"],
                "state": "staged",
                "required_instances": names,
                "revision": 1,
                "effective_at": dt(body["effective_at"]),
                "created_at": self.clock(),
                "restrictive": restrictive,
                "proposer_account_id": current.account_id,
            }
            if restrictive:
                # Fence centrally before broadcasting; keep old evaluator bytes
                # until all exact candidate ACKs and reviews are current.
                control["epoch"] = epoch
                control["mode"] = manifest["mode"]
                self.append_restriction(
                    tx,
                    key,
                    control,
                    {
                        "kind": "kill",
                        "mode": manifest["mode"],
                        "epoch": str(epoch),
                        "bundle_digest": control["bundle_digest"],
                    },
                    SCOPE,
                )
                tx.put("control", control)
            tx.put("gov_activation", row)
            return Outcome("ActivationView", activation_view(tx, row), key)

        return self._run(
            actor,
            "activation_create",
            key,
            data,
            None,
            create,
            contract="ActivationCreate",
            replay=create,
        )

    def activation_read(self, actor: Actor, activation_id: str) -> Record:
        def read(
            tx: Transaction, current: Actor, _b: Record, _s: Record | None, _g: Record | None
        ) -> Outcome:
            current_human(tx, current, self.clock())
            return Outcome(
                "ActivationView", activation_view(tx, required(tx, "gov_activation", activation_id))
            )

        return self._run(
            actor, "activation_read", None, {"activation_id": activation_id}, None, read
        )

    def activation_commit(self, actor: Actor, key: str, data: Record, activation_id: str) -> Record:
        validate_contract("RevisionCommand", data)

        def commit(
            tx: Transaction, current: Actor, body: Record, _s: Record | None, _g: Record | None
        ) -> Outcome:
            current_human(tx, current, self.clock(), "operations")
            row = required(tx, "gov_activation", activation_id)
            if row["state"] == "active":
                control = required(tx, "control", "demo")
                if (
                    control["epoch"] != row["epoch"]
                    or control["bundle_digest"] != row["bundle_digest"]
                ):
                    raise ManualError("governance.superseded_activation", 409)
                return Outcome("ActivationView", activation_view(tx, row), activation_id)
            if row["state"] not in {"staged", "ready"} or integer(
                body["expected_revision"]
            ) != number(row, "revision"):
                raise ManualError("governance.stale_activation", 409)
            if instant(row, "effective_at") > self.clock():
                raise ManualError("governance.activation_not_due", 409)
            control = required(tx, "control", "demo")
            expected = number(row, "epoch") if row["restrictive"] else number(row, "base_epoch")
            if number(control, "epoch") != expected:
                raise ManualError("governance.stale_epoch", 409)
            artifact = required(tx, "gov_artifact", text(row, "bundle_digest"))
            manifest, _classification = verified_candidate(tx, object_value(artifact["metadata"]))
            if integer(manifest["compatible_serving_generation"]) != number(
                control, "serving_generation"
            ):
                raise ManualError("governance.incompatible_serving_generation", 409)
            reviews_current(tx, artifact, self.clock())
            stage_ready(tx, row)
            # Rollback is this same new-epoch path. No credential, consent,
            # subject, hold, journal barrier or serving generation is rewound.
            before = self.journal.head()
            evidence = activation_evidence(tx, row)
            evidence["serving_generation"] = str(number(control, "serving_generation"))
            evidence_digest = digest(evidence)
            journal_request: Record = {
                "command_id": key,
                "expected_tip": str(before.tip),
                "kind": "relax_intent",
                "scope": SCOPE,
                "restriction": {"kind": "none"},
                "binding_digest": evidence_digest,
                "db_operation_id": key,
                "relaxation_evidence_digest": evidence_digest,
            }
            after = self.journal.append(journal_request)
            if (
                after.journal_id != before.journal_id
                or after.generation != before.generation
                or after.tip <= before.tip
                or after.restriction_barrier != before.restriction_barrier
            ):
                raise ManualError("governance.activation_journal_invalid", 503)
            control["journal_tip_seen"] = after.tip
            tx.put(
                "recovery",
                {
                    "command_id": key,
                    "intent_seq": after.tip,
                    "barrier_seq": after.restriction_barrier,
                    "payload_digest": digest(journal_request),
                    "state": "applied",
                    "db_operation_id": key,
                    "applied_at": self.clock(),
                },
            )
            control["epoch"] = number(row, "epoch")
            control["bundle_digest"] = row["bundle_digest"]
            control["mode"] = manifest["mode"]
            tx.put("control", control)
            row["state"] = "active"
            row["revision"] = number(row, "revision") + 1
            tx.put("gov_activation", row)
            artifact["state"] = "approved"
            artifact["last_activated_at"] = self.clock()
            tx.put("gov_artifact", artifact)
            return Outcome("ActivationView", activation_view(tx, row), activation_id)

        def replay(
            tx: Transaction, current: Actor, _b: Record, _s: Record | None, _g: Record | None
        ) -> Outcome:
            current_human(tx, current, self.clock(), "operations")
            row = required(tx, "gov_activation", activation_id)
            control = required(tx, "control", "demo")
            if (
                row["state"] != "active"
                or row["epoch"] != control["epoch"]
                or row["bundle_digest"] != control["bundle_digest"]
            ):
                raise ManualError("governance.superseded_activation", 409)
            return Outcome("ActivationView", activation_view(tx, row), activation_id)

        return self._run(
            actor,
            "activation_commit",
            key,
            {**data, "activation_id": activation_id},
            None,
            commit,
            replay=replay,
        )
