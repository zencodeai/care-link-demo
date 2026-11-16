"""Envelope and remote identity adverse tests with explicit network fixtures."""

import base64
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from care_link_core.manual_envelopes import SignedEnvelopeFactory
from care_link_core.manual_http import HttpManualGateway
from care_link_core.manual_identity import HttpManualIdentity, actor_record, canonical
from care_link_domain import Actor, ManualError
from care_link_policy_input import DelegationVerifier
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


@pytest.mark.parametrize("selected", [None, "10000000-0000-4000-8000-000000000001"])
def test_signed_workspace_selection_survives_the_actual_delegation_verifier(selected):
    factory, actor, verifier, *_rest = fixture()
    key = str(uuid4())
    path = "/internal/v1/data/review_workspace"
    envelope = factory.build(actor, "review_workspace", key, {"session_id": selected}, {})
    assert envelope["delegation"]["scope"]["session_id"] is None
    assert verifier.verify(envelope, "review_workspace", key, path).account_id == actor.account_id
    envelope["arguments"]["session_id"] = str(uuid4())
    with pytest.raises(ManualError, match="delegation_denied"):
        verifier.verify(envelope, "review_workspace", key, path)


@pytest.mark.parametrize("action", ["queue_list", "messages_read"])
@pytest.mark.parametrize("cursor", [None, "opaque-cursor"])
def test_http_pagination_preserves_optional_cursor_contract(action, cursor):
    from care_link_contracts import validate_contract

    factory, actor, verifier, *_rest = fixture()
    calls = []

    def serve(request):
        value = json.loads(request.content)
        validate_contract("Gateway_" + action, value)
        verifier.verify(value, action, request.headers["idempotency-key"], request.url.path)
        calls.append(value["arguments"])
        return httpx.Response(200, json={"items": [], "next_cursor": None})

    gateway = HttpManualGateway(
        httpx.Client(transport=httpx.MockTransport(serve)), "https://data.test", factory
    )
    if action == "messages_read":
        result = gateway.messages_read(actor, str(uuid4()), cursor=cursor)
    else:
        result = gateway.queue_list(actor, cursor=cursor)
    assert result == {"items": [], "next_cursor": None}
    assert calls == [{"limit": 50, **({"cursor": cursor} if cursor is not None else {})}]


def fixture():
    now = [datetime.now(UTC)]
    actor = Actor(
        str(uuid4()),
        "pid",
        1,
        1,
        now[0],
        False,
        hashlib.sha256(b"browser-private-cookie").hexdigest(),
        17,
        "browser-private-cookie",
        now[0] + timedelta(hours=1),
        str(uuid4()),
    )
    identity_key, core_key = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    receipts = {}
    calls = []
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
    facts = {
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
    }
    metadata = {
        "versions": revisions,
        "authority_facts": facts,
        "bundle_digest": "b" * 64,
        "mode": "ai_disabled",
        "complete": True,
    }
    verifier = DelegationVerifier(
        core_key.public_key(),
        identity_key.public_key(),
        lambda e: replace(actor, identity_evidence_id=e["id"]),
        clock=lambda: now[0],
    )

    def sign(value):
        return {
            **value,
            "signature": base64.urlsafe_b64encode(identity_key.sign(canonical(value)))
            .rstrip(b"=")
            .decode(),
        }

    def identity_transport(request):
        assert request.headers["cookie"] == ""
        data = json.loads(request.content)
        name = request.url.path.rsplit("/", 1)[-1]
        if name == "authenticate":
            return httpx.Response(200, json=actor_record(actor))
        if name == "csrf":
            return httpx.Response(200, json={"verified": True})
        if name == "evidence":
            value = sign(
                {
                    "id": str(uuid4()),
                    "principal_id": actor.account_id,
                    "role": actor.role,
                    "identity_revision": "1",
                    "role_revision": "1",
                    "action": data["action"],
                    "resource_id": data["resource_id"],
                    "request_digest": data["request_digest"],
                    "nonce": data["nonce"],
                    "verified_at": now[0].isoformat().replace("+00:00", "Z"),
                    "expires_at": (now[0] + timedelta(seconds=0.95))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "kind": "human_identity",
                }
            )
            receipts[value["id"]] = value
            return httpx.Response(200, json=value)
        raise AssertionError(name)

    def data_transport(request):
        calls.append(request)
        value = json.loads(request.content)
        normalized = {
            "delegation": value["delegation"],
            "arguments": {k: v for k, v in value.items() if k != "delegation"},
            "path_arguments": {"session_id": value["scope"]["session_id"]}
            if value["scope"]["session_id"]
            else {},
        }
        verifier.verify(
            normalized, value["action"], request.headers["idempotency-key"], request.url.path
        )
        return httpx.Response(200, json=metadata)

    class Policy:
        request = None

        def before_return(self):
            return None

        decision = "PERMIT"

        def evaluate(self, request):
            self.request = request
            result = {
                "decision_id": str(uuid4()),
                "decision": self.decision,
                "binding_digest": hashlib.sha256(canonical(request)).hexdigest(),
                "reasons": ["CURRENT_SCOPE"],
                "obligations": [{"kind": "audit_before_effect"}],
                "versions": request["versions"],
                "bundle_digest": request["bundle_digest"],
                "expires_at": (now[0] + timedelta(seconds=0.75)).isoformat().replace("+00:00", "Z"),
            }
            self.before_return()
            return result

    identity = HttpManualIdentity(
        httpx.Client(transport=httpx.MockTransport(identity_transport)),
        "https://identity.test",
        identity_key.public_key(),
        clock=lambda: now[0],
    )
    policy = Policy()
    factory = SignedEnvelopeFactory(
        httpx.Client(transport=httpx.MockTransport(data_transport)),
        "https://data.test",
        identity,
        policy,
        core_key,
        clock=lambda: now[0],
    )
    return factory, actor, verifier, metadata, calls, policy, now, identity


