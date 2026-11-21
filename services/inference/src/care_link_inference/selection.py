"""A model selects evidence; trusted code owns proposal identity and text."""

import json
from collections.abc import Sequence
from importlib.resources import files
from typing import cast

from care_link_contracts import ContractError, parse_contract

from .admission import InferenceDenied
from .context import ORDER, canonical
from .parser import parse_proposal

DATA_LABELS = frozenset({"approved_fact", "untrusted_report", "untrusted_observation"})


def evidence_items(items: Sequence[dict[str, object]]) -> tuple[dict[str, object], ...]:
    return tuple(
        item
        for item in sorted(items, key=lambda item: ORDER[str(item["label"])])
        if item["label"] in DATA_LABELS
    )


def selection_schema(*, wire: bool = False) -> dict[str, object]:
    schema = cast(
        dict[str, object],
        json.loads(files("care_link_contracts").joinpath("schema.json").read_text()),
    )
    value = cast(dict[str, dict[str, object]], schema["$defs"])["ModelEvidenceSelection"]
    if wire:
        properties = cast(dict[str, dict[str, object]], value["properties"])
        properties["selected_indices"].pop("uniqueItems", None)
    return value


def selection_to_proposal(
    raw: str,
    *,
    task_id: str,
    step_id: str,
    fence: str,
    revision: str,
    items: Sequence[dict[str, object]],
) -> dict[str, object]:
    if len(raw.encode()) > 4096:
        raise InferenceDenied("selection_too_large")
    try:
        selected = cast(dict[str, object], parse_contract("ModelEvidenceSelection", raw))
    except ContractError as error:
        raise InferenceDenied("invalid_evidence_selection") from error
    indices = cast(list[int], selected["selected_indices"])
    evidence = evidence_items(items)
    if any(type(index) is not int or index >= len(evidence) for index in indices):
        raise InferenceDenied("selection_outside_current_evidence")
    required = {
        index
        for index, item in enumerate(evidence)
        if cast(dict[str, object], item["source"]).get("kind") == "assertion"
    }
    if not required <= set(indices):
        raise InferenceDenied("critical_evidence_missing")
    chosen = [evidence[index] for index in indices]
    sources = [cast(dict[str, object], item["source"]) for item in chosen]
    proposal: dict[str, object] = {
        "task_id": task_id,
        "step_id": step_id,
        "fence": fence,
        "expected_task_revision": revision,
        "candidate_text": "\n".join(str(item["text"]) for item in chosen),
        "sources": sources,
        "next": None,
        "completion_claim": False,
    }
    return parse_proposal(
        canonical(proposal),
        task_id=task_id,
        step_id=step_id,
        fence=fence,
        revision=revision,
        sources=[cast(dict[str, object], item["source"]) for item in evidence],
        allowed_tools=frozenset(),
        source_texts={canonical(item["source"]): str(item["text"]) for item in evidence},
    )
