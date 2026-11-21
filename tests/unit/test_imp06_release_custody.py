"""AI release and evaluator readiness stay bound to current durable authority."""

import hashlib
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from care_link_domain import ManualError
from care_link_inference import THREATS, proposal_schema, provider_proposal_schema
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tools.imp06_runtime.release_custody import (
    ReleaseCustody,
    ReleaseDenied,
    ReleaseTrust,
    ReviewAuthority,
)
from tools.imp06_runtime.release_custody_records import (
    EVALUATORS,
    EvaluationEvidence,
    EvaluatorAck,
    EvaluatorBoot,
    HumanApproval,
    ModelIdentity,
    ReleaseArtifact,
    ReleaseObservation,
    digest,
)


def timestamp(value):
    return value.isoformat().replace("+00:00", "Z")


class Qualification:
    def __init__(self, tmp_path):
        self.artifact_key = Ed25519PrivateKey.generate()
        self.evaluator_keys = {instance: Ed25519PrivateKey.generate() for instance in EVALUATORS}
        self.review_key = Ed25519PrivateKey.generate()
        self.trust = ReleaseTrust(
            "qual-release-test",
            "qualification",
            {"test-artifact": self.artifact_key.public_key()},
            {instance: key.public_key() for instance, key in self.evaluator_keys.items()},
        )
        self.now = datetime(2026, 11, 20, 12, tzinfo=UTC)
        self.path = tmp_path / "ledger.db"
        self.custody = self.reopen()
        self.custody.initialize()
        self.artifact = self.candidate(self.trust)
        self.activation_id = str(uuid4())
        self.boots = {}

    def reopen(self):
        return ReleaseCustody(
            self.path, trust=self.trust, owner_uid=os.geteuid(), clock=lambda: self.now
        )

    def candidate(self, trust):
        instruction = "Prepare a draft from the observed sources."
        source = {
            "kind": "template",
            "id": str(uuid4()),
            "revision": "1",
            "digest": hashlib.sha256(instruction.encode()).hexdigest(),
            "observed_at": timestamp(self.now),
            "verification": "verified",
        }
        item = {
            "source": source,
            "label": "approved_instruction",
            "text": instruction,
            "critical": True,
        }
        evidence = EvaluationEvidence(
            canonical_schema_digest=digest(proposal_schema()),
            wire_schema_digest=digest(provider_proposal_schema()),
            prompt_digest=digest([item]),
            english_digest=digest("synthetic-en"),
            french_digest=digest("synthetic-fr"),
            grounding_digest=digest("synthetic-grounding"),
            adversarial_digest=digest("synthetic-adversarial"),
            latency_digest=digest("synthetic-latency"),
            threats=tuple(sorted(THREATS)),
        )
        observation = ReleaseObservation(
            model=ModelIdentity(
                artifact_digest=digest("synthetic-weights"),
                origin="test-artifact-origin",
                quantization="test-quantization",
                license="test-license",
                server_version="test-lm-studio",
                engine_version="test-engine",
                sdk_render_mode="test-render-mode",
                tokenizer_digest=digest("synthetic-tokenizer"),
                template_digest=digest("synthetic-template"),
            ),
            code_digest=digest("synthetic-code"),
            image_digest=digest("synthetic-image"),
            catalog_digest=digest("synthetic-catalog"),
            evaluation_digest=digest(evidence.model_dump(mode="json")),
        )
        return ReleaseArtifact(
            purpose=trust.purpose,
            target=trust.target,
            change_class="C2",
            proposer="test-proposer",
            signer="test-artifact",
            evidence=evidence,
            observation=observation,
            instruction_source=source,
            instruction=instruction,
        )

    def stage(self, *, signature=None, approval=None, approval_signature=None):
        return self.custody.stage(
            self.artifact,
            signature or self.artifact_key.sign(self.artifact.signing_bytes()),
            expected_epoch=0,
            activation_id=self.activation_id,
            approval=approval,
            approval_signature=approval_signature,
        )

    def boot(self, instance, *, predecessor=None):
        boot = EvaluatorBoot(
            target=self.trust.target,
            purpose=self.trust.purpose,
            instance=instance,
            boot_id=str(uuid4()),
            previous_boot_id=predecessor,
        )
        self.custody.register_boot(boot, self.evaluator_keys[instance].sign(boot.signing_bytes()))
        self.boots[instance] = boot.boot_id
        return boot

    def acknowledgment(self, instance, **changes):
        values = {
            "target": self.trust.target,
            "purpose": self.trust.purpose,
            "instance": instance,
            "boot_id": self.boots[instance],
            "epoch": 1,
            "activation_id": self.activation_id,
            "bundle_digest": self.artifact.bundle_digest,
            "status": "ready",
            "issued_at": timestamp(self.now),
            "expires_at": timestamp(self.now + timedelta(minutes=1)),
            **changes,
        }
        return EvaluatorAck(**values)

    def acknowledge(self, ack, *, key=None):
        key = key or self.evaluator_keys[ack.instance]
        self.custody.acknowledge(ack, key.sign(ack.signing_bytes()))

    def ready(self):
        self.custody.prepare(self.artifact.observation)
        for instance in EVALUATORS:
            self.boot(instance)
            self.acknowledge(self.acknowledgment(instance))

    def qualification_bindings(self, *, instance="core", custody=None, observation=None):
        return (custody or self.custody).qualification_bindings(
            observation or self.artifact.observation,
            instance=instance,
            boot_id=self.boots[instance],
        )


