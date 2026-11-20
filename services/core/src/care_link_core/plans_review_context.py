"""Server-bound synthetic plans workspaces; public context conveys no authority."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit
from uuid import UUID

from care_link_domain import Actor, ManualError

from .review_context import Record, ReviewContexts

ROLES = {
    "pid": "pid",
    "carer": "carer",
    "professional": "professional_participant",
    "worker1": "worker",
}
FIELDS = {
    "mode",
    "authentication_mode",
    "environment",
    "run_id",
    "slot_id",
    "account_id",
    "provider_subject",
    "role",
    "state",
    "expires_at",
    "started_at",
    "session_id",
    "plan_id",
    "recipient_id",
}


def utc(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("UTC timestamp required")
    result = datetime.fromisoformat(value)
    if result.tzinfo != UTC:
        raise ValueError("UTC timestamp required")
    return result


def canonical_uuid(value: object) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Canonical UUID required")
    return value


def validate_entry(origin: str, entry: Record) -> None:
    if set(entry) != FIELDS:
        raise ValueError("Exact plans review fields required")
    run_id = canonical_uuid(entry["run_id"])
    slot = str(entry["slot_id"])
    parsed = urlsplit(origin)
    expected = f"r{UUID(run_id).hex}-{slot}.plans.localhost"
    if (
        parsed.scheme != "https"
        or parsed.hostname != expected
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
        or parsed.netloc != expected + (f":{parsed.port}" if parsed.port else "")
        or (parsed.port is not None and not 1 <= parsed.port <= 65535)
    ):
        raise ValueError("Exact registered local HTTPS origin required")
    if (
        entry["mode"] != "plans"
        or entry["authentication_mode"] != "automatic_review"
        or entry["environment"] != "synthetic-review"
        or slot not in ROLES
        or entry["role"] != ROLES[slot]
        or entry["state"] not in {"active", "closing", "closed"}
    ):
        raise ValueError("Synthetic plans review binding required")
    for name in ("account_id", "provider_subject", "session_id"):
        canonical_uuid(entry[name])
    for name in ("plan_id", "recipient_id"):
        if entry[name] is not None:
            canonical_uuid(entry[name])
    duration = (utc(entry["expires_at"]) - utc(entry["started_at"])).total_seconds()
    if not 0 < duration <= 14400:
        raise ValueError("Review must have a bounded lifetime of at most four hours")


class PlansReviewContexts(ReviewContexts):
    def __init__(
        self,
        path: Path,
        legacy_origin: str,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        super().__init__(path, legacy_origin)
        self.clock = clock

    def entries(self) -> dict[str, Record]:
        try:
            entries = super().entries()
            for origin, entry in entries.items():
                if not isinstance(cast(object, entry), dict):
                    raise ValueError("Invalid registry record")
                validate_entry(origin, entry)
            return entries
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise ManualError("manual.review_registry_invalid", 503) from exc

    def context(self, host: str) -> Record:
        origin = self.origin(host)
        if origin == self.legacy_origin:
            return {"enabled": False}
        entry = self.entries()[origin]
        state = entry["state"]
        if self.clock() >= utc(entry["expires_at"]) and state == "active":
            state = "closed"
        return {
            "enabled": True,
            "origin": origin,
            "mode": "plans",
            "authentication_mode": "automatic_review",
            "environment": "synthetic-review",
            "run_state": state,
            **{
                key: entry[key]
                for key in ("run_id", "slot_id", "account_id", "role", "expires_at", "started_at")
            },
        }

    def selection(self, host: str, actor: Actor) -> Record:
        origin = self.origin(host)
        if origin == self.legacy_origin:
            raise ManualError("manual.review_context_unavailable", 404)
        entry = self.entries()[origin]
        if entry["state"] != "active" or not utc(entry["started_at"]) <= self.clock() < utc(
            entry["expires_at"]
        ):
            raise ManualError("manual.review_context_unavailable", 409)
        if (
            actor.account_id != entry["account_id"]
            or actor.role != entry["role"]
            or actor.review_run_id != entry["run_id"]
            or actor.review_slot_id != entry["slot_id"]
            or actor.review_origin != origin
        ):
            raise ManualError("manual.review_actor_mismatch", 403)
        return {key: entry[key] for key in ("session_id", "plan_id", "recipient_id")}
