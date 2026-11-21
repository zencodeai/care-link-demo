"""Sequential synthetic source latency sample; no deployed workload/SLO claim."""

import base64
import hashlib
import os
import time
from pathlib import Path

import psycopg
import pytest
from care_link_policy_input import OpaPolicy
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from test_imp08_controls import provision_human


def test_governance_authorization_latency_sample(harness, record_property):
    binary = os.environ.get("CARE_LINK_OPA_BINARY")
    if not binary:
        pytest.skip("Explicit pinned OPA required")
    h = harness
    provision_human(h, h.operator)
    source = (
        Path(__file__).resolve().parents[3] / "config/demo/imp08/policy/manual.rego"
    ).read_bytes()
    signer = Ed25519PrivateKey.generate()
    pdp_ms = []

    class MeasuredPolicy(OpaPolicy):
        def evaluate(self, request):
            started = time.perf_counter()
            result = super().evaluate(request)
            pdp_ms.append((time.perf_counter() - started) * 1000)
            return result

    policy = MeasuredPolicy(
        Path(binary),
        hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
        source,
        base64.b64encode(signer.sign(source)).decode(),
        signer.public_key(),
    )
    h.service.policy = policy
    with psycopg.connect(h.database.admin) as connection:
        connection.execute("UPDATE control.guard SET bundle_digest=%s", (policy.bundle_digest,))
    elapsed_ms = []
    for _ in range(30):
        started = time.perf_counter()
        h.service.health_read(h.operator)
        elapsed_ms.append((time.perf_counter() - started) * 1000)
    pdp_p95 = sorted(pdp_ms)[28]
    record_property(
        "workload",
        "30 sequential synthetic governance health authorizations; "
        "local TLS PostgreSQL and pinned OPA",
    )
    record_property("pdp_p95_ms", round(pdp_p95, 3))
    record_property("authorization_p95_ms", round(sorted(elapsed_ms)[28], 3))
    record_property("authorization_max_ms", round(max(elapsed_ms), 3))
    assert pdp_p95 <= 50
    assert max(pdp_ms) <= 200
    assert max(elapsed_ms) <= 1000
