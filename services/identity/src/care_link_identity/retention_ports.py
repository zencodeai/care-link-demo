"""Typed custody/authority ports for the accepted Option B metadata lifecycle."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol, cast

from .crypto import digest
from .domain import IdentityError, Transaction, instant, text


@dataclass(frozen=True)
class RetentionGrant:
    operator_id: str
    account_issuer: str
    account_revision: str
    role_revision: str
    session_hash: str
    action: str
    target_account_id: str
    issued_at: datetime
    expires_at: datetime


def validate_grant(tx: Transaction, grant: RetentionGrant, now: datetime) -> None:
    if not grant.issued_at <= now < grant.expires_at <= grant.issued_at + timedelta(seconds=1):
        raise IdentityError("identity.retention_grant_expired")
    session = tx.get("session", grant.session_hash)
    if (
        session is None
        or session.get("account_id") != grant.operator_id
        or session.get("revoked") is True
        or session.get("role") != "operator"
        or session.get("mfa") is not True
        or instant(session["expires_at"]) <= now
        or now - instant(session["auth_time"]) > timedelta(minutes=5)
    ):
        raise IdentityError("identity.retention_grant_revoked")
    account_key = next(
        (key for key, row in tx.items("account") if row.get("account_id") == grant.operator_id),
        None,
    )
    account = tx.get("account", account_key) if account_key else None
    issuer = tx.get("issuer", grant.account_issuer)
    if (
        account is None
        or account_key != digest(grant.account_issuer + "\0" + text(account, "subject"))
        or (issuer is not None and issuer.get("quarantined") is True)
        or account.get("enabled") is not True
        or not isinstance(account.get("roles"), list)
        or "operator" not in cast(list[object], account["roles"])
        or account.get("blocked") is True
        or account.get("revision") != grant.account_revision
        or account.get("role_revision") != grant.role_revision
        or session.get("revision") != grant.account_revision
        or session.get("role_revision") != grant.role_revision
        or account.get("access_review_due_at") is None
        or instant(account["access_review_due_at"]) <= now
    ):
        raise IdentityError("identity.retention_grant_revoked")


class RetentionAuthority(Protocol):
    def authorize(self, actor_proof: str, action: str, account_id: str) -> RetentionGrant:
        """Return an exact one-second current operator decision; deny if unavailable."""
        ...


class AccountCleanup(Protocol):
    def disable(self, subject: str, command_id: str) -> bool: ...
    def delete_profile(self, subject: str, command_id: str) -> bool: ...


@dataclass(frozen=True)
class BackupClearance:
    account_id: str
    fully_accounted: bool
    restorable_copies: int
    checked_at: datetime
    immutable_expiries_preserved: bool


class BackupCustody(Protocol):
    def clearance(self, account_id: str) -> BackupClearance: ...


RecordClass = Literal["security_log", "minimal_audit", "reviewer_evidence"]
