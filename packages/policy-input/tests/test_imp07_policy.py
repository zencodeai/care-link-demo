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
    source = (ROOT / "config/demo/imp07/policy/manual.rego").read_bytes()
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
        role="pid",
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
    "action,purpose,role",
    [
        ("followup_read", "follow_up", "pid"),
        ("followup_cancel", "follow_up", "worker"),
        ("participant_inbox", "follow_up", "carer"),
        ("outcomes_read", "support", "worker"),
        ("rights_create", "rights", "pid"),
        ("rights_read", "rights", "carer"),
        ("export_download", "rights", "pid"),
        ("hold_create", "rights", "governance"),
        ("hold_release", "rights", "governance"),
    ],
)
def test_new_actions_require_exact_current_scope(policy, action, purpose, role):
    value = request(policy, action)
    value["actor"]["role"] = role
    value["scope"]["purpose"] = purpose
    assert policy.evaluate(value)["decision"] == "PERMIT"
    value["authority_facts"]["resource_owned_or_assigned"] = False
    assert policy.evaluate(value)["decision"] == "DENY"


@pytest.mark.parametrize(
    "change",
    [
        "wrong_role",
        "wrong_purpose",
        "workload",
        "fenced",
        "incomplete",
        "no_audit",
        "low_assurance",
    ],
)
def test_rights_preflight_is_not_ambient_authority(policy, change):
    value = request(policy, "rights_create")
    value["scope"]["purpose"] = "rights"
    if change == "wrong_role":
        value["actor"]["role"] = "worker"
    elif change == "wrong_purpose":
        value["scope"]["purpose"] = "support"
    elif change == "workload":
        value["actor"]["workload_id"] = "spiffe://care-link.demo/demo/runtime"
    elif change == "fenced":
        value["authority_facts"]["workload_unfenced"] = False
    elif change == "incomplete":
        value["authority_complete"] = False
    elif change == "no_audit":
        value["audit_ready"] = False
    else:
        value["actor"]["assurance"] = "AL1"
    assert policy.evaluate(value)["decision"] == "DENY"


@pytest.mark.parametrize("action", ["followup_create", "followup_bind_anchor"])
def test_contact_authorization_binds_exact_subject_session_recipient_and_revision(policy, action):
    value = request(policy, action)
    value["scope"].update(
        purpose="follow_up",
        subject_id=value["actor"]["principal_id"],
        recipient_id=value["actor"]["principal_id"],
    )
    grant_id = value["actor"]["principal_id"]
    value["consent_id"] = grant_id
    value["authority_facts"]["consent"].update(
        required=True,
        valid=True,
        grant_id=grant_id,
        subject_revision=value["versions"]["subject"],
        scope_digest="a" * 64,
        effective_at="2026-11-21T00:00:00Z",
        expires_at="2026-11-22T00:00:00Z",
        recipient_id=value["scope"]["recipient_id"],
        fields=["summary"],
        subject_id=value["scope"]["subject_id"],
        session_id=value["scope"]["session_id"],
        purpose="follow_up",
    )
    assert policy.evaluate(value)["decision"] == "PERMIT"
    value["authority_facts"]["consent"]["purpose"] = "referral"
    assert policy.evaluate(value)["decision"] == "DENY"


@pytest.mark.parametrize("purpose", ["rights", "follow_up", "support"])
def test_lifecycle_workload_uses_its_exact_canonical_purpose(policy, purpose):
    value = request(policy, "lifecycle_due")
    fixtures = json.loads((ROOT / "doc/LLD/contracts/fixtures.json").read_text())["fixtures"]
    value["actor"] = next(row["value"] for row in fixtures if row["id"] == "shape-WorkloadActor")
    value["actor"].update(
        workload_id="spiffe://care-link.demo/demo/jobs",
        job_id=None,
        task_id=None,
        originating_human_id=None,
    )
    value["scope"].update(
        purpose=purpose, session_id=None, subject_id=None, fields=[], recipient_id=None
    )
    value["artifact_digests"] = ["a" * 64]
    assert policy.evaluate(value)["decision"] == ("PERMIT" if purpose == "rights" else "DENY")
