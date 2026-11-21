"""Tokenizer proof HTTP composition uses a host SDK double, never real-model evidence."""

import json
import ssl
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

import httpx
import pytest
from care_link_inference import BRIDGE_COUNT_ENDPOINT, HttpTokenCounter, InferenceDenied
from care_link_inference.context import content_digest
from care_link_inference_bridge import LMStudioTokenCounter, TokenReceipt, create_app
from fastapi.testclient import TestClient

from services.inference.tests.test_inference import MANIFEST

MESSAGES = [{"role": "user", "content": "A fictional source."}]


class UnusedGeneration:
    def complete(self, _payload, _deadline):
        raise AssertionError("tokenization must not generate")


def receipt(messages):
    return TokenReceipt(
        MANIFEST.model_identifier,
        MANIFEST.loaded_model_id,
        MANIFEST.artifact_digest,
        MANIFEST.tokenizer_digest,
        MANIFEST.template_digest,
        MANIFEST.model_window,
        17,
        0,
        content_digest(messages),
    )


class HostCounter:
    def count(self, messages):
        return receipt(messages)


def body():
    return {"messages": MESSAGES, "content_digest": content_digest(MESSAGES)}


def test_http_counter_uses_only_authenticated_host_bridge_and_validates_actual_proof():
    seen = []
    pins = {
        "model_identifier": MANIFEST.model_identifier,
        "loaded_model_id": MANIFEST.loaded_model_id,
        "artifact_digest": MANIFEST.artifact_digest,
        "tokenizer_digest": MANIFEST.tokenizer_digest,
        "template_digest": MANIFEST.template_digest,
        "model_window": MANIFEST.model_window,
    }

    class Handle:
        def get_context_length(self):
            return MANIFEST.model_window

        def apply_prompt_template(self, chat):
            seen.append(chat)
            return "actual rendered template"

        def tokenize(self, text):
            assert text == "actual rendered template"
            return [1, 2, 3]

    sdk = LMStudioTokenCounter(
        Handle(),
        lambda history: history,
        artifact_digest=MANIFEST.artifact_digest,
        tokenizer_digest=MANIFEST.tokenizer_digest,
        template_digest=MANIFEST.template_digest,
        model_window=MANIFEST.model_window,
        loaded_current=lambda: pins,
    )
    client = TestClient(
        create_app(UnusedGeneration(), lambda _request, role: role == "inference", counter=sdk)
    )

    def serve(request):
        assert str(request.url) == BRIDGE_COUNT_ENDPOINT
        response = client.post(
            request.url.path, content=request.content, headers={"Content-Type": "application/json"}
        )
        return httpx.Response(response.status_code, content=response.content)

    remote = HttpTokenCounter(
        ssl.create_default_context(), MANIFEST, transport=httpx.MockTransport(serve)
    )
    proof = remote.count(MESSAGES)
    assert proof.input_tokens == 3 and proof.template_overhead == 0
    assert proof.content_digest == content_digest(MESSAGES)
    assert seen == [{"messages": MESSAGES}]
    remote.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"loaded_model_id": "other"},
        {"artifact_digest": "9" * 64},
        {"tokenizer_digest": "9" * 64},
        {"template_digest": "9" * 64},
        {"model_window": 1024},
        {"content_digest": "9" * 64},
        {"input_tokens": True},
        {"template_overhead": -1},
        {"extra": "trusted"},
    ],
)
def test_http_counter_rejects_changed_identity_unknown_keys_or_replayed_content(changes):
    value = {**asdict(receipt(MESSAGES)), **changes}
    counter = HttpTokenCounter(
        ssl.create_default_context(),
        MANIFEST,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=value)),
    )
    with pytest.raises(InferenceDenied, match="tokenizer_bridge_unavailable_or_unverified"):
        counter.count(MESSAGES)
    counter.close()


def test_tokenization_requires_inference_workload_host_engine_and_closed_message_text():
    denied = TestClient(
        create_app(UnusedGeneration(), lambda _request, _role: False, counter=HostCounter())
    )
    assert denied.post("/internal/v1/inference/tokenize", json=body()).status_code == 403
    missing = TestClient(create_app(UnusedGeneration(), lambda _request, role: role == "inference"))
    assert missing.post("/internal/v1/inference/tokenize", json=body()).status_code == 503
    admitted = TestClient(
        create_app(
            UnusedGeneration(), lambda _request, role: role == "inference", counter=HostCounter()
        )
    )
    assert (
        admitted.post(
            "/internal/v1/inference/tokenize", json={**body(), "url": "https://external.invalid"}
        ).status_code
        == 400
    )
    binary = {
        "messages": [{"role": "user", "content": [{"image_url": "https://external.invalid"}]}],
        "content_digest": "0" * 64,
    }
    assert admitted.post("/internal/v1/inference/tokenize", json=binary).status_code == 400
    assert (
        admitted.post("/internal/v1/inference/tokenize", content=b"a" * 262145).status_code == 413
    )
    duplicate = json.dumps(body()).replace('"messages":', '"content_digest":"x","messages":')
    assert admitted.post("/internal/v1/inference/tokenize", content=duplicate).status_code == 400


def test_tokenization_has_two_owned_slots_and_never_unbounded_threads():
    both_started, release = threading.Event(), threading.Event()
    lock, started = threading.Lock(), [0]

    class BlockingCounter:
        def count(self, messages):
            with lock:
                started[0] += 1
                if started[0] == 2:
                    both_started.set()
            assert release.wait(timeout=2)
            return receipt(messages)

    client = TestClient(
        create_app(
            UnusedGeneration(),
            lambda _request, role: role == "inference",
            counter=BlockingCounter(),
        )
    )
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(client.post, "/internal/v1/inference/tokenize", json=body())
        second = workers.submit(client.post, "/internal/v1/inference/tokenize", json=body())
        try:
            assert both_started.wait(timeout=1)
            assert client.post("/internal/v1/inference/tokenize", json=body()).status_code == 503
        finally:
            release.set()
        assert first.result().status_code == 200 and second.result().status_code == 200
    assert started[0] == 2
