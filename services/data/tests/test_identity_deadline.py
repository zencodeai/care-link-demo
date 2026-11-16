"""Request-budget exhaustion remains distinct from real identity/fresh-proof loss."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from care_link_data import AESGCMContentCipher, PostgresStore
from care_link_data.engine import Engine
from care_link_domain import Actor, ManualError

from services.data.tests.conftest import Channels, Journal, Policy


class CurrentIdentity:
    def __init__(self, current: Actor, clock: list[datetime], delay: timedelta) -> None:
        self.actor, self.clock, self.delay = current, clock, delay
        self.calls = 0

    def current(self, _actor: Actor) -> Actor:
        self.calls += 1
        self.clock[0] += self.delay
        return self.actor

    def recovery_proof(
        self, actor: Actor, ceremony_id: str, session_id: str, family_id: str
    ) -> None:
        raise AssertionError("Identity refresh does not invoke recovery proof")


def fixture(
    delay: timedelta = timedelta(),
) -> tuple[Engine, Actor, CurrentIdentity, list[datetime]]:
    now = datetime(2026, 11, 16, 12, tzinfo=UTC)
    clock = [now]
    actor = Actor(
        str(uuid4()),
        "worker",
        1,
        1,
        now,
        True,
        "a" * 64,
        1,
        "opaque-test-reference",
        now + timedelta(hours=1),
        str(uuid4()),
        request_deadline=now + timedelta(seconds=1),
    )
    # Fresh identity evidence cannot renew the original request's deadline.
    authority = CurrentIdentity(
        replace(actor, request_deadline=now + timedelta(hours=1)), clock, delay
    )
    engine = Engine(
        PostgresStore("dbname=unused sslmode=verify-full sslrootcert=/unused-test-ca"),
        authority,
        Policy(),
        Journal(),
        AESGCMContentCipher(bytes(range(32))),
        channel=Channels(),
        clock=lambda: clock[0],
    )
    return engine, actor, authority, clock


@pytest.mark.parametrize("already_expired", [False, True])
def test_valid_identity_request_deadline_returns_service_timeout_not_identity_change(
    already_expired: bool,
) -> None:
    engine, actor, authority, clock = fixture(timedelta(seconds=1))
    if already_expired:
        clock[0] = actor.request_deadline
    with pytest.raises(ManualError) as failure:
        engine._fresh_actor(actor)
    assert failure.value.code == "manual.deadline_exceeded"
    assert failure.value.status == 503
    assert authority.actor.account_id == actor.account_id
    assert authority.actor.expires_at > clock[0]
    assert authority.calls == (0 if already_expired else 1)


def test_valid_identity_refresh_cannot_extend_original_request_budget() -> None:
    engine, actor, _authority, _clock = fixture(timedelta(milliseconds=100))
    refreshed = engine._fresh_actor(actor)
    assert refreshed.request_deadline == actor.request_deadline


@pytest.mark.parametrize("change", ["account", "session_expired", "mfa_stale", "mfa_absent"])
def test_real_identity_and_mfa_failures_remain_denied(change: str) -> None:
    engine, actor, authority, clock = fixture()
    if change == "account":
        authority.actor = replace(authority.actor, account_id=str(uuid4()))
    elif change == "session_expired":
        authority.actor = replace(authority.actor, expires_at=clock[0])
    elif change == "mfa_stale":
        authority.actor = replace(authority.actor, auth_time=clock[0] - timedelta(minutes=5))
    else:
        authority.actor = replace(authority.actor, mfa=False)
    with pytest.raises(ManualError) as failure:
        engine._fresh_actor(actor)
    assert failure.value.code == "manual.identity_changed"
    assert failure.value.status == 403
