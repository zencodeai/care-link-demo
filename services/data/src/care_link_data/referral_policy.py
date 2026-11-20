"""Rebuild exact referral metadata for preliminary and final policy checks."""

from typing import TYPE_CHECKING, cast

from care_link_domain import Actor

from .consent import current_fields, owns_subject
from .engine import Engine
from .planning_policy import directory_policy_binding
from .store import Record, Transaction, instant, number, text
from .values import object_value, stamp

if TYPE_CHECKING:
    from .dispatches import Dispatches


def enrich_referral_policy(
    engine: Engine,
    tx: Transaction,
    actor: Actor,
    action: str,
    data: Record,
    snapshot: Record,
    request: Record,
) -> None:
    service = cast("Dispatches", engine)
    scope, facts = object_value(request["scope"]), object_value(request["authority_facts"])
    scope["purpose"] = "referral"
    referral = None
    dispatch = tx.peek("dispatch", text(data, "dispatch_id")) if data.get("dispatch_id") else None
    referral_id = data.get("referral_id", data.get("draft_id"))
    if dispatch:
        referral_id = dispatch["referral_id"]
    if isinstance(referral_id, str):
        referral = tx.peek("referral", referral_id)
    recipient = (
        text(referral, "recipient_service_id") if referral else data.get("recipient_service_id")
    )
    selected = referral["selected"] if referral else data.get("selected", [])
    scope["fields"] = sorted(
        {text(object_value(raw), "field") for raw in cast(list[object], selected)}
    )
    session = object_value(snapshot["session"]) if snapshot.get("session") else None
    if isinstance(recipient, str):
        scope["recipient_id"] = recipient
        directory_policy_binding(
            tx, recipient, request, service.directory_artifacts, service.clock()
        )
        facts["artifact_admitted"] = (
            facts["artifact_admitted"] and recipient in service.simulator_services
        )
    if (
        session
        and selected
        and action
        in {
            "referral_draft",
            "referral_review",
            "referral_dispatch",
            "referral_read",
            "referral_context",
            "dispatch_authorize",
            "dispatch_consume",
            "dispatcher_send",
        }
    ):
        allowed = (
            current_fields(tx, actor, session, service.clock())
            if not owns_subject(tx, actor, session)
            else None
        )
        facts["field_scope_allowed"] = all(
            not text(object_value(raw), "field").startswith("plan.")
            or allowed is None
            or object_value(raw)["field"] in allowed
            for raw in cast(list[object], selected)
        )
    if referral is not None:
        request["referral_payload_digest"] = referral["payload_digest"]
        grant_id = (
            text(dispatch, "consent_id")
            if dispatch
            else text(referral, "consent_id")
            if referral["consent_id"]
            else None
        )
        grant = service.matching_referral_consent(tx, referral, grant_id)
        review_id = (
            text(dispatch, "review_id")
            if dispatch
            else text(referral, "review_id")
            if referral["review_id"]
            else None
        )
        review = tx.peek("referral_review", review_id) if review_id else None
        require_consent = action in {
            "referral_review",
            "referral_dispatch",
            "dispatcher_send",
            "dispatch_authorize",
            "dispatch_consume",
        }
        require_review = action in {
            "referral_dispatch",
            "dispatcher_send",
            "dispatch_authorize",
            "dispatch_consume",
        }
        consent = object_value(facts["consent"])
        consent["required"], consent["valid"] = require_consent, grant is not None
        if grant:
            request["consent_id"] = grant["grant_id"]
            consent.update(
                {
                    "grant_id": grant["grant_id"],
                    "subject_revision": object_value(request["versions"])["subject"],
                    "scope_digest": grant["scope_hash"],
                    "effective_at": stamp(instant(grant, "effective_at")),
                    "expires_at": stamp(instant(grant, "expires_at")),
                    "recipient_id": recipient,
                    "fields": grant["fields"],
                    "subject_id": grant["subject_id"],
                    "session_id": grant["session_id"],
                    "purpose": "referral",
                }
            )
        review_fact = object_value(facts["review"])
        review_fact["required"] = require_review
        if review:
            request["review_id"] = review["id"]
            review_fact.update(
                {
                    "valid": review["decision"] == "accept"
                    and instant(review, "expires_at") > service.clock()
                    and review["exact_digest"] == referral["payload_digest"]
                    and review["reviewer_id"] == actor.account_id
                    and review["source_vector"] == service.referral_vector(tx, actor, referral),
                    "review_id": review["id"],
                    "payload_digest": review["exact_digest"],
                    "reviewer_id": review["reviewer_id"],
                    "expires_at": stamp(instant(review, "expires_at")),
                }
            )
        # Bind immutable generation metadata in addition to session/source guards.
        if session is not None:
            object_value(request["versions"])["resource"] = str(number(session, "revision"))
