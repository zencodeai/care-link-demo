"""Local restriction-only credential disposal; provider outages are not revocation."""

from datetime import datetime
from typing import cast

from .crypto import digest
from .domain import PRIVILEGED_ROLES, IdentityError, Transaction, instant
from .session_policy import marked_interactive_session


def locally_restricted(tx: Transaction, session: dict[str, object], now: datetime) -> bool:
    try:
        if session.get("revoked") is True or instant(session["expires_at"]) <= now:
            return True
        if session.get("role") in PRIVILEGED_ROLES and (
            session.get("mfa") is not True
            or (
                not marked_interactive_session(session, now)
                and (now - instant(session["last_seen"])).total_seconds() >= 900
            )
        ):
            return True
        matches = [
            (key, row)
            for key, row in tx.items("account")
            if row.get("account_id") == session.get("account_id")
            and row.get("subject") == session.get("subject")
        ]
        if len(matches) != 1:
            return True
        account_key, account = matches[0]
        marker = tx.get("account_marker", cast(str, session["account_id"]))
        if (
            account.get("enabled") is not True
            or account.get("blocked") is True
            or (marker and marker.get("blocked") is True)
            or account.get("revision") != session.get("revision")
            or account.get("role_revision") != session.get("role_revision")
            or not isinstance(account.get("roles"), list)
            or session.get("role") not in cast(list[object], account["roles"])
            or instant(account.get("access_review_due_at")) <= now
        ):
            return True
        # Account keys bind the actual issuer and subject. A quarantined foreign
        # issuer must not erase an unrelated issuer's usable local credential.
        return any(
            row.get("quarantined") is True
            and digest(issuer + "\0" + cast(str, session["subject"])) == account_key
            for issuer, row in tx.items("issuer")
        )
    except (IdentityError, KeyError, TypeError):
        return True  # malformed local authority cannot justify bearer retention


def fence_session_material(tx: Transaction, session_hash: str) -> None:
    """Remove only this session's dependent positive material."""
    for key, row in tx.items("intent"):
        if row.get("session_hash") == session_hash and (
            row.get("state") != "failed"
            or row.get("verifier")
            or row.get("nonce")
            or row.get("access_token")
        ):
            row.update({"state": "failed", "verifier": "", "nonce": "", "access_token": ""})
            tx.put("intent", key, row)
    for key, row in tx.items("proof"):
        if row.get("session_hash") == session_hash:
            tx.delete("proof", key)
    for key, row in tx.items("ceremony"):
        if row.get("session_hash") == session_hash and row.get("state") != "expired":
            row["state"] = "expired"
            tx.put("ceremony", key, row)


def maintenance_restricted(tx: Transaction, intent: dict[str, object]) -> bool:
    """Owner recovery permits overdue review, never negative local authority."""
    matches = [
        (key, row)
        for key, row in tx.items("account")
        if row.get("account_id") == intent.get("account_id")
    ]
    if len(matches) != 1:
        return True
    key, account = matches[0]
    marker = tx.get("account_marker", cast(str, intent["account_id"]))
    roles = account.get("roles")
    return bool(
        account.get("enabled") is not True
        or account.get("blocked") is True
        or account.get("deprovisioned_at") is not None
        or (marker and marker.get("blocked") is True)
        or account.get("revision") != intent.get("revision")
        or account.get("role_revision") != intent.get("role_revision")
        or not isinstance(roles, list)
        or "operator" not in roles
        or any(
            row.get("quarantined") is True
            and isinstance(account.get("subject"), str)
            and digest(issuer + "\0" + cast(str, account["subject"])) == key
            for issuer, row in tx.items("issuer")
        )
    )
