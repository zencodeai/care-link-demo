"""Server-owned context ordering with exact pinned token-count proof."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from care_link_contracts import validate_contract

from .admission import InferenceDenied, ModelManifest

ORDER = {
    "approved_instruction": 0,
    "structured_state": 1,
    "approved_fact": 2,
    "untrusted_report": 3,
    "untrusted_observation": 4,
}


@dataclass(frozen=True)
class TokenProof:
    input_tokens: int
    template_overhead: int
    tokenizer_digest: str
    template_digest: str
    content_digest: str


class TokenCounter(Protocol):
    def count(self, messages: Sequence[Mapping[str, str]]) -> TokenProof: ...


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_digest(messages: Sequence[Mapping[str, str]]) -> str:
    return hashlib.sha256(canonical(messages).encode()).hexdigest()


@dataclass(frozen=True)
class Context:
    messages: tuple[dict[str, str], ...]
    input_tokens: int
    output_reserve: int
    admitted_sources: tuple[dict[str, object], ...]


def render_messages(items: Sequence[dict[str, object]]) -> tuple[dict[str, str], ...]:
    """Render attributed data with server-owned stable evidence indices."""
    for item in items:
        validate_contract("ContextItem", item)
    messages: list[dict[str, str]] = []
    evidence_index = 0
    for item in sorted(items, key=lambda item: ORDER[str(item["label"])]):
        role = "system" if item["label"] == "approved_instruction" else "user"
        rendered_item = dict(item)
        if item["label"] in {"approved_fact", "untrusted_report", "untrusted_observation"}:
            rendered_item["evidence_index"] = evidence_index
            evidence_index += 1
        messages.append({"role": role, "content": canonical(rendered_item)})
    return tuple(messages)


def build_context(
    items: Sequence[dict[str, object]],
    manifest: ModelManifest,
    counter: TokenCounter,
    *,
    output_reserve: int = 1024,
    context_limit: int = 8192,
) -> Context:
    if (
        not 1 <= len(items) <= 64
        or not 1 <= output_reserve <= 1024
        or not 1 <= context_limit <= 8192
    ):
        raise InferenceDenied("invalid_context_budget")
    for item in items:
        validate_contract("ContextItem", item)
    ordered = sorted(items, key=lambda item: ORDER[str(item["label"])])
    # Instructions have release custody; other entries remain JSON-attributed data
    # inside a user message, never model role names supplied by retrieved text.
    messages = render_messages(items)
    proof = counter.count(messages)
    if (
        proof.tokenizer_digest != manifest.tokenizer_digest
        or proof.template_digest != manifest.template_digest
        or proof.content_digest != content_digest(messages)
        or type(proof.input_tokens) is not int
        or proof.input_tokens < 0
        or type(proof.template_overhead) is not int
        or proof.template_overhead < 0
    ):
        raise InferenceDenied("token_identity_unverified")
    if proof.input_tokens + proof.template_overhead + output_reserve > min(
        8192, context_limit, manifest.model_window
    ):
        # No character estimates or silent dropping of critical/conflicting facts.
        raise InferenceDenied("context_does_not_fit")
    sources = tuple(
        dict(cast(dict[str, object], item["source"]))
        for item in ordered
        if isinstance(item["source"], dict)
    )
    # Report the complete rendered prompt count, including a separately proved
    # template overhead if a counter exposes it. Provider usage must match this.
    return Context(
        tuple(messages), proof.input_tokens + proof.template_overhead, output_reserve, sources
    )
