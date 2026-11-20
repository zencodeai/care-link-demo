"""Explicit bounded synthetic-review policy; ordinary identity policy is unchanged."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID

from .domain import IdentityError, instant, stamp
from .review_context import ReviewContext

MAX_REVIEW_LIFETIME = timedelta(hours=4)
AUTOMATIC_REVIEW = "automatic_review"
SLOTS = {"pid", "carer", "professional", "worker1"}


@dataclass(frozen=True)
class InteractiveReviewPolicy:
    context: ReviewContext
    not_before: datetime
    expires_at: datetime
    enabled: bool = False

    def __post_init__(self) -> None:
        context = self.context
        parsed = urlsplit(context.origin)
        hostname = parsed.hostname or ""
        subject = context.provider_subject
        if (
            self.enabled is not True
            or context.slot_id not in SLOTS
            or context.mode != "plans"
            or context.authentication_mode != AUTOMATIC_REVIEW
            or context.environment != "synthetic-review"
            or subject is None
            or str(UUID(subject)) != subject
            or parsed.hostname != f"r{UUID(context.run_id).hex}-{context.slot_id}.plans.localhost"
            or parsed.netloc != hostname + (f":{parsed.port}" if parsed.port else "")
            or self.not_before.tzinfo is None
            or self.expires_at.tzinfo is None
            or not timedelta(0) < self.expires_at - self.not_before <= MAX_REVIEW_LIFETIME
            or context.expires_at is None
            or instant(context.expires_at) != self.expires_at
        ):
            raise ValueError("Explicit bounded localhost synthetic interactive review required")

    def check(self, current: ReviewContext | None, now: datetime) -> None:
        if (
            current is None
            or current != self.context
            or current.state != "active"
            or not self.not_before <= now < self.expires_at
        ):
            raise IdentityError("identity.interactive_review_unavailable", 401)

    def metadata(self) -> dict[str, object]:
        return {
            "authentication_mode": AUTOMATIC_REVIEW,
            "review_environment": "synthetic-review",
            "review_mode": "plans",
            "review_expires_at": stamp(self.expires_at),
            "review_not_before": stamp(self.not_before),
        }


def policy_for_context(
    context: ReviewContext,
    *,
    enabled: bool = False,
    lifetime: timedelta = MAX_REVIEW_LIFETIME,
) -> InteractiveReviewPolicy:
    if context.expires_at is None or not timedelta(0) < lifetime <= MAX_REVIEW_LIFETIME:
        raise ValueError("Explicit bounded review expiry required")
    expiry = instant(context.expires_at)
    start = instant(context.started_at) if context.started_at else expiry - lifetime
    return InteractiveReviewPolicy(context, start, expiry, enabled)


def marked_interactive_session(session: dict[str, object], now: datetime) -> bool:
    """Idle exemption only for fully marked server-issued, finite review sessions.

    This is not a permission decision: every existing account/issuer/revision
    restriction still runs, and requests independently recheck the live registry.
    """
    try:
        if session.get("authentication_mode") != AUTOMATIC_REVIEW or session.get("mfa") is not True:
            return False
        if session.get("origin") != session.get("review_origin"):
            return False
        context = ReviewContext(
            origin=str(session["review_origin"]),
            run_id=str(session["review_run_id"]),
            slot_id=str(session["review_slot_id"]),
            account_id=str(session["account_id"]),
            role=str(session["role"]),
            provider_subject=str(session["subject"]),
            mode=str(session["review_mode"]),
            authentication_mode=AUTOMATIC_REVIEW,
            environment=str(session["review_environment"]),
            expires_at=str(session["review_expires_at"]),
            started_at=str(session["review_not_before"]),
        )
        policy = policy_for_context(context, enabled=True)
        policy.check(context, now)
        return now < instant(session["expires_at"]) <= policy.expires_at
    except (ValueError, IdentityError, KeyError, TypeError):
        return False
