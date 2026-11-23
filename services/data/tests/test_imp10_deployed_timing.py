"""Check the evidence collector against failed and missing synthetic observations."""

import pytest

from tools.imp10_verification.deployed_timing import (
    Candidate,
    ColdStart,
    Condition,
    Load,
    Model,
    Round,
    Turn,
    Workload,
    collect_deployed_timing,
    distribution,
)

PEAK = Load(connected_sessions=10, occupied_inference_slots=2, unique_pending_tasks=8)
MODEL = Model(
    identifier="synthetic-example",
    instance_sha256="0" * 64,
    artifact_sha256="a" * 64,
    tokenizer_sha256="b" * 64,
    template_sha256="c" * 64,
    effective_settings_sha256="d" * 64,
)
CANDIDATE = Candidate(
    image_sha256="e" * 64,
    config_sha256="f" * 64,
    role_identity_evidence_sha256="a" * 64,
    node_uid="owned-node",
    namespace_uid="owned-namespace",
    model=MODEL,
)
LOAD = Workload(
    peak=PEAK,
    session_reads_ms=tuple(float(index) for index in range(10)),
    arrival_offsets_ms=tuple(float(index) for index in range(10)),
    locales=("en-CA", "fr-CA") * 5,
    channel="web",
    source_bytes_per_task=(15,) * 10,
)
SUCCESS = Turn(
    elapsed_ms=20,
    state="awaiting_human",
    safe_reason=None,
    job_state="completed",
    result_digest_present=True,
    drafts_created=1,
    bridge_ms=15,
    prompt_tokens=3,
    completion_tokens=1,
)
UNKNOWN = Turn(
    elapsed_ms=40,
    state="compute_unknown",
    safe_reason="provider_stop_unverified",
    job_state="compute_unknown",
    result_digest_present=False,
    drafts_created=0,
    bridge_ms=None,
    prompt_tokens=None,
    completion_tokens=None,
)


class Adapter:
    def __init__(self, *, missing: bool = False) -> None:
        self.model = MODEL
        self.missing = missing

    def cold_start(self, cycle: int) -> ColdStart:
        if self.missing and cycle == 1:
            raise RuntimeError("Private failure text must not be copied into evidence")
        before = self.model
        self.model = before.model_copy(update={"instance_sha256": str(cycle) * 64})
        return ColdStart(
            before=before,
            absent_in_authenticated_catalog=True,
            after=self.model,
            reload_ms=100,
            binding_ms=20,
            bridge_boot_before_sha256="e" * 64,
            bridge_boot_after_sha256=str(cycle) * 64,
            no_other_inference_observed=True,
        )

    def exercise(self, condition: Condition, cycle: int) -> Round:
        turns = (SUCCESS, SUCCESS)
        if condition == "error":
            turn = UNKNOWN
            if self.missing and cycle == 2:
                turn = turn.model_copy(update={"drafts_created": 1})
            turns = (turn,)
        return Round(
            model=self.model,
            workload=LOAD,
            turns=turns,
            manual_delivery_visible=True,
            private_help_connection_confirmed=False,
        )


def collect(adapter: Adapter):
    return collect_deployed_timing(
        adapter,
        candidate=CANDIDATE,
        peak=PEAK,
        context_tokens=16,
        output_tokens=8,
        environment={"system": "synthetic"},
        cycles=2,
    )


def test_reports_paired_cycles_and_durable_unknown_outcomes():
    report = collect(Adapter())
    assert report["state"] == "passed"
    assert report["rounds_by_state"] == {
        mode: {"passed": 2, "failed": 0, "missing": 0} for mode in ("cold", "warm", "error")
    }
    assert report["accepted_turn_distribution"] == {
        "cold": distribution([20.0] * 4, expected=4),
        "warm": distribution([20.0] * 4, expected=4),
        "error": distribution([40.0] * 2, expected=2),
    }


def test_missing_reload_and_forbidden_draft_cannot_pass_or_disappear():
    report = collect(Adapter(missing=True))
    assert report["state"] == "partial"
    assert report["rounds_by_state"] == {
        "cold": {"passed": 1, "failed": 0, "missing": 1},
        "warm": {"passed": 2, "failed": 0, "missing": 0},
        "error": {"passed": 1, "failed": 1, "missing": 0},
    }
    assert "Private failure" not in str(report)
    assert "RuntimeError" in str(report)
    assert report["accepted_turn_distribution"] == {
        "cold": distribution([20.0, 20.0], expected=4),
        "warm": distribution([20.0] * 4, expected=4),
        "error": distribution([40.0], expected=2),
    }


def test_reused_model_instance_cannot_count_as_a_cold_sample():
    class ReusedInstance(Adapter):
        def cold_start(self, cycle: int) -> ColdStart:
            observation = super().cold_start(cycle)
            self.model = observation.before
            return observation.model_copy(update={"after": self.model})

    report = collect(ReusedInstance())
    assert report["state"] == "partial"
    assert report["rounds_by_state"] == {
        "cold": {"passed": 0, "failed": 0, "missing": 2},
        "warm": {"passed": 2, "failed": 0, "missing": 0},
        "error": {"passed": 2, "failed": 0, "missing": 0},
    }


def test_distribution_preserves_observed_and_missing_counts():
    assert distribution([], expected=2) == {
        "expected": 2,
        "observed": 0,
        "missing": 2,
        "samples_ms": [],
        "p50_ms": None,
        "p95_ms": None,
        "max_ms": None,
    }
    assert distribution([5.0, 1.0, 2.0], expected=4)["p95_ms"] == 5.0
    with pytest.raises(ValueError, match="scheduled"):
        distribution([1.0], expected=0)
    with pytest.raises(ValueError, match="Finite"):
        distribution([float("nan")], expected=1)
