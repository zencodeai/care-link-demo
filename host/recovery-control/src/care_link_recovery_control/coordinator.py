"""Current-authority recovery orchestration; no live deployment at import time."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID, uuid5

from care_link_contracts import validate_contract
from care_link_domain import Actor, JournalState, ManualError

from .capture import EncryptedCaptures
from .encoding import canonical, digest, signed, stamp
from .journal import FileJournal
from .ledger import MAX_GENERATION, RecoveryLedger
from .ports import CaptureSource, RecoveryAuthority, RecoveryHuman, RecoveryTargets

ROLES = {
    "backup_capture": {"operator"},
    "backup_read": {"operator"},
    "restore_create": {"operator"},
    "restore_read": {"operator", "security"},
    "restore_validate": {"operator"},
    "promotion_propose": {"operator"},
    "promotion_approve": {"security", "governance"},
    "promotion_execute": {"operator"},
    "promotion_read": {"operator", "security", "governance"},
    "evidence_target": {"operator", "security", "governance"},
    "evidence_promotion": {"operator", "security", "governance"},
}
REQUESTS = {
    "backup_capture": "Empty",
    "restore_create": "RestoreCreate",
    "restore_validate": "RevisionCommand",
    "promotion_propose": "PromotionPropose",
    "promotion_approve": "PromotionApprove",
    "promotion_execute": "PromotionExecute",
}


def mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ManualError("recovery.ledger_invalid", 503)
    return cast(dict[str, object], value)


def head_binding(head: JournalState) -> dict[str, object]:
    return {
        "journal_id": head.journal_id,
        "journal_generation": str(head.generation),
        "tip": str(head.tip),
        "head_digest": head.tip_digest,
        "restriction_barrier": str(head.restriction_barrier),
    }


def next_generation(state: dict[str, object]) -> int:
    value = state.get("next_generation")
    if type(value) is not int or not 1 <= value <= MAX_GENERATION:
        raise ManualError("recovery.generation_exhausted", 503)
    return value


def human_record(human: RecoveryHuman) -> dict[str, object]:
    return {
        "account_id": human.account_id,
        "human_id": human.human_id,
        "role": human.role,
        "identity_revision": human.identity_revision,
        "role_revision": human.role_revision,
        "expires_at": stamp(human.expires_at),
    }


def human_value(value: object) -> RecoveryHuman:
    row = mapping(value)
    return RecoveryHuman(
        str(row["account_id"]),
        str(row["human_id"]),
        str(row["role"]),
        int(str(row["identity_revision"])),
        int(str(row["role_revision"])),
        datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00")),
    )


class RecoveryCoordinator:
    def __init__(
        self,
        captures: EncryptedCaptures,
        journal: FileJournal,
        ledger: RecoveryLedger,
        targets: RecoveryTargets,
        authority: RecoveryAuthority,
        source: CaptureSource,
        target_root: Path,
        *,
        host_custody: Callable[[], bool],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        crash_hook: Callable[[str], None] | None = None,
    ) -> None:
        if target_root.is_symlink() or not target_root.is_dir():
            raise ManualError("recovery.target_custody_unavailable", 503)
        self.captures, self.journal, self.ledger = captures, journal, ledger
        self.targets, self.authority, self.source = targets, authority, source
        self.target_root, self.clock, self.crash_hook = target_root, clock, crash_hook
        self.host_custody = host_custody

    def execute(
        self,
        operation: str,
        actor: Actor,
        body: dict[str, object] | None = None,
        resource_id: str | None = None,
        command_id: str | None = None,
    ) -> dict[str, object]:
        self.require_host_custody()
        human = self.authority.current(actor, operation)
        if (
            operation not in ROLES
            or human.role not in ROLES[operation]
            or human.expires_at <= self.clock()
            or not human.human_id
            or human.account_id != actor.account_id
        ):
            raise ManualError("recovery.current_human_required")
        request = mapping(body or {})
        if operation in REQUESTS:
            validate_contract(REQUESTS[operation], request)
            if command_id is None:
                raise ManualError("recovery.command_id_required", 422)
            command_id = str(UUID(command_id))
        if resource_id is not None:
            resource_id = str(UUID(resource_id))
        with self.ledger.exclusive():
            state = self.ledger.load()
            commands = mapping(state["commands"])
            command_digest = digest(
                canonical(
                    {
                        "operation": operation,
                        "body": request,
                        "resource": resource_id,
                        "account": human.account_id,
                    }
                )
            )
            if command_id is not None and command_id in commands:
                old = mapping(commands[command_id])
                if old["digest"] != command_digest:
                    raise ManualError("recovery.idempotency_conflict", 409)
                if old["state"] != "committed":
                    raise ManualError("recovery.operation_uncertain", 409)
                return self._repeat(operation, state, old, command_id)
            if command_id is not None:
                commands[command_id] = {"digest": command_digest, "state": "pending"}
                self.ledger.save(state)
            result = self._apply(operation, actor, human, request, resource_id, command_id, state)
            if command_id is not None:
                commands[command_id] = {
                    "digest": command_digest,
                    "state": "committed",
                    "resource_id": result.get("resource_id", result.get("id")),
                    "audit_ref": result.get("audit_ref", command_id),
                }
                self.ledger.save(state)
            return result

    def require_host_custody(self) -> None:
        if not self.host_custody():
            raise ManualError("recovery.continuing_host_custody_required", 503)

    def _repeat(
        self, operation: str, state: dict[str, object], old: dict[str, object], command_id: str
    ) -> dict[str, object]:
        identity = str(old["resource_id"])
        if operation == "backup_capture":
            return self.captures.inspect(identity)
        if operation in {"restore_create", "restore_validate"}:
            return self._target_view(self.get_record(state, "targets", identity))
        proposal = self.get_record(state, "promotions", identity)
        return self._command(command_id, identity, proposal, str(old["audit_ref"]))

    @staticmethod
    def get_record(state: dict[str, object], table: str, identity: str | None) -> dict[str, object]:
        row = mapping(state[table]).get(str(identity))
        if row is None:
            raise ManualError("recovery.resource_missing", 404)
        return mapping(row)

    def _apply(
        self,
        operation: str,
        actor: Actor,
        human: RecoveryHuman,
        body: dict[str, object],
        resource_id: str | None,
        command_id: str | None,
        state: dict[str, object],
    ) -> dict[str, object]:
        if operation == "backup_capture":
            material = self.source.capture()
            identity = str(uuid5(UUID(str(command_id)), "backup"))
            return self.captures.capture(
                identity,
                material.objects,
                material.metadata,
                self.journal.head(),
                capture_at=material.capture_at,
            )
        if operation == "backup_read":
            return self.captures.inspect(str(resource_id))
        if operation == "restore_create":
            recovery_started_at = stamp(self.clock())
            if body["expected_revision"] != "0":
                raise ManualError("recovery.stale_revision", 409)
            backup = str(body["backup_id"])
            manifest = self.captures.manifest(backup)
            if digest(canonical(manifest)) != body["manifest_digest"]:
                raise ManualError("recovery.backup_changed", 409)
            staged = self.captures.restore_quarantine(
                backup, self.target_root / str(command_id), self.journal.head()
            )
            row: dict[str, object] = {
                "id": staged.target_id,
                "revision": 1,
                "backup_id": backup,
                "state": "quarantined",
                "head": head_binding(staged.journal),
                "validation_digest": None,
                "serving_generation": "0",
                "manifest": manifest,
                "operator": human_record(human),
                "created_at": recovery_started_at,
                "capture_at": manifest["capture_at"],
            }
            mapping(state["targets"])[staged.target_id] = row
            self.ledger.save(state)
            self.targets.create(staged, manifest)
            return self._target_view(row)
        if operation == "restore_read":
            return self._target_view(self.get_record(state, "targets", resource_id))
        if operation == "restore_validate":
            row = self.get_record(state, "targets", resource_id)
            if str(row["revision"]) != body["expected_revision"]:
                raise ManualError("recovery.stale_revision", 409)
            if row["state"] == "serving":
                raise ManualError("recovery.serving_target_cannot_revalidate", 409)
            generation = next_generation(state)
            head = self.journal.head()
            self.captures.inspect(str(row["backup_id"]))
            evidence = self.targets.reconcile(str(row["id"]), head, self.journal.records())
            keys = {
                "target_id",
                "target_digest",
                "audit_digest",
                "rights_digest",
                "uncertainties",
                "schema_digest",
                "artifact_digest",
            }
            manifest = mapping(row["manifest"])
            if (
                set(evidence) != keys
                or evidence["target_id"] != row["id"]
                or evidence["uncertainties"] != []
                or evidence["schema_digest"] != manifest["schema_digest"]
                or evidence["artifact_digest"] != manifest["artifact_digest"]
                or evidence["target_digest"] != self.targets.inspect(str(row["id"]))
                or head_binding(self.journal.head()) != head_binding(head)
            ):
                raise ManualError("recovery.validation_incomplete", 409)
            row.update(
                evidence=evidence,
                head=head_binding(head),
                state="validated",
                validation_digest=digest(canonical(evidence)),
                revision=int(str(row["revision"])) + 1,
                serving_generation=str(generation),
            )
            self.ledger.save(state)
            return self._target_view(row)
        if operation == "evidence_target":
            return self._binding(self.get_record(state, "targets", resource_id), state)
        if operation == "evidence_promotion":
            return mapping(self.get_record(state, "promotions", resource_id)["binding"])
        if operation == "promotion_read":
            return self._promotion_view(self.get_record(state, "promotions", resource_id))
        if operation == "promotion_propose":
            target = self.get_record(state, "targets", str(body["target_id"]))
            binding = self._binding(target, state)
            if (
                body["binding"] != binding
                or body["expected_revision"] != str(target["revision"])
                or any(
                    body[k] != binding[k]
                    for k in (
                        "backup_digest",
                        "head_digest",
                        "restriction_barrier",
                        "validation_digest",
                        "serving_generation",
                    )
                )
            ):
                raise ManualError("recovery.exact_binding_required", 409)
            identity = str(uuid5(UUID(str(command_id)), "promotion"))
            proposal: dict[str, object] = {
                "id": identity,
                "revision": 1,
                "target_id": target["id"],
                "binding": binding,
                "binding_digest": digest(canonical(binding)),
                "state": "proposed",
                "approval_id": None,
                "expires_at": None,
                "operator": target["operator"],
                "proposer": human_record(human),
                "proposed_at": stamp(self.clock()),
                "expected_old_generation": str(next_generation(state) - 1),
            }
            mapping(state["promotions"])[identity] = proposal
            target["state"] = "promotion_pending"
            self.ledger.save(state)
            return self._command(str(command_id), identity, proposal)
        if operation == "promotion_approve":
            proposal = self.get_record(state, "promotions", str(body["proposal_id"]))
            self.require_fresh_proposal(proposal, state)
            expiry = datetime.fromisoformat(str(body["expires_at"]).replace("Z", "+00:00"))
            if (
                body["exact_binding_digest"] != proposal["binding_digest"]
                or not self.clock() < expiry <= self.clock() + timedelta(seconds=300)
                or proposal["state"] != "proposed"
            ):
                raise ManualError("recovery.exact_unexpired_approval_required", 409)
            approver = self.authority.approval(
                actor,
                str(body["ceremony_id"]),
                str(proposal["id"]),
                str(proposal["binding_digest"]),
                expiry,
            )
            if approver != human or approver.human_id in {
                human_value(proposal["operator"]).human_id,
                human_value(proposal["proposer"]).human_id,
            }:
                raise ManualError("recovery.independent_human_required")
            proposal.update(
                approval_id=str(uuid5(UUID(str(command_id)), "approval")),
                expires_at=stamp(expiry),
                approver=human_record(approver),
                approved_at=stamp(self.clock()),
                state="approved",
                revision=int(str(proposal["revision"])) + 1,
            )
            self.ledger.save(state)
            return self._command(str(command_id), str(proposal["id"]), proposal)
        if operation == "promotion_execute":
            proposal = self.get_record(state, "promotions", str(body["proposal_id"]))
            if (
                proposal["state"] != "approved"
                or body["approval_id"] != proposal["approval_id"]
                or body["exact_binding_digest"] != proposal["binding_digest"]
                or body["expected_serving_generation"] != proposal["expected_old_generation"]
            ):
                raise ManualError("recovery.approved_binding_required", 409)
            self._cutover(proposal, state)
            return self._command(str(command_id), str(proposal["id"]), proposal)
        raise ManualError("recovery.operation_unknown", 404)

    def _binding(self, target: dict[str, object], state: dict[str, object]) -> dict[str, object]:
        if target["state"] not in {"validated", "promotion_pending"}:
            raise ManualError("recovery.validated_target_required", 409)
        manifest, evidence, head = (mapping(target[k]) for k in ("manifest", "evidence", "head"))
        self.captures.inspect(str(target["backup_id"]))
        if (
            head != head_binding(self.journal.head())
            or evidence["target_digest"] != self.targets.inspect(str(target["id"]))
            or target["serving_generation"] != str(next_generation(state))
        ):
            raise ManualError("recovery.revalidation_required", 409)
        binding: dict[str, object] = {
            "target_id": target["id"],
            "backup_digest": digest(canonical(manifest)),
            "schema_digest": manifest["schema_digest"],
            "artifact_digest": manifest["artifact_digest"],
            "journal_id": head["journal_id"],
            "journal_generation": head["journal_generation"],
            "head_digest": head["head_digest"],
            "restriction_barrier": head["restriction_barrier"],
            "validation_digest": target["validation_digest"],
            "serving_generation": target["serving_generation"],
        }
        validate_contract("PromotionBinding", binding)
        return binding

    def require_fresh_proposal(self, proposal: dict[str, object], state: dict[str, object]) -> None:
        target = self.get_record(state, "targets", str(proposal["target_id"]))
        if self._binding(target, state) != proposal["binding"]:
            raise ManualError("recovery.revalidation_required", 409)

    @staticmethod
    def _command(
        command_id: str, identity: str, row: dict[str, object], audit_ref: str | None = None
    ) -> dict[str, object]:
        return {
            "operation_id": command_id,
            "state": "committed",
            "resource_id": identity,
            "revision": str(row["revision"]),
            "audit_ref": audit_ref or command_id,
        }

    def _target_view(self, row: dict[str, object]) -> dict[str, object]:
        head = mapping(row["head"])
        public_head = signed(
            {
                "journal_id": head["journal_id"],
                "generation": head["journal_generation"],
                "tip": head["tip"],
                "tip_digest": head["head_digest"],
                "restriction_barrier": head["restriction_barrier"],
                "observed_at": stamp(self.clock()),
            },
            self.ledger.signer,
        )
        result = {
            key: row[key]
            for key in ("id", "backup_id", "state", "validation_digest", "serving_generation")
        }
        result.update(revision=str(row["revision"]), head=public_head)
        validate_contract("RestoreView", result)
        return result

    @staticmethod
    def _promotion_view(row: dict[str, object]) -> dict[str, object]:
        result = {
            key: row[key]
            for key in ("id", "target_id", "binding_digest", "state", "approval_id", "expires_at")
        }
        result["revision"] = str(row["revision"])
        validate_contract("PromotionView", result)
        return result

    def evidence_target(self, actor: Actor, target_id: str) -> dict[str, object]:
        return self.execute("evidence_target", actor, resource_id=target_id)

    def evidence_promotion(self, actor: Actor, proposal_id: str) -> dict[str, object]:
        return self.execute("evidence_promotion", actor, resource_id=proposal_id)

    def _cutover(self, proposal: dict[str, object], state: dict[str, object]) -> None:
        # Implemented below: every side-effect follows a durable restricting state.
        from .cutover import execute_cutover

        execute_cutover(self, proposal, state)
