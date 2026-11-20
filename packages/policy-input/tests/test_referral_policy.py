"""Real OPA checks for exact referral consent/review and fixed exclusions."""

import base64
import hashlib
import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from care_link_contracts import ContractError
from care_link_policy_input import OpaPolicy
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[3]
SOURCE = (ROOT / "config/demo/imp05/policy/manual.rego").read_bytes()


def stamp(value):
    return value.isoformat().replace("+00:00", "Z")


def request_for(action="dispatcher_send"):
    now = datetime.now(UTC)
    actor, subject, session, recipient, consent, review = [str(uuid4()) for _ in range(6)]
    versions = dict.fromkeys(
        [
            "identity",
            "roles",
            "subject",
            "session_access",
            "assignment",
            "resource",
            "directory",
            "policy_epoch",
            "control_epoch",
            "serving_generation",
            "restriction_barrier",
        ],
        "1",
    )
    return {
        "operation_id": str(uuid4()),
        "actor": {
            "kind": "human",
            "principal_id": actor,
            "workload_id": "spiffe://care-link.demo/demo/data",
            "role": "worker",
            "assurance": "AL2",
            "identity_evidence_id": str(uuid4()),
            "task_id": None,
            "job_id": None,
        },
        "action": action,
        "scope": {
            "session_id": session,
            "subject_id": subject,
            "purpose": "referral",
            "fields": ["needs", "preferences"],
            "recipient_id": recipient,
        },
        "tags": {"environment": "demo", "population": "synthetic"},
        "jurisdiction": None,
        "versions": versions,
        "payload_digest": "a" * 64,
        "referral_payload_digest": "b" * 64,
        "consent_id": consent,
        "review_id": review,
        "bundle_digest": hashlib.sha256(SOURCE).hexdigest(),
        "artifact_digests": ["c" * 64],
        "mode": "ai_disabled",
        "audit_ready": True,
        "authority_complete": True,
        "directory_bindings": [
            {
                "service_id": recipient,
                "revision": "1",
                "artifact_digest": "c" * 64,
                "suspended": False,
                "current": True,
            }
        ],
        "authority_facts": {
            **dict.fromkeys(
                [
                    "actor_role_allowed",
                    "resource_owned_or_assigned",
                    "field_scope_allowed",
                    "source_current",
                    "artifact_admitted",
                    "jurisdiction_allowed",
                    "workload_unfenced",
                ],
                True,
            ),
            "consent": {
                "required": True,
                "valid": True,
                "grant_id": consent,
                "subject_revision": "1",
                "scope_digest": "d" * 64,
                "effective_at": stamp(now - timedelta(seconds=1)),
                "expires_at": stamp(now + timedelta(minutes=10)),
                "recipient_id": recipient,
                "fields": ["needs", "preferences"],
                "subject_id": subject,
                "session_id": session,
                "purpose": "referral",
            },
            "review": {
                "required": True,
                "valid": True,
                "review_id": review,
                "payload_digest": "b" * 64,
                "reviewer_id": actor,
                "expires_at": stamp(now + timedelta(minutes=3)),
            },
            "exception_id": None,
            "exception_expires_at": None,
        },
    }


@pytest.fixture(scope="module")
def policy():
    executable = os.environ.get("CARE_LINK_OPA_BINARY")
    if not executable:
        pytest.skip("Pinned OPA fixture explicitly required for referral policy qualification")
    key = Ed25519PrivateKey.generate()
    binary = Path(executable)
    with binary.open("rb") as stream:
        executable_digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return OpaPolicy(
        binary,
        executable_digest,
        SOURCE,
        base64.b64encode(key.sign(SOURCE)).decode(),
        key.public_key(),
    )


@pytest.mark.parametrize(
    "action", ["referral_dispatch", "dispatcher_send", "dispatch_authorize", "dispatch_consume"]
)
def test_current_human_exact_consent_and_review_can_authorize(policy, action):
    assert policy.evaluate(request_for(action))["decision"] == "PERMIT"


