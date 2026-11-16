"""Durable state, real row-security/privilege, ownership and lost-response cases."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import psycopg
import pytest
from care_link_contracts import ContractError
from care_link_data import AESGCMContentCipher, PostgresStore
from care_link_data.values import stamp
from care_link_domain import ManualError

if TYPE_CHECKING:
    from services.data.tests.conftest import Harness


def key() -> str:
    return str(uuid4())


def requested(h: Harness) -> tuple[dict[str, object], dict[str, object]]:
    session = h.create()
    queue = h.service.session_human_request(
        h.participant,
        key(),
        {"expected_revision": session["revision"], "reason": "user_requested"},
        str(session["id"]),
    )
    return h.service.session_read(h.participant, str(session["id"])), queue


def accepted(h: Harness) -> tuple[dict[str, object], dict[str, object]]:
    session, queue = requested(h)
    sid = str(session["id"])
    reservation = h.service.workforce_reserve(
        h.worker,
        key(),
        {"expected_revision": queue["revision"], "worker_id": h.worker.account_id},
        sid,
    )
    assignment = h.service.workforce_accept(
        h.worker, key(), {"expected_revision": reservation["revision"]}, sid
    )
    return h.service.session_read(h.worker, sid), assignment


def connected(h: Harness) -> dict[str, object]:
    session, assignment = accepted(h)
    sid = str(session["id"])
    h.service.workforce_prepare_transfer(
        h.worker, key(), {"expected_revision": assignment["revision"]}, sid
    )
    session = h.service.session_read(h.participant, sid)
    participant = h.service.channel_challenge_read(h.participant, sid)
    worker = h.service.channel_challenge_read(h.worker, sid)

    def body(nonce):
        return {
            "expected_revision": session["revision"],
            "challenge_id": nonce["challenge_id"],
            "nonce": nonce["nonce"],
            "transport_generation": nonce["transport_generation"],
            "expected_control_epoch": nonce["control_epoch"],
        }

    worker_key = key()
    worker_body = body(worker)
    initial = h.service.channel_ack(h.worker, worker_key, worker_body, sid)
    assert initial["state"] == "one_party_acknowledged"
    h.service.channel_ack(h.participant, key(), body(participant), sid)
    refreshed = h.service.channel_ack(h.worker, worker_key, worker_body, sid)
    assert refreshed["state"] == "two_party_confirmed"
    return h.service.workforce_confirm_transfer(
        h.worker,
        key(),
        {
            "expected_revision": session["revision"],
            "assignment_id": assignment["id"],
            "channel_evidence_id": refreshed["evidence_id"],
            "worker_ack_id": refreshed["ack_id"],
            "expected_control_epoch": session["control_epoch"],
        },
        sid,
    )


def test_manual_service_connects_only_after_two_current_acks(harness: Harness) -> None:
    h = harness
    result = connected(h)
    assert result["service_phase"] == "human_controlled"
    assert result["owner_id"] == h.worker.account_id
    assert result["control_epoch"] == "1"
    sent = h.service.message_send(
        h.worker,
        key(),
        {
            "expected_revision": result["revision"],
            "expected_control_epoch": result["control_epoch"],
            "text": "Fictional worker message",
            "accepted_draft_id": None,
        },
        str(result["id"]),
    )
    assert sent["kind"] == "human_authored"
    page = h.service.messages_read(h.participant, str(result["id"]))
    assert page["items"][0]["text"] == "Fictional worker message"
    stored = h.read("SELECT text_ciphertext FROM core.message")
    assert "Fictional worker message" not in str(stored)
    assert h.read("SELECT count(*) FROM audit.event")[0][0] >= 14


def test_racing_reservations_leave_exactly_one_owner_candidate(harness: Harness) -> None:
    h = harness
    session, queue = requested(h)

    def reserve(actor):
        try:
            return h.service.workforce_reserve(
                actor,
                key(),
                {"expected_revision": queue["revision"], "worker_id": actor.account_id},
                str(session["id"]),
            )
        except ManualError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(reserve, [h.worker, h.supervisor]))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert h.read("SELECT count(*) FROM workforce.assignment WHERE status='reserved'")[0][0] == 1
    assert h.read("SELECT service_phase,owner_id FROM core.session")[0] == ("queued", None)


def test_unassigned_worker_and_observer_cannot_send_or_read_without_grant(harness: Harness) -> None:
    h = harness
    session, _queue = requested(h)
    sid = str(session["id"])
    with pytest.raises(ManualError):
        h.service.session_read(h.worker, sid)
    with pytest.raises(ManualError):
        h.service.session_read(h.supervisor, sid)
    assert not h.read("SELECT * FROM core.message")


def test_takeover_fences_old_owner_and_requires_new_handshake(harness: Harness) -> None:
    h = harness
    session = connected(h)
    sid = str(session["id"])
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
    taken = h.service.workforce_takeover(
        h.supervisor,
        key(),
        {"expected_revision": current["revision"], "worker_id": h.supervisor.account_id},
        sid,
    )
    assert taken["service_phase"] == "worker_assigned"
    assert int(taken["control_epoch"]) == int(session["control_epoch"]) + 1
    for actor in [h.worker, h.supervisor]:
        with pytest.raises(ManualError):
            h.service.message_send(
                actor,
                key(),
                {
                    "expected_revision": session["revision"],
                    "expected_control_epoch": session["control_epoch"],
                    "text": "stale output",
                    "accepted_draft_id": None,
                },
                sid,
            )
    with pytest.raises(ManualError):
        h.service.session_events(h.worker, sid)
    assert not h.read("SELECT * FROM core.message")


def test_one_party_and_dead_channel_never_connect(harness: Harness) -> None:
    h = harness
    session, assignment = accepted(h)
    sid = str(session["id"])
    prepared = h.service.workforce_prepare_transfer(
        h.worker, key(), {"expected_revision": assignment["revision"]}, sid
    )
    session = h.service.session_read(h.worker, sid)
    challenge = h.service.channel_challenge_read(h.worker, sid)
    with pytest.raises(ManualError, match="replacement"):
        h.service.channel_challenge_read(h.worker, sid)
    ack = h.service.channel_ack(
        h.worker,
        key(),
        {
            "expected_revision": session["revision"],
            "challenge_id": challenge["challenge_id"],
            "nonce": challenge["nonce"],
            "transport_generation": challenge["transport_generation"],
            "expected_control_epoch": challenge["control_epoch"],
        },
        sid,
    )
    with pytest.raises((ManualError, ValueError)):
        h.service.workforce_confirm_transfer(
            h.worker,
            key(),
            {
                "expected_revision": session["revision"],
                "assignment_id": assignment["id"],
                "channel_evidence_id": key(),
                "worker_ack_id": ack["ack_id"],
                "expected_control_epoch": session["control_epoch"],
            },
            sid,
        )
    assert prepared["challenge_id"] == challenge["challenge_id"]
    assert h.read("SELECT service_phase FROM core.session")[0][0] == "handoff_pending"


def test_disclosure_gate_and_deterministic_unknown_route(harness: Harness) -> None:
    h = harness
    session = h.create()
    sid = str(session["id"])
    turn = {
        "expected_revision": session["revision"],
        "client_turn_id": key(),
        "text": "Fictional situation",
        "locale": "en-CA",
    }
    with pytest.raises(ManualError, match="disclosure"):
        h.service.session_turns(h.participant, key(), turn, sid)
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
    session = h.service.session_read(h.participant, sid)
    turn["expected_revision"] = session["revision"]
    assessment = h.service.session_turns(h.participant, key(), turn, sid)
    assert assessment["situation_factors"] == {}
    assert assessment["content_class"] == "stub"
    assert "critical_unknown" in assessment["human_reasons"]
    assert h.read("SELECT status FROM workforce.queue_entry")[0][0] == "pending"


def test_continuation_lost_reply_recovery_is_same_principal_fresh_and_hash_only(
    harness: Harness,
) -> None:
    h = harness
    session = h.create()
    sid = str(session["id"])
    initial = h.service.continuation_bootstrap(h.participant, key(), sid)
    rotation_key = key()
    body = {
        "session_id": sid,
        "family_id": initial["family_id"],
        "token": initial["token"],
        "channel": "web",
        "expected_revision": "1",
    }
    replacement = h.service.continuation_rotate(h.participant, rotation_key, body)
    replay = h.service.continuation_rotate(h.participant, rotation_key, body)
    assert replay["state"] == "replacement_unavailable"
    assert "token" not in replay
    assert replacement["token"] not in str(h.read("SELECT * FROM access.continuation_token"))
    assert (
        h.service.operation_status(h.participant, rotation_key)["state"]
        == "replacement_unavailable"
    )
    proof = key()
    recovery = {
        "session_id": sid,
        "family_id": initial["family_id"],
        "ceremony_id": proof,
        "channel": "web",
        "expected_revision": "2",
    }
    with pytest.raises(ManualError):
        h.service.continuation_recover(h.participant, key(), recovery)
    h.authority.proofs[proof] = (h.participant.account_id, sid, str(initial["family_id"]))
    recovered = h.service.continuation_recover(h.participant, key(), recovery)
    assert recovered["family_id"] != initial["family_id"]
    assert recovered["assurance"] == "AL0"
    assert (
        h.read(
            "SELECT status FROM access.continuation_family WHERE id=%s", (initial["family_id"],)
        )[0][0]
        == "revoked"
    )


def test_idempotent_send_rebuilds_current_view_without_duplicate_effect(harness: Harness) -> None:
    h = harness
    session = connected(h)
    sid = str(session["id"])
    operation = key()
    body = {
        "expected_revision": session["revision"],
        "expected_control_epoch": session["control_epoch"],
        "text": "One logical message",
        "accepted_draft_id": None,
    }
    first = h.service.message_send(h.worker, operation, body, sid)
    second = h.service.message_send(h.worker, operation, body, sid)
    assert first == second
    assert h.read("SELECT count(*) FROM core.message")[0][0] == 1
    body["text"] = "Changed payload"
    with pytest.raises(ManualError, match="idempotency"):
        h.service.message_send(h.worker, operation, body, sid)


def test_audit_failure_rolls_back_private_state_and_result(harness: Harness) -> None:
    h = harness
    session = h.create()
    with psycopg.connect(h.database.admin) as admin:
        admin.execute(
            "REVOKE EXECUTE ON FUNCTION audit.append_event"
            "(uuid,uuid,uuid,text,text,text,text,jsonb,timestamptz,text,text,jsonb) "
            "FROM care_link_data_runtime"
        )
    try:
        with pytest.raises(ManualError):
            h.service.session_human_request(
                h.participant,
                key(),
                {"expected_revision": session["revision"], "reason": "user_requested"},
                str(session["id"]),
            )
        with pytest.raises(ManualError):
            h.service.session_read(h.participant, str(session["id"]))
        assert not h.read("SELECT * FROM workforce.queue_entry")
        assert h.read("SELECT revision FROM core.session")[0][0] == 1
    finally:
        with psycopg.connect(h.database.admin) as admin:
            admin.execute(
                "GRANT EXECUTE ON FUNCTION audit.append_event"
                "(uuid,uuid,uuid,text,text,text,text,jsonb,timestamptz,text,text,jsonb) "
                "TO care_link_data_runtime"
            )


def test_pdp_and_journal_failures_release_no_private_success(harness: Harness) -> None:
    h = harness
    session = h.create()
    for target in [h.policy, h.journal]:
        target.fail = True
        with pytest.raises(ManualError):
            h.service.session_read(h.participant, str(session["id"]))
        target.fail = False
    h.policy.obligations = [{"kind": "require_human_review"}]
    with pytest.raises((ManualError, ContractError)):
        h.service.session_read(h.participant, str(session["id"]))
    assert h.read("SELECT count(*) FROM audit.event")[0][0] >= 1


def test_journal_success_db_failure_fences_every_subsequent_read(harness: Harness) -> None:
    h = harness
    session = h.create()
    with psycopg.connect(h.database.admin) as admin:
        admin.execute(
            "REVOKE EXECUTE ON FUNCTION audit.append_event"
            "(uuid,uuid,uuid,text,text,text,text,jsonb,timestamptz,text,text,jsonb) "
            "FROM care_link_data_runtime"
        )
    try:
        with pytest.raises(ManualError):
            h.service.control_change(
                h.operator,
                key(),
                {
                    "expected_revision": "1",
                    "mode": "restricted",
                    "reason": "operator_request",
                    "approval_id": None,
                },
            )
    finally:
        with psycopg.connect(h.database.admin) as admin:
            admin.execute(
                "GRANT EXECUTE ON FUNCTION audit.append_event"
                "(uuid,uuid,uuid,text,text,text,text,jsonb,timestamptz,text,text,jsonb) "
                "TO care_link_data_runtime"
            )
    assert h.journal.state.restriction_barrier == 1
    assert h.read("SELECT restriction_barrier FROM control.guard")[0][0] == 0
    with pytest.raises(ManualError, match="journal_barrier"):
        h.service.session_read(h.participant, str(session["id"]))


def test_silence_preserves_unresolved_and_explicit_end_never_resurrects(harness: Harness) -> None:
    h = harness
    session, _queue = requested(h)
    sid = str(session["id"])
    before = h.read("SELECT service_phase,unresolved,closed_at FROM core.session")[0]
    assert before == ("queued", True, None)
    current = h.service.session_read(h.participant, sid)
    h.service.session_end(
        h.participant,
        key(),
        {"expected_revision": current["revision"], "reason": "user_choice"},
        sid,
    )
    with pytest.raises(ManualError):
        h.service.session_human_request(
            h.participant, key(), {"expected_revision": "999", "reason": "user_requested"}, sid
        )
    assert h.read("SELECT service_phase,unresolved FROM core.session")[0] == ("ended", True)


def test_runtime_roles_rls_and_append_only_audit(harness: Harness) -> None:
    h = harness
    session = h.create()
    with psycopg.connect(h.database.runtime) as runtime:
        assert runtime.execute("SELECT count(*) FROM core.session").fetchone()[0] == 0
        role = runtime.execute(
            "SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls "
            "FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
        assert role == (False, False, False, False)
    for statement in [
        "DELETE FROM audit.event",
        "UPDATE audit.head SET digest=repeat('a',64)",
        "CREATE TABLE core.escape(id integer)",
        "TRUNCATE core.session",
    ]:
        with psycopg.connect(h.database.runtime) as runtime:
            with pytest.raises(psycopg.Error):
                runtime.execute(statement)
    assert h.service.session_read(h.participant, str(session["id"]))["id"] == session["id"]


def test_encryption_rejects_tamper_and_wrong_key() -> None:
    cipher = AESGCMContentCipher(b"a" * 32)
    encrypted = cipher.encrypt("Fictional text")
    assert cipher.decrypt(encrypted) == "Fictional text"
    assert cipher.encrypt("Fictional text") != encrypted
    with pytest.raises(ManualError):
        AESGCMContentCipher(b"b" * 32).decrypt(encrypted)
    with pytest.raises(ValueError):
        PostgresStore("dbname=bad sslmode=disable")


def test_payload_mutation_after_policy_cannot_change_committed_message(
    harness: Harness, monkeypatch
) -> None:
    h = harness
    session = connected(h)
    body = {
        "expected_revision": session["revision"],
        "expected_control_epoch": session["control_epoch"],
        "text": "Original authorized text",
        "accepted_draft_id": None,
    }
    original = h.policy.evaluate

    def mutate(request):
        body["text"] = "Changed after permit input"
        return original(request)

    monkeypatch.setattr(h.policy, "evaluate", mutate)
    result = h.service.message_send(h.worker, key(), body, str(session["id"]))
    assert result["text"] == "Original authorized text"
    assert body["text"] == "Changed after permit input"


def test_terminal_rejection_key_cannot_become_successful_after_disclosure(harness: Harness) -> None:
    h = harness
    session = h.create()
    sid = str(session["id"])
    operation = key()
    turn = {
        "expected_revision": session["revision"],
        "client_turn_id": key(),
        "text": "Fictional text",
        "locale": "en-CA",
    }
    with pytest.raises(ManualError, match="disclosure"):
        h.service.session_turns(h.participant, operation, turn, sid)
    assert h.service.operation_status(h.participant, operation)["state"] == "rejected"
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
    with pytest.raises(ManualError, match="operation_rejected"):
        h.service.session_turns(h.participant, operation, turn, sid)
    assert not h.read("SELECT * FROM core.turn")


def test_lost_database_commit_acknowledgement_reconciles_one_message(
    harness: Harness, monkeypatch
) -> None:
    from contextlib import contextmanager

    h = harness
    session = connected(h)
    sid = str(session["id"])
    operation = key()
    body = {
        "expected_revision": session["revision"],
        "expected_control_epoch": session["control_epoch"],
        "text": "Committed once",
        "accepted_draft_id": None,
    }
    original = h.service.store.transaction
    lost = False

    @contextmanager
    def ambiguous(*args, **kwargs):
        nonlocal lost
        with original(*args, **kwargs) as tx:
            yield tx
        if kwargs.get("locked", True) and not lost:
            lost = True
            raise ManualError("manual.commit_unknown", 503)

    monkeypatch.setattr(h.service.store, "transaction", ambiguous)
    with pytest.raises(ManualError, match="commit_unknown"):
        h.service.message_send(h.worker, operation, body, sid)
    assert h.service.operation_status(h.worker, operation)["state"] == "committed"
    result = h.service.message_send(h.worker, operation, body, sid)
    assert result["text"] == "Committed once"
    assert h.read("SELECT count(*) FROM core.message")[0][0] == 1


def test_current_acl_revocation_blocks_later_participant_disclosure(harness: Harness) -> None:
    h = harness
    session = h.create()
    with psycopg.connect(h.database.admin) as admin:
        admin.execute(
            "UPDATE core.session_acl SET revoked_at=now() WHERE session_id=%s", (session["id"],)
        )
    with pytest.raises(ManualError):
        h.service.session_read(h.participant, str(session["id"]))


def test_expired_reservation_requeues_without_resetting_request_time(harness: Harness) -> None:
    h = harness
    session, queue = requested(h)
    sid = str(session["id"])
    reserved = h.service.workforce_reserve(
        h.worker,
        key(),
        {"expected_revision": queue["revision"], "worker_id": h.worker.account_id},
        sid,
    )
    with psycopg.connect(h.database.admin) as admin:
        admin.execute(
            "UPDATE workforce.assignment SET expires_at=now() WHERE id=%s", (reserved["id"],)
        )
    with pytest.raises(ManualError, match="expired"):
        h.service.workforce_accept(
            h.worker, key(), {"expected_revision": reserved["revision"]}, sid
        )
    current = h.service.session_read(h.participant, sid)
    h.service.review_queue(
        h.operator, key(), {"session_id": sid, "expected_revision": current["revision"]}
    )
    assert h.read("SELECT status,requested_at FROM workforce.queue_entry")[0][0] == "pending"
    assert (
        stamp(h.read("SELECT requested_at FROM workforce.queue_entry")[0][0])
        == queue["requested_at"]
    )
    assert h.read("SELECT status FROM workforce.assignment")[0][0] == "expired"
    assert h.read("SELECT service_phase,unresolved FROM core.session")[0] == ("queued", True)


def test_journalled_principal_restriction_stops_current_worker(harness: Harness) -> None:
    h = harness
    session = connected(h)
    h.service.restrict_principal(
        h.operator, key(), {"principal_id": h.worker.account_id, "expected_identity_revision": "1"}
    )
    assert h.journal.records[0]["restriction"]["kind"] == "identity_revoke"
    assert h.read(
        "SELECT revoked,identity_revision FROM control.principal_guard WHERE principal_id=%s",
        (h.worker.account_id,),
    )[0] == (True, 2)
    with pytest.raises(ManualError):
        h.service.session_read(h.worker, str(session["id"]))
    assert h.service.session_read(h.participant, str(session["id"]))["unresolved"] is True


def test_inventory_registers_encrypted_children_and_closes_exact_parent_anchor(
    harness: Harness,
) -> None:
    h = harness
    session = connected(h)
    sid = str(session["id"])
    h.service.message_send(
        h.worker,
        key(),
        {
            "expected_revision": session["revision"],
            "expected_control_epoch": session["control_epoch"],
            "text": "Fictional durable copy",
            "accepted_draft_id": None,
        },
        sid,
    )
    copies = h.read(
        "SELECT aggregate_type,anchor_at,expires_at,encryption_key_ref,state "
        "FROM lifecycle.copy ORDER BY aggregate_type"
    )
    assert len(copies) == 2
    assert all(
        row[1:3] == (None, None) and row[3].startswith("sha256:") and row[4] == "anchor_pending"
        for row in copies
    )
    assert h.read("SELECT count(*) FROM lifecycle.dependency")[0][0] == 1
    current = h.service.session_read(h.participant, sid)
    h.service.session_end(
        h.participant,
        key(),
        {"expected_revision": current["revision"], "reason": "user_choice"},
        sid,
    )
    assert (
        h.read(
            "SELECT count(*) FROM lifecycle.copy WHERE state='retained' "
            "AND expires_at=anchor_at+interval '7 days'"
        )[0][0]
        == 2
    )


def test_audit_chain_rejects_metadata_tamper(harness: Harness) -> None:
    from care_link_data import verify_audit_chain
    from psycopg.rows import dict_row

    h = harness
    session = h.create()
    h.service.session_read(h.participant, str(session["id"]))
    with psycopg.connect(h.database.admin, row_factory=dict_row) as admin:
        events = admin.execute("SELECT * FROM audit.event ORDER BY sequence").fetchall()
    normalized = [
        {name: str(value) if isinstance(value, UUID) else value for name, value in event.items()}
        for event in events
    ]
    assert verify_audit_chain(normalized) == normalized[-1]["hash"]
    normalized[0]["action"] = "changed"
    with pytest.raises(ManualError, match="chain_invalid"):
        verify_audit_chain(normalized)


def test_lost_recovery_response_allows_new_fresh_ancestor_bound_recovery(harness: Harness) -> None:
    h = harness
    session = h.create()
    sid = str(session["id"])
    initial = h.service.continuation_bootstrap(h.participant, key(), sid)
    proof = key()
    body = {
        "session_id": sid,
        "family_id": initial["family_id"],
        "ceremony_id": proof,
        "channel": "web",
        "expected_revision": "1",
    }
    h.authority.proofs[proof] = (h.participant.account_id, sid, str(initial["family_id"]))
    recovery_key = key()
    lost = h.service.continuation_recover(h.participant, recovery_key, body)
    assert (
        h.service.continuation_recover(h.participant, recovery_key, body)["state"]
        == "replacement_unavailable"
    )
    second_proof = key()
    body["ceremony_id"] = second_proof
    h.authority.proofs[second_proof] = (h.participant.account_id, sid, str(initial["family_id"]))
    recovered = h.service.continuation_recover(h.participant, key(), body)
    assert recovered["family_id"] not in {initial["family_id"], lost["family_id"]}
    assert (
        h.read("SELECT count(*) FROM access.continuation_family WHERE status='active'")[0][0] == 1
    )
    with pytest.raises(ManualError):
        h.service.continuation_rotate(
            h.participant,
            key(),
            {
                "session_id": sid,
                "family_id": lost["family_id"],
                "token": lost["token"],
                "channel": "web",
                "expected_revision": "1",
            },
        )


@pytest.mark.parametrize(
    "restriction", ["principal", "acl_revoked", "acl_expired", "access_revision"]
)
def test_participant_revoked_after_both_acks_cannot_be_connected(
    harness: Harness, restriction: str
) -> None:
    h = harness
    session, assignment = accepted(h)
    sid = str(session["id"])
    h.service.workforce_prepare_transfer(
        h.worker, key(), {"expected_revision": assignment["revision"]}, sid
    )
    session = h.service.session_read(h.participant, sid)
    acks = []
    for actor in [h.participant, h.worker]:
        challenge = h.service.channel_challenge_read(actor, sid)
        ack = h.service.channel_ack(
            actor,
            key(),
            {
                "expected_revision": session["revision"],
                "challenge_id": challenge["challenge_id"],
                "nonce": challenge["nonce"],
                "transport_generation": challenge["transport_generation"],
                "expected_control_epoch": challenge["control_epoch"],
            },
            sid,
        )
        acks.append(ack)
    assert acks[-1]["state"] == "two_party_confirmed"
    if restriction == "principal":
        h.service.restrict_principal(
            h.operator,
            key(),
            {"principal_id": h.participant.account_id, "expected_identity_revision": "1"},
        )
    else:
        with psycopg.connect(h.database.admin) as connection:
            if restriction == "acl_revoked":
                connection.execute(
                    "UPDATE core.session_acl SET revoked_at=now() WHERE principal_id=%s",
                    (h.participant.account_id,),
                )
            elif restriction == "acl_expired":
                connection.execute(
                    "UPDATE core.session_acl SET valid_until=now() WHERE principal_id=%s",
                    (h.participant.account_id,),
                )
            else:
                connection.execute(
                    "UPDATE core.session_guard SET access_revision=access_revision+1 "
                    "WHERE session_id=%s",
                    (sid,),
                )
    with pytest.raises(ManualError):
        h.service.workforce_confirm_transfer(
            h.worker,
            key(),
            {
                "expected_revision": session["revision"],
                "assignment_id": assignment["id"],
                "channel_evidence_id": acks[-1]["evidence_id"],
                "worker_ack_id": acks[-1]["ack_id"],
                "expected_control_epoch": session["control_epoch"],
            },
            sid,
        )
    assert h.read("SELECT service_phase,owner_id FROM core.session")[0] == ("handoff_pending", None)


def test_original_request_deadline_survives_fresh_identity_and_rolls_back(harness: Harness) -> None:
    from dataclasses import replace

    h = harness
    session = h.create()
    actor = replace(h.participant, request_deadline=datetime.now(UTC) + timedelta(seconds=0.2))
    original = h.service._audit

    def delayed_audit(*args, **kwargs):
        result = original(*args, **kwargs)
        h.service.clock = lambda: actor.request_deadline + timedelta(seconds=1)
        return result

    h.service._audit = delayed_audit
    with pytest.raises(ManualError):
        h.service.session_human_request(
            actor,
            key(),
            {"expected_revision": session["revision"], "reason": "user_requested"},
            str(session["id"]),
        )
    assert h.read("SELECT count(*) FROM workforce.queue_entry")[0][0] == 0
    assert h.read("SELECT service_phase FROM core.session")[0][0] == "active"


def test_supervisor_observe_then_interrupt_can_take_over_without_role_or_order_changes(
    harness: Harness,
) -> None:
    """Exercise the visible workflow with both valid grant purposes present."""
    h = harness
    before = connected(h)
    sid = str(before["id"])
    queue = h.service.queue_list(h.supervisor)["items"][0]
    h.service.workforce_observe(
        h.supervisor,
        key(),
        {
            "expected_revision": queue["revision"],
            "scope": "observe",
            "expires_at": stamp(datetime.now(UTC) + timedelta(minutes=5)),
        },
        sid,
    )
    observed = h.service.session_read(h.supervisor, sid)
    assert observed["owner_id"] == h.worker.account_id
    assert observed["control_epoch"] == before["control_epoch"]
    with pytest.raises(ManualError):
        h.service.workforce_takeover(
            h.supervisor,
            key(),
            {"expected_revision": observed["revision"], "worker_id": h.supervisor.account_id},
            sid,
        )
    queue = h.service.queue_list(h.supervisor)["items"][0]
    h.service.workforce_observe(
        h.supervisor,
        key(),
        {
            "expected_revision": queue["revision"],
            "scope": "interrupt",
            "expires_at": stamp(datetime.now(UTC) + timedelta(minutes=5)),
        },
        sid,
    )
    assert h.read(
        "SELECT purpose FROM core.session_acl WHERE session_id=%s AND principal_id=%s "
        "AND revoked_at IS NULL ORDER BY purpose",
        (sid, h.supervisor.account_id),
    ) == [("interrupt",), ("observe",)]
    current = h.service.session_read(h.supervisor, sid)
    taken = h.service.workforce_takeover(
        h.supervisor,
        key(),
        {"expected_revision": current["revision"], "worker_id": h.supervisor.account_id},
        sid,
    )
    assert taken["owner_id"] == h.supervisor.account_id
    assert taken["service_phase"] == "worker_assigned"
    assert int(taken["control_epoch"]) == int(before["control_epoch"]) + 1
    assert taken["unresolved"] is True
    with pytest.raises(ManualError):
        h.service.session_read(h.worker, sid)
