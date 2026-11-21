"""Synthetic host adapters exercise durable orchestration and prohibited admission."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from care_link_domain import Actor, JournalState, ManualError
from care_link_recovery_control import (
    BoundGenerationJournal,
    CaptureInput,
    CaptureMetadata,
    EncryptedCaptures,
    FileJournal,
    QuarantineRestore,
    RecoveryCoordinator,
    RecoveryHuman,
    RecoveryLedger,
)
from care_link_recovery_control.coordinator import head_binding
from care_link_recovery_control.cutover import CUTOVER_BOUNDARIES
from care_link_recovery_control.encoding import canonical, digest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

NOW = datetime(2026, 11, 21, tzinfo=UTC)
META = CaptureMetadata("012", "a" * 64, "b" * 64, "c" * 64, "0/12345678")


def actor(role: str) -> Actor:
    return Actor(
        str(uuid4()),
        role,
        1,
        1,
        NOW,
        True,
        "d" * 64,
        1,
        "synthetic",
        NOW + timedelta(minutes=20),
        str(uuid4()),
    )


class Authority:
    def __init__(self):
        self.people: dict[str, RecoveryHuman] = {}
        self.revoked: set[str] = set()
        self.proofs: set[str] = set()

    def current(self, actor: Actor, operation: str) -> RecoveryHuman:
        if actor.account_id in self.revoked or not actor.mfa:
            raise ManualError("test.current_authority_denied")
        return self.people.setdefault(
            actor.account_id,
            RecoveryHuman(actor.account_id, actor.account_id, actor.role, 1, 1, actor.expires_at),
        )

    def approval(
        self,
        actor: Actor,
        ceremony_id: str,
        proposal_id: str,
        binding_digest: str,
        expires_at: datetime,
    ) -> RecoveryHuman:
        if ceremony_id in self.proofs:
            raise ManualError("test.ceremony_consumed")
        self.proofs.add(ceremony_id)
        return self.current(actor, "promotion_approve")

    def still_current(self, human: RecoveryHuman) -> bool:
        return human.account_id not in self.revoked


class Targets:
    def __init__(self):
        self.rows: dict[str, str] = {}
        self.route_id: str | None = None
        self.generation = 0
        self.uncertainties: list[str] = []
        self.smoke_ok = True
        self.effects: list[str] = []

    def create(self, staged: QuarantineRestore, metadata: dict[str, object]) -> None:
        self.rows[staged.target_id] = digest((staged.path / "database.dump").read_bytes())

    def reconcile(
        self, target_id: str, head: JournalState, records: tuple[dict[str, object], ...]
    ) -> dict[str, object]:
        return {
            "target_id": target_id,
            "target_digest": self.rows[target_id],
            "audit_digest": META.audit_digest,
            "rights_digest": "e" * 64,
            "uncertainties": self.uncertainties,
            "schema_digest": META.schema_digest,
            "artifact_digest": META.artifact_digest,
        }

    def inspect(self, target_id: str) -> str:
        return self.rows[target_id]

    def fence_all(self) -> None:
        self.effects.append("fence")
        self.generation = 0

    def route(self, target_id: str) -> None:
        self.effects.append("route")
        self.route_id = target_id

    def enable(self, target_id: str, generation: int) -> None:
        self.effects.append("enable")
        assert self.route_id == target_id
        self.generation = generation

    def smoke(self, target_id: str, generation: int) -> bool:
        self.effects.append("smoke")
        return self.smoke_ok

    def state(self) -> tuple[str | None, int]:
        return self.route_id, self.generation


class Source:
    def capture(self) -> CaptureInput:
        return CaptureInput(
            {"database.dump": b"synthetic old restricted data"}, META, NOW - timedelta(seconds=20)
        )


class Harness:
    def __init__(self, path: Path):
        self.now = NOW
        self.signer = Ed25519PrivateKey.generate()
        self.journal = FileJournal.provision(
            path / "journal", self.signer, "journal", clock=lambda: self.now
        )
        EncryptedCaptures.provision(path / "captures")
        self.captures = EncryptedCaptures(
            path / "captures", b"k" * 32, self.signer, "capture", clock=lambda: self.now
        )
        self.ledger = RecoveryLedger.provision(path / "ledger", self.signer)
        self.targets, self.authority = Targets(), Authority()
        (path / "targets").mkdir()
        self.coordinator = RecoveryCoordinator(
            self.captures,
            self.journal,
            self.ledger,
            self.targets,
            self.authority,
            Source(),
            path / "targets",
            clock=lambda: self.now,
            host_custody=lambda: True,
        )
        self.operator, self.approver = actor("operator"), actor("security")

    def call(self, action: str, body=None, *, resource=None, who=None, command=None):
        return self.coordinator.execute(
            action,
            who or self.operator,
            body,
            resource_id=resource,
            command_id=command or str(uuid4()),
        )

    def prepare(self):
        backup = self.call("backup_capture", {})
        target = self.call(
            "restore_create",
            {
                "backup_id": backup["id"],
                "manifest_digest": backup["manifest_digest"],
                "expected_revision": "0",
            },
        )
        target = self.call(
            "restore_validate", {"expected_revision": target["revision"]}, resource=target["id"]
        )
        binding = self.coordinator.evidence_target(self.operator, str(target["id"]))
        body = {
            key: binding[key]
            for key in (
                "target_id",
                "backup_digest",
                "head_digest",
                "restriction_barrier",
                "validation_digest",
                "serving_generation",
            )
        }
        proposal = self.call(
            "promotion_propose",
            {**body, "expected_revision": target["revision"], "binding": binding},
        )
        return target, binding, proposal

    def approve(self, proposal, binding, *, who=None, delta=300):
        return self.call(
            "promotion_approve",
            {
                "proposal_id": proposal["resource_id"],
                "exact_binding_digest": digest(canonical(binding)),
                "ceremony_id": str(uuid4()),
                "expires_at": (self.now + timedelta(seconds=delta))
                .isoformat()
                .replace("+00:00", "Z"),
            },
            who=who or self.approver,
        )

    def promote(self, proposal, binding):
        view = self.coordinator.execute(
            "promotion_read", self.operator, resource_id=str(proposal["resource_id"])
        )
        return self.call(
            "promotion_execute",
            {
                "proposal_id": proposal["resource_id"],
                "approval_id": view["approval_id"],
                "exact_binding_digest": digest(canonical(binding)),
                "expected_serving_generation": "1",
            },
        )


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


def test_exact_independent_approval_then_single_generation_admission(h):
    target, binding, proposal = h.prepare()
    gate = BoundGenerationJournal(h.coordinator, target["id"])
    assert not gate.admits(1) and not gate.admits(2)
    h.approve(proposal, binding)
    h.promote(proposal, binding)
    assert gate.admits(2) and not gate.admits(1)
    assert not BoundGenerationJournal(h.coordinator, str(uuid4())).admits(2)
    assert h.targets.effects == ["fence", "route", "enable", "smoke"]
    # Reopen signed durable host state, compare actual route and DB generation.
    h.coordinator.ledger = RecoveryLedger(h.ledger.path, h.signer)
    assert gate.admits(2)
    h.targets.generation = 1
    assert not gate.admits(2)


@pytest.mark.parametrize("boundary", CUTOVER_BOUNDARIES)
def test_crash_each_cutover_gap_never_admits_old_or_target(h, boundary):
    target, binding, proposal = h.prepare()
    h.approve(proposal, binding)

    def crash(point):
        if point == boundary:
            raise RuntimeError("synthetic process interruption")

    h.coordinator.crash_hook = crash
    with pytest.raises(RuntimeError):
        h.promote(proposal, binding)
    h.coordinator.ledger = RecoveryLedger(h.ledger.path, h.signer)
    gate = BoundGenerationJournal(h.coordinator, target["id"])
    assert not gate.admits(1) and not gate.admits(2)
    with pytest.raises(ManualError):
        h.promote(proposal, binding)


def test_same_human_second_account_cannot_approve(h):
    _target, binding, proposal = h.prepare()
    original = h.authority.current(h.operator, "promotion_propose")
    h.authority.people[h.approver.account_id] = replace(
        original, account_id=h.approver.account_id, role="security"
    )
    with pytest.raises(ManualError, match="independent_human"):
        h.approve(proposal, binding)
    assert h.targets.effects == []


@pytest.mark.parametrize("delta", [0, 301])
def test_expiry_must_be_future_and_no_more_than_five_minutes(h, delta):
    _target, binding, proposal = h.prepare()
    with pytest.raises(ManualError, match="exact_unexpired"):
        h.approve(proposal, binding, delta=delta)


def test_new_head_invalidates_approval_and_no_cutover_effect(h):
    target, binding, proposal = h.prepare()
    h.approve(proposal, binding)
    head = h.journal.head()
    h.journal.append(
        {
            "command_id": str(uuid4()),
            "expected_tip": str(head.tip),
            "kind": "checkpoint",
            "restriction": {"kind": "none"},
            "scope": {
                "session_id": None,
                "subject_id": None,
                "purpose": "recovery",
                "fields": [],
                "recipient_id": None,
            },
            "binding_digest": "1" * 64,
            "db_operation_id": None,
            "relaxation_evidence_digest": None,
        }
    )
    with pytest.raises(ManualError, match="revalidation_required"):
        h.promote(proposal, binding)
    assert h.targets.effects == []
    assert not BoundGenerationJournal(h.coordinator, target["id"]).admits(2)


def test_target_mutation_revoked_approver_and_expired_receipt_deny(h):
    target, binding, proposal = h.prepare()
    h.approve(proposal, binding)
    h.targets.rows[target["id"]] = "f" * 64
    with pytest.raises(ManualError):
        h.promote(proposal, binding)
    h.targets.rows[target["id"]] = digest(b"synthetic old restricted data")
    h.authority.revoked.add(h.approver.account_id)
    with pytest.raises(ManualError, match="approval_authority_expired"):
        h.promote(proposal, binding)
    h.authority.revoked.clear()
    h.now += timedelta(seconds=300)
    with pytest.raises(ManualError, match="approval_authority_expired"):
        h.promote(proposal, binding)
    assert h.targets.effects == []


def test_unresolved_restriction_blocks_validation(h):
    h.targets.uncertainties = ["unknown_restrictive_intent"]
    with pytest.raises(ManualError, match="validation_incomplete"):
        h.prepare()
    assert h.targets.effects == []


def test_failed_smoke_fences_both_and_requires_new_validation(h):
    target, binding, proposal = h.prepare()
    h.approve(proposal, binding)
    h.targets.smoke_ok = False
    with pytest.raises(ManualError, match="manual_smoke_failed"):
        h.promote(proposal, binding)
    assert h.targets.state() == (target["id"], 0)
    assert not BoundGenerationJournal(h.coordinator, target["id"]).admits(2)


def test_live_journal_missing_or_corrupt_denies_even_after_success(h):
    target, binding, proposal = h.prepare()
    h.approve(proposal, binding)
    h.promote(proposal, binding)
    (h.journal.path / "head.json").unlink()
    assert not BoundGenerationJournal(h.coordinator, target["id"]).admits(2)


def test_ordinary_new_checkpoint_preserves_generation_but_exposes_fresh_barrier(h):
    target, binding, proposal = h.prepare()
    h.approve(proposal, binding)
    h.promote(proposal, binding)
    head = h.journal.head()
    h.journal.append(
        {
            "command_id": str(uuid4()),
            "expected_tip": str(head.tip),
            "kind": "checkpoint",
            "restriction": {"kind": "none"},
            "scope": {
                "session_id": None,
                "subject_id": None,
                "purpose": "recovery",
                "fields": [],
                "recipient_id": None,
            },
            "binding_digest": "1" * 64,
            "db_operation_id": None,
            "relaxation_evidence_digest": None,
        }
    )
    gate = BoundGenerationJournal(h.coordinator, target["id"])
    assert gate.admits(2)
    assert head_binding(gate.head()) == head_binding(h.journal.head())


def test_inventory_expiry_and_copy_accounting_preserve_signed_original_manifest(h):
    backup = h.call("backup_capture", {})
    identity = backup["id"]
    manifest_before = (h.captures.path / identity / "manifest.json").read_bytes()
    h.now += timedelta(days=7)
    assert h.captures.inventory()[0]["state"] == "expired"
    with pytest.raises(ManualError, match="expiry_or_hold_denied"):
        h.captures.expire(identity, retained_by_hold=True)
    result = h.captures.expire(identity, retained_by_hold=False)
    assert result["physical_erasure_proven"] is False
    assert result["known_encrypted_objects_unlinked"] is True
    assert (h.captures.path / identity / "manifest.json").read_bytes() == manifest_before
    assert len(list((h.captures.path / identity).iterdir())) == 1
    assert h.captures.expire(identity, retained_by_hold=False) == result
    with pytest.raises(ManualError, match="expired"):
        h.captures.inspect(identity)


@pytest.mark.parametrize("boundary", CUTOVER_BOUNDARIES)
def test_process_death_at_each_gap_reopens_signed_ledger_restricted(h, boundary):
    # A real process exits without exception unwinding or cleanup. Target/router
    # side effects are explicit doubles; on restart assume their worst possible
    # state (target already enabled), then require the host gate still denies.
    import multiprocessing
    import os

    target, binding, proposal = h.prepare()
    h.approve(proposal, binding)

    def child():
        def crash(point):
            if point == boundary:
                os._exit(79)

        h.coordinator.crash_hook = crash
        h.promote(proposal, binding)
        os._exit(0)

    process = multiprocessing.get_context("fork").Process(target=child)
    process.start()
    process.join(10)
    try:
        assert process.exitcode == 79
        h.coordinator.ledger = RecoveryLedger(h.ledger.path, h.signer)
        h.targets.route_id, h.targets.generation = target["id"], 2
        gate = BoundGenerationJournal(h.coordinator, target["id"])
        assert not gate.admits(1) and not gate.admits(2)
        with pytest.raises(ManualError):
            h.promote(proposal, binding)
    finally:
        if process.is_alive():
            process.kill()
            process.join(5)


def test_duplicate_command_rechecks_authority_and_preserves_capture_time(h):
    command = str(uuid4())
    original = h.call("backup_capture", {}, command=command)
    h.now += timedelta(seconds=15)
    assert h.call("backup_capture", {}, command=command) == original
    h.authority.revoked.add(h.operator.account_id)
    with pytest.raises(ManualError, match="current_authority_denied"):
        h.call("backup_capture", {}, command=command)


def test_gate_can_be_read_during_internal_smoke_without_reentrant_file_deadlock(h):
    target, binding, proposal = h.prepare()
    h.approve(proposal, binding)
    gate = BoundGenerationJournal(h.coordinator, target["id"])
    original_smoke = h.targets.smoke

    def smoke(target_id, generation):
        assert not gate.admits(generation)
        return original_smoke(target_id, generation)

    h.targets.smoke = smoke
    h.promote(proposal, binding)
    assert gate.admits(2)


def test_suspect_host_cannot_replace_missing_recency_with_signed_old_head(h):
    target, binding, proposal = h.prepare()
    h.approve(proposal, binding)
    h.coordinator.host_custody = lambda: False
    with pytest.raises(ManualError, match="continuing_host_custody"):
        h.promote(proposal, binding)
    with pytest.raises(ManualError, match="continuing_host_custody"):
        h.coordinator.evidence_target(h.operator, target["id"])
    assert not BoundGenerationJournal(h.coordinator, target["id"]).admits(2)
    assert h.targets.effects == []


def test_restriction_arriving_during_maintenance_invalidates_exact_approval(h):
    target, binding, proposal = h.prepare()
    h.approve(proposal, binding)

    def restrict(point):
        if point == "maintenance":
            h.journal.append(
                {
                    "command_id": str(uuid4()),
                    "expected_tip": "0",
                    "kind": "restrict_intent",
                    "binding_digest": "1" * 64,
                    "scope": {
                        "session_id": None,
                        "subject_id": None,
                        "purpose": "security",
                        "fields": [],
                        "recipient_id": None,
                    },
                    "restriction": {
                        "kind": "identity_revoke",
                        "principal_id": str(uuid4()),
                        "identity_revision": "2",
                        "disabled": True,
                    },
                    "db_operation_id": None,
                    "relaxation_evidence_digest": None,
                }
            )

    h.coordinator.crash_hook = restrict
    with pytest.raises(ManualError, match="approval_invalidated"):
        h.promote(proposal, binding)
    assert not BoundGenerationJournal(h.coordinator, target["id"]).admits(1)
    assert not BoundGenerationJournal(h.coordinator, target["id"]).admits(2)
    assert h.targets.effects == []


def test_serving_target_cannot_be_mutated_by_revalidation(h):
    target, binding, proposal = h.prepare()
    h.approve(proposal, binding)
    h.promote(proposal, binding)
    view = h.coordinator.execute("restore_read", h.operator, resource_id=target["id"])
    with pytest.raises(ManualError, match="serving_target_cannot_revalidate"):
        h.call("restore_validate", {"expected_revision": view["revision"]}, resource=target["id"])
    assert BoundGenerationJournal(h.coordinator, target["id"]).admits(2)


def serving_fence(h, target_id):
    head = h.journal.head()
    return h.journal.append(
        {
            "command_id": str(uuid4()),
            "expected_tip": str(head.tip),
            "kind": "serving_fence",
            "binding_digest": "1" * 64,
            "scope": {
                "session_id": None,
                "subject_id": None,
                "purpose": "security",
                "fields": [],
                "recipient_id": None,
            },
            "restriction": {
                "kind": "serving_fence",
                "generation": "2",
                "target_id": target_id,
                "promotion_id": str(uuid4()),
            },
            "db_operation_id": None,
            "relaxation_evidence_digest": None,
        }
    )


def test_new_raw_serving_fence_revokes_completed_promotion_at_every_bound_gate(h):
    target, binding, proposal = h.prepare()
    h.approve(proposal, binding)
    h.promote(proposal, binding)
    # Edge, data-final-authorization and dispatch each compose the same fresh
    # target-bound host port. A valid raw restriction must dominate its ledger.
    gates = [BoundGenerationJournal(h.coordinator, target["id"]) for _ in range(3)]
    assert all(gate.admits(2) for gate in gates)
    assert serving_fence(h, target["id"]).serving_generation == 0
    for gate in gates:
        assert gate.head().serving_generation == 0
        assert not gate.admits(2)
        with pytest.raises(ManualError, match="generation_fenced"):
            gate.require(2)
    # Reopening the signed host ledger cannot revive its stale promotion.
    h.coordinator.ledger = RecoveryLedger(h.ledger.path, h.signer)
    assert not gates[0].admits(2)


def test_prior_serving_fence_can_be_reconciled_by_exact_new_promotion(h):
    serving_fence(h, str(uuid4()))
    target, binding, proposal = h.prepare()
    h.approve(proposal, binding)
    h.promote(proposal, binding)
    assert h.journal.head().serving_generation == 0
    assert BoundGenerationJournal(h.coordinator, target["id"]).admits(2)


def test_final_valid_generation_serves_then_new_generation_allocation_exhausts(h, tmp_path):
    from care_link_recovery_control.ledger import MAX_GENERATION

    h.coordinator.ledger = RecoveryLedger.provision(
        tmp_path / "last-generation-ledger", h.signer, initial_serving_generation=MAX_GENERATION - 1
    )
    target, binding, proposal = h.prepare()
    assert binding["serving_generation"] == str(MAX_GENERATION)
    h.approve(proposal, binding)
    view = h.coordinator.execute(
        "promotion_read", h.operator, resource_id=str(proposal["resource_id"])
    )
    h.call(
        "promotion_execute",
        {
            "proposal_id": proposal["resource_id"],
            "approval_id": view["approval_id"],
            "exact_binding_digest": digest(canonical(binding)),
            "expected_serving_generation": str(MAX_GENERATION - 1),
        },
    )
    gate = BoundGenerationJournal(h.coordinator, target["id"])
    assert gate.admits(MAX_GENERATION)
    with pytest.raises(ManualError, match="generation_exhausted"):
        h.prepare()
    assert gate.admits(MAX_GENERATION)
    with h.coordinator.ledger.exclusive():
        assert h.coordinator.ledger.load()["next_generation"] is None


def test_signed_overflow_generation_ledger_is_rejected(h):
    from care_link_recovery_control.ledger import MAX_GENERATION

    with h.ledger.exclusive():
        state = h.ledger.load()
        state["next_generation"] = MAX_GENERATION + 1
        h.ledger.save(state)
    with pytest.raises(ManualError, match="ledger_invalid"):
        h.call("backup_capture", {})
