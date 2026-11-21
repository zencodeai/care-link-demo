"""Current, independently approved audit grants; never standing audit access."""

from datetime import datetime, timedelta
from typing import cast

from care_link_domain import Actor, ManualError

from ..store import Record, Transaction, instant, number, text
from ..values import digest, dt, object_value
from .authority import approval, current_human, human_account


def audit_reviewer(row: Record) -> bool:
    classes = row["authority_classes"]
    return isinstance(classes, list) and any(
        value in ("security", "privacy") for value in cast(list[object], classes)
    )


def grant_request_digest(data: Record) -> str:
    return digest({key: value for key, value in data.items() if key != "approval_receipt_id"})


def check_grant(
    tx: Transaction, actor: Actor, query: Record, now: datetime, *, epoch: int | None = None
) -> Record:
    current_human(tx, actor, now)
    grant = tx.get("gov_scope_grant", text(query, "grant_id"))
    if grant is None or grant["grantee_id"] != actor.account_id:
        raise ManualError("governance.audit_grant_required", 403)
    if (
        grant["revoked"] is not False
        or instant(grant, "expires_at") <= now
        or number(grant, "grantee_identity_revision") != actor.identity_revision
        or number(grant, "grantee_role_revision") != actor.role_revision
        or (epoch is not None and number(grant, "control_epoch") != epoch)
    ):
        raise ManualError("governance.audit_grant_stale", 403)
    request = object_value(grant["request"])
    # Revalidate the actual creator and independent authority for every use,
    # rather than letting a durable grant outlive its human approval.
    creator = tx.get("gov_human", text(grant, "grantor_id"))
    creator_guard = tx.get("principal", text(grant, "grantor_id"))
    if (
        creator is None
        or creator_guard is None
        or creator["active"] is not True
        or creator_guard["revoked"] is not False
        or creator["identity_revision"] != creator_guard["identity_revision"]
        or grant["grantor_human_id"] != creator["human_id"]
        or grant["grantor_identity_revision"] != creator_guard["identity_revision"]
        or grant["grantor_role_revision"] != creator_guard["role_revision"]
        or creator_guard["role"] not in {"governance", "security"}
    ):
        raise ManualError("governance.audit_grant_stale", 403)
    receipt = tx.get("gov_approval", text(grant, "approval_receipt_id"))
    if receipt is None:
        raise ManualError("governance.approval_required", 403)
    reviewer = tx.get("gov_human", text(receipt, "approver_account_id"))
    reviewer_guard = tx.get("principal", text(receipt, "approver_account_id"))
    if (
        receipt["purpose"] != "scoped_access_grant"
        or receipt["request_digest"] != grant_request_digest(request)
        or receipt["active"] is not True
        or instant(receipt, "expires_at") <= now
        or reviewer is None
        or reviewer_guard is None
        or reviewer["active"] is not True
        or reviewer_guard["revoked"] is not False
        or reviewer_guard["role"] not in {"security", "governance"}
        or reviewer_guard["identity_revision"] != reviewer["identity_revision"]
        or reviewer["human_id"] != receipt["approver_human_id"]
        or reviewer["human_id"] == creator["human_id"]
        or not audit_reviewer(reviewer)
    ):
        raise ManualError("governance.approval_stale", 403)
    window = object_value(receipt["scope"])
    if (
        query.get("purpose") != "audit"
        or not instant(grant, "window_from")
        <= dt(query["from"])
        < dt(query["to"])
        <= instant(grant, "window_to")
        or dt(query["to"]) > now
        or dt(window["from"]) != instant(grant, "window_from")
        or dt(window["to"]) != instant(grant, "window_to")
    ):
        raise ManualError("governance.audit_window_denied", 403)
    return grant


def grant_values(tx: Transaction, actor: Actor, data: Record, now: datetime) -> Record:
    human = current_human(tx, actor, now)
    scope = object_value(data["scope"])
    expiry = dt(data["expires_at"])
    if (
        scope["purpose"] != "audit"
        or scope["recipient_id"] != data["grantee_id"]
        or scope["fields"] != data["fields"]
        or not now < expiry <= now + timedelta(minutes=15)
    ):
        raise ManualError("governance.audit_grant_scope", 422)
    # This endpoint releases canonical metadata only. Content scope does not
    # silently turn it into transcript/plan browsing.
    if data["fields"]:
        raise ManualError("governance.audit_content_not_supported", 422)
    receipt = approval(
        tx,
        actor,
        text(data, "approval_receipt_id"),
        "scoped_access_grant",
        grant_request_digest(data),
        now,
    )
    reviewer = human_account(tx, text(receipt, "approver_account_id"))
    if not audit_reviewer(reviewer):
        raise ManualError("governance.audit_approval_authority_required", 403)
    window = object_value(receipt["scope"])
    if not {"from", "to"}.issubset(window) or not dt(window["from"]) < dt(window["to"]) <= now:
        raise ManualError("governance.audit_window_required", 422)
    if expiry > instant(receipt, "expires_at"):
        raise ManualError("governance.approval_expiry", 422)
    target = tx.get("principal", text(data, "grantee_id"))
    target_human = tx.get("gov_human", text(data, "grantee_id"))
    if (
        target is None
        or target_human is None
        or target["revoked"] is not False
        or target_human["active"] is not True
        or target["role"] != "auditor"
        or target["identity_revision"] != target_human["identity_revision"]
    ):
        raise ManualError("governance.auditor_required", 403)
    return {
        "grantor_id": actor.account_id,
        "grantor_human_id": human["human_id"],
        "grantor_identity_revision": actor.identity_revision,
        "grantor_role_revision": actor.role_revision,
        "grantee_id": data["grantee_id"],
        "grantee_identity_revision": target["identity_revision"],
        "grantee_role_revision": target["role_revision"],
        "scope": scope,
        "request": data,
        "approval_receipt_id": data["approval_receipt_id"],
        "window_from": dt(window["from"]),
        "window_to": dt(window["to"]),
        "created_at": now,
        "expires_at": expiry,
        "revoked": False,
        "revision": 1,
    }
