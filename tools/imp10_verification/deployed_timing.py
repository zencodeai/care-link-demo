"""Record repeated timings without collapsing failed or missing observations."""

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from functools import partial
from math import ceil, isfinite
from time import monotonic_ns
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

type Condition = Literal["cold", "warm", "error"]
type Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
type Milliseconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]
type Count = Annotated[int, Field(ge=0)]

CONDITIONS: tuple[Condition, ...] = ("cold", "warm", "error")


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Load(Closed):
    connected_sessions: Count
    occupied_inference_slots: Count
    unique_pending_tasks: Count


class Model(Closed):
    identifier: str
    instance_sha256: Digest
    artifact_sha256: Digest
    tokenizer_sha256: Digest
    template_sha256: Digest
    effective_settings_sha256: Digest


class Candidate(Closed):
    image_sha256: Digest
    config_sha256: Digest
    role_identity_evidence_sha256: Digest
    node_uid: str
    namespace_uid: str
    model: Model


class ColdStart(Closed):
    before: Model
    absent_in_authenticated_catalog: bool
    after: Model
    reload_ms: Milliseconds
    binding_ms: Milliseconds
    bridge_boot_before_sha256: Digest
    bridge_boot_after_sha256: Digest
    no_other_inference_observed: bool


class Workload(Closed):
    peak: Load
    session_reads_ms: tuple[Milliseconds, ...]
    # Cumulative offset from the first admitted request, ordered by arrival.
    arrival_offsets_ms: tuple[Milliseconds, ...]
    locales: tuple[Literal["en-CA", "fr-CA"], ...]
    channel: Literal["web"]
    source_bytes_per_task: tuple[Count, ...]


class Turn(Closed):
    elapsed_ms: Milliseconds
    state: str
    safe_reason: str | None
    job_state: str
    result_digest_present: bool
    drafts_created: Count
    bridge_ms: Milliseconds | None
    prompt_tokens: Count | None
    completion_tokens: Count | None


class Round(Closed):
    model: Model
    workload: Workload
    turns: tuple[Turn, ...]
    manual_delivery_visible: bool
    private_help_connection_confirmed: bool


class DeployedTiming(Protocol):
    """The leased operator supplies product observations and cold lifecycle authority."""

    def cold_start(self, cycle: int) -> ColdStart: ...

    def exercise(self, condition: Condition, cycle: int) -> Round: ...


def nearest_rank(values: Sequence[float], quantile: float) -> float:
    if not values or not 0 < quantile <= 1:
        raise ValueError("Nonempty observations and probability in (0, 1] required")
    return sorted(values)[ceil(len(values) * quantile) - 1]


def distribution(values: Sequence[float], *, expected: int) -> dict[str, object]:
    if len(values) > expected:
        raise ValueError("Observed count exceeds scheduled count")
    if any(not isfinite(value) or value < 0 for value in values):
        raise ValueError("Finite nonnegative observations required")
    return {
        "expected": expected,
        "observed": len(values),
        "missing": expected - len(values),
        "samples_ms": list(values),
        "p50_ms": nearest_rank(values, 0.50) if values else None,
        "p95_ms": nearest_rank(values, 0.95) if values else None,
        "max_ms": max(values) if values else None,
    }


def _same_artifact(left: Model, right: Model) -> bool:
    return left.model_dump(exclude={"instance_sha256"}) == right.model_dump(
        exclude={"instance_sha256"}
    )


def _cold_is_current(observation: ColdStart, previous: Model) -> bool:
    return (
        observation.before == previous
        and observation.absent_in_authenticated_catalog
        and _same_artifact(observation.after, previous)
        and observation.after.instance_sha256 != previous.instance_sha256
        and observation.bridge_boot_after_sha256 != observation.bridge_boot_before_sha256
        and observation.no_other_inference_observed
    )


def _timed_call[T](operation: Callable[[], T]) -> tuple[T | None, float, str | None]:
    started = monotonic_ns()
    try:
        value = operation()
    except (OSError, ValueError, RuntimeError) as failure:
        return None, round((monotonic_ns() - started) / 1e6, 3), type(failure).__name__
    return value, round((monotonic_ns() - started) / 1e6, 3), None


def _successful(turn: Turn, *, context_tokens: int, output_tokens: int) -> bool:
    return (
        turn.state == "awaiting_human"
        and turn.safe_reason is None
        and turn.job_state == "completed"
        and turn.result_digest_present
        and turn.drafts_created == 1
        and turn.bridge_ms is not None
        and turn.prompt_tokens is not None
        and 0 < turn.prompt_tokens <= context_tokens
        and turn.completion_tokens is not None
        and 0 < turn.completion_tokens <= output_tokens
    )


