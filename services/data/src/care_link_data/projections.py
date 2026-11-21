"""Explicit permitted views; persistence rows are never serialized wholesale."""

from collections.abc import Callable

from care_link_domain import CipherPort, ManualError

from .store import Record, Transaction, instant, number, text
from .values import object_value, stamp


def session_view(tx: Transaction, session: Record, guard: Record) -> Record:
    control = tx.get("control", "demo")
    subject = tx.peek("subject", text(session, "persona_id"))
    if subject is None:
        raise ManualError("manual.subject_unavailable", 404)
    degraded = ["ai_unavailable"] if control and control["mode"] == "ai_disabled" else []
    if session["transport"] != "connected":
        degraded.append("channel_disconnected")
    return {
        "id": session["id"],
        "revision": str(number(session, "revision")),
        "tags": {"environment": "demo", "population": "synthetic"},
        "participant_kind": session["participant_kind"],
        "jurisdiction": session["jurisdiction"],
        "locale": session["locale"],
        "service_phase": session["service_phase"],
        "transport": session["transport"],
        "control_epoch": str(number(guard, "control_epoch")),
        "owner_id": session["owner_id"],
        "degraded_reasons": degraded,
        "tier": session["tier"],
        "unresolved": session["unresolved"],
        "persona_id": session["persona_id"],
        "subject_id": session["persona_id"],
        "subject_revision": str(number(subject, "authority_revision")),
    }


def queue_view(tx: Transaction, queue: Record) -> Record:
    session = tx.get("session", text(queue, "session_id"))
    if session is None:
        raise ManualError("manual.corrupt_state", 503)
    return {
        "session_id": queue["session_id"],
        "ticket_id": queue["id"],
        "revision": str(number(queue, "revision")),
        "mode": queue["mode"],
        "state": queue["status"],
        "requested_at": stamp(instant(queue, "requested_at")),
        "next_review_at": stamp(instant(queue, "next_review_at")),
        "wait_estimate_seconds": None,
        "connection_confirmed": session["service_phase"] == "human_controlled",
    }


def assignment_view(assignment: Record) -> Record:
    return {
        "id": assignment["id"],
        "session_id": assignment["session_id"],
        "worker_id": assignment["worker_id"],
        "revision": str(number(assignment, "revision")),
        "reservation_id": assignment["reservation_id"],
        "expires_at": stamp(instant(assignment, "expires_at")),
        "state": assignment["status"],
        "control_epoch": str(number(assignment, "control_epoch")),
    }


def message_view(message: Record, cipher: CipherPort) -> Record:
    return {
        "id": message["id"],
        "session_id": message["session_id"],
        "revision": str(number(message, "revision")),
        "sender_id": message["sender_id"],
        "kind": message["kind"],
        "text": cipher.decrypt(text(message, "text_ciphertext")),
        "sources": [],
        "control_epoch": str(number(message, "control_epoch")),
        "created_at": stamp(instant(message, "created_at")),
    }


def assessment_view(assessment: Record) -> Record:
    return {
        "session_id": assessment["session_id"],
        "revision": str(number(assessment, "revision")),
        "fields": assessment["field_states"],
        "tier": assessment["tier"],
        "tier_set_digest": assessment["tier_set_digest"],
        "content_class": "stub",
        "situation_factors": {},
        "human_reasons": assessment["human_reasons"],
    }


def assertion_view(assertion: Record, cipher: CipherPort, parse: Callable[[str], object]) -> Record:
    return {
        "id": assertion["id"],
        "revision": str(number(assertion, "revision")),
        "subject_id": assertion["subject_id"],
        "field": assertion["field_key"],
        "value": object_value(parse(cipher.decrypt(text(assertion, "value_ciphertext")))),
        "author_id": assertion["author_id"],
        "source": None,
        "verification": assertion["verification"],
        "supersedes_id": assertion["supersedes_id"],
        "effective_at": stamp(instant(assertion, "effective_at")),
    }


def event_view(event: Record) -> Record:
    return {
        "event_id": event["event_id"],
        "sequence": str(number(event, "sequence")),
        "occurred_at": stamp(instant(event, "occurred_at")),
        "type": event["type"],
        "resource_id": event["resource_id"],
        "resource_revision": str(number(event, "resource_revision")),
    }
