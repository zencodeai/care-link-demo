"""One synthetic session across the gateway, OPA and separately credentialed receiver."""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast

import psycopg
import pytest
from care_link_data import PostgresStore
from care_link_data.store import Record
from care_link_data.values import object_value, stamp
from care_link_domain import Actor, ManualError
from care_link_policy_input import OpaPolicy
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from services.data.tests.test_imp07_lifecycle import execute, followup, key, make_due
from services.data.tests.test_plans_consent import grant_body, plans_harness
from services.data.tests.test_referrals import build_case, dispatch, reconcile, send

if TYPE_CHECKING:
    from services.data.tests.conftest import Harness

referral_harness = plans_harness
ConsentProofs = dict[str, tuple[str, str, str, str, str]]


@pytest.fixture
def integrated_case(referral_harness, receiver_database):
    executable = os.environ.get("CARE_LINK_OPA_BINARY")
    if not executable:
        pytest.skip("Explicit pinned OPA executable required for the integrated journey")
    h, proofs = referral_harness
    root = Path(__file__).resolve().parents[3]
    source = (root / "config/demo/imp08/policy/manual.rego").read_bytes()
    signing = Ed25519PrivateKey.generate()
    binary = Path(executable)
    with binary.open("rb") as stream:
        binary_digest = hashlib.file_digest(stream, "sha256").hexdigest()
    policy = OpaPolicy(
        binary,
        binary_digest,
        source,
        base64.b64encode(signing.sign(source)).decode(),
        signing.public_key(),
    )
    with psycopg.connect(h.database.admin) as connection:
        connection.execute("UPDATE control.guard SET bundle_digest=%s", (policy.bundle_digest,))
    h.service.policy = policy
    case = build_case(referral_harness, receiver_database)
    return case, proofs


def share_plan(h: Harness, session: Record, proofs: ConsentProofs) -> None:
    sid = str(session["id"])
    current = h.service.session_read(h.participant, sid)
    plan = h.service.plan_create(
        h.participant,
        key(),
        {"subject_id": session["subject_id"], "expected_revision": current["revision"]},
    )
    plan_id = str(plan["id"])
    private_note = "Fictional unverified medication report"
    for field, text in [
        ("plan.strategies", "Ask for a quiet room"),
        ("plan.medication_report", private_note),
    ]:
        plan = h.service.plan_field_append(
            h.participant,
            key(),
            {
                "expected_revision": plan["revision"],
                "field": field,
                "value": {"kind": "text", "text": text},
                "source": None,
                "safety_relevant": False,
            },
            plan_id,
        )
    with pytest.raises(ManualError):
        h.service.plan_read(h.worker, plan_id)
    grant = h.service.consent_grant(h.participant, key(), grant_body(h, proofs, session))
    shared = h.service.plan_read(h.worker, plan_id)
    assert [field["field"] for field in cast(list[Record], shared["fields"])] == ["plan.strategies"]
    assert private_note not in str(shared)
    h.service.consent_revoke(
        h.participant, key(), {"expected_revision": grant["revision"]}, str(grant["id"])
    )
    with pytest.raises(ManualError):
        h.service.plan_read(h.worker, plan_id)


def deliver_followup(h: Harness, session: Record, proofs: ConsentProofs) -> str:
    current = h.service.session_read(h.participant, str(session["id"]))
    consent_key = key()
    proofs[consent_key] = (
        h.participant.account_id,
        str(session["subject_id"]),
        str(session["id"]),
        "follow_up",
        "self",
    )
    now = datetime.now(UTC)
    contact = h.service.consent_grant(
        h.participant,
        key(),
        {
            "subject_id": session["subject_id"],
            "session_id": session["id"],
            "expected_revision": current["revision"],
            "purpose": "follow_up",
            "basis": "self",
            "authority_proof_id": consent_key,
            "recipient": {"kind": "account", "account_id": h.participant.account_id},
            "fields": ["summary"],
            "effective_at": stamp(now - timedelta(seconds=1)),
            "expires_at": stamp(now + timedelta(days=4)),
        },
    )
    scheduled = followup(h, session, contact)
    assert scheduled["state"] == "scheduled"
    assert h.service.participant_inbox(h.participant)["items"] == []
    make_due(h, scheduled)
    execute(h)
    execute(h)
    items = cast(list[Record], h.service.participant_inbox(h.participant)["items"])
    assert len(items) == 1
    message_id = str(items[0]["id"])
    assert h.read(
        "SELECT id::text,recipient_account_id::text FROM care.inbox_message WHERE followup_id=%s",
        (scheduled["id"],),
    ) == [(message_id, h.participant.account_id)]
    assert h.service.followup_read(h.participant, str(scheduled["id"]))["state"] == "sent"
    with pytest.raises(ManualError):
        h.service.inbox_message_read(h.worker, message_id)
    assert h.service.inbox_message_read(h.participant, message_id)["read_at"] is not None
    return message_id


