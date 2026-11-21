from care_link_runtime import RuntimeClient


def test_runtime_sends_only_fenced_references_never_context_or_destinations():
    class Transport:
        def invoke(self, operation, body):
            assert operation == "inference_request"
            assert set(body) == {"task_id", "step_id", "fence", "expected_task_revision"}
            return {"state": "disabled"}

    result = RuntimeClient(Transport()).inference(
        task_id="00000000-0000-0000-0000-000000000001",
        step_id="00000000-0000-0000-0000-000000000002",
        fence="1",
        expected_task_revision="1",
    )
    assert result["state"] == "disabled"


def test_runtime_fixed_tls_broker_routes_no_direct_inference():
    import ssl

    import httpx
    import pytest
    from care_link_runtime import HttpBrokerTransport

    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(503)

    transport = HttpBrokerTransport(
        ssl.create_default_context(), transport=httpx.MockTransport(respond)
    )
    with pytest.raises(ValueError):
        transport.invoke("inference_execute", {})
    body = {
        "task_id": "00000000-0000-0000-0000-000000000001",
        "step_id": "00000000-0000-0000-0000-000000000002",
        "fence": "1",
        "expected_task_revision": "1",
    }
    with pytest.raises(httpx.HTTPError):
        transport.invoke("inference_request", body)
    with pytest.raises(httpx.HTTPError):
        transport.invoke("inference_request", body)
    assert str(calls[0].url) == "https://core:8443/internal/v1/broker/inference"
    assert calls[0].headers["Idempotency-Key"] == calls[1].headers["Idempotency-Key"]
    transport.close()


def test_one_turn_renews_lease_during_inference_and_submits_only_unsent_proposal():
    import threading
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    task_id = str(uuid4())
    calls = []
    renewed = threading.Event()

    class Transport:
        def invoke(self, operation, body, *, task_id=None):
            calls.append(operation)
            if operation in {"step_lease", "step_renew"}:
                if operation == "step_renew":
                    renewed.set()
                return {
                    "task_id": task_id,
                    "step_id": body["step_id"],
                    "fence": "1",
                    "task_revision": "1",
                    "expires_at": (datetime.now(UTC) + timedelta(seconds=10))
                    .isoformat()
                    .replace("+00:00", "Z"),
                }
            if operation == "inference_request":
                assert renewed.wait(timeout=1)
                return {
                    "job_id": str(uuid4()),
                    "state": "completed",
                    "proposal": {
                        **body,
                        "candidate_text": "Fictional source.",
                        "sources": [],
                        "next": None,
                        "completion_claim": False,
                    },
                    "input_tokens": 30,
                    "output_tokens": 20,
                    "model_digest": "a" * 64,
                    "safe_reason": None,
                }
            assert operation == "proposal_submit"
            return {"state": "awaiting_human"}

    result = RuntimeClient(Transport()).run_one_turn(task_id, "1", renew_interval=0.01)
    assert result["state"] == "awaiting_human"
    assert calls[0] == "step_lease"
    assert calls[-1] == "proposal_submit"
    assert calls.count("inference_request") == 1
    assert "step_renew" in calls
    assert "tool_invoke" not in calls
