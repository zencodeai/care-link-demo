"""Real signed identity, named HTTP, pinned OPA and PostgreSQL governance boundary.

OIDC provider, identity persistence and mesh connections are synthetic in-process
fixtures; current identity logic, signatures, closed contracts and policy are real.
"""

import base64
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import httpx
import psycopg
import pytest
from care_link_core.governance_http import HttpGovernanceGateway
from care_link_core.manual_envelopes import SignedEnvelopeFactory
from care_link_core.manual_identity import HttpManualIdentity
from care_link_data.app import SignedGatewaySecurity, create_app
from care_link_domain import ManualError
from care_link_identity import Custody, IdentityService, ReceiptSigner
from care_link_identity.manual_runtime import create_manual_identity_app
from care_link_policy_input import DelegationVerifier, OpaPolicy
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from test_imp08_controls import key, provision_human, signed_candidate

from services.identity.tests.conftest import Clock, FakeProvider, MemoryStore, signed_in

ROOT = Path(__file__).resolve().parents[3]


def test_exact_artifact_through_current_signed_identity_policy_gateway(harness):
    binary = os.environ.get("CARE_LINK_OPA_BINARY")
    if not binary:
        pytest.skip("Explicit pinned OPA required")
    h = harness
    clock, storage = Clock(), MemoryStore()
    provider = FakeProvider(clock)
    identity_key, core_key, signing_key = [Ed25519PrivateKey.generate() for _ in range(3)]
    identity = IdentityService(
        storage,
        provider,
        Custody(Fernet.generate_key()),
        ReceiptSigner(identity_key, "synthetic"),
        "https://issuer.test",
        "https://app.test",
        clock,
    )
    identity.provision(provider.subject, h.operator.account_id, ["operator"])
    raw = signed_in(identity, role="operator")
    identity_client = TestClient(
        create_manual_identity_app(
            identity, lambda request, peer: request.headers.get("x-peer") == peer
        )
    )

    def identity_transport(request):
        name = request.url.path.rsplit("/", 1)[-1]
        result = identity_client.post(
            request.url.path,
            content=request.content,
            headers={
                "Content-Type": "application/json",
                "x-peer": "core" if name in {"authenticate", "evidence", "csrf"} else "data",
            },
        )
        return httpx.Response(result.status_code, json=result.json())

    remote = HttpManualIdentity(
        httpx.Client(transport=httpx.MockTransport(identity_transport)),
        "https://identity.test",
        identity_key.public_key(),
    )
    actor = replace(remote.authenticate(raw), transport_generation=1)
    provision_human(h, actor)
    source = (ROOT / "config/demo/imp08/policy/manual.rego").read_bytes()
    policy = OpaPolicy(
        Path(binary),
        hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
        source,
        base64.b64encode(signing_key.sign(source)).decode(),
        signing_key.public_key(),
    )
    h.service.authority, h.service.policy = remote, policy
    with psycopg.connect(h.database.admin) as connection:
        connection.execute("UPDATE control.guard SET bundle_digest=%s", (policy.bundle_digest,))
    verifier = DelegationVerifier(core_key.public_key(), identity_key.public_key(), remote.resolve)
    data_app = TestClient(
        create_app(
            h.service,
            SignedGatewaySecurity(
                verifier, lambda request, peer: request.headers.get("x-peer") == peer
            ),
        )
    )
    calls = []

    def data_transport(request):
        calls.append((request.url.path, json.loads(request.content)))
        result = data_app.post(
            request.url.path,
            content=request.content,
            headers={
                "Content-Type": "application/json",
                "x-peer": "core",
                "Idempotency-Key": request.headers["idempotency-key"],
            },
        )
        return httpx.Response(result.status_code, json=result.json())

    client = httpx.Client(transport=httpx.MockTransport(data_transport))
    gateway = HttpGovernanceGateway(
        client,
        "https://data.test",
        SignedEnvelopeFactory(client, "https://data.test", remote, policy, core_key),
    )
    candidate = signed_candidate(h)
    registered = gateway.artifact_register(actor, key(), candidate)
    assert registered["digest"] == candidate["digest"]
    context = gateway.artifact_context(actor, candidate["digest"])
    assert context["payload_digest"] == candidate["digest"]
    assert set(context["missing_authorities"]) == {"technical", "operations", "security"}
    assert calls[-2][1]["planning"]["path_arguments"] == {"artifact_digest": candidate["digest"]}
    path, envelope = calls[-1]
    envelope["path_arguments"]["artifact_digest"] = "0" * 64
    tampered = data_app.post(
        path,
        json=envelope,
        headers={"x-peer": "core", "Idempotency-Key": envelope["delegation"]["id"]},
    )
    assert tampered.status_code == 403
    provider.is_active = False
    with pytest.raises(ManualError):
        gateway.artifact_context(actor, candidate["digest"])
