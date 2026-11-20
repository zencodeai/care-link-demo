"""Fresh identity bridge and exact, one-use continuation recovery ceremony.

The bridge is an in-process verification/composition adapter. Network deployment
must replace direct calls with authenticated request-bound identity evidence.
"""

import secrets
from dataclasses import replace
from uuid import UUID, uuid4

from care_link_domain import Actor, ManualError

from . import stepup
from .crypto import digest
from .domain import IdentityError, instant, text
from .service import IdentityService


def start_recovery(
    service: IdentityService, raw_session: str, binding: str, request: dict[str, object]
) -> dict[str, object]:
    if set(request) != {"session_id", "family_id", "expected_revision"}:
        raise IdentityError("identity.invalid_recovery", 422)
    for field in ("session_id", "family_id"):
        if str(UUID(text(request, field))) != request[field]:
            raise IdentityError("identity.invalid_recovery", 422)
    ceremony = stepup.start(
        service,
        raw_session,
        binding,
        {
            "purpose": "continuation_recover",
            "resource_id": request["session_id"],
            "expected_revision": request["expected_revision"],
        },
    )
    with service.store.transaction() as tx:
        stored = tx.get("ceremony", text(ceremony, "ceremony_id"))
        if stored is None or stored["session_hash"] != digest(raw_session):
            raise IdentityError("identity.invalid_recovery")
        stored["family_id"] = request["family_id"]
        tx.put("ceremony", text(ceremony, "ceremony_id"), stored)
    return ceremony


class ManualIdentityAuthority:
    def __init__(self, service: IdentityService) -> None:
        self.service = service

    def authenticate(self, raw_session: str) -> Actor:
        try:
            session = self.service.current(raw_session)
        except IdentityError as error:
            raise ManualError(error.code, error.status) from error
        return Actor(
            account_id=text(session, "account_id"),
            role=text(session, "role"),
            identity_revision=int(text(session, "revision")),
            role_revision=int(text(session, "role_revision")),
            auth_time=instant(session["auth_time"]),
            mfa=session.get("mfa") is True,
            browser_session_digest=digest(raw_session),
            transport_generation=0,
            credential_ref=raw_session,
            expires_at=instant(session["expires_at"]),
            identity_evidence_id=str(uuid4()),
            review_run_id=self.service.review_context.run_id
            if self.service.review_context
            else None,
            review_slot_id=self.service.review_context.slot_id
            if self.service.review_context
            else None,
            review_origin=self.service.review_context.origin
            if self.service.review_context
            else None,
        )

    def current(self, actor: Actor) -> Actor:
        fresh = self.authenticate(actor.credential_ref)
        return replace(
            fresh,
            transport_generation=actor.transport_generation,
            identity_evidence_id=actor.identity_evidence_id,
            request_deadline=actor.request_deadline,
        )

    def csrf(self, actor: Actor, origin: str | None, supplied: str | None) -> None:
        try:
            current = self.service.current(actor.credential_ref)
        except IdentityError as error:
            raise ManualError(error.code, error.status) from error
        if (
            origin != self.service.origin
            or not supplied
            or not secrets.compare_digest(supplied, text(current, "csrf"))
        ):
            raise ManualError("manual.csrf_denied")

    def consent_proof(
        self,
        actor: Actor,
        proof_id: str,
        subject_id: str,
        session_id: str,
        purpose: str,
        basis: str,
    ) -> None:
        """Validate an action/subject-bound MFA ceremony, never a relationship.

        Business custody separately verifies own-subject/session binding. The
        verified grant retains its explicit expiry; ceremony expiry governs new
        grants and does not silently shorten an already-created sharing grant.
        """
        for value in (proof_id, subject_id, session_id):
            if str(UUID(value)) != value:
                raise ManualError("manual.consent_proof_required")
        expected = {
            "plan": "plan_edit",
            "referral": "referral_consent",
            "follow_up": "follow_up_consent",
        }.get(purpose)
        if basis != "self" or expected is None:
            raise ManualError("manual.consent_proof_required")
        current = self.current(actor)
        with self.service.store.transaction() as tx:
            session = tx.get("session", digest(current.credential_ref))
            ceremony = tx.get("ceremony", proof_id)
            now = self.service.clock()
            if (
                session is None
                or ceremony is None
                or session.get("account_id") != actor.account_id
                or session.get("role") != "pid"
                or session.get("mfa") is not True
                or ceremony.get("session_hash") != digest(current.credential_ref)
                or ceremony.get("purpose") != expected
                or ceremony.get("resource_id") != subject_id
                or ceremony.get("state") != "verified"
                or ceremony.get("expected_revision") != session.get("revision")
                or instant(ceremony["expires_at"]) <= now
                or not 0 <= (now - instant(session["auth_time"])).total_seconds() <= 300
            ):
                raise ManualError("manual.consent_proof_required")

    def recovery_proof(
        self, actor: Actor, ceremony_id: str, session_id: str, family_id: str
    ) -> None:
        self.current(actor)
        with self.service.store.transaction() as tx:
            session = tx.get("session", digest(actor.credential_ref))
            ceremony = tx.get("ceremony", ceremony_id)
            if (
                session is None
                or ceremony is None
                or session.get("account_id") != actor.account_id
                or ceremony.get("session_hash") != digest(actor.credential_ref)
                or ceremony.get("purpose") != "continuation_recover"
                or ceremony.get("resource_id") != session_id
                or ceremony.get("family_id") != family_id
                or ceremony.get("state") != "verified"
                or ceremony.get("recovery_consumed") is True
                or instant(ceremony["expires_at"]) <= self.service.clock()
                or (self.service.clock() - instant(session["auth_time"])).total_seconds() > 300
            ):
                raise ManualError("manual.fresh_recovery_required")
            ceremony["recovery_consumed"] = True
            tx.put("ceremony", ceremony_id, ceremony)
