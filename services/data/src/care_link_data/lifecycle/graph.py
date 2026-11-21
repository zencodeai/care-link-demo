"""Bounded copy graph eligibility. Unknown dependencies and cycles never imply absence."""

from collections.abc import Mapping
from datetime import datetime
from typing import cast

from ..store import Record, instant


def graph_blockers(
    copies: Mapping[str, Record],
    edges: list[tuple[str, str]],
    now: datetime,
    *,
    rights_subject: str | None = None,
) -> dict[str, str]:
    children: dict[str, list[str]] = {key: [] for key in copies}
    parents: dict[str, list[str]] = {key: [] for key in copies}
    blocked: dict[str, str] = {}
    for parent, child in edges:
        if parent not in copies or child not in copies:
            for key in (parent, child):
                if key in copies:
                    blocked[key] = "unknown_dependency"
            continue
        children[parent].append(child)
        parents[child].append(parent)
    visited: set[str] = set()
    active: list[str] = []

    def visit(key: str) -> None:
        if key in active:
            for member in active[active.index(key) :]:
                blocked[member] = "cyclic_dependency"
            return
        if key in visited:
            return
        active.append(key)
        for child in children[key]:
            visit(child)
        active.pop()
        visited.add(key)

    for key in copies:
        visit(key)
    for key, row in copies.items():
        if row["state"] == "purged":
            continue
        if row.get("classification") != "synthetic_content":
            blocked[key] = "unclassified_copy"
        if rights_subject == row["subject_id"]:
            continue
        if row.get("anchor_at") is None or row.get("expires_at") is None:
            blocked[key] = "anchor_pending"
        elif instant(row, "expires_at") > now:
            blocked[key] = "not_due"
        if any(
            copies[parent]["state"] != "purged" and copies[parent].get("anchor_at") is None
            for parent in parents[key]
        ):
            blocked[key] = "parent_anchor_pending"
    return blocked


def hold_matches(hold: Record, copy: Record, now: datetime) -> bool:
    if (
        hold["released_at"] is not None
        or hold["expires_at"] is not None
        and instant(hold, "expires_at") <= now
    ):
        return False
    scope = hold["scope"]
    if not isinstance(scope, dict):
        return True
    scope = cast(Record, scope)
    return (scope.get("subject_id") is None or scope["subject_id"] == copy["subject_id"]) and (
        scope.get("session_id") is None or scope["session_id"] == copy["session_id"]
    )
