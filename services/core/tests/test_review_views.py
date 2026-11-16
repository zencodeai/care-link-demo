from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from care_link_core.manual_channels import ManualChannels
from care_link_core.review_channels import ReviewViews
from care_link_domain import Actor, ManualError


def actor():
    now = datetime.now(UTC)
    return Actor(
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
        review_origin="https://worker.test",
    )


def test_observer_registration_does_not_replace_channel_and_explicit_claim_fences_it():
    subject = actor()
    channels = ManualChannels()
    views = ReviewViews(channels)
    active = views.register(subject)
    with channels.open(subject) as connection:
        observer = views.register(subject)
        assert active["state"] == "active" and observer["state"] == "observer"
        assert channels.current(
            connection.account_id,
            connection.browser_session_digest,
            connection.transport_generation,
        )
        with pytest.raises(ManualError, match="review_observer"):
            views.require(subject, observer["view_id"])
        views.claim(subject, observer["view_id"], observer["revision"])
        assert not channels.current(
            connection.account_id,
            connection.browser_session_digest,
            connection.transport_generation,
        )
        views.require(subject, observer["view_id"])
        with pytest.raises(ManualError, match="review_observer"):
            views.require(subject, active["view_id"])
        with pytest.raises(ManualError, match="review_view_stale"):
            views.claim(subject, active["view_id"], observer["revision"])


def test_view_handle_is_bound_to_exact_session_run_and_actor():
    subject = actor()
    views = ReviewViews(ManualChannels())
    active = views.register(subject)
    for changed in [
        replace(subject, review_run_id=str(uuid4())),
        replace(subject, account_id=str(uuid4())),
        replace(subject, browser_session_digest="b" * 64),
    ]:
        with pytest.raises(ManualError):
            views.require(changed, active["view_id"])
    with pytest.raises(ManualError):
        views.require(subject, "")
