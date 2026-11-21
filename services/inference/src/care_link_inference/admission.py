"""Fail-closed release evidence for the one accepted local model.

Release custody verifies signed evidence before constructing this manifest. Model
listing, file names and schema support alone never admit a function.
"""

import re
from dataclasses import dataclass

MODEL = "qwen/qwen3.8-27b"
FUNCTIONS = frozenset(
    {
        "client_navigation",
        "carer_context",
        "worker_summary",
        "worker_wording",
        "referral_preparation",
        "handoff_tracking",
        "receiver_completeness",
        "plan_draft",
        "follow_up_draft",
        "supervisor_queue",
        "incident_draft",
        "evidence_draft",
        "training_debrief",
    }
)
THREATS = frozenset(
    {
        "LLM01:2025",
        "LLM02:2025",
        "LLM06:2025",
        "LLM03:2025",
        "LLM10:2025",
        "LLM09:2025",
        "LLM05:2025",
        "AML.T0051",
        "AML.T0054",
    }
)
DIGEST = re.compile(r"^[0-9a-f]{64}$")
WORKER_SUMMARY_INPUT_LIMIT = 2048


class InferenceDenied(Exception):
    """Safe failure code, containing no prompt or model output."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class FunctionEvidence:
    function: str
    prompt_digest: str
    schema_digest: str
    english_digest: str
    french_digest: str
    grounding_digest: str
    adversarial_digest: str
    latency_digest: str
    threats: frozenset[str]
    input_token_limit: int = WORKER_SUMMARY_INPUT_LIMIT

    def valid(self) -> bool:
        return (
            self.function in FUNCTIONS
            and type(self.input_token_limit) is int
            and 1 <= self.input_token_limit <= WORKER_SUMMARY_INPUT_LIMIT
            and THREATS <= self.threats
            and all(
                DIGEST.fullmatch(value) is not None
                for value in (
                    self.prompt_digest,
                    self.schema_digest,
                    self.english_digest,
                    self.french_digest,
                    self.grounding_digest,
                    self.adversarial_digest,
                    self.latency_digest,
                )
            )
        )


@dataclass(frozen=True)
class ModelManifest:
    model_identifier: str
    loaded_model_id: str
    artifact_digest: str
    origin: str
    quantization: str
    license: str
    server_version: str
    engine_version: str
    tokenizer_digest: str
    template_digest: str
    model_window: int
    schema_digest: str
    release_digest: str
    functions: tuple[FunctionEvidence, ...]

    def admit(self, function: str, *, release_verified: bool) -> FunctionEvidence:
        if (
            not release_verified
            or self.model_identifier != MODEL
            or self.loaded_model_id != MODEL
            or not all(
                (
                    self.origin,
                    self.quantization,
                    self.license,
                    self.server_version,
                    self.engine_version,
                )
            )
            or self.model_window < 1
            or not all(
                DIGEST.fullmatch(value)
                for value in (
                    self.artifact_digest,
                    self.tokenizer_digest,
                    self.template_digest,
                    self.schema_digest,
                    self.release_digest,
                )
            )
        ):
            raise InferenceDenied("model_evidence_unverified")
        matches = [item for item in self.functions if item.function == function]
        if len(matches) != 1 or not matches[0].valid():
            raise InferenceDenied("function_not_admitted")
        if matches[0].schema_digest != self.schema_digest:
            raise InferenceDenied("schema_identity_mismatch")
        return matches[0]