def _bounded_error(turn: Turn) -> bool:
    return (
        turn.state == turn.job_state == "compute_unknown"
        and turn.safe_reason == "provider_stop_unverified"
        and not turn.result_digest_present
        and turn.drafts_created == 0
        and turn.bridge_ms is None
        and turn.prompt_tokens is None
        and turn.completion_tokens is None
    )


def _round_is_current(
    sample: Round,
    condition: Condition,
    model: Model,
    peak: Load,
    *,
    context_tokens: int,
    output_tokens: int,
) -> bool:
    work = sample.workload
    count = peak.connected_sessions
    if (
        sample.model != model
        or work.peak != peak
        or len(work.session_reads_ms) != count
        or len(work.locales) != count
        or len(work.source_bytes_per_task) != count
        or not all(work.source_bytes_per_task)
        or len(work.arrival_offsets_ms) != count
        or work.arrival_offsets_ms[0] != 0
        or sorted(work.arrival_offsets_ms) != list(work.arrival_offsets_ms)
        or not sample.manual_delivery_visible
        or sample.private_help_connection_confirmed
    ):
        return False
    if condition == "error":
        return len(sample.turns) == 1 and _bounded_error(sample.turns[0])
    return len(sample.turns) == peak.occupied_inference_slots and all(
        _successful(turn, context_tokens=context_tokens, output_tokens=output_tokens)
        for turn in sample.turns
    )


def collect_deployed_timing(
    adapter: DeployedTiming,
    *,
    candidate: Candidate,
    peak: Load,
    context_tokens: int,
    output_tokens: int,
    environment: Mapping[str, str | int],
    cycles: int = 3,
) -> dict[str, object]:
    """Measure paired cold/warm/error attempts and keep incomplete rounds in the denominator."""
    if cycles < 2 or peak != Load(
        connected_sessions=10, occupied_inference_slots=2, unique_pending_tasks=8
    ):
        raise ValueError("Repeated observations at the declared 10-session load required")
    if context_tokens <= 0 or output_tokens <= 0:
        raise ValueError("Positive candidate token caps required")

    observed_model = candidate.model
    started_at = datetime.now(UTC)
    attempts: list[dict[str, object]] = []
    timings: dict[Condition, list[float]] = {condition: [] for condition in CONDITIONS}
    states = {condition: {"passed": 0, "failed": 0, "missing": 0} for condition in CONDITIONS}
    wall_times: dict[Condition, list[float]] = {condition: [] for condition in CONDITIONS}
    for cycle in range(1, cycles + 1):
        cold, lifecycle_ms, failure = _timed_call(partial(adapter.cold_start, cycle))
        verified_cold = cold is not None and _cold_is_current(cold, observed_model)
        if cold is not None and _same_artifact(cold.after, candidate.model):
            observed_model = cold.after
        for condition in CONDITIONS:
            attempt: dict[str, object] = {"condition": condition, "cycle": cycle}
            attempts.append(attempt)
            if condition == "cold":
                attempt["lifecycle"] = cold.model_dump(mode="json") if cold is not None else None
                attempt["observed_lifecycle_ms"] = lifecycle_ms
                if not verified_cold:
                    states[condition]["missing"] += 1
                    attempt.update(status="missing", reason=failure or "cold_rebind_unverified")
                    continue
            sample, effort_ms, reason = _timed_call(partial(adapter.exercise, condition, cycle))
            attempt["round_wall_ms"] = effort_ms
            wall_times[condition].append(effort_ms)
            if sample is None:
                states[condition]["missing"] += 1
                attempt.update(status="missing", reason=reason)
                continue
            attempt["observation"] = sample.model_dump(mode="json")
            passed = _round_is_current(
                sample,
                condition,
                observed_model,
                peak,
                context_tokens=context_tokens,
                output_tokens=output_tokens,
            )
            status = "passed" if passed else "failed"
            states[condition][status] += 1
            attempt["status"] = status
            if passed:
                timings[condition].extend(turn.elapsed_ms for turn in sample.turns)

    return {
        "started_at_utc": started_at.isoformat(),
        "ended_at_utc": datetime.now(UTC).isoformat(),
        "candidate": candidate.model_dump(mode="json"),
        "environment": dict(environment),
        "declared_peak": peak.model_dump(mode="json"),
        "context_tokens": context_tokens,
        "output_tokens": output_tokens,
        "cycles": cycles,
        "attempts": attempts,
        "rounds_by_state": states,
        "timing_method": "Monotonic milliseconds. Nearest-rank percentiles describe this sample.",
        "accepted_turn_distribution": {
            condition: distribution(
                timings[condition],
                expected=cycles if condition == "error" else cycles * peak.occupied_inference_slots,
            )
            for condition in CONDITIONS
        },
        "round_wall_distribution": {
            condition: distribution(wall_times[condition], expected=cycles)
            for condition in CONDITIONS
        },
        "state": (
            "passed" if all(value["passed"] == cycles for value in states.values()) else "partial"
        ),
    }
