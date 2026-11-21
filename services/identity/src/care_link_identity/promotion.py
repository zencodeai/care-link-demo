"""Current, action-bound promotion MFA; independent identity comes from host custody."""

from datetime import datetime
from uuid import UUID

from care_link_domain import Actor, ManualError

from .crypto import digest
from .domain import instant, stamp
from .manual import ManualIdentityAuthority
from .service import IdentityService


def consume_promotion_proof(
    service: IdentityService,
    actor: Actor,
    ceremony_id: str,
    proposal_id: str,
    binding_digest: str,
    expires_at: datetime,
) -> None:
    """Consume exactly one verified ceremony for an immutable host proposal.

    A retry for the same exact proposal/binding/expiry is safe; changing any of
    them requires a new ceremony. This does not itself approve serving.
    """
    for value in (ceremony_id, proposal_id):
        if str(UUID(value)) != value:
            raise ManualError("recovery.promotion_proof_required")
    fresh = ManualIdentityAuthority(service).current(actor)
    now = service.clock()
    if (
        fresh.account_id != actor.account_id
        or fresh.role not in {"security", "governance"}
        or not fresh.mfa
        or not 0 <= (now - fresh.auth_time).total_seconds() < 300
        or not 0 < (expires_at - now).total_seconds() <= 300
    ):
        raise ManualError("recovery.promotion_proof_required")
    exact = {
        "proposal_id": proposal_id,
        "binding_digest": binding_digest,
        "expires_at": stamp(expires_at),
    }
    with service.store.transaction() as tx:
        session = tx.get("session", digest(actor.credential_ref))
        ceremony = tx.get("ceremony", ceremony_id)
        if (
            session is None
            or ceremony is None
            or session.get("account_id") != actor.account_id
            or ceremony.get("session_hash") != digest(actor.credential_ref)
            or ceremony.get("purpose") != "promotion"
            or ceremony.get("resource_id") != proposal_id
            or ceremony.get("expected_revision") != session.get("revision")
            or ceremony.get("state") != "verified"
            or ceremony.get("verified_mfa") is not True
            or not 0 <= (now - instant(ceremony.get("verified_auth_time"))).total_seconds() < 300
            or instant(ceremony["expires_at"]) <= now
            or (
                ceremony.get("promotion_receipt") is not None
                and ceremony["promotion_receipt"] != exact
            )
        ):
            raise ManualError("recovery.promotion_proof_required")
        ceremony["promotion_receipt"] = exact
        tx.put("ceremony", ceremony_id, ceremony)
