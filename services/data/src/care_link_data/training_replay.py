"""Bounded offline comparison of an admitted training capture against pinned rules."""

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from care_link_contracts import parse_contract, validate_contract
from care_link_domain import Actor, ManualError
from care_link_domain import canonical_training as canonical
from care_link_domain import exercise_training_fixture as exercise
from care_link_domain import training_digest as digest

from .evaluation import ReplayCreate, ReplayResult
from .store import Record


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@dataclass(frozen=True)
class TrainingCapture:
    """Configured evidence bytes, with an explicit trainer and reviewer allowlist."""

    manifest: bytes
    observations: bytes
    owner_id: str
    reviewers: frozenset[str]


def _unique(pairs: list[tuple[str, object]]) -> Record:
    result: Record = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate capture field")
        result[key] = value
    return result


def _decode(data: bytes) -> object:
    if len(data) > 65536:
        raise ValueError("Capture exceeds the replay bound")
    parsed = json.loads(data, object_pairs_hook=_unique)
    if data != canonical(parsed):
        raise ValueError("Noncanonical capture bytes")
    return parsed


def training_bundle(components: dict[str, bytes]) -> str:
    """Bind the exact runner, artifact, schemas and runtime classifier bytes."""
    if not {"runner", "artifact", "contracts"} <= set(components):
        raise ValueError("Incomplete training bundle")
    return digest({name: sha256(content) for name, content in components.items()})


def capture(
    scenario_id: str,
    fixture: Record,
    observations: Record | None,
    created_at: datetime,
    *,
    bundle: str,
    owner_id: str,
    reviewers: frozenset[str] = frozenset(),
) -> TrainingCapture:
    """Package separately captured observations, never refreshing their source age."""
    if created_at.tzinfo is None:
        raise ValueError("Missing real capture anchor")
    return TrainingCapture(
        manifest=canonical(
            {
                "version": 1,
                "scenario_id": scenario_id,
                "bundle_digest": bundle,
                "captured_at": created_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                "fixture": fixture,
            }
        ),
        observations=canonical(observations),
        owner_id=owner_id,
        reviewers=frozenset(reviewers),
    )


@dataclass(frozen=True)
class _Entry:
    request: ReplayCreate
    capture: TrainingCapture
    captured_at: datetime
    fixture: bytes


class OfflineTrainingReplay:
    def __init__(
        self,
        captures: Iterable[TrainingCapture],
        *,
        bundle: str,
        artifact_digest: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._entries: dict[str, _Entry] = {}
        self._clock = clock
        for capture_data in captures:
            decoded = _decode(capture_data.manifest)
            if not isinstance(decoded, dict):
                raise ValueError("Capture manifest must be an object")
            manifest = cast(Record, decoded)
            observed = _decode(capture_data.observations)
            if (
                set(manifest)
                != {"version", "scenario_id", "bundle_digest", "captured_at", "fixture"}
                or type(manifest["version"]) is not int
                or manifest["version"] != 1
                or manifest["bundle_digest"] != bundle
                or not isinstance(manifest["captured_at"], str)
                or not manifest["captured_at"].endswith("Z")
                or (observed is not None and not isinstance(observed, dict))
            ):
                raise ValueError("Invalid pinned synthetic capture")
            fixture_bytes = canonical(manifest["fixture"])
            fixture = cast(Record, parse_contract("ScenarioCreate", fixture_bytes.decode()))
            if fixture["artifact_digest"] != artifact_digest:
                raise ValueError("Capture artifact differs from admitted artifact")
            validate_contract("Id", capture_data.owner_id)
            reviewers = frozenset(capture_data.reviewers)
            for reviewer in reviewers:
                validate_contract("Id", reviewer)
            request: ReplayCreate = {
                "scenario_id": cast(str, manifest["scenario_id"]),
                "input_manifest_digest": sha256(capture_data.manifest),
                "recorded_outputs_digest": sha256(capture_data.observations),
                "bundle_digest": bundle,
            }
            validate_contract("ReplayCreate", request)
            captured_at = datetime.fromisoformat(manifest["captured_at"])
            identifier = request["input_manifest_digest"]
            if captured_at > clock() or identifier in self._entries or len(self._entries) >= 128:
                raise ValueError("Future, duplicate or oversized replay catalog")
            self._entries[identifier] = _Entry(request, capture_data, captured_at, fixture_bytes)

    def _entry(self, request: ReplayCreate) -> _Entry:
        entry = self._entries.get(request["input_manifest_digest"])
        if (
            entry is None
            or entry.request != request
            or self._clock() >= entry.captured_at + timedelta(days=7)
        ):
            raise ManualError("evaluation.capture_unavailable", 404)
        return entry

    def authorize(self, actor: Actor, request: ReplayCreate) -> None:
        entry = self._entry(request)
        admitted = (actor.role == "trainer" and actor.account_id == entry.capture.owner_id) or (
            actor.role == "governance" and actor.account_id in entry.capture.reviewers
        )
        if not admitted or not actor.mfa or actor.expires_at <= self._clock():
            raise ManualError("evaluation.capture_unavailable", 404)

    def evaluate(self, request: ReplayCreate) -> ReplayResult:
        entry = self._entry(request)
        expected = _decode(entry.capture.observations)
        fixture = cast(Record, json.loads(entry.fixture))
        actual = exercise(request["scenario_id"], fixture)
        result = "missing" if expected is None else "matched" if expected == actual else "diverged"
        evidence = digest(
            {
                "request": request,
                "comparison": result,
                "actual_digest": digest(actual),
                "capture_kind": "deterministic_fixture",
                "clinical_claim": False,
            }
        )
        return ReplayResult("completed" if result == "matched" else "failed", evidence)
