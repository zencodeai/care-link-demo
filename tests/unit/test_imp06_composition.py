"""Fail-closed role composition and long-call disclosure fencing."""

import json
import ssl
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, create_autospec
from uuid import uuid4

import httpx
import pytest
from care_link_core.assistance_broker import InferenceBroker, attach_broker_routes
from care_link_domain import ManualError, WorkloadPeer
from care_link_runtime import HttpBrokerTransport
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from tools.imp06_runtime.inference import inference_application
from tools.imp06_runtime.releases import ReleaseBindings
from tools.imp06_runtime.routes import inbound, outbound


def test_absent_evaluated_release_cannot_construct_inference_listener():
    bindings = ReleaseBindings(None, (), lambda: False)
    assert not bindings.admitted("worker_summary")
    counterless_tls = ssl.create_default_context()
    with pytest.raises(ManualError, match="function_disabled"):
        inference_application(
            bindings,
            data_tls=counterless_tls,
            bridge_tls=counterless_tls,
            verify=lambda _request, _role: True,
        )


def test_workload_graph_has_no_runtime_inference_or_model_route():
    assert set(outbound("runtime")) == {"core"}
    assert set(outbound("inference")) == {"data", "host-inference-bridge"}
    assert [peer.spiffe_id for peer in inbound("inference")] == [
        "spiffe://care-link.demo/demo/core"
    ]
    assert [peer.spiffe_id for peer in inbound("host-inference-bridge")] == [
        "spiffe://care-link.demo/demo/inference"
    ]
    assert not any(
        "stop" in path or "reset" in path
        for peer in inbound("data")
        for _method, path in peer.routes
    )


def test_runtime_revoked_during_inference_cannot_receive_completed_proposal():
    app = FastAPI()
    broker = create_autospec(InferenceBroker, instance=True)
    fixture = json.loads(
        (Path(__file__).parents[2] / "doc/LLD/contracts/fixtures.json").read_text()
    )
    result = next(
        row["value"] for row in fixture["fixtures"] if row["id"] == "shape-InferenceResult"
    )
    broker.infer.return_value = result
    peer = WorkloadPeer(
        "spiffe://care-link.demo/demo/runtime",
        1,
        "a" * 64,
        datetime.now(UTC) + timedelta(minutes=1),
    )
    verify = Mock(side_effect=[peer, ManualError("assistance.runtime_required", 403)])

    async def denied(_request, error):
        return JSONResponse({"reason": error.code}, status_code=error.status)

    app.add_exception_handler(ManualError, denied)
    attach_broker_routes(app, broker, verify)
    response = TestClient(app).post(
        "/internal/v1/broker/inference",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "task_id": str(uuid4()),
            "step_id": str(uuid4()),
            "fence": "1",
            "expected_task_revision": "1",
        },
    )
    assert response.status_code == 403
    assert "proposal" not in response.json()
    assert verify.call_count == 2
    broker.infer.assert_called_once()


def test_runtime_poll_transport_reaches_the_real_broker_claim_route():
    app = FastAPI()
    broker = create_autospec(InferenceBroker, instance=True)
    broker.claim_work.return_value = {"task_id": None, "task_revision": None, "fence": None}
    peer = WorkloadPeer(
        "spiffe://care-link.demo/demo/runtime",
        1,
        "a" * 64,
        datetime.now(UTC) + timedelta(minutes=1),
    )
    attach_broker_routes(app, broker, lambda _request: peer)

    async def denied(_request, error):
        return JSONResponse({"reason": error.code}, status_code=error.status)

    app.add_exception_handler(ManualError, denied)
    keys: list[str] = []
    with TestClient(app) as listener:

        def relay(request: httpx.Request) -> httpx.Response:
            keys.append(request.headers.get("idempotency-key", ""))
            response = listener.post(
                request.url.path, content=request.content, headers=request.headers
            )
            return httpx.Response(response.status_code, content=response.content)

        transport = HttpBrokerTransport(
            ssl.create_default_context(), transport=httpx.MockTransport(relay)
        )
        try:
            assert transport.poll_work()["task_id"] is None
            assert transport.poll_work()["task_id"] is None
        finally:
            transport.close()
    assert keys[0] != keys[1]
    assert broker.claim_work.call_count == 2
