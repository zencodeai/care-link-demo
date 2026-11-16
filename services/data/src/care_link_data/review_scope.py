"""Current review namespace and submission guards at the gateway boundary."""

from datetime import datetime, timedelta

from care_link_domain import Actor, ChannelPort, CipherPort, ManualError

from .store import Record, Transaction, instant, text
from .values import canonical

STATUS_ACTIONS = frozenset({"operation_status", "review_workspace"})


def run_snapshot(tx: Transaction, actor: Actor) -> Record | None:
    if actor.review_run_id is None:
        if actor.review_slot_id is not None or actor.review_origin is not None:
            raise ManualError("manual.invalid_review_context")
        return None
    if not actor.review_slot_id or not actor.review_origin:
        raise ManualError("manual.invalid_review_context")
    run = tx.peek("review_run", actor.review_run_id)
    if run is None:
        raise ManualError("manual.review_run_unavailable", 404)
    return run


def scope_allowed(
    tx: Transaction, actor: Actor, action: str, session_id: str | None, run: Record | None
) -> bool:
    if actor.review_run_id is not None:
        if run is None or (run["state"] != "active" and action not in STATUS_ACTIONS):
            return False
    if session_id is not None and tx.review_available():
        member = tx.peek("review_member", session_id)
        return (member["run_id"] if member else None) == actor.review_run_id
    return True


def assert_channel_current(actor: Actor, channel: ChannelPort) -> None:
    if actor.review_run_id is not None and not channel.current(
        actor.account_id, actor.browser_session_digest, actor.transport_generation
    ):
        raise ManualError("manual.stale_view", 409)


def assert_submission_intent(
    tx: Transaction,
    actor: Actor,
    action: str,
    operation_id: str,
    session_id: str | None,
    payload: Record,
    cipher: CipherPort,
    now: datetime,
) -> None:
    if actor.review_run_id is None or action not in {"session_turns", "message_send"}:
        return
    intent = tx.peek("review_intent", operation_id)
    if (
        intent is None
        or intent.get("cancelled_at") is not None
        or intent["principal_id"] != actor.account_id
        or intent["session_id"] != session_id
        or intent["action"] != action
        or instant(intent, "created_at") + timedelta(days=1) <= now
        or cipher.decrypt(text(intent, "payload_ciphertext")) != canonical(payload)
    ):
        raise ManualError("manual.submission_intent_required", 409)
