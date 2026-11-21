"""Current independently provisioned human authority, never request-declared roles."""

from datetime import datetime
from typing import cast

from care_link_domain import Actor, ManualError

from ..store import Record, Transaction, instant, number, text


def current_human(
    tx: Transaction, actor: Actor, now: datetime, authority: str | None = None
) -> Record:
    if not actor.mfa or not 0 <= (now - actor.auth_time).total_seconds() < 300:
        raise ManualError("governance.fresh_mfa_required")
    return human_account(tx, actor.account_id, authority, actor.identity_revision)


def human_account(
    tx: Transaction, account_id: str, authority: str | None = None, revision: int | None = None
) -> Record:
    row = tx.peek("gov_human", account_id)
    principal = tx.peek("principal", account_id)
    if (
        row is None
        or principal is None
        or row["active"] is not True
        or principal["revoked"] is not False
        or number(row, "identity_revision") != number(principal, "identity_revision")
        or revision is not None
        and number(row, "identity_revision") != revision
        or authority is not None
        and authority not in cast(list[str], row["authority_classes"])
    ):
        raise ManualError("governance.human_authority_required")
    return row


def approval(
    tx: Transaction,
    actor: Actor,
    receipt_id: str,
    purpose: str,
    request_digest: str,
    now: datetime,
) -> Record:
    requester = current_human(tx, actor, now)
    row = tx.peek("gov_approval", receipt_id)
    if (
        row is None
        or row["active"] is not True
        or row["purpose"] != purpose
        or row["request_digest"] != request_digest
        or instant(row, "expires_at") <= now
    ):
        raise ManualError("governance.current_exact_approval_required")
    reviewer = human_account(tx, text(row, "approver_account_id"))
    eligibility = {
        "exception_create": ({"security"}, {"security", "governance"}),
        "incident_transition": ({"security"}, {"security", "governance", "operator"}),
        "scoped_access_grant": ({"security", "privacy"}, {"security", "governance"}),
    }
    classes, roles = eligibility.get(purpose, (set(), set()))
    principal = tx.peek("principal", text(row, "approver_account_id"))
    if (
        not classes
        or principal is None
        or principal["role"] not in roles
        or not classes.intersection(cast(list[str], reviewer["authority_classes"]))
    ):
        raise ManualError("governance.approver_authority_required")
    if (
        reviewer["human_id"] != row["approver_human_id"]
        or reviewer["human_id"] == requester["human_id"]
    ):
        raise ManualError("governance.independent_human_required")
    return row
