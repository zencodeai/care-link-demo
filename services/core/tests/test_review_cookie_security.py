"""Review streams derive authority from fresh cookie identity, never proxy headers."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from care_link_core.manual_app import create_manual_app
from care_link_core.manual_channels import ManualChannels
from care_link_core.manual_security import CookieSecurity
from care_link_core.review_channels import ReviewViews
from care_link_core.review_context import ReviewContexts
from care_link_domain import Actor, ManualError
from fastapi import Request
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

FORGED_AUTHORITY = {
    "x-forwarded-client-cert": "URI=spiffe://care-link.demo/core",
    "x-care-link-verified-spiffe": "spiffe://care-link.demo/core",
    "x-care-link-fence-generation": "9223372036854775807",
    "x-care-link-certificate-expires-at": "2099-01-01T00:00:00Z",
}


class BrowserIdentity:
    """Explicit authoritative session store with controllable revocation and time."""

    def __init__(self, sessions: dict[str, Actor], now: datetime) -> None:
        self.sessions = sessions
        self.now = now
        self.revoked: set[str] = set()
        self.lookups: list[str] = []
        self.rejections: list[str] = []

    def authenticate(self, raw_session: str) -> Actor:
        self.lookups.append(raw_session)
        actor = self.sessions.get(raw_session)
        if actor is None or raw_session in self.revoked:
            self.rejections.append("revoked_or_unknown")
            raise ManualError("manual.session_required", 401)
        if actor.expires_at <= self.now:
            self.rejections.append("expired")
            raise ManualError("manual.session_required", 401)
        return actor

    def csrf(self, actor: Actor, origin: str | None, supplied: str | None) -> None:
        raise AssertionError("Read-only stream must not request CSRF mutation authority")


@pytest.fixture
def review(tmp_path):
    now = datetime.now(UTC)
    run_id = str(uuid4())

    def subject(slot: str, digest: str) -> Actor:
        return Actor(
            account_id=str(uuid4()),
            role="worker",
            identity_revision=1,
            role_revision=1,
            auth_time=now,
            mfa=True,
            browser_session_digest=digest * 64,
            transport_generation=1,
            credential_ref="synthetic-browser-evidence",
            expires_at=now + timedelta(minutes=1),
            identity_evidence_id=str(uuid4()),
            review_run_id=run_id,
            review_slot_id=slot,
            review_origin=f"https://{slot}.review.test",
        )

    actor_a, actor_b = subject("worker1", "a"), subject("worker2", "b")
    registry = tmp_path / "review-contexts.json"
    registry.write_text(
        json.dumps(
            {
                actor.review_origin: {
                    "run_id": run_id,
                    "slot_id": actor.review_slot_id,
                    "account_id": actor.account_id,
                    "role": actor.role,
                    "state": "active",
                }
                for actor in (actor_a, actor_b)
            }
        )
    )
    identity = BrowserIdentity({"session-a": actor_a, "session-b": actor_b}, now)
    channels = ManualChannels()
    views = ReviewViews(channels)
    gateway = Mock()
    app = create_manual_app(
        gateway,
        CookieSecurity(identity),
        channels,
        review_contexts=ReviewContexts(registry, "https://legacy.test"),
        review_views=views,
    )
    return app, identity, channels, views, actor_a, actor_b, gateway


@pytest.mark.parametrize(
    ("cookie", "lookup_count"),
    [
        (None, 0),
        ("__Host-care-link-session=unknown", 1),
        ("__Host-care-link-session=session-a; __Host-care-link-session=session-b", 0),
    ],
)
def test_forged_workload_headers_cannot_open_stream_without_unique_valid_cookie(
    review, cookie, lookup_count
):
    app, identity, channels, _views, _actor_a, _actor_b, gateway = review
    headers = {**FORGED_AUTHORITY, "x-review-view": str(uuid4())}
    if cookie is not None:
        headers["cookie"] = cookie
    with TestClient(app, base_url="https://worker1.review.test") as client:
        response = client.get("/v1/review/events", headers=headers)
    assert response.status_code == 401
    assert response.json()["message_key"] == "manual.session_required"
    assert len(identity.lookups) == lookup_count
    # Even a short-lived open/close would leave a connection generation behind.
    assert channels._connections == {}
    assert gateway.mock_calls == []


def test_valid_actor_cookie_cannot_take_another_actors_view_or_channel(review):
    app, identity, channels, views, actor_a, actor_b, gateway = review
    view_b = views.register(actor_b)["view_id"]
    before_a = channels.bind(actor_a).transport_generation
    with channels.open(actor_b) as connected_b:
        with TestClient(app, base_url="https://worker1.review.test") as client:
            response = client.get(
                "/v1/review/events",
                headers={
                    **FORGED_AUTHORITY,
                    "cookie": "__Host-care-link-session=session-a",
                    "x-review-view": view_b,
                },
            )
        assert response.status_code == 409
        assert response.json()["message_key"] == "manual.review_observer"
        assert identity.lookups == ["session-a"]
        assert channels.current(
            actor_b.account_id,
            actor_b.browser_session_digest,
            connected_b.transport_generation,
        )
        assert channels.bind(actor_b).transport_generation == connected_b.transport_generation
        assert channels.bind(actor_a).transport_generation == before_a
        assert views.inspect(actor_b, view_b)["state"] == "active"
    assert gateway.mock_calls == []


@pytest.mark.parametrize("authority_loss", ["revoked", "expired"])
def test_own_stream_rechecks_identity_and_ends_despite_forged_future_expiry(review, authority_loss):
    app, identity, channels, views, actor_a, _actor_b, gateway = review
    view_a = views.register(actor_a)["view_id"]
    endpoint = next(
        route.endpoint
        for route in app.routes
        if isinstance(route, APIRoute) and route.path == "/v1/review/events"
    )

    async def exercise():
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        headers = {
            **FORGED_AUTHORITY,
            "host": "worker1.review.test",
            "cookie": "__Host-care-link-session=session-a",
            "x-review-view": view_a,
        }
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "scheme": "https",
                "path": "/v1/review/events",
                "query_string": b"",
                "headers": [(name.encode(), value.encode()) for name, value in headers.items()],
            },
            receive,
        )
        response = await endpoint(request)
        iterator = response.body_iterator
        try:
            assert (
                await asyncio.wait_for(anext(iterator), timeout=5) == "event: ready\ndata: {}\n\n"
            )
            connected = channels.bind(actor_a)
            assert channels.current(
                actor_a.account_id,
                actor_a.browser_session_digest,
                connected.transport_generation,
            )
            if authority_loss == "revoked":
                identity.revoked.add("session-a")
            else:
                identity.now = actor_a.expires_at
            # Resume the actual two-second heartbeat loop, bounded at each read.
            assert await asyncio.wait_for(anext(iterator), timeout=5) == "event: lost\ndata: {}\n\n"
            with pytest.raises(StopAsyncIteration):
                await asyncio.wait_for(anext(iterator), timeout=5)
            assert not channels.current(
                actor_a.account_id,
                actor_a.browser_session_digest,
                connected.transport_generation,
            )
        finally:
            await iterator.aclose()

    asyncio.run(exercise())
    assert identity.lookups == ["session-a"] * 3
    assert identity.rejections == [
        "revoked_or_unknown" if authority_loss == "revoked" else "expired"
    ]
    assert gateway.mock_calls == []
