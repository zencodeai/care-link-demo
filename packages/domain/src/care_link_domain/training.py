"""Deterministic observations for the fictional training artifact."""

import hashlib
import json
from datetime import datetime
from typing import cast
from uuid import UUID, uuid5

from .ports import ManualError

Record = dict[str, object]
MODES = (
    "accept",
    "reject",
    "partial",
    "delay",
    "drop_after_store",
    "receipt_unavailable",
    "poisoned_feed",
    "channel_drop",
    "regional_outage",
)
CHANNELS = ("sms", "voice", "mobile", "relay", "interpretation")
DIRECTORY_STATES = (
    "normal",
    "temporary_closure",
    "regional_outage",
    "holiday_hours",
    "severe_weather",
    "api_failure",
    "conflicting_source",
)
ARTIFACT = {
    "version": 1,
    "environment": "demo",
    "population": "synthetic",
    "fixture_modes": list(MODES),
    "channels": list(CHANNELS),
    "directory_states": list(DIRECTORY_STATES),
}


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def admit_artifact(content: bytes, expected: str) -> str:
    if len(content) > 4096 or hashlib.sha256(content).hexdigest() != expected:
        raise ValueError("Training artifact pin mismatch")
    if canonical(json.loads(content)) != canonical(ARTIFACT):
        raise ValueError("Unsupported training artifact")
    return expected


def channel_observation(
    scenario_id: str,
    channel: str,
    locale: str,
    *,
    worker_confirmed: bool,
    participant_confirmed: bool,
    dropped: bool,
) -> Record:
    """Build a rehearsal observation with no routable address or credential."""
    if channel not in CHANNELS or locale not in {"en-CA", "fr-CA"}:
        raise ManualError("training.unknown_channel", 422)
    return {
        "message_id": str(uuid5(UUID(scenario_id), channel)),
        "locale": locale,
        "channel": channel,
        "simulated": True,
        "delivery": "dropped" if dropped else "internal_observation",
        "connection": "confirmed_in_simulation"
        if worker_confirmed and participant_confirmed and not dropped
        else "unconnected",
        "reported_input_verified": False,
        "credential_issued": False,
    }


def exercise(scenario_id: str, fixture: Record) -> Record:
    """Re-execute fictional rules. The result is evidence, never a service command."""
    if set(fixture) != {"artifact_digest", "locale", "fixture_mode", "business_clock_at"}:
        raise ValueError("Invalid training inputs")
    mode, locale = cast(str, fixture["fixture_mode"]), cast(str, fixture["locale"])
    if mode not in MODES or locale not in {"en-CA", "fr-CA"}:
        raise ValueError("Unsupported training mode or locale")
    clock = fixture["business_clock_at"]
    if not isinstance(clock, str) or not clock.endswith("Z"):
        raise ValueError("Training clock must be UTC")
    datetime.fromisoformat(clock)
    # A receipt records the fictional transport observation. The human decision
    # remains distinct and a partial decision keeps its exact fixture fields.
    send, lookup, decision = {
        "accept": ("received", "received", "accepted"),
        "reject": ("received", "received", "rejected"),
        "partial": ("received", "received", "partial"),
        "delay": ("unknown", "pending", "pending"),
        "drop_after_store": ("unknown", "received", "pending"),
        "receipt_unavailable": ("unknown", "unsupported", "pending"),
    }.get(mode, ("not_requested", "not_requested", "not_requested"))
    dropped = mode in {"channel_drop", "regional_outage"}
    directory = [
        {
            "state": state,
            "source_revision": "1",
            "availability": "reported_normal" if state == "normal" else "unconfirmed",
            "fallback": state != "normal",
        }
        for state in DIRECTORY_STATES
    ]
    return {
        "scenario_id": scenario_id,
        "artifact_digest": fixture["artifact_digest"],
        "business_clock_at": clock,
        "locale": locale,
        "fixture_mode": mode,
        "capture_kind": "deterministic_fixture",
        "receiver": {
            "send": send,
            "lookup": lookup,
            "decision": decision,
            "accepted_fields": ["support_preference"] if decision == "partial" else [],
        },
        "channels": [
            channel_observation(
                scenario_id,
                channel,
                locale,
                worker_confirmed=True,
                participant_confirmed=not dropped,
                dropped=dropped,
            )
            for channel in CHANNELS
        ],
        "directory": {
            "states": directory,
            "feed": "quarantined" if mode == "poisoned_feed" else "fixture",
        },
        "effects": {
            "external_contact": "suppressed",
            "emergency_target": "denied",
            "serving_write": "suppressed",
            "model_request": "suppressed",
            "identity_link": "disabled",
        },
    }
