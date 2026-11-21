"""Measure bounded synthetic Qwen workloads through the authenticated host adapter."""

import argparse
import hashlib
import json
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import lmstudio as lms
from care_link_inference.admission import WORKER_SUMMARY_INPUT_LIMIT
from care_link_inference_bridge import LocalModelBridge
from care_link_inference_bridge.credentials import read_api_token
from care_link_inference_bridge.loaded import RENDER_MODE, bind_loaded_model

from tests.evaluation.qwen_local import evaluate_case


def latency(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    return {
        f"p{percentile}": round(ordered[math.ceil(len(ordered) * percentile / 100) - 1], 3)
        for percentile in (50, 95, 100)
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--model-index", required=True, type=Path)
    parser.add_argument("--token-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--diagnostic-stress", action="store_true")
    args = parser.parse_args()
    turns_per_wave = (0, 2, 4, 6, 8) if args.diagnostic_stress else (0, 1, 1, 2, 2)
    input_limit = 7168 if args.diagnostic_stress else WORKER_SUMMARY_INPUT_LIMIT

    results: list[dict[str, object]] = []
    record: dict[str, object] = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "scope": "Direct workstation Qwen preadmission with synthetic data",
        "render_mode": RENDER_MODE,
        "maximum_concurrent_jobs": 2,
        "provider_deadline_seconds": 30,
        "input_token_limit": input_limit,
        "diagnostic_stress": args.diagnostic_stress,
        "raw_reasoning_retained": False,
        "state": "failed",
        "cases": results,
    }
    bridge: LocalModelBridge | None = None
    try:
        token = read_api_token(args.token_file)
        bridge = LocalModelBridge(api_token=token)
        bridge.require_authentication()
        binding = bind_loaded_model(args.artifact_dir, args.model_index, api_token=token)
        try:
            record["artifact_digest"] = binding.artifact.artifact_digest
            record["tokenizer_digest"] = binding.counter.tokenizer_digest
            record["template_digest"] = binding.counter.template_digest
            with ThreadPoolExecutor(max_workers=2) as workers:
                for wave, turns in enumerate(turns_per_wave, start=1):
                    futures = [
                        workers.submit(
                            evaluate_case,
                            binding,
                            bridge,
                            locale,
                            wave % 2 == 0,
                            history_turns=turns,
                            history_filler=21 if args.diagnostic_stress else 17,
                            input_token_limit=input_limit,
                        )
                        for locale in ("en-CA", "fr-CA")
                    ]
                    for future in futures:
                        case = future.result()
                        results.append(
                            {
                                key: case[key]
                                for key in (
                                    "language",
                                    "injection",
                                    "history_turns",
                                    "preparation_seconds",
                                    "elapsed_seconds",
                                    "state",
                                )
                            }
                            | {
                                "wave": wave,
                                "prompt_tokens": cast(dict[str, object], case["token_proof"])[
                                    "input_tokens"
                                ],
                                "prompt_count_matches": case.get("prompt_count_matches", False),
                                "exact_grounding": case.get("exact_grounding", False),
                                "safe_reason": case.get("safe_reason"),
                            }
                        )
                    if any(case["state"] != "passed" for case in results):
                        break
        finally:
            binding.close()
    except (OSError, ValueError, lms.LMStudioError) as error:
        record["safe_reason"] = type(error).__name__
    finally:
        if bridge is not None:
            bridge.close()

    if results:
        record["generation_latency_seconds"] = latency(
            [cast(float, case["elapsed_seconds"]) for case in results]
        )
        record["end_to_end_latency_seconds"] = latency(
            [
                cast(float, case["elapsed_seconds"]) + cast(float, case["preparation_seconds"])
                for case in results
            ]
        )
    if len(results) == 10 and all(case["state"] == "passed" for case in results):
        record["state"] = "passed"
    record["harness_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    record["case_harness_sha256"] = hashlib.sha256(
        Path(__file__).with_name("qwen_local.py").read_bytes()
    ).hexdigest()
    args.output.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"state": record["state"], "cases": len(results)}))
    if record["state"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
