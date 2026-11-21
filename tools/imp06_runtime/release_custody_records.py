"""Closed signed records for the evaluated IMP-06 worker summary release."""

import hashlib
from typing import Annotated, Literal

from care_link_contracts import validate_contract
from care_link_core.assistance_broker import ReleasedFunction
from care_link_inference import (
    MODEL,
    THREATS,
    FunctionEvidence,
    ModelManifest,
    proposal_schema,
    provider_proposal_schema,
)
from care_link_policy_input.opa import canonical
from pydantic import BaseModel, ConfigDict, Field

type Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
type Identity = Annotated[str, Field(min_length=1, max_length=128)]
type Identifier = Annotated[
    str, Field(pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")
]
type Purpose = Literal["serving", "qualification"]
type ChangeClass = Literal["C2", "C3"]
type Epoch = Annotated[int, Field(ge=1, le=9223372036854775807)]

EVALUATORS = frozenset({"core", "data", "runtime", "inference", "host-inference-bridge"})


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


class ReleaseRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    def signing_bytes(self) -> bytes:
        return canonical(self.model_dump(mode="json"))


class ModelIdentity(ReleaseRecord):
    model_identifier: Literal["qwen/qwen3.8-27b"] = MODEL
    loaded_model_id: Literal["qwen/qwen3.8-27b"] = MODEL
    artifact_digest: Digest
    origin: Identity
    quantization: Identity
    license: Identity
    server_version: Identity
    engine_version: Identity
    sdk_render_mode: Identity
    tokenizer_digest: Digest
    template_digest: Digest
    model_window: Literal[8192] = 8192


class ReleaseObservation(ReleaseRecord):
    """Pins measured or supplied by trusted composition, never by a request."""

    model: ModelIdentity
    code_digest: Digest
    image_digest: Digest
    catalog_digest: Digest
    evaluation_digest: Digest


class EvaluationEvidence(ReleaseRecord):
    canonical_schema_digest: Digest
    wire_schema_digest: Digest
    prompt_digest: Digest
    english_digest: Digest
    french_digest: Digest
    grounding_digest: Digest
    adversarial_digest: Digest
    latency_digest: Digest
    threats: Annotated[tuple[str, ...], Field(min_length=1, max_length=32)]
    input_token_limit: Annotated[int, Field(ge=1, le=2048)] = 2048

    def function_evidence(self) -> FunctionEvidence:
        return FunctionEvidence(
            "worker_summary",
            self.prompt_digest,
            self.canonical_schema_digest,
            self.english_digest,
            self.french_digest,
            self.grounding_digest,
            self.adversarial_digest,
            self.latency_digest,
            frozenset(self.threats),
            input_token_limit=self.input_token_limit,
        )


class ReleaseArtifact(ReleaseRecord):
    """Immutable signed bytes. Mode and target are part of signature scope."""

    kind: Literal["care.link.ai-release.v1"] = "care.link.ai-release.v1"
    purpose: Purpose
    target: Identity
    population: Literal["synthetic"] = "synthetic"
    change_class: ChangeClass
    proposer: Identity
    signer: Identity
    evidence: EvaluationEvidence
    observation: ReleaseObservation
    instruction_source: dict[str, object]
    instruction: Annotated[str, Field(min_length=1, max_length=12000)]

    @property
    def bundle_digest(self) -> str:
        return hashlib.sha256(self.signing_bytes()).hexdigest()

    def validated_function(self) -> tuple[ModelManifest, ReleasedFunction]:
        item = {
            "source": self.instruction_source,
            "label": "approved_instruction",
            "text": self.instruction,
            "critical": True,
        }
        validate_contract("ContextItem", item)
        if (
            self.instruction_source.get("kind") != "template"
            or self.instruction_source.get("verification") != "verified"
            or self.instruction_source.get("digest")
            != hashlib.sha256(self.instruction.encode()).hexdigest()
            or self.evidence.prompt_digest != digest([item])
            or self.evidence.canonical_schema_digest != digest(proposal_schema())
            or self.evidence.wire_schema_digest != digest(provider_proposal_schema())
            or self.observation.evaluation_digest != digest(self.evidence.model_dump(mode="json"))
            or frozenset(self.evidence.threats) != THREATS
            or len(self.evidence.threats) != len(THREATS)
        ):
            raise ValueError("evaluated release pins do not match")
        model = self.observation.model
        manifest = ModelManifest(
            model_identifier=model.model_identifier,
            loaded_model_id=model.loaded_model_id,
            artifact_digest=model.artifact_digest,
            origin=model.origin,
            quantization=model.quantization,
            license=model.license,
            server_version=model.server_version,
            engine_version=model.engine_version,
            tokenizer_digest=model.tokenizer_digest,
            template_digest=model.template_digest,
            model_window=model.model_window,
            schema_digest=self.evidence.canonical_schema_digest,
            release_digest=self.bundle_digest,
            functions=(self.evidence.function_evidence(),),
        )
        return manifest, ReleasedFunction(
            "worker_summary",
            model.artifact_digest,
            self.evidence.prompt_digest,
            dict(self.instruction_source),
            self.instruction,
        )


class HumanApproval(ReleaseRecord):
    kind: Literal["care.link.ai-release-approval.v1"] = "care.link.ai-release-approval.v1"
    target: Identity
    reviewer: Identity
    authority: ChangeClass
    activation_id: Identifier
    bundle_digest: Digest
    epoch: Epoch
    decision: Literal["approved"] = "approved"
    issued_at: Identity
    expires_at: Identity
    evidence_digest: Digest


class EvaluatorBoot(ReleaseRecord):
    kind: Literal["care.link.ai-evaluator-boot.v1"] = "care.link.ai-evaluator-boot.v1"
    purpose: Purpose
    target: Identity
    instance: Identity
    boot_id: Identifier
    previous_boot_id: Identifier | None


class EvaluatorAck(ReleaseRecord):
    kind: Literal["care.link.ai-evaluator-ack.v1"] = "care.link.ai-evaluator-ack.v1"
    purpose: Purpose
    target: Identity
    instance: Identity
    boot_id: Identifier
    activation_id: Identifier
    bundle_digest: Digest
    epoch: Epoch
    status: Literal["ready", "rejected"]
    issued_at: Identity
    expires_at: Identity
