"""Fresh Data authorization uses Identity proofs for one exact inference operation."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from care_link_data.assistance.actors import TaskActors
from care_link_data.assistance_transport import StoredInferenceAuthority
from care_link_data.inference_actor import HttpInferenceActor
from care_link_domain import INFERENCE_ACTOR_PATH, Actor, InferenceActorRequest, ManualError

NOW = datetime(2026, 11, 23, 18, tzinfo=UTC)


def initiating_actor():
    return Actor(
        account_id=str(uuid4()),
        role="worker",
        identity_revision=1,
        role_revision=1,
        auth_time=NOW - timedelta(seconds=30),
        mfa=True,
        browser_session_digest="a" * 64,
        transport_generation=12,
        credential_ref="initial-request-expired",
        expires_at=NOW + timedelta(minutes=2),
        identity_evidence_id="initial-request-expired",
    )


def request(operation="context"):
    return InferenceActorRequest.create(
        job_id=uuid4(), task_id=uuid4(), step_id=uuid4(), fence=2, revision=3, operation=operation
    )


def test_fresh_proofs_replace_expired_creation_evidence_and_keep_both_deadlines():
    initial = initiating_actor()
    command = request()
    clock = [NOW]
    issued = []

    def old_reference(_actor):
        raise ManualError("manual.identity_denied")

    def mint(bound):
        issued.append(bound)
        ref = str(uuid4())
        return replace(
            initial,
            credential_ref=ref,
            identity_evidence_id=ref,
            request_deadline=clock[0] + timedelta(milliseconds=950),
        )

    registry = TaskActors(lambda: clock[0], old_reference)
    ceiling = NOW + timedelta(seconds=8)
    registry.bind(command.task_id, initial, ceiling, command.revision)
    clock[0] += timedelta(seconds=2)
    with pytest.raises(ManualError, match="identity_denied"):
        registry.resolve(command.task_id)
    actor_ids = set()
    for operation in ("context", "current", "reserve", "complete"):
        operation_command = InferenceActorRequest.create(
            job_id=command.job_id,
            task_id=command.task_id,
            step_id=command.step_id,
            fence=command.fence,
            revision=command.revision,
            operation=operation,
        )
        job_end = clock[0] + timedelta(milliseconds=300)
        actor = registry.refresh(operation_command, mint, job_deadline=job_end)
        assert actor.request_deadline == job_end
        actor_ids.add(actor.identity_evidence_id)
    assert len(actor_ids) == len({item.nonce for item in issued}) == 4
    clock[0] = ceiling - timedelta(milliseconds=250)
    assert registry.refresh(command, mint).request_deadline == ceiling
    clock[0] = ceiling
    with pytest.raises(ManualError, match="actor_resumption_required"):
        registry.refresh(command, mint)
    assert len(issued) == 5


def test_registry_rejects_changed_binding_and_revoke_during_mint():
    initial = initiating_actor()
    command = request("current")
    registry = TaskActors(lambda: NOW, lambda actor: actor)
    registry.bind(command.task_id, initial, NOW + timedelta(seconds=10), command.revision)
    fresh = replace(initial, request_deadline=NOW + timedelta(milliseconds=950))
    with pytest.raises(ManualError, match="inference_actor_changed"):
        registry.refresh(command, lambda _value: replace(fresh, transport_generation=13))
    with pytest.raises(ManualError, match="stale_revision"):
        registry.refresh(replace(command, revision="4"), lambda _value: pytest.fail("minted"))

    def revoke(_value):
        registry.revoke(command.task_id)
        return fresh

    with pytest.raises(ManualError, match="actor_resumption_required"):
        registry.refresh(command, revoke)


@pytest.mark.parametrize(
    "mutation", [None, "nonce", "resource_id", "request_digest", "action", "expires_at"]
)
def test_data_resolves_only_exact_core_proof(mutation):
    initial = initiating_actor()
    command = request()
    proof_id = str(uuid4())
    expiry = NOW + timedelta(milliseconds=950)
    proof = {
        "id": proof_id,
        "principal_id": initial.account_id,
        "role": "worker",
        "identity_revision": "1",
        "role_revision": "1",
        "action": command.action,
        "resource_id": command.task_id,
        "request_digest": command.digest,
        "nonce": command.nonce,
        "verified_at": NOW.isoformat().replace("+00:00", "Z"),
        "expires_at": expiry.isoformat().replace("+00:00", "Z"),
        "signature": "public-test-proof",
        "kind": "human_identity",
    }
    if mutation is not None:
        proof[mutation] = {
            "nonce": str(uuid4()),
            "resource_id": str(uuid4()),
            "request_digest": "f" * 64,
            "action": "assistance_inference_reserve",
            "expires_at": (NOW + timedelta(seconds=2)).isoformat().replace("+00:00", "Z"),
        }[mutation]

    class Identity:
        def resolve(self, evidence):
            assert mutation is None
            assert evidence == proof
            return replace(
                initial,
                credential_ref=proof_id,
                identity_evidence_id=proof_id,
                request_deadline=expiry,
            )

    def send(outgoing):
        assert outgoing.url.path == INFERENCE_ACTOR_PATH
        assert InferenceActorRequest.parse(json.loads(outgoing.read())) == command
        return httpx.Response(200, json=proof)

    with httpx.Client(transport=httpx.MockTransport(send)) as client:
        adapter = HttpInferenceActor(client, "https://core:8443", Identity(), clock=lambda: NOW)
        if mutation is not None:
            with pytest.raises(ManualError, match="inference_actor_denied"):
                adapter(command)
        else:
            assert adapter(command).request_deadline == expiry


def test_current_authority_requires_the_exact_job_identity():
    initial = initiating_actor()
    command = request("current")
    calls = []

    class Coordinator:
        def context_snapshot(self, actor, task_id):
            assert actor is initial and task_id == command.task_id
            return {
                "task": {"revision": command.revision},
                "fence": command.fence,
                "lease": {"step_id": command.step_id},
            }

    def current(record, operation):
        calls.append(operation)
        if record["job_id"] != command.job_id:
            raise ManualError("assistance.inference_actor_denied")
        return initial

    authority = StoredInferenceAuthority(
        Coordinator(),
        lambda _id: pytest.fail("used task-creation reference"),
        {},
        "bridge",
        fresh_actor=current,
    )
    context = {
        "task_id": command.task_id,
        "step_id": command.step_id,
        "revision": command.revision,
        "fence": command.fence,
    }
    assert not authority.current(context)
    assert not calls
    assert not authority.current({**context, "job_id": str(uuid4())})
    assert authority.current({**context, "job_id": command.job_id})
    assert calls == ["current", "current"]
