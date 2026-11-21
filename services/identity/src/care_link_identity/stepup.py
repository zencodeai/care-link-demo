"""Action/resource-bound MFA ceremonies and post-cooling second authentication."""

from datetime import timedelta
from uuid import uuid4

from .crypto import digest
from .domain import IdentityError, instant, stamp, text
from .service import IdentityService


def start(
    service: IdentityService, raw_session: str, binding: str, request: dict[str, object]
) -> dict[str, object]:
    session, now = service.current(raw_session), service.clock()
    if request["expected_revision"] != session["revision"]:
        raise IdentityError("identity.revision_conflict", 409)
    high = request["purpose"] in {"export", "delete", "identity_link"}
    ceremony_id = str(uuid4())
    with service.store.transaction() as tx:
        # Starting again for the exact action after cooling gives the second proof
        # intent; it does not silently restart or bypass the first ceremony.
        for key, candidate in tx.items("ceremony"):
            if (
                candidate.get("session_hash") == digest(raw_session)
                and candidate.get("purpose") == request["purpose"]
                and candidate.get("resource_id") == request["resource_id"]
                and candidate.get("state") == "cooling_off"
                and instant(candidate["expires_at"]) > now
                and instant(candidate["not_before"]) <= now
            ):
                ceremony_id = key
                break
        existing = tx.get("ceremony", ceremony_id)
        if existing is None:
            existing = {
                "session_hash": digest(raw_session),
                "purpose": request["purpose"],
                "resource_id": request["resource_id"],
                "expected_revision": request["expected_revision"],
                "state": "pending",
                "high": high,
                "not_before": stamp(now),
                "expires_at": stamp(now + timedelta(minutes=15)),
                "first_proof": None,
            }
            tx.put("ceremony", ceremony_id, existing)
    login, _state = service.login_start(
        text(session, "role"), binding, ceremony_id, digest(raw_session)
    )
    return {
        "ceremony_id": ceremony_id,
        "state": existing["state"],
        "not_before": existing["not_before"],
        "expires_at": existing["expires_at"],
        "authorization_url": login["authorization_url"],
    }


def confirm(
    service: IdentityService, raw_session: str, request: dict[str, object]
) -> dict[str, object]:
    session, now = service.current(raw_session), service.clock()
    with service.store.transaction() as tx:
        ceremony = tx.get("ceremony", text(request, "ceremony_id"))
        reference = tx.get("intent", text(request, "proof_intent_id"))
        proof = tx.get("intent", text(reference, "state_hash")) if reference else None
        if (
            ceremony is None
            or reference is None
            or proof is None
            or ceremony.get("session_hash") != digest(raw_session)
            or proof.get("session_hash") != digest(raw_session)
            or proof.get("ceremony_id") != request["ceremony_id"]
            or proof.get("state") != "completed"
            or proof.get("proof_consumed") is not False
            or proof.get("proof_subject") != session["subject"]
            or proof.get("proof_mfa") is not True
            or request["expected_revision"] != session["revision"]
            or ceremony["expected_revision"] != session["revision"]
            or instant(ceremony["expires_at"]) <= now
            or ceremony.get("state") in {"verified", "expired"}
            or not 0 <= (now - instant(proof["proof_auth_time"])).total_seconds() <= 300
        ):
            raise IdentityError("identity.invalid_ceremony")
        if ceremony["high"] is True and ceremony["first_proof"] is None:
            ceremony.update(
                {
                    "first_proof": request["proof_intent_id"],
                    "first_proof_auth_time": proof["proof_auth_time"],
                    "first_verified_at": stamp(now),
                    "state": "cooling_off",
                    "not_before": stamp(now + timedelta(minutes=5)),
                }
            )
        elif ceremony["high"] is True and (
            now < instant(ceremony["not_before"])
            or instant(proof["proof_auth_time"]) < instant(ceremony["not_before"])
            or request["proof_intent_id"] == ceremony["first_proof"]
        ):
            raise IdentityError("identity.cooling_or_fresh_proof_required")
        else:
            ceremony.update(
                {
                    "state": "verified",
                    "verified_proof": request["proof_intent_id"],
                    "verified_auth_time": proof["proof_auth_time"],
                    "verified_at": stamp(now),
                    "verified_mfa": proof["proof_mfa"],
                    "verified_factors": proof.get("proof_factors", []),
                }
            )
            # The action-bound ceremony is the proof; a general browser session
            # never receives ambient AL3 authority for unrelated operations.
        proof["proof_consumed"] = True
        tx.put("intent", text(reference, "state_hash"), proof)
        tx.put("ceremony", text(request, "ceremony_id"), ceremony)
    return {
        "ceremony_id": request["ceremony_id"],
        "state": ceremony["state"],
        "not_before": ceremony["not_before"],
        "expires_at": ceremony["expires_at"],
        "authorization_url": None,
    }
