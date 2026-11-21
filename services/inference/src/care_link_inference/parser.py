"""Bounded whole-proposal validation. No model tool is ever executed here."""

from collections.abc import Mapping, Sequence
from typing import cast

from care_link_contracts import ContractError, parse_contract

from .admission import InferenceDenied
from .context import canonical

MAX_RESPONSE_BYTES = 65536


def _depth(raw: str) -> None:
    depth, quoted, escaped = 0, False, False
    for char in raw:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > 20:
                raise InferenceDenied("response_too_deep")
        elif char in "]}":
            depth -= 1


def parse_proposal(
    raw: str,
    *,
    task_id: str,
    step_id: str,
    fence: str,
    revision: str,
    sources: Sequence[Mapping[str, object]],
    allowed_tools: frozenset[str],
    source_texts: Mapping[str, str] | None = None,
) -> dict[str, object]:
    if len(raw.encode()) > MAX_RESPONSE_BYTES:
        raise InferenceDenied("response_too_large")
    _depth(raw)
    try:
        value = cast(dict[str, object], parse_contract("Proposal", raw))
    except ContractError as error:
        raise InferenceDenied("invalid_proposal") from error
    if any(
        value[key] != expected
        for key, expected in (
            ("task_id", task_id),
            ("step_id", step_id),
            ("fence", fence),
            ("expected_task_revision", revision),
        )
    ):
        raise InferenceDenied("proposal_binding_mismatch")
    admitted = {canonical(source) for source in sources}
    proposed = cast(list[dict[str, object]], value["sources"])
    if not proposed or any(canonical(source) not in admitted for source in proposed):
        raise InferenceDenied("unresolved_proposal_source")
    if source_texts is not None:
        allowed_texts = {
            source_texts[canonical(source)]
            for source in proposed
            if canonical(source) in source_texts
        }
        lines = [line.strip() for line in str(value["candidate_text"]).splitlines() if line.strip()]
        exact_join = "\n".join(source_texts.get(canonical(source), "") for source in proposed)
        if not lines or (
            value["candidate_text"] != exact_join
            and any(line not in allowed_texts for line in lines)
        ):
            raise InferenceDenied("unsupported_generated_claim")
    tool = value["next"]
    if isinstance(tool, dict) and cast(dict[str, object], tool).get("tool") not in allowed_tools:
        raise InferenceDenied("tool_not_admitted")
    # The result is an unsent draft/observation proposal; completion_claim grants
    # no state/effect authority. Broker still validates factual grounding.
    return value
