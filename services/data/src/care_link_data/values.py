"""Canonical metadata encoding and safe projections, independent of SQL/HTTP."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from care_link_domain import ManualError

Record = dict[str, object]
PARTICIPANTS = frozenset({"pid", "carer", "professional_participant"})
WORKFORCE = frozenset({"worker", "supervisor"})
ROLES: dict[str, frozenset[str]] = {
    **{
        name: PARTICIPANTS
        for name in (
            "session_create",
            "session_disclosure",
            "session_turns",
            "session_assertions",
            "session_choices",
            "session_human_request",
            "session_end",
            "continuation_issue",
            "continuation_rotate",
            "continuation_recover",
            "continuation_bootstrap",
        )
    },
    **{
        name: WORKFORCE
        for name in (
            "queue_list",
            "workforce_reserve",
            "workforce_accept",
            "workforce_prepare_transfer",
            "workforce_confirm_transfer",
            "workforce_transfer_failed",
        )
    },
    "review_workspace": PARTICIPANTS | WORKFORCE,
    "review_draft_save": PARTICIPANTS | WORKFORCE,
    "review_intent_prepare": PARTICIPANTS | WORKFORCE,
    "review_intent_cancel": PARTICIPANTS | WORKFORCE,
    "workforce_observe": frozenset({"supervisor"}),
    "workforce_takeover": frozenset({"supervisor"}),
    "control_change": frozenset({"operator", "security"}),
    "manual_identity_restrict": frozenset({"operator", "security"}),
    "manual_queue_review": frozenset({"operator"}),
    **{
        name: PARTICIPANTS | WORKFORCE
        for name in (
            "session_read",
            "messages_read",
            "message_send",
            "session_events",
            "channel_challenge_read",
            "channel_ack",
            "operation_status",
        )
    },
}


# Exact IMP-04 public operation roles; relationship labels grant no authority.
ROLES.update(
    {
        "own_reports_read": PARTICIPANTS,
        "plan_create": frozenset({"pid"}),
        "plan_read": frozenset(
            {"professional_participant", "pid", "worker", "carer", "supervisor"}
        ),
        "plan_field_append": frozenset({"pid", "worker"}),
        "plan_retire": frozenset({"pid"}),
        "consent_grant": frozenset({"carer", "pid", "professional_participant"}),
        "consent_read": frozenset(
            {"professional_participant", "pid", "worker", "carer", "supervisor"}
        ),
        "consent_revoke": frozenset({"carer", "pid", "professional_participant"}),
        "directory_search": frozenset(
            {"professional_participant", "pid", "worker", "carer", "supervisor"}
        ),
        "directory_read": frozenset(
            {"professional_participant", "pid", "worker", "carer", "supervisor"}
        ),
        "directory_ingest": frozenset({"operator", "governance"}),
        "directory_suspend": frozenset({"governance", "security"}),
    }
)


ROLES.update(
    {
        name: WORKFORCE
        for name in (
            "referral_sources",
            "referral_draft",
            "referral_review",
            "referral_dispatch",
            "dispatcher_send",
            "dispatch_authorize",
            "dispatch_consume",
            "dispatch_observe",
            "dispatch_reconcile",
        )
    }
)
ROLES.update(
    {
        name: WORKFORCE
        for name in (
            "referral_read",
            "referral_context",
            "dispatch_read",
            "receipt_read",
        )
    }
)


# Optional assistance never grants new actor roles or business effects.
ROLES.update(
    {
        name: PARTICIPANTS | WORKFORCE
        for name in (
            "task_create",
            "task_read",
            "task_cancel",
            "task_revise",
            "draft_read",
            "draft_review",
            "assistance_status",
            "assistance_task_context",
            "assistance_draft_context",
        )
    }
)


ROLES.update(
    {
        **{
            name: PARTICIPANTS | WORKFORCE
            for name in (
                "post_crisis_record",
                "followup_create",
                "followup_read",
                "followup_bind_anchor",
                "followup_cancel",
                "outcome_append",
                "outcomes_read",
            )
        },
        **{
            name: PARTICIPANTS
            for name in (
                "participant_inbox",
                "inbox_message_read",
                "rights_create",
                "rights_read",
                "export_download",
            )
        },
        "hold_create": frozenset({"governance"}),
        "hold_release": frozenset({"governance"}),
    }
)
LIFECYCLE_ACTIONS = frozenset(
    {
        "post_crisis_record",
        "followup_create",
        "followup_read",
        "followup_bind_anchor",
        "followup_cancel",
        "outcome_append",
        "outcomes_read",
        "participant_inbox",
        "inbox_message_read",
        "rights_create",
        "rights_read",
        "export_download",
        "hold_create",
        "hold_release",
    }
)


def stamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def token_digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ManualError("manual.invalid_revision", 422)
    number = int(value)
    if not 0 <= number <= 9223372036854775807 or str(number) != str(value):
        raise ManualError("manual.invalid_revision", 422)
    return number


def dt(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise ManualError("manual.corrupt_time", 503)


def object_value(value: object) -> Record:
    if not isinstance(value, dict):
        raise ManualError("manual.corrupt_state", 503)
    return cast(Record, value)


@dataclass(frozen=True)
class Outcome:
    contract: str
    value: Record
    resource_id: str | None = None
    session_id: str | None = None
    sensitive_once: bool = False


ROLES["referral_read"] = PARTICIPANTS | WORKFORCE
ROLES["referral_context"] = PARTICIPANTS | WORKFORCE
