from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import create_autospec
from uuid import uuid4

import pytest
from care_link_core.manual_app import create_manual_app
from care_link_core.manual_channels import ManualChannels
from care_link_core.manual_ports import ManualGateway
from care_link_core.training_routes import EvaluationGateway
from care_link_domain import Actor, ManualError
from fastapi.testclient import TestClient


def actor():
    now = datetime.now(UTC)
    return Actor(
        str(uuid4()),
        "pid",
        1,
        1,
        now,
        False,
        "a" * 64,
        1,
        "opaque-private-reference",
        now + timedelta(hours=1),
        str(uuid4()),
    )


def test_channel_disconnect_reconnect_and_process_replacement_fence_old_generation():
    subject, registry = actor(), ManualChannels()
    with registry.open(subject) as first:
        assert registry.current(
            first.account_id, first.browser_session_digest, first.transport_generation
        )
        with registry.open(subject) as replacement:
            registry.disconnect(first)
            assert registry.current(
                replacement.account_id,
                replacement.browser_session_digest,
                replacement.transport_generation,
            )
            assert replacement.transport_generation > first.transport_generation
            assert not registry.current(
                first.account_id, first.browser_session_digest, first.transport_generation
            )
        assert not registry.current(
            replacement.account_id,
            replacement.browser_session_digest,
            replacement.transport_generation,
        )
    with registry.open(subject) as next_connection:
        assert next_connection.transport_generation > replacement.transport_generation
        assert not registry.current(
            first.account_id, first.browser_session_digest, first.transport_generation
        )
        fresh_process = ManualChannels()
        with fresh_process.open(subject) as restarted:
            assert restarted.transport_generation != next_connection.transport_generation
    assert not registry.current(
        subject.account_id, subject.browser_session_digest, next_connection.transport_generation
    )


def test_liveness_expires_without_server_heartbeat():
    now = [0.0]
    registry = ManualChannels(clock=lambda: now[0])
    with registry.open(actor()) as connected:
        now[0] = 10
        assert not registry.current(
            connected.account_id, connected.browser_session_digest, connected.transport_generation
        )


class Security:
    def __init__(self):
        self.actor = actor()

    def authenticate(self, request):
        if request.headers.get("authorization") == "denied":
            raise ManualError("manual.session_required", 401)
        return self.actor

    def csrf(self, request, _actor):
        if (
            request.headers.get("origin") != "https://app.test"
            or request.headers.get("x-csrf-token") != "csrf"
        ):
            raise ManualError("manual.csrf_denied")


@pytest.mark.parametrize(
    "key,wire,status",
    [
        ("manual.idempotency_conflict", "IDEMPOTENCY_CONFLICT", 409),
        ("manual.commit_unknown", "COMMIT_UNKNOWN", 503),
        ("manual.replacement_unavailable", "REPLACEMENT_UNAVAILABLE", 409),
    ],
)
def test_error_semantics_keep_stable_operation_identity(key, wire, status):
    gateway = create_autospec(ManualGateway, instance=True)
    gateway.session_human_request.side_effect = ManualError(key, status)
    client = TestClient(
        create_manual_app(gateway, Security(), ManualChannels()), base_url="https://app.test"
    )
    operation = str(uuid4())
    response = client.post(
        f"/v1/sessions/{uuid4()}/human-request",
        json={"expected_revision": "1", "reason": "user_requested"},
        headers={
            "Origin": "https://app.test",
            "X-CSRF-Token": "csrf",
            "Idempotency-Key": operation,
        },
    )
    assert response.status_code == status
    assert response.json()["code"] == wire
    assert response.json()["operation_id"] == operation


@pytest.mark.parametrize(
    "raw",
    [
        '{"expected_revision":"1","reason":"user_requested","reason":"fixture_escalation"}',
        '{"expected_revision":"01","reason":"user_requested"}',
    ],
)
def test_invalid_request_never_reaches_gateway(raw):
    gateway = create_autospec(ManualGateway, instance=True)
    client = TestClient(
        create_manual_app(gateway, Security(), ManualChannels()), base_url="https://app.test"
    )
    result = client.post(
        f"/v1/sessions/{uuid4()}/human-request",
        content=raw,
        headers={
            "Origin": "https://app.test",
            "X-CSRF-Token": "csrf",
            "Idempotency-Key": str(uuid4()),
            "Content-Type": "application/json",
        },
    )
    assert result.status_code in {400, 422}
    gateway.session_human_request.assert_not_called()


def test_missing_csrf_denies_even_with_body_role_spoofing():
    gateway = create_autospec(ManualGateway, instance=True)
    client = TestClient(
        create_manual_app(gateway, Security(), ManualChannels()), base_url="https://app.test"
    )
    response = client.post(
        f"/v1/sessions/{uuid4()}/human-request",
        json={"role": "worker"},
        headers={"Origin": "https://evil.test", "Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 403
    gateway.session_human_request.assert_not_called()


def test_replay_binds_only_a_current_authenticated_request_channel():
    registry, security = ManualChannels(), Security()
    security.actor = replace(security.actor, role="trainer", mfa=True)
    observed = []
    replay = create_autospec(
        EvaluationGateway,
        instance=True,
    )

    def execute(current, _key, _data):
        observed.append(current)
        assert registry.current(
            current.account_id, current.browser_session_digest, current.transport_generation
        )
        return {
            "id": str(uuid4()),
            "state": "completed",
            "evidence_digest": "d" * 64,
            "clinical_claim": False,
        }

    replay.replay_create.side_effect = execute
    replay.evaluation_read.side_effect = lambda current, _: execute(current, None, None)
    client = TestClient(
        create_manual_app(
            create_autospec(ManualGateway, instance=True), security, registry, evaluation=replay
        ),
        base_url="https://app.test",
    )
    arguments = {
        "scenario_id": str(uuid4()),
        "input_manifest_digest": "a" * 64,
        "recorded_outputs_digest": "b" * 64,
        "bundle_digest": "c" * 64,
    }
    headers = {
        "Origin": "https://app.test",
        "X-CSRF-Token": "csrf",
        "Idempotency-Key": str(uuid4()),
    }
    route = "/v1/evaluation/replays"

    assert (
        client.post(route, json=arguments, headers={**headers, "X-CSRF-Token": "bad"}).status_code
        == 403
    )
    assert not observed
    assert client.post(route, json=arguments, headers=headers).status_code == 200
    assert client.get(f"{route}/{uuid4()}").status_code == 200
    assert len(observed) == 2
    for current in observed:
        assert not registry.current(
            current.account_id, current.browser_session_digest, current.transport_generation
        )