def exercise_rights(h: Harness, session: Record, monkeypatch) -> Record:
    subject = str(session["subject_id"])
    proofs = {kind: key() for kind in ("export", "delete")}

    def verify(actor: Actor, ceremony: str, subject_id: str, kind: str) -> None:
        if (
            actor.account_id != h.participant.account_id
            or not actor.mfa
            or subject_id != subject
            or ceremony != proofs.get(kind)
        ):
            raise ManualError("test.rights_proof_required")

    monkeypatch.setattr(h.authority, "rights_proof", verify, raising=False)
    monkeypatch.setattr(
        h.authority,
        "rights_download_proof",
        lambda a, c, s: verify(a, c, s, "export"),
        raising=False,
    )

    def request(kind: str) -> Record:
        [(revision,)] = h.read(
            "SELECT authority_revision FROM core.subject_guard WHERE subject_id=%s",
            (subject,),
        )
        return h.service.rights_create(
            h.participant,
            key(),
            {
                "subject_id": subject,
                "expected_revision": str(revision),
                "kind": kind,
                "ceremony_id": proofs[kind],
            },
        )

    exported = request("export")
    export_id = str(exported["id"])
    assert exported["state"] == "completed"
    report = h.service.export_download(h.participant, export_id)
    assert report["subject_id"] == subject
    assert {value["field"] for value in cast(list[Record], report["assertions"])} == {
        "needs",
        "preferences",
    }
    assert len(cast(list[Record], report["plans"])) == 1
    with pytest.raises(ManualError, match="export_unavailable"):
        h.service.export_download(h.participant, export_id)
    assert h.read(
        "SELECT downloaded_at IS NOT NULL,export_ciphertext IS NULL "
        "FROM rights.request WHERE id=%s",
        (export_id,),
    ) == [(True, True)]

    deleted = request("delete")
    assert deleted["state"] == "eligible"
    with pytest.raises(ManualError):
        h.service.session_read(h.participant, str(session["id"]))
    execute(h, "person")
    return h.service.rights_read(h.participant, str(deleted["id"]))


def test_integrated_actor_journey_through_partial_referral_plan_followup_and_rights(
    integrated_case,
    receiver_database,
    monkeypatch,
) -> None:
    case, proofs = integrated_case
    h, receiver, receiver_actor, session, draft, *_ = case
    receiver_actor = replace(
        receiver_actor,
        browser_session_digest=secrets.token_hex(32),
        credential_ref=secrets.token_hex(32),
        identity_evidence_id=key(),
    )
    PostgresStore(h.database.admin).provision_principal(receiver_actor)
    sid = str(session["id"])
    assert session["service_phase"] == "human_controlled"
    assert session["owner_id"] == h.worker.account_id
    with pytest.raises(ManualError):
        h.service.session_read(receiver_actor, sid)
    assert h.read(
        "SELECT count(*) FROM core.session_acl WHERE session_id=%s AND principal_id=%s",
        (sid, receiver_actor.account_id),
    ) == [(0,)]

    pending = dispatch(case)
    dispatch_id = pending["dispatch_id"]
    assert (pending["state"], pending["attempt_count"]) == ("pending", 0)
    assert receiver.receiver_inbox(receiver_actor, {})["dispatch_ids"] == []
    receiver.scenario = "drop_after_store"
    unknown = send(case, pending)
    assert unknown["state"] == "unknown"
    assert receiver.receiver_inbox(receiver_actor, {})["dispatch_ids"] == [dispatch_id]
    received = reconcile(case, unknown)
    assert received["state"] == "received"
    detail = receiver.receiver_detail(receiver_actor, dispatch_id)
    payload = object_value(detail["payload"])
    assert payload["session_id"] == sid
    assert {field["field"] for field in cast(list[Record], payload["fields"])} == {
        "needs",
        "preferences",
    }
    receiver.receiver_decide(
        receiver_actor,
        key(),
        {
            "expected_revision": detail["revision"],
            "dispatch_id": dispatch_id,
            "payload_digest": draft["digest"],
            "decision": "partial",
            "accepted_fields": ["needs"],
            "reason": "capacity",
        },
    )
    partial = reconcile(case, received)
    assert partial["state"] == "partial"
    assert h.service.receipt_read(h.worker, dispatch_id)["accepted_fields"] == ["needs"]
    assert h.read(
        "SELECT count(*),count(consumed_at) FROM referral.authorization WHERE dispatch_id=%s",
        (dispatch_id,),
    ) == [(1, 1)]
    assert h.read(
        "SELECT count(*) FROM referral.attempt WHERE dispatch_id=%s",
        (dispatch_id,),
    ) == [(1,)]
    with psycopg.connect(receiver_database[0]) as connection:
        assert connection.execute(
            "SELECT payload_digest,receipt->>'status' FROM receiver.package WHERE dispatch_id=%s",
            (dispatch_id,),
        ).fetchall() == [(draft["digest"], "partial")]
    current = h.service.session_read(h.participant, sid)
    assert (current["service_phase"], current["owner_id"]) == (
        "human_controlled",
        h.worker.account_id,
    )

    share_plan(h, session, proofs)
    message_id = deliver_followup(h, session, proofs)
    progress = exercise_rights(h, session, monkeypatch)
    assert progress["state"] == "reconciliation_needed"
    assert {
        "backup_erasure_pending_IMP09",
        "physical_erasure_not_proven",
        "delivery_reconciliation_required",
    } <= set(progress["exceptions"])
    assert h.read(
        "SELECT state,anchor_at FROM lifecycle.copy WHERE aggregate_id=%s",
        (draft["id"],),
    ) == [("anchor_pending", None)]
    assert h.read(
        "SELECT state FROM lifecycle.copy WHERE aggregate_id=%s",
        (message_id,),
    ) == [("purged",)]
    assert h.journal.records[-1]["restriction"]["kind"] == "subject_delete"
