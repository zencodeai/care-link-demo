"""Authenticated broker-to-bridge inference; runtime cannot supply context.

The ledger is an out-of-process data-gateway port. Unknown compute stays owned
in durable storage across process restarts; timeout never means stopped.
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import uuid4

from care_link_contracts import validate_contract

from .admission import InferenceDenied, ModelManifest
from .context import TokenCounter, build_context, canonical
from .parser import MAX_RESPONSE_BYTES
from .selection import selection_schema, selection_to_proposal


class Bridge(Protocol):
    def complete(self, payload: dict[str, object], deadline: datetime) -> bytes: ...


class JobLedger(Protocol):
    def reserve(self, record: dict[str, object]) -> str | None: ...
    def mark_unknown(self, job_id: str) -> None: ...
    def complete(self, job_id: str, result_digest: str, *, deliverable: bool) -> bool: ...


@dataclass(frozen=True)
class BrokerRequest:
    task_id: str
    step_id: str
    fence: str
    revision: str
    function: str
    items: tuple[dict[str, object], ...]
    allowed_tools: frozenset[str]
    deadline: datetime
    bridge_generation: str
    job_id: str = ""
    output_tokens: int = 1024
    context_tokens: int = 8192


@dataclass(frozen=True)
class GatewayResult:
    job_id: str
    state: str
    proposal: dict[str, object] | None
    safe_reason: str | None
    input_tokens: int = 0
    output_tokens: int = 0


class InferenceGateway:
    def __init__(
        self,
        manifest: ModelManifest,
        *,
        release_verified: Callable[[], bool],
        counter: TokenCounter,
        bridge: Bridge,
        ledger: JobLedger,
        broker_current: Callable[[BrokerRequest], bool],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.manifest, self.release_verified = manifest, release_verified
        self.counter, self.bridge, self.ledger = counter, bridge, ledger
        self.broker_current, self.clock = broker_current, clock

    def execute(self, authenticated_caller: str, request: BrokerRequest) -> GatewayResult:
        if authenticated_caller != "broker":
            raise InferenceDenied("broker_workload_required")
        evidence = self.manifest.admit(request.function, release_verified=self.release_verified())
        remaining = (request.deadline - self.clock()).total_seconds()
        if not 0 < remaining <= 30 or not self.broker_current(request):
            raise InferenceDenied("stale_inference_request")
        required_assertions = sum(
            item.get("label") in {"approved_fact", "untrusted_report", "untrusted_observation"}
            and isinstance(item.get("source"), dict)
            and cast(dict[str, object], item["source"]).get("kind") == "assertion"
            for item in request.items
        )
        if required_assertions > 12:
            # Every patient assertion must survive selection. Reduce scope before
            # tokenization, allocation or model work rather than silently omit.
            raise InferenceDenied("reduce_scope_required")
        schema_digest = hashlib.sha256(canonical(proposal_schema()).encode()).hexdigest()
        instructions = [
            item for item in request.items if item.get("label") == "approved_instruction"
        ]
        prompt_digest = hashlib.sha256(canonical(instructions).encode()).hexdigest()
        if evidence.schema_digest != schema_digest or evidence.prompt_digest != prompt_digest:
            raise InferenceDenied("release_payload_identity_mismatch")
        context = build_context(
            request.items,
            self.manifest,
            self.counter,
            output_reserve=request.output_tokens,
            context_limit=request.context_tokens,
        )
        if context.input_tokens > evidence.input_token_limit:
            raise InferenceDenied("reduce_scope_required")
        payload: dict[str, object] = {
            "model": self.manifest.loaded_model_id,
            "messages": list(context.messages),
            "temperature": 0,
            "stream": False,
            "max_tokens": context.output_reserve,
            "reasoning_effort": "none",
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "care_link_proposal",
                    "strict": True,
                    "schema": provider_proposal_schema(request.function),
                },
            },
        }
        job_id = request.job_id or str(uuid4())
        slot_id = self.ledger.reserve(
            {
                "id": job_id,
                "task_id": request.task_id,
                "step_id": request.step_id,
                "fence": request.fence,
                "revision": request.revision,
                "model_digest": self.manifest.artifact_digest,
                "prompt_digest": evidence.prompt_digest,
                "request_digest": hashlib.sha256(canonical(payload).encode()).hexdigest(),
                "deadline": request.deadline,
                "bridge_generation": request.bridge_generation,
            }
        )
        if slot_id is None:
            return GatewayResult(job_id, "rejected", None, "compute_capacity_unavailable")
        try:
            raw = self.bridge.complete(payload, request.deadline)
        except (TimeoutError, OSError):
            self.ledger.mark_unknown(job_id)
            return GatewayResult(job_id, "compute_unknown", None, "provider_stop_unverified")
        # Complete transport return is observed completion even when output is bad;
        # malformed output can free its slot, but never produce a partial effect.
        result_digest = hashlib.sha256(raw).hexdigest()
        try:
            proposal, output_tokens = self._response(
                raw, request, context.admitted_sources, context.input_tokens
            )
        except InferenceDenied as error:
            self.ledger.complete(job_id, result_digest, deliverable=False)
            return GatewayResult(job_id, "rejected", None, error.reason, context.input_tokens)
        fresh = (
            self.clock() < request.deadline
            and self.release_verified()
            and self.broker_current(request)
        )
        deliverable = self.ledger.complete(job_id, result_digest, deliverable=fresh)
        if not fresh or not deliverable:
            return GatewayResult(job_id, "cancelled", None, "late_or_fenced_output")
        return GatewayResult(
            job_id, "completed", proposal, None, context.input_tokens, output_tokens
        )

    def _response(
        self,
        raw: bytes,
        request: BrokerRequest,
        sources: tuple[dict[str, object], ...],
        input_tokens: int,
    ) -> tuple[dict[str, object], int]:
        if len(raw) > MAX_RESPONSE_BYTES:
            raise InferenceDenied("response_too_large")
        envelope = provider_envelope(raw)
        if envelope.get("model") != self.manifest.loaded_model_id:
            raise InferenceDenied("loaded_identity_mismatch")
        choices = envelope.get("choices")
        if not isinstance(choices, list) or len(cast(list[object], choices)) != 1:
            raise InferenceDenied("invalid_provider_choices")
        choice_value = cast(list[object], choices)[0]
        if not isinstance(choice_value, dict):
            raise InferenceDenied("invalid_provider_choice")
        choice = cast(dict[str, object], choice_value)
        if choice.get("finish_reason") != "stop":
            raise InferenceDenied("truncated_provider_output")
        message = cast(dict[str, object] | None, choice.get("message"))
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise InferenceDenied("invalid_provider_message")
        if message.get("tool_calls") or message.get("function_call"):
            raise InferenceDenied("native_tool_execution_forbidden")
        usage = cast(dict[str, object] | None, envelope.get("usage"))
        if not isinstance(usage, dict) or type(usage.get("completion_tokens")) is not int:
            raise InferenceDenied("missing_token_accounting")
        if type(usage.get("prompt_tokens")) is not int or usage["prompt_tokens"] != input_tokens:
            raise InferenceDenied("provider_template_token_mismatch")
        output_tokens = cast(int, usage["completion_tokens"])
        if not 0 <= output_tokens <= request.output_tokens:
            raise InferenceDenied("output_budget_exceeded")
        return selection_to_proposal(
            cast(str, message["content"]),
            task_id=request.task_id,
            step_id=request.step_id,
            fence=request.fence,
            revision=request.revision,
            items=request.items,
        ), output_tokens


def provider_envelope(raw: bytes) -> dict[str, object]:
    import json

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise InferenceDenied("duplicate_provider_key")
            value[key] = item
        return value

    try:
        value: object = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, RecursionError) as error:
        raise InferenceDenied("invalid_provider_envelope") from error
    if not isinstance(value, dict) or set(cast(dict[str, object], value)) - {
        "id",
        "object",
        "created",
        "model",
        "choices",
        "usage",
        "system_fingerprint",
        "stats",
        "runtime",
        "model_info",
    }:
        raise InferenceDenied("invalid_provider_envelope")
    return cast(dict[str, object], value)


def proposal_schema() -> dict[str, object]:
    """Obtain the packaged, reviewed schema without maintaining another copy."""
    import json
    from importlib.resources import files

    schema = cast(
        dict[str, object],
        json.loads(files("care_link_contracts").joinpath("schema.json").read_text()),
    )
    all_definitions = cast(dict[str, object], schema["$defs"])
    definitions: dict[str, object] = {}

    def collect(value: object) -> None:
        if isinstance(value, dict):
            values = cast(dict[str, object], value)
            ref = values.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                name = ref.removeprefix("#/$defs/")
                if name not in definitions:
                    definitions[name] = all_definitions[name]
                    collect(all_definitions[name])
            for item in values.values():
                collect(item)
        elif isinstance(value, list):
            for item in cast(list[object], value):
                collect(item)

    collect({"$ref": "#/$defs/Proposal"})
    value: dict[str, object] = {"$ref": "#/$defs/Proposal", "$defs": definitions}
    validate_contract(
        "Proposal",
        {
            "task_id": "00000000-0000-0000-0000-000000000001",
            "step_id": "00000000-0000-0000-0000-000000000002",
            "fence": "1",
            "expected_task_revision": "1",
            "candidate_text": "",
            "sources": [],
            "next": None,
            "completion_claim": False,
        },
    )
    return value


def provider_proposal_schema(function: str = "worker_summary") -> dict[str, object]:
    """MLX worker-summary grammar v3: select bounded evidence indices only.

    Full canonical selection validation preserves uniqueness omitted on wire.
    Trusted code then constructs the unsent Proposal from current server-owned
    sources and bindings and validates it against the unchanged full contract.
    Another profile needs separately evaluated format/source compatibility.
    """
    if function != "worker_summary":
        raise InferenceDenied("provider_profile_not_supported")
    return selection_schema(wire=True)
