"""Graph and dispatch behavior; no local model or deployment claims."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from care_link_runtime import HttpBrokerTransport, RuntimeClient
from care_link_runtime.worker import RuntimeWorker


def test_stale_lease_binding_stops_before_inference():
    calls = []

    class Transport:
        def invoke(self, operation, body, *, task_id=None):
            calls.append(operation)
            return {
                "task_id": str(uuid4()),
                "step_id": body["step_id"],
                "fence": "1",
                "task_revision": "1",
                "expires_at": (datetime.now(UTC) + timedelta(seconds=10))
                .isoformat()
                .replace("+00:00", "Z"),
            }

    with pytest.raises(ValueError, match="lease task binding"):
        RuntimeClient(Transport()).run_one_turn(str(uuid4()), "1")
    assert calls == ["step_lease"]


def test_unknown_compute_ends_graph_without_retry_or_proposal():
    calls = []

    class Transport:
        def invoke(self, operation, body, *, task_id=None):
            calls.append(operation)
            if operation == "step_lease":
                return {
                    "task_id": task_id,
                    "step_id": body["step_id"],
                    "fence": "1",
                    "task_revision": "1",
                    "expires_at": (datetime.now(UTC) + timedelta(seconds=10))
                    .isoformat()
                    .replace("+00:00", "Z"),
                }
            return {
                "job_id": str(uuid4()),
                "state": "compute_unknown",
                "proposal": None,
                "input_tokens": 0,
                "output_tokens": 0,
                "model_digest": "a" * 64,
                "safe_reason": "provider_stop_unverified",
            }

    result = RuntimeClient(Transport()).run_one_turn(str(uuid4()), "1")
    assert result["state"] == "compute_unknown"
    assert calls == ["step_lease", "inference_request"]


def test_framework_cloud_tracing_is_denied_before_broker_access(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    with pytest.raises(ValueError, match="tracing"):
        RuntimeClient(None).run_one_turn(str(uuid4()), "1")


def test_worker_claim_is_consumed_once_and_never_automatically_retried():
    task = str(uuid4())
    claims = [
        {"task_id": task, "task_revision": "3", "fence": "2"},
        {"task_id": None, "task_revision": None, "fence": None},
    ]
    calls = []

    class Client:
        def run_one_turn(self, task_id, revision, *, initial_fence):
            calls.append((task_id, revision, initial_fence))
            raise TimeoutError("unknown compute")

    worker = RuntimeWorker(Client(), lambda: claims.pop(0))
    with pytest.raises(TimeoutError):
        worker.run_once()
    assert worker.run_once() is None
    assert calls == [(task, "3", "2")]


def test_poll_has_fixed_destination_empty_body_and_bounded_response():
    import ssl

    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"task_id": None, "task_revision": None, "fence": None})

    transport = HttpBrokerTransport(
        ssl.create_default_context(), transport=httpx.MockTransport(respond)
    )
    assert transport.poll_work()["task_id"] is None
    assert str(calls[0].url) == "https://core:8443/internal/v1/broker/work"
    assert calls[0].content == b"{}"
    transport.close()
