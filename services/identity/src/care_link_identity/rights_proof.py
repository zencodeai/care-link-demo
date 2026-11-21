"""Exact AL3 rights evidence; business custody owns request/download consumption."""

from datetime import timedelta
from typing import cast
from uuid import UUID

from care_link_domain import Actor, ManualError

from .crypto import digest
from .domain import IdentityError, instant
from .service import IdentityService


def verify_rights_proof(
    service: IdentityService, actor: Actor, ceremony_id: str, subject_id: str, kind: str
) -> None:
    """Recheck the actual second MFA and cooling interval on every invocation.

    This read supplies no ambient AL3 and grants no subject relationship. The
    data gateway independently verifies exact own-subject scope, binds a single
    request to this ceremony and consumes the download in its transaction.
    """
    try:
        if kind not in {"export", "delete"} or any(
            str(UUID(value)) != value for value in (ceremony_id, subject_id)
        ):
            raise ValueError("invalid rights binding")
        session = service.current(actor.credential_ref)
        now = service.clock()
        with service.store.transaction() as tx:
            ceremony = tx.get("ceremony", ceremony_id)
            if ceremony is None:
                raise ValueError("missing rights ceremony")
            factors = ceremony.get("verified_factors")
            factor_values = cast(list[object], factors) if isinstance(factors, list) else []
            if (
                session.get("account_id") != actor.account_id
                or session.get("role") != actor.role
                or session.get("revision") != str(actor.identity_revision)
                or session.get("role_revision") != str(actor.role_revision)
                or session.get("role") not in {"pid", "carer", "professional_participant"}
                or session.get("mfa") is not True
                or actor.expires_at <= now
                or actor.request_deadline is not None
                and actor.request_deadline <= now
                or ceremony.get("session_hash") != digest(actor.credential_ref)
                or ceremony.get("purpose") != kind
                or ceremony.get("resource_id") != subject_id
                or ceremony.get("expected_revision") != session.get("revision")
                or ceremony.get("state") != "verified"
                or ceremony.get("high") is not True
                or ceremony.get("verified_mfa") is not True
                or not factor_values
                or any(not isinstance(value, str) or not value for value in factor_values)
                or not isinstance(ceremony.get("first_proof"), str)
                or not isinstance(ceremony.get("verified_proof"), str)
                or ceremony["first_proof"] == ceremony["verified_proof"]
                or instant(ceremony["expires_at"]) <= now
                or instant(ceremony["not_before"])
                < instant(ceremony["first_verified_at"]) + timedelta(minutes=5)
                or instant(ceremony["verified_auth_time"]) < instant(ceremony["not_before"])
                or not 0 <= (now - instant(ceremony["verified_auth_time"])).total_seconds() <= 300
                or not 0 <= (now - instant(ceremony["verified_at"])).total_seconds() <= 300
                or not 0 <= (now - instant(session["auth_time"])).total_seconds() <= 300
            ):
                raise ValueError("stale or mismatched rights proof")
    except IdentityError as error:
        raise ManualError(error.code, error.status) from error
    except (ValueError, TypeError, KeyError) as error:
        raise ManualError("manual.rights_proof_required") from error
