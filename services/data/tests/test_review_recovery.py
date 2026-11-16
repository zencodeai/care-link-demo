"""Real PostgreSQL review namespace/recovery behavior with declared port doubles.

The shared harness supplies explicit current identity/channel and PDP/journal test
ports; these tests qualify SQL/transaction behavior, not issued identity or OPA.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING
from uuid import uuid4

import psycopg
import pytest
from care_link_data import ReviewRunAdmin, apply_review_migration
from care_link_data.values import object_value
from care_link_domain import ManualError
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

if TYPE_CHECKING:
    from services.data.tests.conftest import Harness


def key() -> str:
    return str(uuid4())


@pytest.fixture
def review(harness: Harness) -> tuple[Harness, ReviewRunAdmin, str]:
    h = harness
    with psycopg.Connection[dict[str, object]].connect(h.database.admin, row_factory=dict_row) as c:
        apply_review_migration(c)
    admin = ReviewRunAdmin(
        h.database.admin,
        environment_id="test-" + key(),
        expected_database=conninfo_to_dict(h.database.admin)["dbname"],
        expected_journal_id=h.journal.head().journal_id,
    )
    rid = key()
    admin.create(rid, "manual-service", key())
    for name, slot in [
        ("participant", "participant"),
        ("worker", "worker1"),
        ("supervisor", "supervisor"),
        ("operator", "operator"),
    ]:
        actor = getattr(h, name)
        setattr(
            h,
            name,
            replace(
                actor,
                review_run_id=rid,
                review_slot_id=slot,
                review_origin=f"https://{slot}.review.localhost",
            ),
        )
    return h, admin, rid


def acknowledge(h: Harness, sid: str) -> dict[str, object]:
    session = h.service.session_read(h.participant, sid)
    template = h.service.disclosure_templates["en-CA"]
    h.service.session_disclosure(
        h.participant,
        key(),
        {
            "expected_revision": session["revision"],
            "template_id": template["id"],
            "template_digest": template["digest"],
            "locale": "en-CA",
            "acknowledged": True,
        },
        sid,
    )
    return h.service.session_read(h.participant, sid)


def save_intake(
    h: Harness, sid: str, value: str = "A fictional review situation"
) -> dict[str, object]:
    return h.service.review_draft_save(
        h.participant,
        key(),
        {
            "kind": "intake",
            "text": value,
            "expected_revision": "0",
        },
        sid,
    )


def prepare_intake(h: Harness, sid: str, draft: dict[str, object]) -> dict[str, object]:
    current = h.service.session_read(h.participant, sid)
    return h.service.review_intent_prepare(
        h.participant,
        key(),
        {
            "kind": "intake",
            "draft_revision": draft["revision"],
            "expected_revision": current["revision"],
            "expected_control_epoch": current["control_epoch"],
            "locale": "en-CA",
        },
        sid,
    )


def test_workspace_recovers_current_assignment_and_draft_after_reauthentication(review) -> None:
    h, _admin, rid = review
    assert h.service.review_workspace(h.participant)["conversation"] is None
    session = h.create()
    sid = str(session["id"])
    save_intake(h, sid)
    queue = h.service.session_human_request(
        h.participant,
        key(),
        {
            "expected_revision": session["revision"],
            "reason": "user_requested",
        },
        sid,
    )
    reserved = h.service.workforce_reserve(
        h.worker,
        key(),
        {
            "expected_revision": queue["revision"],
            "worker_id": h.worker.account_id,
        },
        sid,
    )
    accepted = h.service.workforce_accept(
        h.worker, key(), {"expected_revision": reserved["revision"]}, sid
    )
    h.worker = replace(h.worker, browser_session_digest="b" * 64)
    current = h.service.review_workspace(h.worker)
    assert current["run_id"] == rid
    assert object_value(current["conversation"])["owner_id"] is None
    assert object_value(current["assignment"])["revision"] == accepted["revision"]
    assert current["drafts"] == []
    h.participant = replace(h.participant, browser_session_digest="c" * 64)
    participant = h.service.review_workspace(h.participant)
    assert participant["drafts"][0]["text"] == "A fictional review situation"
    assert "A fictional review situation" not in str(
        h.read("SELECT text_ciphertext FROM core.review_draft")
    )


def test_reserved_assignment_recovers_without_disclosing_unaccepted_context(review) -> None:
    h, _admin, _rid = review
    session = h.create()
    sid = str(session["id"])
    queue = h.service.session_human_request(
        h.participant,
        key(),
        {
            "expected_revision": session["revision"],
            "reason": "user_requested",
        },
        sid,
    )
    reservation = h.service.workforce_reserve(
        h.worker,
        key(),
        {
            "expected_revision": queue["revision"],
            "worker_id": h.worker.account_id,
        },
        sid,
    )
    workspace = h.service.review_workspace(h.worker)
    assert workspace["conversation"] is None
    assert workspace["conversations"] == []
    assert object_value(workspace["assignment"])["id"] == reservation["id"]


def test_intent_identity_survives_lost_reply_and_reload_without_duplicate_turn(review) -> None:
    h, _admin, _rid = review
    sid = str(h.create()["id"])
    acknowledge(h, sid)
    draft = save_intake(h, sid)
    intent = prepare_intake(h, sid, draft)
    repeated = prepare_intake(h, sid, draft)
    assert repeated["operation_id"] == intent["operation_id"]
    payload = object_value(intent["payload"])
    first = h.service.session_turns(h.participant, str(intent["operation_id"]), payload, sid)
    h.participant = replace(h.participant, browser_session_digest="d" * 64)
    workspace = h.service.review_workspace(h.participant)
    assert workspace["drafts"][0]["text"] == ""
    assert workspace["drafts"][0]["revision"] == draft["revision"]
    assert workspace["pending_intents"][0]["operation_id"] == intent["operation_id"]
    assert workspace["pending_intents"][0]["state"] == "committed"
    assert workspace["disclosure_acknowledged"] is True
    assert workspace["intake_submitted"] is True
    replay = h.service.session_turns(h.participant, str(intent["operation_id"]), payload, sid)
    assert replay == first
    assert h.read("SELECT count(*) FROM core.turn WHERE session_id=%s", (sid,))[0][0] == 1


def test_different_draft_cannot_replace_an_uncertain_submission(review) -> None:
    h, _admin, _rid = review
    sid = str(h.create()["id"])
    acknowledge(h, sid)
    draft = save_intake(h, sid)
    old = prepare_intake(h, sid, draft)
    changed = h.service.review_draft_save(
        h.participant,
        key(),
        {
            "kind": "intake",
            "text": "A revised fictional situation",
            "expected_revision": draft["revision"],
        },
        sid,
    )
    with pytest.raises(ManualError, match="pending_operation"):
        prepare_intake(h, sid, changed)
    workspace = h.service.review_workspace(h.participant)
    assert workspace["pending_intents"][0]["operation_id"] == old["operation_id"]


def test_run_close_preserves_status_only_and_fresh_run_excludes_old_queue(review) -> None:
    h, admin, rid = review
    sid = str(h.create()["id"])
    acknowledge(h, sid)
    draft = save_intake(h, sid)
    intent = prepare_intake(h, sid, draft)
    h.service.session_turns(
        h.participant, str(intent["operation_id"]), object_value(intent["payload"]), sid
    )
    current = h.service.session_read(h.participant, sid)
    h.service.session_human_request(
        h.participant,
        key(),
        {
            "expected_revision": current["revision"],
            "reason": "user_requested",
        },
        sid,
    )
    admin.close(rid, key())
    assert (
        h.service.operation_status(h.participant, str(intent["operation_id"]))["state"]
        == "committed"
    )
    closed = h.service.review_workspace(h.participant)
    assert closed["conversation"] is None and closed["drafts"] == []
    assert closed["pending_intents"][0]["payload"] is None
    with pytest.raises(ManualError):
        h.service.session_read(h.participant, sid)
    new_run = key()
    admin.create(new_run, "manual-service", key())
    h.worker = replace(h.worker, review_run_id=new_run)
    assert h.service.queue_list(h.worker)["items"] == []
    with pytest.raises(ManualError):
        h.service.session_read(h.worker, sid)
    assert h.read("SELECT unresolved FROM core.session WHERE id=%s", (sid,))[0][0] is True


def test_legacy_context_cannot_read_or_queue_review_resources(review) -> None:
    h, _admin, _rid = review
    session = h.create()
    sid = str(session["id"])
    h.service.session_human_request(
        h.participant,
        key(),
        {
            "expected_revision": session["revision"],
            "reason": "user_requested",
        },
        sid,
    )
    legacy = replace(h.participant, review_run_id=None, review_slot_id=None, review_origin=None)
    with pytest.raises(ManualError):
        h.service.session_read(legacy, sid)
    worker = replace(h.worker, review_run_id=None, review_slot_id=None, review_origin=None)
    assert h.service.queue_list(worker)["items"] == []


def test_final_channel_loss_rolls_back_draft_effect(review, monkeypatch) -> None:
    h, _admin, _rid = review
    sid = str(h.create()["id"])
    original = h.service.cipher.encrypt

    def lose_channel(value: str) -> str:
        encoded = original(value)
        h.channels.closed.add(h.participant.account_id)
        return encoded

    monkeypatch.setattr(h.service.cipher, "encrypt", lose_channel)
    with pytest.raises(ManualError, match="stale_view"):
        save_intake(h, sid)
    assert h.read("SELECT count(*) FROM core.review_draft WHERE session_id=%s", (sid,))[0][0] == 0


def test_admin_metadata_idempotency_and_runtime_privileges(review) -> None:
    h, admin, rid = review
    closed_op = key()
    first = admin.close(rid, closed_op)
    assert admin.close(rid, closed_op) == first
    next_id = key()
    operation = key()
    created = admin.create(next_id, "manual-service", operation)
    assert admin.create(next_id, "manual-service", operation) == created
    with pytest.raises(ValueError):
        admin.create(key(), "manual-service", operation)
    with psycopg.connect(h.database.runtime) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("UPDATE core.review_run SET state='closed' WHERE id=%s", (next_id,))


def test_connected_owner_can_explicitly_prepare_fresh_channel_after_reload(review) -> None:
    from services.data.tests.test_manual import connected

    h, _admin, _rid = review
    before = connected(h)
    sid = str(before["id"])
    assignment = object_value(h.service.review_workspace(h.worker)["assignment"])
    h.worker = replace(h.worker, browser_session_digest="e" * 64)
    prepared = h.service.workforce_prepare_transfer(
        h.worker, key(), {"expected_revision": assignment["revision"]}, sid
    )
    assert object_value(prepared["assignment"])["state"] == "accepted"
    current = h.service.session_read(h.worker, sid)
    assert current["service_phase"] == "handoff_pending"
    assert current["owner_id"] == before["owner_id"]
    assert current["control_epoch"] == before["control_epoch"]
    assert current["unresolved"] is True
    assert h.service.review_workspace(h.worker)["handshake"]["worker_acknowledged"] is False


def test_prepared_cancellation_fences_late_packet_and_keeps_draft_usable(review) -> None:
    h, _admin, _rid = review
    sid = str(h.create()["id"])
    acknowledge(h, sid)
    draft = save_intake(h, sid)
    intent = prepare_intake(h, sid, draft)
    cancellation_key = key()
    cancelled = h.service.review_intent_cancel(
        h.participant, cancellation_key, {"operation_id": intent["operation_id"]}, sid
    )
    assert cancelled["state"] == "cancelled" and cancelled["payload"] is None
    assert (
        h.service.review_intent_cancel(
            h.participant, cancellation_key, {"operation_id": intent["operation_id"]}, sid
        )
        == cancelled
    )
    workspace = h.service.review_workspace(h.participant)
    replacement_draft = workspace["drafts"][0]
    assert replacement_draft["revision"] == str(int(draft["revision"]) + 1)
    assert replacement_draft["text"] == "A fictional review situation"
    with pytest.raises(ManualError, match="submission_intent_required"):
        h.service.session_turns(
            h.participant, str(intent["operation_id"]), object_value(intent["payload"]), sid
        )
    assert h.read("SELECT count(*) FROM core.turn WHERE session_id=%s", (sid,))[0][0] == 0
    replacement = prepare_intake(h, sid, replacement_draft)
    assert replacement["operation_id"] != intent["operation_id"]
    h.service.session_turns(
        h.participant, str(replacement["operation_id"]), object_value(replacement["payload"]), sid
    )
    assert h.read("SELECT count(*) FROM core.turn WHERE session_id=%s", (sid,))[0][0] == 1


def test_cancellation_cannot_erase_committed_effect_or_cross_principal(review) -> None:
    h, _admin, _rid = review
    sid = str(h.create()["id"])
    acknowledge(h, sid)
    draft = save_intake(h, sid)
    intent = prepare_intake(h, sid, draft)
    h.service.session_turns(
        h.participant, str(intent["operation_id"]), object_value(intent["payload"]), sid
    )
    with pytest.raises(ManualError, match="operation_not_cancellable"):
        h.service.review_intent_cancel(
            h.participant, key(), {"operation_id": intent["operation_id"]}, sid
        )
    assert (
        h.read(
            "SELECT cancelled_at FROM core.review_intent WHERE operation_id=%s",
            (intent["operation_id"],),
        )[0][0]
        is None
    )
    assert (
        h.service.operation_status(h.participant, str(intent["operation_id"]))["state"]
        == "committed"
    )
    current = h.service.session_read(h.participant, sid)
    queue = h.service.session_human_request(
        h.participant,
        key(),
        {
            "expected_revision": current["revision"],
            "reason": "user_requested",
        },
        sid,
    )
    reserved = h.service.workforce_reserve(
        h.worker,
        key(),
        {
            "expected_revision": queue["revision"],
            "worker_id": h.worker.account_id,
        },
        sid,
    )
    h.service.workforce_accept(h.worker, key(), {"expected_revision": reserved["revision"]}, sid)
    with pytest.raises(ManualError, match="not_found"):
        h.service.review_intent_cancel(
            h.worker, key(), {"operation_id": intent["operation_id"]}, sid
        )


def test_recovery_payload_is_hidden_after_current_assignment_rights_are_lost(review) -> None:
    from datetime import UTC, datetime, timedelta

    from care_link_data.values import stamp

    from services.data.tests.test_manual import connected

    h, _admin, _rid = review
    current = connected(h)
    sid = str(current["id"])
    draft = h.service.review_draft_save(
        h.worker,
        key(),
        {
            "kind": "message",
            "text": "A fictional worker-only draft",
            "expected_revision": "0",
        },
        sid,
    )
    intent = h.service.review_intent_prepare(
        h.worker,
        key(),
        {
            "kind": "message",
            "draft_revision": draft["revision"],
            "expected_revision": current["revision"],
            "expected_control_epoch": current["control_epoch"],
            "locale": "en-CA",
        },
        sid,
    )
    queue = h.service.queue_list(h.supervisor)["items"][0]
    h.service.workforce_observe(
        h.supervisor,
        key(),
        {
            "expected_revision": queue["revision"],
            "scope": "interrupt",
            "expires_at": stamp(datetime.now(UTC) + timedelta(minutes=1)),
        },
        sid,
    )
    current = h.service.session_read(h.supervisor, sid)
    h.service.workforce_takeover(
        h.supervisor,
        key(),
        {
            "expected_revision": current["revision"],
            "worker_id": h.supervisor.account_id,
        },
        sid,
    )
    workspace = h.service.review_workspace(h.worker)
    assert workspace["conversation"] is None and workspace["drafts"] == []
    assert workspace["pending_intents"][0]["operation_id"] == intent["operation_id"]
    assert workspace["pending_intents"][0]["payload"] is None


def test_nonce_consumption_rolls_back_when_view_loses_channel_before_commit(
    review, monkeypatch
) -> None:
    from care_link_data import workforce

    from services.data.tests.test_manual import accepted

    h, _admin, _rid = review
    session, assignment = accepted(h)
    sid = str(session["id"])
    prepared = h.service.workforce_prepare_transfer(
        h.worker, key(), {"expected_revision": assignment["revision"]}, sid
    )
    original = workforce.secrets.token_urlsafe

    def lose_channel(length: int) -> str:
        value = original(length)
        h.channels.closed.add(h.participant.account_id)
        return value

    monkeypatch.setattr(workforce.secrets, "token_urlsafe", lose_channel)
    with pytest.raises(ManualError, match="stale_view"):
        h.service.channel_challenge_read(h.participant, sid)
    assert (
        h.read(
            "SELECT participant_nonce_hash FROM workforce.channel_challenge WHERE id=%s",
            (prepared["challenge_id"],),
        )[0][0]
        is None
    )


def test_supervisor_interrupt_scope_recovers_after_reload_and_expires_truthfully(review) -> None:
    from datetime import UTC, datetime, timedelta

    from care_link_data.values import stamp

    from services.data.tests.test_manual import connected

    h, admin, rid = review
    connected_session = connected(h)
    sid = str(connected_session["id"])
    assert h.service.review_workspace(h.supervisor)["interrupt_expires_at"] is None
    queue = h.service.queue_list(h.supervisor)["items"][0]
    expiry = stamp(datetime.now(UTC) + timedelta(minutes=5))
    h.service.workforce_observe(
        h.supervisor,
        key(),
        {
            "expected_revision": queue["revision"],
            "scope": "observe",
            "expires_at": expiry,
        },
        sid,
    )
    assert h.service.review_workspace(h.supervisor)["interrupt_expires_at"] is None
    queue = h.service.queue_list(h.supervisor)["items"][0]
    h.service.workforce_observe(
        h.supervisor,
        key(),
        {
            "expected_revision": queue["revision"],
            "scope": "interrupt",
            "expires_at": expiry,
        },
        sid,
    )
    h.supervisor = replace(h.supervisor, browser_session_digest="f" * 64)
    recovered = h.service.review_workspace(h.supervisor, sid)
    assert recovered["interrupt_expires_at"] == expiry
    assert object_value(recovered["conversation"])["owner_id"] == h.worker.account_id
    assert h.service.review_workspace(h.worker, sid)["interrupt_expires_at"] is None
    with psycopg.connect(h.database.admin) as connection:
        connection.execute(
            "UPDATE core.session_acl SET valid_until=clock_timestamp()-interval '1 second' "
            "WHERE session_id=%s AND principal_id=%s AND purpose='interrupt'",
            (sid, h.supervisor.account_id),
        )
    assert h.service.review_workspace(h.supervisor, sid)["interrupt_expires_at"] is None
    admin.close(rid, key())
    assert h.service.review_workspace(h.supervisor)["interrupt_expires_at"] is None
