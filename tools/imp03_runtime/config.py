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
    if role not in (*ROLES, "receiver", "training", "help"):
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


def protected_routes(config: Record, role: str) -> dict[str, frozenset[tuple[str, str]]]:
    """Select the same exact peer paths for backend and proxy authorization."""
    peers = routes(role) if role not in {"receiver", "training"} else {}
    if config.get("assistance_enabled") is True and role == "data":
        actions = (
            "task_create",
            "task_read",
            "task_cancel",
            "task_revise",
            "draft_read",
            "draft_review",
            "assistance_task_context",
            "assistance_draft_context",
        )
        peers["core"] = peers["core"] | frozenset(
            ("POST", "/internal/v1/data/" + action) for action in actions
        )
    if config.get("referral_enabled") is True:
        if role == "data":
            actions = (
                "referral_draft",
                "referral_read",
                "referral_context",
                "referral_sources",
                "referral_review",
                "referral_dispatch",
                "dispatch_read",
                "receipt_read",
                "dispatcher_send",
                "dispatch_reconcile",
            )
            peers["core"] = peers["core"] | frozenset(
                ("POST", "/internal/v1/data/" + action) for action in actions
            )
        if role == "identity":
            peers["receiver"] = frozenset(
                ("POST", "/internal/v1/manual-identity/" + name) for name in ("resolve", "current")
            )
        if role == "receiver":
            peers = {
                "data": frozenset(
                    ("POST", "/internal/v1/receiver/" + name) for name in ("send", "lookup")
                ),
                "core": frozenset(
                    ("POST", "/internal/v1/receiver/" + name)
                    for name in (
                        "receiver_inbox",
                        "receiver_package",
                        "receiver_detail",
                        "receiver_decide",
                    )
                ),
            }
    elif role == "receiver":
        raise ValueError("Receiver process requires explicit referral configuration")

    from tools.imp10_runtime.routes import (
        EVALUATION_ROUTES,
        HELP_AUTH_ROUTES,
        HELP_IDENTITY_ROUTES,
        TRAINING_IDENTITY_ROUTES,
        TRAINING_ROUTES,
    )

    enabled = config.get("training_enabled", False)
    if type(enabled) is not bool:
        raise ValueError("Explicit boolean training feature selection required")
    if enabled and role == "identity":
        peers["training"] = TRAINING_IDENTITY_ROUTES
    if enabled and role == "data":
        peers["core"] |= EVALUATION_ROUTES
    if role == "training":
        if not enabled:
            raise ValueError("Training process requires explicit training configuration")
        peers["core"] = TRAINING_ROUTES
    if role == "identity" and "help_identity" in config:
        record(config["help_identity"])
        peers["help"] = HELP_AUTH_ROUTES | HELP_IDENTITY_ROUTES
    return peers


def workload(config: Record, role: str) -> BackendVerifier:
    if text(config, "role") != role or integer(config, "uid") != os.geteuid():
        raise ValueError("Exact process role/custodian required")
    peers = protected_routes(config, role)
    return BackendVerifier(
        integer(config, "proxy_uid"),
        tuple(PeerRule(spiffe(peer), pairs) for peer, pairs in peers.items()),
        UnixFenceClient(Path(text(config, "fence_socket")), integer(config, "fence_uid")),
        backend_uid=os.geteuid(),
        local_spiffe_id=spiffe(role),
    )
