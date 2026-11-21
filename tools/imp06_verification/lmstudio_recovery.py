"""Observe cancellation of an owned LM Studio prediction without changing lifecycle.

This qualification probe does not mint a provider-stop receipt or update Data.
"""

import argparse
import json
import os
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from time import monotonic

import lmstudio as lms
from care_link_inference_bridge.bridge import MODEL, LocalModelBridge
from care_link_inference_bridge.credentials import read_api_token
from lmstudio._sdk_models import ModelSpecifierInstanceReference
from lmstudio.sync_api import PredictionStream

_SDK_VERSION = "1.6.0b1"
_PROMPT = (
    "Repeat the following positive integers in order, separated by spaces: 1 2 3 4 5 6 7 8 9 10"
)
_PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


def observe_cancel(
    stream: PredictionStream, expected_model_key: str, selected_instance: str
) -> dict[str, object]:
    started = monotonic()
    sent_at: float | None = None
    for _fragment in stream:
        if sent_at is None:
            sent_at = monotonic()
            stream.cancel()
    ended = monotonic()
    result = stream.result()
    terminal = result.model_info.to_dict()
    stop_reason = result.stats.stop_reason
    model_matches = terminal.get("modelKey") == expected_model_key
    terminal_instance = terminal.get("instanceReference")
    instance_matches = terminal_instance == selected_instance if terminal_instance else None
    cancelled = (
        sent_at is not None
        and stop_reason == "userStopped"
        and model_matches
        and instance_matches is not False
    )
    return {
        "state": "passed" if cancelled else "unverified",
        "cancel_after_first_fragment": sent_at is not None,
        "provider_terminal_stop_reason": stop_reason,
        "provider_terminal_model_key_matches": model_matches,
        "provider_terminal_instance_reference_present": bool(terminal_instance),
        "provider_terminal_instance_reference_matches_when_present": instance_matches,
        "provider_terminal_identifier_present": bool(terminal.get("identifier")),
        "provider_terminal_context_present": bool(terminal.get("contextLength")),
        "seconds_cancel_to_terminal": round(ended - sent_at, 3) if sent_at is not None else None,
        "seconds_request_to_terminal": round(ended - started, 3),
        "prediction_tokens": result.stats.predicted_tokens_count,
    }


def probe(token_file: Path) -> dict[str, object]:
    if any(os.environ.get(key) for key in _PROXY_KEYS):
        raise ValueError("SDK proxy environment forbidden")
    installed = version("lmstudio")
    if installed != _SDK_VERSION:
        raise ValueError("the instance-selector probe requires the pinned SDK")
    token = read_api_token(token_file)
    bridge = LocalModelBridge(api_token=token)
    try:
        bridge.require_authentication()
    finally:
        bridge.close()
    with lms.Client("127.0.0.1:1234", api_token=token) as client:
        matches = [model for model in client.list_loaded_models("llm") if model.identifier == MODEL]
        if len(matches) != 1 or not isinstance(matches[0], lms.LLM):
            raise ValueError("exact existing model required")
        handle = matches[0]
        before = handle.get_info().to_dict()
        instance = before.get("instanceReference")
        if before.get("modelKey") != MODEL or not instance:
            raise ValueError("exact existing instance reference required")
        specifier = ModelSpecifierInstanceReference(instance_reference=instance)
        selected = client.llm.get_model_info(specifier).to_dict()
        if selected != before:
            raise ValueError("SDK instance selection did not resolve to the known loaded model")
        # The public LLM handle's completion method selects by model identifier.
        # Qualification needs an explicit instance reference and pins this private SDK seam.
        stream = client.llm._complete_stream(  # pyright: ignore[reportPrivateUsage]
            specifier, _PROMPT, config={"maxTokens": 96, "temperature": 0}
        )
        observed = observe_cancel(stream, MODEL, instance)
        stable = handle.get_info().to_dict() == before
    return {
        **observed,
        "state": observed["state"] if stable else "unverified",
        "selected_by_existing_provider_instance_reference": True,
        "catalog_instance_stable_before_and_after": stable,
        "authenticated_loopback": True,
        "sdk_version": installed,
        "model_key": MODEL,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--probe-owned-cancel", required=True, action="store_true")
    args = parser.parse_args()
    old_timeout = lms.get_sync_api_timeout()
    lms.set_sync_api_timeout(10.0)
    try:
        observed = probe(args.token_file)
    except (OSError, ValueError, lms.LMStudioError) as error:
        observed = {"state": "unverified", "error_type": type(error).__name__}
    finally:
        lms.set_sync_api_timeout(old_timeout)
    receipt = {
        **observed,
        "recorded_at": datetime.now(UTC).isoformat(),
        "scope": "One bounded SDK prediction of synthetic integers using the loaded model",
        "production_rest_job_cancellation_verified": False,
        "provider_process_exit_observed": False,
        "provider_stop_receipt_issued": False,
        "database_mutated": False,
    }
    with args.output.open("x", encoding="ascii") as output:
        output.write(json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=True) + "\n")
    print(json.dumps({"state": receipt["state"], "scope": "synthetic SDK request cancellation"}))
    return 0 if receipt["state"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
