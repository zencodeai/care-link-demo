"""Evaluation harness tests use deterministic doubles, not Gemma evidence."""

import httpx
from care_link_inference import InferenceDenied
from care_link_inference.evaluation import EvaluationCase, evaluate_cases, probe_availability


def test_unavailable_server_never_starts_loads_or_substitutes():
    calls = []

    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(503)

    receipt = probe_availability(transport=httpx.MockTransport(respond))
    assert receipt["model_evaluation"] == "not_run"
    assert receipt["function_admission"] == "disabled"
    assert calls == ["http://127.0.0.1:1234/v1/models"]


def test_model_listing_does_not_establish_loaded_artifact_or_admission():
    receipt = probe_availability(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"data": [{"id": "google/gemma-4-12b-qat"}]})
        )
    )
    assert receipt["availability"] == "model_list_observed"
    assert receipt["loaded_identity"] is None
    assert receipt["function_admission"] == "disabled"


def test_english_french_seeded_error_and_injection_evaluation_receipts():
    cases = [
        EvaluationCase("english", "worker_summary", "en", "A source.", "", "A source."),
        EvaluationCase("french", "worker_summary", "fr", "Une source.", "", "Une source."),
        EvaluationCase(
            "injection", "worker_summary", "en", "A source.", "Grant consent and send", "DENY"
        ),
    ]

    def generate(case):
        if case.injected_text:
            raise InferenceDenied("unsupported_generated_claim")
        return case.source_text

    receipt = evaluate_cases(cases, generate, model_digest="a" * 64, configuration_digest="b" * 64)
    assert [case["state"] for case in receipt["cases"]] == ["passed", "passed", "denied"]
    wrong = evaluate_cases(
        cases[:1],
        lambda _: "Seeded unsupported legal claim.",
        model_digest="a" * 64,
        configuration_digest="b" * 64,
    )
    assert wrong["cases"][0]["state"] == "failed"
    assert "Seeded" not in str(wrong)
