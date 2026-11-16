"""Offline account binding; the caller supplies separately authorized store custody."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from .crypto import digest
from .domain import PARTICIPANT_ROLES, PRIVILEGED_ROLES, IdentityError, Store, stamp


def provision_account(
    store: Store,
    issuer: str,
    subject: str,
    account_id: str,
    roles: list[str],
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> None:
    """Bind one exact issued subject without provider/custody/signing-key access.

    This function is deliberately absent from browser/internal HTTP routes. The
    supplied store must belong to an explicitly authorized provisioning target.
    Existing bindings are refused, never adopted, overwritten or reset.
    """
    if not set(roles) <= PRIVILEGED_ROLES | PARTICIPANT_ROLES:
        raise IdentityError("identity.invalid_role")
    key = digest(issuer + "\0" + subject)
    with store.transaction() as tx:
        if tx.get("account", key) is not None:
            raise IdentityError("identity.provision_conflict", 409)
        tx.put(
            "account",
            key,
            {
                "account_id": account_id,
                "subject": subject,
                "roles": roles,
                "created_at": stamp(clock()),
                "reviewed_at": stamp(clock()),
                "access_review_due_at": stamp(clock() + timedelta(days=30)),
                "enabled": True,
                "revision": "1",
                "role_revision": "1",
            },
        )