def test_factory_signs_exact_metadata_and_final_body_with_fresh_receipts():
    factory, actor, verifier, _metadata, calls, policy, _now, identity = fixture()
    assert identity.authenticate(actor.credential_ref).account_id == actor.account_id
    sid, key = str(uuid4()), str(uuid4())
    result = factory.build(
        actor,
        "session_human_request",
        key,
        {"expected_revision": "1", "reason": "user_requested"},
        {"session_id": sid},
    )
    verified = verifier.verify(
        result, "session_human_request", key, "/internal/v1/data/session_human_request"
    )
    assert verified.account_id == actor.account_id
    assert policy.request["authority_facts"] == _metadata["authority_facts"]
    assert policy.request["bundle_digest"] == _metadata["bundle_digest"]
    assert len(calls) == 1
    preflight = json.loads(calls[0].content)["delegation"]
    assert preflight["evidence"]["id"] != result["delegation"]["evidence"]["id"]
    assert preflight["body_digest"] != result["delegation"]["body_digest"]
    assert actor.credential_ref not in json.dumps(result)
    changed = json.loads(json.dumps(result))
    changed["arguments"]["reason"] = "fixture_escalation"
    with pytest.raises(ManualError, match="delegation_denied"):
        verifier.verify(
            changed, "session_human_request", key, "/internal/v1/data/session_human_request"
        )


def test_unknown_operation_denies_before_any_authority_call():
    factory, actor, _verifier, _metadata, calls, _policy, _now, _identity = fixture()
    with pytest.raises(ManualError, match="unsupported_operation"):
        factory.build(actor, "../../escape", str(uuid4()), {}, {})
    assert not calls


@pytest.mark.parametrize(
    "case", ["incomplete", "deny", "expired", "original-deadline", "metadata-delay"]
)
def test_incomplete_denied_or_expired_preflight_never_returns_envelope(case):
    factory, actor, _verifier, metadata, _calls, policy, now, _identity = fixture()
    if case == "incomplete":
        metadata["complete"] = False
    elif case == "deny":
        policy.decision = "DENY"
    elif case == "expired":
        policy.before_return = lambda: now.__setitem__(0, now[0] + timedelta(seconds=2))
    elif case == "original-deadline":
        actor = replace(actor, request_deadline=now[0] + timedelta(seconds=0.1))
        policy.before_return = lambda: now.__setitem__(0, now[0] + timedelta(seconds=0.2))
    else:
        old = factory.client

        def delayed(request):
            response = old.send(request)
            now[0] += timedelta(seconds=2)
            return response

        factory.client = httpx.Client(transport=httpx.MockTransport(delayed))
    with pytest.raises(ManualError):
        factory.build(actor, "session_read", str(uuid4()), {}, {"session_id": str(uuid4())})


def test_caller_mutation_during_policy_cannot_change_signed_payload():
    factory, actor, verifier, _metadata, _calls, policy, _now, _identity = fixture()
    args = {"expected_revision": "1", "reason": "user_requested"}
    policy.before_return = lambda: args.update(reason="fixture_escalation")
    key = str(uuid4())
    result = factory.build(actor, "session_human_request", key, args, {"session_id": str(uuid4())})
    assert result["arguments"]["reason"] == "user_requested"
    verifier.verify(result, "session_human_request", key, "/internal/v1/data/session_human_request")


@pytest.mark.parametrize(
    "action,args,paths,expected",
    [
        ("operation_status", {}, {"operation_id": str(uuid4())}, None),
        (
            "continuation_recover",
            {
                "session_id": str(uuid4()),
                "family_id": str(uuid4()),
                "ceremony_id": str(uuid4()),
                "channel": "web",
                "expected_revision": "1",
            },
            {},
            "argument",
        ),
    ],
)
def test_global_and_argument_session_scope_bindings(action, args, paths, expected):
    factory, actor, verifier, _metadata, _calls, _policy, _now, _identity = fixture()
    key = str(uuid4())
    result = factory.build(actor, action, key, args, paths)
    assert result["delegation"]["scope"]["session_id"] == (args["session_id"] if expected else None)
    verifier.verify(result, action, key, "/internal/v1/data/" + action)


def test_remote_identity_rejects_valid_signature_for_different_request_binding():
    factory, actor, _verifier, _metadata, _calls, _policy, _now, identity = fixture()
    original = identity.client

    def mutate(request):
        value = json.loads(request.content)
        value["request_digest"] = "f" * 64
        return original.post(request.url, json=value, headers={"Cookie": ""})

    identity.client = httpx.Client(transport=httpx.MockTransport(mutate))
    with pytest.raises(ManualError, match="identity_evidence_denied"):
        factory.build(actor, "session_read", str(uuid4()), {}, {"session_id": str(uuid4())})
