"""Private exact-role configuration and current workload route ownership."""

import json
import os
import stat
from pathlib import Path
from typing import cast

from care_link_workload_trust import BackendVerifier, PeerRule, UnixFenceClient

Record = dict[str, object]
ROLES = ("identity", "core", "data", "pdp", "journal")
FENCE_READER_GID = 22999
FENCE_RESTRICT_UID = 22001
AUTH_ROUTES = frozenset(
    {
        ("GET", "/v1/auth/csrf"),
        ("POST", "/v1/auth/login"),
        ("POST", "/v1/auth/review/login"),
        ("POST", "/v1/auth/review/verify"),
        ("GET", "/v1/auth/callback"),
        ("GET", "/v1/auth/session"),
        ("POST", "/v1/auth/logout"),
        ("POST", "/v1/auth/continuation-recovery"),
        ("POST", "/v1/auth/step-up"),
        ("POST", "/v1/auth/step-up/confirm"),
        ("GET", "/v1/auth/step-up/proof"),
    }
)
DATA_ACTIONS = (
    "own_reports_read",
    "plan_create",
    "plan_read",
    "plan_field_append",
    "plan_retire",
    "consent_grant",
    "consent_read",
    "consent_revoke",
    "directory_search",
    "directory_read",
    "directory_ingest",
    "directory_suspend",
    "session_create",
    "session_read",
    "session_disclosure",
    "session_turns",
    "session_assertions",
    "session_choices",
    "session_human_request",
    "session_end",
    "message_send",
    "messages_read",
    "queue_list",
    "operation_status",
    "session_events",
    "workforce_reserve",
    "workforce_accept",
    "workforce_prepare_transfer",
    "workforce_confirm_transfer",
    "workforce_transfer_failed",
    "workforce_observe",
    "workforce_takeover",
    "channel_ack",
    "channel_challenge_read",
    "continuation_issue",
    "continuation_rotate",
    "continuation_recover",
    "control_change",
    "authority",
    "review_workspace",
    "review_draft_save",
    "review_intent_prepare",
    "review_intent_cancel",
)


def spiffe(role: str) -> str:
    if role not in ROLES:
        raise ValueError("Unknown IMP-03 role")
    return "spiffe://care-link.demo/demo/" + role


def routes(role: str) -> dict[str, frozenset[tuple[str, str]]]:
    if role == "identity":
        return {
            "core": frozenset((method, "/bff/main" + path) for method, path in AUTH_ROUTES)
            | frozenset(
                ("POST", "/internal/v1/manual-identity/" + path)
                for path in ("authenticate", "csrf", "evidence")
            ),
            "data": frozenset(
                ("POST", "/internal/v1/manual-identity/" + path)
                for path in ("resolve", "current", "recovery", "consent-proof")
            ),
        }
    if role == "data":
        return {"core": frozenset(("POST", "/internal/v1/data/" + name) for name in DATA_ACTIONS)}
    if role == "core":
        return {"data": frozenset({("POST", "/internal/v1/channels/current")})}
    if role == "pdp":
        return {
            peer: frozenset({("POST", "/internal/v1/policy/evaluate")}) for peer in ("core", "data")
        }
    if role == "journal":
        return {
            "data": frozenset(
                {("POST", "/internal/v1/journal/head"), ("POST", "/internal/v1/journal/append")}
            )
        }
    raise ValueError("Unknown IMP-03 role")


def text(config: Record, key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError("Missing configured field: " + key)
    return value


def record(value: object) -> Record:
    if not isinstance(value, dict):
        raise ValueError("Configuration object required")
    return cast(Record, value)


def integer(config: Record, key: str) -> int:
    value = config.get(key)
    if type(value) is not int or value < 0:
        raise ValueError("Explicit nonnegative integer required: " + key)
    return value


def load(path: Path, *, owned: bool = True) -> Record:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise ValueError("Owner-only regular configuration required")
    if owned and info.st_uid != os.geteuid():
        raise ValueError("Configuration must belong to current custodian")
    value = json.loads(path.read_text(), object_pairs_hook=unique)
    return record(value)


def unique(pairs: list[tuple[str, object]]) -> Record:
    result: Record = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate configuration field")
        result[key] = value
    return result


def workload(config: Record, role: str) -> BackendVerifier:
    if text(config, "role") != role or integer(config, "uid") != os.geteuid():
        raise ValueError("Exact process role/custodian required")
    return BackendVerifier(
        integer(config, "proxy_uid"),
        tuple(PeerRule(spiffe(peer), pairs) for peer, pairs in routes(role).items()),
        UnixFenceClient(Path(text(config, "fence_socket")), integer(config, "fence_uid")),
        backend_uid=os.geteuid(),
        local_spiffe_id=spiffe(role),
    )