@pytest.mark.parametrize(
    "path,value",
    [
        (("actor", "role"), "receiver"),
        (("actor", "role"), "operator"),
        (("actor", "assurance"), "AL1"),
        (("actor", "workload_id"), "spiffe://care-link.demo/demo/runtime"),
        (("mode",), "restricted"),
        (("mode",), "quarantine"),
        (("audit_ready",), False),
        (("authority_complete",), False),
        (("scope", "purpose"), "support"),
        (("scope", "purpose"), "security"),
        (("scope", "fields"), []),
        (("scope", "recipient_id"), str(uuid4())),
        (("scope", "session_id"), str(uuid4())),
        (("scope", "subject_id"), str(uuid4())),
        (("authority_facts", "resource_owned_or_assigned"), False),
        (("authority_facts", "field_scope_allowed"), False),
        (("authority_facts", "source_current"), False),
        (("authority_facts", "artifact_admitted"), False),
        (("authority_facts", "workload_unfenced"), False),
        (("authority_facts", "consent", "required"), False),
        (("authority_facts", "consent", "valid"), False),
        (("authority_facts", "consent", "grant_id"), str(uuid4())),
        (("authority_facts", "consent", "subject_revision"), "2"),
        (("authority_facts", "consent", "fields"), ["needs"]),
        (("authority_facts", "consent", "purpose"), "plan"),
        (("authority_facts", "consent", "effective_at"), "2099-01-01T00:00:00Z"),
        (("authority_facts", "consent", "expires_at"), "2000-01-01T00:00:00Z"),
        (("authority_facts", "review", "required"), False),
        (("authority_facts", "review", "valid"), False),
        (("authority_facts", "review", "review_id"), str(uuid4())),
        (("authority_facts", "review", "reviewer_id"), str(uuid4())),
        (("authority_facts", "review", "payload_digest"), "e" * 64),
        (("authority_facts", "review", "expires_at"), "2000-01-01T00:00:00Z"),
        (("directory_bindings",), []),
        (("artifact_digests",), []),
    ],
)
def test_stale_or_mismatched_authority_cannot_send(policy, path, value):
    request = request_for()
    target = request
    for name in path[:-1]:
        target = target[name]
    target[path[-1]] = value
    assert policy.evaluate(request)["decision"] == "DENY"


@pytest.mark.parametrize(
    "field", ["suspended", "current", "revision", "service_id", "artifact_digest"]
)
def test_directory_binding_is_current_exact_and_unsuspended(policy, field):
    request = request_for()
    request["directory_bindings"][0][field] = {
        "suspended": True,
        "current": False,
        "revision": "2",
        "service_id": str(uuid4()),
        "artifact_digest": "e" * 64,
    }[field]
    assert policy.evaluate(request)["decision"] == "DENY"


@pytest.mark.parametrize(
    "action", ["dispatch_read", "receipt_read", "dispatch_reconcile", "dispatch_observe"]
)
def test_honest_status_and_reconciliation_survive_revoked_send_permission(policy, action):
    request = request_for(action)
    request["authority_facts"]["consent"]["required"] = False
    request["authority_facts"]["consent"]["valid"] = False
    request["authority_facts"]["review"]["required"] = False
    request["authority_facts"]["review"]["valid"] = False
    request["authority_facts"]["source_current"] = False
    request["directory_bindings"][0]["suspended"] = True
    assert policy.evaluate(request)["decision"] == "PERMIT"
    denied = deepcopy(request)
    denied["authority_facts"]["resource_owned_or_assigned"] = False
    assert policy.evaluate(denied)["decision"] == "DENY"


@pytest.mark.parametrize(
    "action", ["referral_sources", "referral_draft", "referral_read", "referral_context"]
)
def test_unsent_work_is_separate_from_service_disclosure_consent(policy, action):
    request = request_for(action)
    request["authority_facts"]["consent"]["required"] = False
    request["authority_facts"]["consent"]["valid"] = False
    request["authority_facts"]["review"]["required"] = False
    request["authority_facts"]["review"]["valid"] = False
    assert policy.evaluate(request)["decision"] == "PERMIT"


@pytest.mark.parametrize(
    "action", ["contact_police", "emergency_dispatch", "simulator_send", "receiver_decide"]
)
def test_no_new_machine_contact_or_receiver_authority(policy, action):
    request = request_for(action)
    assert policy.evaluate(request)["decision"] == "DENY"


def test_real_population_rejected_before_policy(policy):
    request = request_for()
    request["tags"]["population"] = "real"
    with pytest.raises(ContractError):
        policy.evaluate(request)


@pytest.mark.parametrize(
    "action", ["referral_review", "referral_dispatch", "dispatcher_send", "dispatch_authorize"]
)
def test_valid_workload_shape_cannot_supply_human_approval(policy, action):
    request = request_for(action)
    request["actor"] = {
        "kind": "workload",
        "actor_id": str(uuid4()),
        "workload_id": "spiffe://care-link.demo/demo/runtime",
        "duty_id": str(uuid4()),
        "job_id": None,
        "task_id": str(uuid4()),
        "originating_human_id": request["actor"]["principal_id"],
    }
    assert policy.evaluate(request)["decision"] == "DENY"


@pytest.mark.parametrize("kind,minutes", [("consent", 16), ("review", 6)])
def test_oversized_human_authority_interval_cannot_send(policy, kind, minutes):
    request = request_for()
    request["authority_facts"][kind]["expires_at"] = stamp(
        datetime.now(UTC) + timedelta(minutes=minutes)
    )
    assert policy.evaluate(request)["decision"] == "DENY"


def test_own_participant_read_can_use_al1_but_never_review_or_send(policy):
    request = request_for("referral_read")
    request["actor"]["role"] = "pid"
    request["actor"]["assurance"] = "AL1"
    request["authority_facts"]["consent"]["required"] = False
    request["authority_facts"]["review"]["required"] = False
    assert policy.evaluate(request)["decision"] == "PERMIT"
    request["action"] = "referral_dispatch"
    assert policy.evaluate(request)["decision"] == "DENY"
