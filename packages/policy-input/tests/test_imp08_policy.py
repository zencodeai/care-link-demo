"""Pinned OPA governance role/purpose/mode negatives and exact evaluator selection."""

import base64
import hashlib
import os
from pathlib import Path

import pytest
from care_link_domain import ManualError
from care_link_policy_input import GovernedPolicies, OpaPolicy
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from test_imp07_policy import request

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def policy():
    binary = os.environ.get("CARE_LINK_OPA_BINARY")
    if not binary:
        pytest.skip("Explicit pinned OPA required")
    source = (ROOT / "config/demo/imp08/policy/manual.rego").read_bytes()
    key = Ed25519PrivateKey.generate()
    return OpaPolicy(
        Path(binary),
        hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
        source,
        base64.b64encode(key.sign(source)).decode(),
        key.public_key(),
    )


@pytest.mark.parametrize(
    "action,purpose,role",
    [
        ("artifact_register", "governance", "operator"),
        ("artifact_review", "governance", "governance"),
        ("artifact_context", "governance", "security"),
        ("activation_create", "governance", "operator"),
        ("activation_commit", "governance", "operator"),
        ("exception_create", "governance", "governance"),
        ("incident_transition", "security", "security"),
        ("audit_query", "audit", "auditor"),
        ("metrics_query", "audit", "supervisor"),
        ("health_read", "service_operations", "operator"),
    ],
)
def test_governance_requires_exact_role_purpose_current_facts_in_restricted_modes(
    policy, action, purpose, role
):
    value = request(policy, action)
    value["actor"]["role"] = role
    value["scope"]["purpose"] = purpose
    value["mode"] = "quarantine"
    assert policy.evaluate(value)["decision"] == "PERMIT"
    value["scope"]["purpose"] = "support"
    assert policy.evaluate(value)["decision"] == "DENY"
    value["scope"]["purpose"] = purpose
    value["actor"]["role"] = "pid"
    assert policy.evaluate(value)["decision"] == "DENY"
    value["actor"]["role"] = role
    value["authority_facts"]["workload_unfenced"] = False
    assert policy.evaluate(value)["decision"] == "DENY"


def test_evaluator_selection_cannot_fall_back_to_old_or_unsigned_bundle(policy):
    registry = GovernedPolicies([policy])
    value = request(policy, "health_read")
    value["actor"]["role"] = "operator"
    value["scope"]["purpose"] = "service_operations"
    assert registry.evaluate(value)["decision"] == "PERMIT"
    value["bundle_digest"] = "0" * 64
    with pytest.raises(ManualError, match="bundle_not_staged"):
        registry.evaluate(value)
    policy.source += b"\n# modified after staging\n"
    value["bundle_digest"] = policy.bundle_digest
    with pytest.raises(ManualError, match="integrity"):
        registry.evaluate(value)
