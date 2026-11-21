"""Real Ed25519 signatures across HTTP adapters; authority doubles are explicit."""

import json
from datetime import timedelta
from uuid import uuid4

import httpx
from care_link_core.assistance_broker.remote import HttpCoordinator, TaskDelegationSigner
from care_link_data.assistance_transport import RuntimeAuthenticator
from care_link_domain import ManualError, WorkloadPeer
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from services.core.tests.test_manual_envelopes import fixture


def test_signed_task_delegation_binds_human_runtime_task_and_entire_payload():
    factory, actor, verifier, *_rest, now, identity = fixture()
    peer = WorkloadPeer(
        "spiffe://care-link.demo/demo/runtime", 1, "a" * 64, now[0] + timedelta(minutes=1)
    )
    signer = TaskDelegationSigner(identity, factory.key, clock=lambda: now[0])
    authenticated = RuntimeAuthenticator(
        verifier, lambda _request, role: role == "core", lambda p: p == peer, clock=lambda: now[0]
    )
    task_id = str(uuid4())
    body = {"expected_revision": "1", "step_id": str(uuid4()), "fence": "0"}
    path = "/internal/v1/data/assistance/step_lease/" + task_id
    headers = signer.headers(actor, "step_lease", task_id, body, peer, path)
    assert actor.credential_ref not in headers["X-Assistance-Delegation"]
    app = FastAPI()

    async def handler(request: Request):
        try:
            current, runtime = await authenticated(
                request, "step_lease", request.path_params["task_id"]
            )
            return JSONResponse({"principal": current.account_id, "runtime": runtime.workload_id})
        except ManualError:
            return JSONResponse({}, status_code=403)

    app.add_api_route(
        "/internal/v1/data/assistance/step_lease/{task_id}", handler, methods=["POST"]
    )
    client = TestClient(app)
    assert client.post(path, json=body, headers=headers).json()["principal"] == actor.account_id
    assert client.post(path, json={**body, "fence": "1"}, headers=headers).status_code == 403
    wrong_runtime = {
        **headers,
        "X-Assistance-Runtime": headers["X-Assistance-Runtime"].replace("a" * 64, "b" * 64),
    }
    assert client.post(path, json=body, headers=wrong_runtime).status_code == 403
    assert (
        client.post(path.replace(task_id, str(uuid4())), json=body, headers=headers).status_code
        == 403
    )
    authenticated.runtime_current = lambda _: False
    assert client.post(path, json=body, headers=headers).status_code == 403


def test_http_coordinator_uses_fixed_destination_signed_no_actor_body():
    factory, actor, _verifier, *_rest, now, identity = fixture()
    signer = TaskDelegationSigner(identity, factory.key, clock=lambda: now[0])
    peer = WorkloadPeer(
        "spiffe://care-link.demo/demo/runtime", 1, "a" * 64, now[0] + timedelta(minutes=1)
    )
    task_id, step_id = str(uuid4()), str(uuid4())
    calls = []

    def serve(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "task_id": task_id,
                "step_id": step_id,
                "fence": "1",
                "expires_at": (now[0] + timedelta(seconds=10)).isoformat().replace("+00:00", "Z"),
                "task_revision": "1",
            },
        )

    class Reader:
        def task_read(self, _actor, _task_id):
            raise AssertionError("not used")

    client = httpx.Client(
        transport=httpx.MockTransport(serve), trust_env=False, follow_redirects=False
    )
    remote = HttpCoordinator(client, signer, Reader())
    result = remote.step_lease(
        actor, task_id, {"expected_revision": "1", "step_id": step_id, "fence": "0"}, peer
    )
    assert result["fence"] == "1"
    assert (
        str(calls[0].url) == "https://data:8443/internal/v1/data/assistance/step_lease/" + task_id
    )
    assert set(json.loads(calls[0].content)) == {"expected_revision", "step_id", "fence"}
    client.close()
