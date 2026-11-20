"""Signed receiver trust boundary and uncertain transport results; no live workload claim."""

import base64
import copy
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import create_autospec
from uuid import uuid4

import httpx
import pytest
from care_link_core.receiver_http import HttpReceiverGateway
from care_link_data.referral_http import HttpReceiverPort
from care_link_data.referral_mapping import SimulatorMapping
from care_link_domain import Actor, ManualError
from care_link_simulators import ReceiverService
from care_link_simulators.app import create_app
from care_link_simulators.security import ReceiverIdentity
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def example(name):
    rows = json.loads((ROOT / "doc/LLD/contracts/fixtures.json").read_text())["fixtures"]
    return copy.deepcopy(next(row["value"] for row in rows if row["id"] == "shape-" + name))


@pytest.fixture
def actor():
    now = datetime.now(UTC)
    return Actor(
        str(uuid4()),
        "receiver",
        1,
        1,
        now,
        True,
        "a" * 64,
        1,
        "private",
        now + timedelta(hours=1),
        str(uuid4()),
    )


class Evidence:
    def __init__(self, key, actor):
        self.key, self.actor = key, actor

    def evidence(self, actor, action, request_digest, nonce, resource):
        now = datetime.now(UTC)
        proof = {
            "id": str(uuid4()),
            "principal_id": actor.account_id,
            "role": actor.role,
            "identity_revision": "1",
            "role_revision": "1",
            "action": action,
            "resource_id": resource,
            "request_digest": request_digest,
            "nonce": nonce,
            "verified_at": now.isoformat().replace("+00:00", "Z"),
            "expires_at": (now + timedelta(seconds=0.9)).isoformat().replace("+00:00", "Z"),
            "kind": "human_identity",
        }
        proof["signature"] = (
            base64.urlsafe_b64encode(self.key.sign(canonical(proof))).rstrip(b"=").decode()
        )
        return proof


def test_signed_receiver_human_roundtrip_and_tampering(actor):
    core_key, identity_key = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()

    def current(proof):
        return replace(actor, identity_evidence_id=proof["id"])

    verifier = ReceiverIdentity(core_key.public_key(), identity_key.public_key(), current)
    service = create_autospec(ReceiverService, instance=True)
    payload, receipt = example("ReferralPayload"), example("ReceiptView")
    service.receiver_detail.return_value = {"payload": payload, "revision": "1", "receipt": receipt}
    receiver = TestClient(
        create_app(service, verifier, lambda request, peer: request.headers.get("x-peer") == peer)
    )
    captured = []

    def route(request):
        body = json.loads(request.content)
        captured.append(body)
        reply = receiver.post(
            request.url.path,
            json=body,
            headers={"x-peer": "core", "Idempotency-Key": request.headers["idempotency-key"]},
        )
        return httpx.Response(reply.status_code, json=reply.json())

    gateway = HttpReceiverGateway(
        httpx.Client(transport=httpx.MockTransport(route)),
        "https://receiver.test",
        Evidence(identity_key, actor),
        core_key,
    )
    result = gateway.receiver_detail(actor, receipt["dispatch_id"])
    assert result["revision"] == "1"
    assert service.receiver_detail.call_count == 1
    wire = captured[-1]
    key = wire["operation_id"]
    changed = copy.deepcopy(wire)
    changed["path_arguments"]["dispatch_id"] = str(uuid4())
    path = "/internal/v1/receiver/receiver_detail"
    assert (
        receiver.post(
            path, json=changed, headers={"x-peer": "core", "Idempotency-Key": key}
        ).status_code
        == 403
    )
    assert (
        receiver.post(
            path, json=wire, headers={"x-peer": "data", "Idempotency-Key": key}
        ).status_code
        == 403
    )
    assert (
        receiver.post(
            path, json=wire, headers={"x-peer": "core", "Idempotency-Key": str(uuid4())}
        ).status_code
        == 403
    )
    assert service.receiver_detail.call_count == 1
    # Same signed bytes cannot impersonate the data-only send workload.
    assert (
        receiver.post("/internal/v1/receiver/send", json={}, headers={"x-peer": "core"}).status_code
        == 403
    )


@pytest.mark.parametrize("kind", ["bad_json", "wrong_media", "oversized", "reset", "status"])
def test_data_adapter_uncertain_wire_never_returns_a_receipt(kind):
    payload = example("SimulatorSend")
    service_id = payload["payload"]["recipient_service_id"]

    def route(request):
        if kind == "reset":
            raise httpx.ReadError("lost reply", request=request)
        return httpx.Response(
            503 if kind == "status" else 200,
            content=b"x" * 65537 if kind == "oversized" else b"{}",
            headers={"Content-Type": "text/html" if kind == "wrong_media" else "application/json"},
        )

    port = HttpReceiverPort(
        httpx.Client(transport=httpx.MockTransport(route)),
        "https://receiver.test",
        frozenset({service_id}),
    )
    with pytest.raises(ConnectionError):
        port.send(service_id, payload)


def test_signed_mapping_rejects_changed_target_and_empty_host():
    key = Ed25519PrivateKey.generate()
    mapping = {
        "key_id": "technical",
        "revision": 1,
        "origin": "https://receiver.test",
        "service_ids": [str(uuid4())],
        "workload_id": "spiffe://care-link.demo/demo/receiver",
        "tags": {"environment": "demo", "population": "synthetic"},
    }
    mapping["signature"] = base64.b64encode(key.sign(canonical(mapping))).decode()
    admitted = SimulatorMapping.verify(mapping, {"technical": key.public_key()})
    assert admitted.origin == "https://receiver.test"
    changed = {**mapping, "origin": "https://elsewhere.test"}
    with pytest.raises(ValueError):
        SimulatorMapping.verify(changed, {"technical": key.public_key()})
    empty = {**mapping, "origin": "https://"}
    empty["signature"] = base64.b64encode(
        key.sign(canonical({k: v for k, v in empty.items() if k != "signature"}))
    ).decode()
    with pytest.raises(ValueError):
        SimulatorMapping.verify(empty, {"technical": key.public_key()})


def test_human_mutation_invalid_reply_is_unknown(actor):
    core_key, identity_key = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    )
    gateway = HttpReceiverGateway(
        client, "https://receiver.test", Evidence(identity_key, actor), core_key
    )
    with pytest.raises(ManualError, match="receiver_result_unknown"):
        gateway.receiver_decide(actor, str(uuid4()), example("ReceiverDecision"))
