import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

from care_link_core.manual_app import create_manual_app
from care_link_core.manual_channels import ManualChannels
from care_link_core.review_channels import ReviewViews
from care_link_core.review_context import ReviewContexts
from care_link_domain import Actor
from fastapi.testclient import TestClient


def setup(tmp_path, legacy=False, *, injected_views=None):
    now = datetime.now(UTC)
    subject = Actor(
        str(uuid4()),
        "worker",
        1,
        1,
        now,
        True,
        "a" * 64,
        1,
        "opaque",
        now + timedelta(hours=1),
        str(uuid4()),
        review_run_id=str(uuid4()),
        review_slot_id="worker1",
        review_origin="https://review.test",
    )
    context = {
        "run_id": subject.review_run_id,
        "slot_id": "worker1",
        "account_id": subject.account_id,
        "role": "worker",
        "state": "active",
    }
    file = tmp_path / "contexts.json"
    file.write_text(json.dumps({subject.review_origin: context}))
    security = Mock()
    security.authenticate.return_value = (
        replace(subject, review_run_id=None, review_slot_id=None, review_origin=None)
        if legacy
        else subject
    )
    channels = ManualChannels()
    if injected_views is not None:
        channels = injected_views.channels
    gateway = Mock()
    app = create_manual_app(
        gateway,
        security,
        channels,
        review_contexts=ReviewContexts(file, "https://legacy.test"),
        review_views=injected_views,
    )
    return TestClient(app, base_url="https://review.test"), subject, channels, gateway


def test_registered_origin_rejects_unscoped_legacy_cookie_before_gateway(tmp_path):
    client, subject, channels, gateway = setup(tmp_path, legacy=True)
    response = client.get("/v1/sessions/" + str(uuid4()))
    assert response.status_code == 403
    gateway.session_read.assert_not_called()


def test_review_observer_cannot_replace_active_stream_via_legacy_endpoint(tmp_path):
    client, subject, channels, gateway = setup(tmp_path)
    with channels.open(subject) as active:
        response = client.get("/v1/sessions/" + str(uuid4()) + "/events")
        assert response.status_code == 409
        assert channels.current(
            subject.account_id, subject.browser_session_digest, active.transport_generation
        )
    gateway.session_read.assert_not_called()


def test_nonce_read_needs_active_view_handle(tmp_path):
    client, subject, channels, gateway = setup(tmp_path)
    response = client.get("/v1/sessions/" + str(uuid4()) + "/workforce/challenge")
    assert response.status_code == 409
    gateway.channel_challenge_read.assert_not_called()


def test_operator_retirement_uses_exact_serving_view_custody(tmp_path):
    channels = ManualChannels()
    views = ReviewViews(channels)
    client, subject, _channels, _gateway = setup(tmp_path, injected_views=views)
    registered = client.post("/v1/review/view", json={})
    assert registered.status_code == 200
    handle = registered.json()["view_id"]
    assert client.get("/v1/review/view", headers={"X-Review-View": handle}).status_code == 200
    assert views.retire_run(subject.review_run_id) == 1
    assert client.get("/v1/review/view", headers={"X-Review-View": handle}).status_code == 409
