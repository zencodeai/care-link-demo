"""Job-scoped Core proofs with a synthetic Identity producer."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, create_autospec
from uuid import uuid4

import pytest
from care_link_core.assistance_broker import InferenceBroker
from care_link_core.assistance_broker.actors import ActorTasks
from care_link_core.assistance_broker.inference_authority import (
    InferenceActorAuthority,
    attach_inference_authority,
)
from care_link_core.assistance_broker.ports import Coordinator, InferencePort
from care_link_core.manual_app import create_manual_app
from care_link_core.manual_channels import ManualChannels
from care_link_core.manual_envelopes import IdentityEvidencePort
from care_link_core.manual_ports import ManualGateway
from care_link_domain import INFERENCE_ACTOR_PATH, InferenceActorRequest, ManualError, WorkloadPeer
from fastapi.testclient import TestClient
from test_assistance_work import synthetic_release, task
from test_manual_transport import Security, actor


def stamp(instant):
    return instant.isoformat().replace("+00:00", "Z")


@pytest.fixture
def live_job():
    now = [datetime.now(UTC)]

    def clock():
        return now[0]

    channels = ManualChannels(clock=lambda: 0.0)
    actors = ActorTasks(clock=clock)
    identity = create_autospec(IdentityEvidencePort, instance=True)
    authority = InferenceActorAuthority(actors, identity, channels, clock=clock)

    def issue(owner, action, digest, nonce, resource_id):
        return {
            "id": str(uuid4()),
            "principal_id": owner.account_id,
            "role": owner.role,
            "identity_revision": str(owner.identity_revision),
            "role_revision": str(owner.role_revision),
            "action": action,
            "resource_id": resource_id,
            "request_digest": digest,
            "nonce": nonce,
            "verified_at": stamp(clock()),
            "expires_at": stamp(clock() + timedelta(milliseconds=950)),
            "signature": "synthetic-proof",
            "kind": "human_identity",
        }

    identity.evidence.side_effect = issue
    with channels.open(replace(actor(), role="worker", mfa=True, auth_time=clock())) as owner:
        value = task(owner)
        actors.bind(owner, value)
        command = InferenceActorRequest.create(
            job_id=str(uuid4()),
            task_id=value["id"],
            step_id=str(uuid4()),
            fence="1",
            revision=value["revision"],
            operation="context",
        )
        request = {**command.record(), "deadline": stamp(clock() + timedelta(seconds=30))}
        yield authority, actors, channels, identity, owner, value, command, request, now


def test_active_job_mints_fresh_proofs_for_each_exact_operation(live_job):
    authority, actors, _, identity, owner, _, command, request, now = live_job
    original = actors.resolve(command.task_id)
    with authority.track(request, command.revision, original):
        now[0] += timedelta(seconds=2)
        assert original.request_deadline < now[0]
        evidence_ids = set()
        for operation in ("context", "current", "reserve", "complete"):
            current = replace(command, operation=operation, nonce=str(uuid4()))
            evidence = authority.mint(current)
            evidence_ids.add(evidence["id"])
            assert evidence["action"] == current.action
            assert evidence["request_digest"] == current.digest
            assert evidence["nonce"] == current.nonce
            assert evidence["resource_id"] == current.task_id
            assert owner.credential_ref not in str(evidence)
            assert identity.evidence.call_args.args[0].request_deadline == now[0] + timedelta(
                seconds=1
            )
        assert len(evidence_ids) == 4
    with pytest.raises(ManualError, match="inference_binding"):
        authority.mint(command)


@pytest.mark.parametrize("field", ["job_id", "task_id", "step_id", "fence", "revision"])
def test_job_binding_mismatch_denies_before_identity(live_job, field):
    authority, _, _, identity, owner, _, command, request, _ = live_job
    value = "2" if field in {"fence", "revision"} else str(uuid4())
    with authority.track(request, command.revision, owner):
        with pytest.raises(ManualError, match="inference_binding"):
            authority.mint(replace(command, **{field: value}))
    identity.evidence.assert_not_called()


@pytest.mark.parametrize("change", ["different_owner", "rebind", "disconnect", "expiration"])
def test_inactive_original_actor_cannot_mint(live_job, change):
    authority, actors, channels, identity, owner, value, command, request, now = live_job
    substitute = replace(owner, account_id=str(uuid4())) if change == "different_owner" else owner
    with pytest.raises(ManualError), authority.track(request, command.revision, substitute):
        if change == "rebind":
            actors.bind(owner, value)
        elif change == "disconnect":
            channels.disconnect(owner)
        elif change == "expiration":
            now[0] += timedelta(seconds=31)
        else:
            pytest.fail("the substituted actor should be denied before inference")
        authority.mint(command)
    identity.evidence.assert_not_called()


def test_actor_revocation_during_identity_mint_fences_the_proof(live_job):
    authority, actors, _, identity, owner, _, command, request, _ = live_job
    issue = identity.evidence.side_effect

    def issue_then_revoke(*args):
        evidence = issue(*args)
        actors.revoke(command.task_id)
        return evidence

    identity.evidence.side_effect = issue_then_revoke
    with authority.track(request, command.revision, owner):
        with pytest.raises(ManualError, match="actor_resumption_required"):
            authority.mint(command)


def test_actor_operation_deadline_is_clipped_to_existing_task_ceiling(live_job):
    _, actors, _, _, owner, value, command, _, now = live_job
    expiry = now[0] + timedelta(milliseconds=350)
    actors.bind(owner, {**value, "deadline": stamp(expiry)})
    assert actors.resolve(command.task_id).request_deadline == expiry


def test_signed_receipt_cannot_outlive_active_job(live_job):
    authority, _, _, _, owner, _, command, request, now = live_job
    deadline = stamp(now[0] + timedelta(milliseconds=750))
    with authority.track({**request, "deadline": deadline}, command.revision, owner):
        with pytest.raises(ManualError, match="inference_binding"):
            authority.mint(command)


def test_data_only_route_rejects_unsafe_bodies_and_rechecks_workload(live_job):
    authority, _, channels, identity, owner, _, command, request, _ = live_job
    app = create_manual_app(create_autospec(ManualGateway, instance=True), Security(), channels)
    verify = Mock()
    attach_inference_authority(app, authority, verify)
    with authority.track(request, command.revision, owner), TestClient(app) as client:
        verify.return_value = False
        assert client.post(INFERENCE_ACTOR_PATH, json=command.record()).status_code == 403
        identity.evidence.assert_not_called()
        verify.return_value = True
        duplicate = '{"nonce":"duplicate",' + json.dumps(command.record())[1:]
        assert (
            client.post(
                INFERENCE_ACTOR_PATH,
                content=duplicate,
                headers={"Content-Type": "application/json"},
            ).status_code
            == 400
        )
        assert (
            client.post(INFERENCE_ACTOR_PATH, json={**command.record(), "actor": {}}).status_code
            == 400
        )
        identity.evidence.assert_not_called()
        verify.side_effect = (True, False)
        assert client.post(INFERENCE_ACTOR_PATH, json=command.record()).status_code == 403
        verify.side_effect = None
        response = client.post(INFERENCE_ACTOR_PATH, json=command.record())
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["request_digest"] == command.digest
        assert owner.credential_ref not in response.text


@pytest.mark.parametrize("downstream_error", [False, True])
def test_broker_keeps_job_proof_active_only_during_inference(live_job, downstream_error):
    authority, actors, _, _, _, task_view, command, _, now = live_job
    coordinator = create_autospec(Coordinator, instance=True)
    coordinator.reserve_proposal.return_value = {
        "task": {**task_view, "function": "worker_summary"},
        "goal": "prepare_summary",
        "reservation_id": str(uuid4()),
        "sources": [],
    }
    inference = create_autospec(InferencePort, instance=True)
    release = synthetic_release(None)
    observed = []

    def infer(request):
        active = replace(command, job_id=request["job_id"])
        observed.append(active)
        assert authority.mint(active)["request_digest"] == active.digest
        if downstream_error:
            raise ManualError("assistance.inference_unavailable", 503)
        return {
            "job_id": request["job_id"],
            "state": "rejected",
            "proposal": None,
            "input_tokens": 0,
            "output_tokens": 0,
            "model_digest": request["model_digest"],
            "safe_reason": "synthetic_test_denial",
        }

    inference.infer.side_effect = infer
    broker = InferenceBroker(
        coordinator,
        inference,
        actor_for_task=actors.resolve,
        release=release.release,
        clock=lambda: now[0],
        inference_authority=authority,
    )
    peer = WorkloadPeer(
        "spiffe://care-link.demo/demo/runtime", 1, "a" * 64, now[0] + timedelta(minutes=1)
    )
    request = {key: command.record()[key] for key in ("task_id", "step_id", "fence")}
    request["expected_task_revision"] = command.revision
    if downstream_error:
        with pytest.raises(ManualError, match="inference_unavailable"):
            broker.infer(request, peer)
    else:
        assert broker.infer(request, peer)["state"] == "rejected"
    assert len(observed) == 1
    with pytest.raises(ManualError, match="inference_binding"):
        authority.mint(observed[0])