@pytest.fixture
def lab(tmp_path):
    return Qualification(tmp_path)


def test_release_requires_each_current_ack_and_survives_restart(lab):
    assert lab.stage() == 1
    lab.boot("core")
    binding = lab.qualification_bindings()
    assert not binding.current()
    with pytest.raises(ManualError):
        binding.release("worker_summary")
    for instance in EVALUATORS - {"core"}:
        lab.boot(instance)
        lab.acknowledge(lab.acknowledgment(instance))
    with pytest.raises(ReleaseDenied, match="acknowledgments"):
        lab.custody.activate(expected_epoch=1)
    lab.acknowledge(lab.acknowledgment("core"))
    lab.custody.activate(expected_epoch=1)
    assert binding.current()
    reopened = lab.qualification_bindings(custody=lab.reopen())
    assert reopened.current()
    assert reopened.admitted_for_knowledge(
        "worker_summary", lab.artifact.observation.catalog_digest
    )
    assert not reopened.admitted_for_knowledge("worker_summary", digest("different catalog"))
    assert not reopened.admitted("worker_wording")
    assert reopened.manifest.release_digest == lab.artifact.bundle_digest


def test_restrictive_epoch_survives_reopen_and_invalidates_old_bindings(lab):
    lab.stage()
    lab.ready()
    lab.custody.activate(expected_epoch=1)
    binding = lab.qualification_bindings()
    assert binding.current()
    assert lab.reopen().disable(expected_epoch=1) == 2
    assert not binding.current()
    with pytest.raises(ReleaseDenied, match="stale release epoch"):
        lab.reopen().activate(expected_epoch=1)
    with pytest.raises(ReleaseDenied):
        lab.reopen().acknowledge(lab.acknowledgment("core"), b"")
    with pytest.raises(ReleaseDenied):
        lab.qualification_bindings(custody=lab.reopen())


def test_restarted_evaluator_invalidates_exact_prior_ack(lab):
    lab.stage()
    lab.ready()
    lab.custody.activate(expected_epoch=1)
    core = lab.qualification_bindings()
    old_binding = lab.qualification_bindings(instance="data")
    old_ack = lab.acknowledgment("data")
    old_boot = lab.boots["data"]
    new_boot = lab.boot("data", predecessor=old_boot)
    assert not core.current() and not old_binding.current()
    with pytest.raises(ReleaseDenied, match="stale evaluator acknowledgment"):
        lab.acknowledge(old_ack)
    prior_boot = new_boot.model_copy(
        update={"boot_id": old_boot, "previous_boot_id": new_boot.boot_id}
    )
    with pytest.raises(ReleaseDenied):
        lab.custody.register_boot(
            prior_boot, lab.evaluator_keys["data"].sign(prior_boot.signing_bytes())
        )
    lab.acknowledge(lab.acknowledgment("data"))
    assert core.current()
    assert not old_binding.current()
    assert lab.qualification_bindings(instance="data").current()


@pytest.mark.parametrize(
    "changes",
    [
        {"epoch": 2},
        {"bundle_digest": "f" * 64},
        {"activation_id": "7d3140ba-c22a-41ae-a830-bf2a3a1b3760"},
        {"target": "qual-elsewhere"},
        {"purpose": "serving"},
        {"expires_at": "2026-11-20T13:00:00Z"},
    ],
)
def test_wrong_ack_scope_and_duration_are_rejected(lab, changes):
    lab.stage()
    lab.boot("core")
    ack = lab.acknowledgment("core", **changes)
    with pytest.raises(ReleaseDenied):
        lab.acknowledge(ack)


def test_wrong_key_and_ack_replay_cannot_undo_rejection(lab):
    lab.stage()
    lab.ready()
    lab.custody.activate(expected_epoch=1)
    binding = lab.qualification_bindings()
    original = lab.acknowledgment("core")
    with pytest.raises(ReleaseDenied):
        lab.acknowledge(original, key=lab.evaluator_keys["data"])
    lab.now += timedelta(seconds=1)
    lab.acknowledge(lab.acknowledgment("core", status="rejected"))
    assert not binding.current()
    with pytest.raises(ReleaseDenied, match="stale evaluator acknowledgment"):
        lab.acknowledge(original)
    lab.now += timedelta(minutes=1)
    assert not binding.current()


