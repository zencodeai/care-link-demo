"""Explicit synthetic evaluation, including truthful unavailable-model receipts.

The CLI probes existing read-only loopback model listing. It never starts a
server, loads/downloads a model, changes application admission, or sends prompts.
Actual function evaluation uses evaluate_cases with an explicitly composed local
pipeline; deterministic tests of that harness are not real-model evidence.
"""

import argparse
import hashlib
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx

from .admission import MODEL, InferenceDenied


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    function: str
    language: str
    source_text: str
    injected_text: str
    expected: str


def evaluate_cases(
    cases: Sequence[EvaluationCase],
    generate: Callable[[EvaluationCase], str],
    *,
    model_digest: str,
    configuration_digest: str,
) -> dict[str, object]:
    results: list[dict[str, object]] = []
    for case in cases:
        started = time.monotonic()
        status, output = "failed", ""
        try:
            output = generate(case)
            # Initial function admission is extractive. Injected instructions
            # cannot add unsupported claims even when they cite a valid source.
            status = "passed" if output == case.expected else "failed"
        except (InferenceDenied, TimeoutError, OSError):
            status = "denied" if case.expected == "DENY" else "failed"
        results.append(
            {
                "case_id": case.case_id,
                "function": case.function,
                "language": case.language,
                "state": status,
                "latency_seconds": time.monotonic() - started,
                "source_digest": hashlib.sha256(case.source_text.encode()).hexdigest(),
                "output_digest": hashlib.sha256(output.encode()).hexdigest(),
            }
        )
    return {
        "model_identifier": MODEL,
        "model_digest": model_digest,
        "configuration_digest": configuration_digest,
        "cases": results,
    }


def probe_availability(*, transport: httpx.BaseTransport | None = None) -> dict[str, object]:
    receipt: dict[str, object] = {
        "model_identifier": MODEL,
        "function_admission": "disabled",
        "model_evaluation": "not_run",
        "human_review": "deferred_until_after_IMP10",
        "loaded_identity": None,
        "artifact_digest": None,
        "tokenizer_digest": None,
        "template_digest": None,
        "grounding_en_fr_adversarial_latency": "not_run",
    }
    try:
        with httpx.Client(transport=transport, trust_env=False, follow_redirects=False) as client:
            response = client.get("http://127.0.0.1:1234/v1/models", timeout=3)
            response.raise_for_status()
            if len(response.content) > 65536:
                raise ValueError("model list exceeds bound")
            value: object = response.json()
            # A successful list is availability only, never artifact/loaded proof.
            receipt["availability"] = (
                "model_list_observed" if isinstance(value, dict) else "invalid"
            )
            receipt["reason"] = (
                "Artifact, loaded identity, tokenizer/template and per-function evidence required"
            )
    except (httpx.HTTPError, ValueError):
        receipt["availability"] = "unavailable"
        receipt["reason"] = "Existing loopback model server unavailable; no startup/load attempted"
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    arguments.output.write_text(json.dumps(probe_availability(), indent=2) + "\n")


if __name__ == "__main__":
    main()
