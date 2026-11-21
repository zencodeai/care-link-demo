"""Mechanical maximum class floors from an explicit trusted path/domain map."""

from collections.abc import Sequence

from care_link_domain import ManualError

HIGH = frozenset(
    {
        "triage",
        "thresholds",
        "consent",
        "disclosure",
        "emergency_guard",
        "tool_permissions",
        "triage_features",
    }
)
SENSITIVE = frozenset(
    {
        "policy",
        "prompt",
        "model",
        "protocol_content",
        "static_content",
        "jurisdiction",
        "infrastructure",
    }
)
# This map is code-owned and cannot be supplied by an ArtifactRegister caller.
# Unmapped paths conservatively require C3, including unknown service/package code.
PATH_FLOORS: tuple[tuple[str, int], ...] = (
    ("services/data/src/care_link_data/", 3),
    ("services/core/src/care_link_core/", 3),
    ("services/identity/", 3),
    ("packages/domain/", 3),
    ("packages/policy-input/", 3),
    ("packages/contracts/", 3),
    ("packages/workload-trust/", 3),
    ("services/runtime/", 3),
    ("services/inference/", 2),
    ("packages/knowledge/", 2),
    ("deploy/", 2),
    ("config/", 2),
    ("host/", 2),
    ("services/simulators/", 2),
    ("apps/web/src/", 1),
    ("tests/", 1),
    ("doc/research/", 1),
)


def path_floor(path: str) -> int:
    if (
        not path
        or path.startswith("/")
        or "\\" in path
        or any(part in {"..", "."} for part in path.split("/"))
    ):
        return 3
    if any(
        part in path
        for part in (
            "consent",
            "disclosure",
            "assessment",
            "triage",
            "tool_registry",
            "emergency",
            "classification",
            "permission",
            "delegation",
            "security",
        )
    ):
        return 3
    mapped = next((floor for prefix, floor in PATH_FLOORS if path.startswith(prefix)), 3)
    if any(
        part in path for part in ("prompt", "model", "network", "jurisdiction", "static_content")
    ):
        return max(mapped, 2)
    return mapped


def change_class(kind: str, domains: Sequence[str], paths: Sequence[str]) -> str:
    if not paths or not domains:
        raise ManualError("governance.classification_incomplete")
    floor = (
        2
        if kind
        in {
            "policy",
            "model",
            "prompt",
            "tool_registry",
            "content",
            "config",
            "migration",
            "release",
        }
        else 1
    )
    for domain in domains:
        floor = max(
            floor,
            3
            if domain in HIGH
            else 2
            if domain in SENSITIVE
            else 1
            if domain in {"technical", "directory"}
            else 3,
        )
    return "C" + str(max(floor, *(path_floor(path) for path in paths)))


def required_authorities(classification: str, domains: Sequence[str]) -> frozenset[str]:
    required = {"technical", "operations"}
    if classification >= "C2":
        required.add("security")
    if classification == "C3":
        required.update({"privacy", "equity"})
        if set(domains) & {
            "triage",
            "thresholds",
            "emergency_guard",
            "triage_features",
            "protocol_content",
        }:
            required.add("clinical")
        if "protocol_content" in domains:
            required.add("community")
    return frozenset(required)
