import base64
import hashlib
import json
import os
import tracemalloc
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch
from uuid import uuid4

import pytest
from care_link_domain import ManualError
from care_link_policy_input import OpaPolicy
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[3]
SOURCE = (ROOT / "config/demo/imp03/policy/manual.rego").read_bytes()


def policy_request():
    revisions = dict.fromkeys(
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
            "principal_id": str(uuid4()),
            "workload_id": "spiffe://care-link.demo/demo/data",
            "role": "pid",
            "assurance": "AL1",
            "identity_evidence_id": str(uuid4()),
            "task_id": None,
            "job_id": None,
        },
        "action": "session_read",
        "scope": {
            "session_id": str(uuid4()),
            "subject_id": str(uuid4()),
            "purpose": "support",
            "fields": [],
            "recipient_id": None,
        },
        "tags": {"environment": "demo", "population": "synthetic"},
        "jurisdiction": None,
        "versions": revisions,
        "payload_digest": "a" * 64,
        "consent_id": None,
        "review_id": None,
        "bundle_digest": hashlib.sha256(SOURCE).hexdigest(),
        "artifact_digests": [],
        "mode": "ai_disabled",
        "audit_ready": True,
        "authority_complete": True,
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
                "required": False,
                "valid": False,
                "grant_id": None,
                "subject_revision": "0",
                "scope_digest": None,
                "effective_at": None,
                "expires_at": None,
                "recipient_id": None,
                "fields": [],
            },
            "review": {
                "required": False,
                "valid": False,
                "review_id": None,
                "payload_digest": None,
                "reviewer_id": None,
                "expires_at": None,
            },
            "exception_id": None,
            "exception_expires_at": None,
        },
    }


def build(tmp_path, executable=None):
    key = Ed25519PrivateKey.generate()
    if executable is None:
        executable = tmp_path / "opa"
        executable.write_bytes(b"not executed in signature unit tests")
    return OpaPolicy(
        executable,
        hashlib.sha256(executable.read_bytes()).hexdigest(),
        SOURCE,
        base64.b64encode(key.sign(SOURCE)).decode(),
        key.public_key(),
    )


def test_policy_binds_exact_evaluated_bytes_under_caller_mutation(tmp_path):
    policy, request = build(tmp_path), policy_request()
    evaluated = None

    def evaluate(_args, **kwargs):
        nonlocal evaluated
        evaluated = kwargs["input"]
        request["payload_digest"] = "b" * 64
        request["versions"]["policy_epoch"] = "2"
        return CompletedProcess([], 0, b'{"result":[{"expressions":[{"value":true}]}]}', b"")

    with patch("care_link_policy_input.opa.subprocess.run", side_effect=evaluate):
        decision = policy.evaluate(request)
    assert decision["binding_digest"] == hashlib.sha256(evaluated).hexdigest()
    assert decision["versions"]["policy_epoch"] == "1"
    assert json.loads(evaluated)["payload_digest"] == "a" * 64


def test_binary_tamper_and_wrong_signature_deny(tmp_path):
    policy = build(tmp_path)
    policy.executable.write_bytes(b"changed")
    with pytest.raises(ManualError, match="policy_integrity"):
        policy.evaluate(policy_request())
    with pytest.raises(ManualError, match="policy_integrity"):
        OpaPolicy(
            policy.executable,
            hashlib.sha256(b"changed").hexdigest(),
            SOURCE,
            policy.signature,
            Ed25519PrivateKey.generate().public_key(),
        )


def test_every_evaluation_streams_binary_integrity_without_whole_file_allocation(tmp_path):
    executable = tmp_path / "opa"
    # A sparse large file makes any complete read visible to tracemalloc while
    # keeping this integrity-only test independent of an installed OPA fixture.
    with executable.open("wb") as binary:
        binary.truncate(16 * 1024 * 1024)
    policy = build(tmp_path, executable)
    reply = CompletedProcess([], 0, b'{"result":[{"expressions":[{"value":true}]}]}', b"")
    tracemalloc.start()
    try:
        with (
            patch.object(Path, "read_bytes", side_effect=AssertionError("Whole-file read")),
            patch("care_link_policy_input.opa.subprocess.run", return_value=reply),
        ):
            assert policy.evaluate(policy_request())["decision"] == "PERMIT"
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 1024 * 1024
    # Successful verification is not cached: modifying the exact executable
    # must still be detected on the next operation.
    with executable.open("r+b") as binary:
        binary.write(b"modified")
    with pytest.raises(ManualError, match="policy_integrity"):
        policy.evaluate(policy_request())


@pytest.mark.parametrize(
    "change", ["restricted", "scope", "role", "audit", "tag", "action", "consent"]
)
def test_real_opa_fixed_exclusions_and_current_predicates(tmp_path, change):
    executable = os.environ.get("CARE_LINK_OPA_BINARY")
    if not executable:
        pytest.skip("Pinned OPA fixture explicitly required for integration")
    policy, request = build(tmp_path, Path(executable)), policy_request()
    assert policy.evaluate(request)["decision"] == "PERMIT"
    if change == "restricted":
        request["mode"] = "restricted"
    elif change == "scope":
        request["authority_facts"]["resource_owned_or_assigned"] = False
    elif change == "role":
        request["actor"]["role"] = "operator"
    elif change == "audit":
        request["audit_ready"] = False
    elif change == "tag":
        # Schema itself denies real population before OPA.
        from care_link_contracts import ContractError

        request["tags"]["population"] = "real"
        with pytest.raises(ContractError):
            policy.evaluate(request)
        return
    elif change == "action":
        request["action"] = "contact_police"
    elif change == "consent":
        request["authority_facts"]["consent"]["required"] = True
    assert policy.evaluate(request)["decision"] == "DENY"
