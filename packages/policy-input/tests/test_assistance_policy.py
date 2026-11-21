"""Actual pinned OPA for assistance preflight; engine still makes final admission."""

import base64
import hashlib
import json
import os
from pathlib import Path

import pytest
from care_link_policy_input import OpaPolicy
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def policy():
    executable = os.environ.get("CARE_LINK_OPA_BINARY")
    if not executable:
        pytest.skip("Explicit pinned OPA binary required")
    source = (ROOT / "config/demo/imp06/policy/manual.rego").read_bytes()
    key = Ed25519PrivateKey.generate()
    return OpaPolicy(
        Path(executable),
        hashlib.sha256(Path(executable).read_bytes()).hexdigest(),
        source,
        base64.b64encode(key.sign(source)).decode(),
        key.public_key(),
    )


def request(policy, action):
    fixtures = json.loads((ROOT / "doc/LLD/contracts/fixtures.json").read_text())["fixtures"]
    value = next(row["value"] for row in fixtures if row["id"] == "shape-PolicyInput")
    value.update(
        action=action,
        bundle_digest=policy.bundle_digest,
        audit_ready=True,
        authority_complete=True,
        consent_id=None,
        review_id=None,
        jurisdiction=None,
    )
    value["actor"].update(
        role="worker",
        assurance="AL2",
        task_id=None,
        job_id=None,
        workload_id="spiffe://care-link.demo/demo/data",
    )
    value["scope"].update(purpose="support", recipient_id=None)
    for name, fact in value["authority_facts"].items():
        if isinstance(fact, bool):
            value["authority_facts"][name] = True
    value["authority_facts"].update(exception_id=None, exception_expires_at=None)
    return value


@pytest.mark.parametrize(
    "action",
    [
        "task_create",
        "task_read",
        "task_revise",
        "task_cancel",
        "draft_read",
        "draft_review",
        "assistance_task_context",
        "assistance_draft_context",
    ],
)
def test_only_exact_current_session_scope_can_reach_assistance_preflight(policy, action):
    value = request(policy, action)
    assert policy.evaluate(value)["decision"] == "PERMIT"
    value["authority_facts"]["resource_owned_or_assigned"] = False
    assert policy.evaluate(value)["decision"] == "DENY"


@pytest.mark.parametrize("change", ["role", "workload", "purpose", "fenced", "disabled"])
def test_runtime_or_stale_governance_cannot_create_a_human_task(policy, change):
    value = request(policy, "task_create")
    if change == "role":
        value["actor"]["role"] = "operator"
    elif change == "workload":
        value["actor"]["workload_id"] = "spiffe://care-link.demo/demo/runtime"
    elif change == "purpose":
        value["scope"]["purpose"] = "referral"
    elif change == "fenced":
        value["authority_facts"]["workload_unfenced"] = False
    else:
        value["mode"] = "ai_disabled"
    assert policy.evaluate(value)["decision"] == "DENY"