def test_bad_signer_and_changed_runtime_pins_fail_closed(lab):
    with pytest.raises(ReleaseDenied):
        lab.stage(signature=lab.review_key.sign(lab.artifact.signing_bytes()))
    lab.stage()
    lab.ready()
    lab.custody.activate(expected_epoch=1)
    original = lab.artifact.observation
    changes = (
        {"catalog_digest": digest("changed catalog")},
        {"image_digest": digest("changed image")},
        {"code_digest": digest("changed code")},
        {"evaluation_digest": digest("changed evaluation")},
        {"model": original.model.model_copy(update={"engine_version": "different"})},
        {"model": original.model.model_copy(update={"sdk_render_mode": "different"})},
    )
    for update in changes:
        observed = original.model_copy(update=update)
        with pytest.raises(ReleaseDenied, match="local evaluator pins"):
            lab.qualification_bindings(observation=observed)


def test_signed_candidate_with_stale_wire_schema_cannot_stage(lab):
    evidence = lab.artifact.evidence.model_copy(update={"wire_schema_digest": digest("stale")})
    observation = lab.artifact.observation.model_copy(
        update={"evaluation_digest": digest(evidence.model_dump(mode="json"))}
    )
    lab.artifact = lab.artifact.model_copy(
        update={"evidence": evidence, "observation": observation}
    )
    with pytest.raises(ReleaseDenied):
        lab.stage()


def test_fixture_authority_cannot_activate_serving_even_with_fixture_keys(lab):
    with pytest.raises(ValueError, match="trust configuration"):
        ReleaseTrust(
            "qual-release-test", "serving", lab.trust.artifact_keys, lab.trust.evaluator_keys
        )
    lab.stage()
    lab.ready()
    lab.custody.activate(expected_epoch=1)
    with pytest.raises(ReleaseDenied, match="serving release trust"):
        lab.custody.serving_bindings(
            lab.artifact.observation, instance="core", boot_id=lab.boots["core"]
        )


def test_serving_requires_independent_signed_exact_receipt_and_current_expiry(lab, tmp_path):
    proposer_key = Ed25519PrivateKey.generate()
    lab.trust = ReleaseTrust(
        "reviewed-demo-fixture",
        "serving",
        lab.trust.artifact_keys,
        lab.trust.evaluator_keys,
        {
            "test-proposer": ReviewAuthority(proposer_key.public_key(), "C2"),
            "test-independent": ReviewAuthority(lab.review_key.public_key(), "C2"),
        },
    )
    lab.path = tmp_path / "reviewed-fixture.db"
    lab.custody = lab.reopen()
    lab.custody.initialize()
    lab.artifact = lab.candidate(lab.trust)
    with pytest.raises(ReleaseDenied):
        lab.stage()
    receipt = HumanApproval(
        target=lab.trust.target,
        reviewer="test-independent",
        authority="C2",
        activation_id=lab.activation_id,
        bundle_digest=lab.artifact.bundle_digest,
        epoch=1,
        issued_at=timestamp(lab.now),
        expires_at=timestamp(lab.now + timedelta(seconds=2)),
        evidence_digest=digest("unit-test receipt only"),
    )
    for invalid in (
        receipt.model_copy(update={"bundle_digest": digest("different release")}),
        receipt.model_copy(update={"epoch": 2}),
        receipt.model_copy(update={"activation_id": str(uuid4())}),
    ):
        with pytest.raises(ReleaseDenied, match="independent release approval"):
            lab.stage(
                approval=invalid, approval_signature=lab.review_key.sign(invalid.signing_bytes())
            )
    self_approval = receipt.model_copy(update={"reviewer": "test-proposer"})
    with pytest.raises(ReleaseDenied, match="independent release approval"):
        lab.stage(
            approval=self_approval,
            approval_signature=proposer_key.sign(self_approval.signing_bytes()),
        )
    lab.stage(approval=receipt, approval_signature=lab.review_key.sign(receipt.signing_bytes()))
    lab.ready()
    lab.custody.activate(expected_epoch=1)
    binding = lab.custody.serving_bindings(
        lab.artifact.observation, instance="core", boot_id=lab.boots["core"]
    )
    assert binding.current()
    lab.now += timedelta(seconds=2)
    assert not binding.current()


def test_mounted_ledger_replacement_and_unsafe_permissions_disable_existing_binding(lab):
    lab.stage()
    lab.ready()
    lab.custody.activate(expected_epoch=1)
    binding = lab.qualification_bindings()
    assert binding.current()
    lab.path.chmod(0o660)
    assert not binding.current()
    lab.path.chmod(0o640)
    assert binding.current()
    lab.path.rename(lab.path.with_suffix(".prior"))
    lab.path.symlink_to(lab.path.with_suffix(".prior"))
    assert not binding.current()
