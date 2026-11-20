"""Current field privacy and exact grant authority, plus real PostgreSQL workflows."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast
from uuid import uuid4

import psycopg
import pytest
from care_link_contracts import validate_contract
from care_link_data import AESGCMContentCipher
from care_link_data.consent import capability_access, current_fields, grant_current
from care_link_data.plans import Plans
from care_link_data.store import Transaction
from care_link_data.values import canonical, stamp
from care_link_domain import Actor, ManualError

if TYPE_CHECKING:
    from services.data.tests.conftest import Harness


class Rows:
    def __init__(self, records):
        self.records = records

    def get(self, repository, key):
        return next(
            (
                row
                for row in self.records.get(repository, [])
                if row.get(
                    "grant_id", row.get("id", row.get("principal_id", row.get("subject_id")))
                )
                == key
            ),
            None,
        )

    def rows(self, repository, *, limit=100, **where):
        return [
            row
            for row in self.records.get(repository, [])
            if all(row.get(key) == value for key, value in where.items())
        ][:limit]


def actor(role="pid", *, mfa=True):
    now = datetime.now(UTC)
    return Actor(
        str(uuid4()),
        role,
        1,
        1,
        now,
        mfa,
        "a" * 64,
        1,
        "credential",
        now + timedelta(hours=1),
        str(uuid4()),
    )


def privacy_fixture():
    now = datetime.now(UTC)
    owner, carer = actor(), actor("carer")
    subject, sid = str(uuid4()), str(uuid4())
    session = {"id": sid, "persona_id": subject, "participant_account_id": owner.account_id}
    grant = {
        "grant_id": str(uuid4()),
        "subject_id": subject,
        "session_id": sid,
        "recipient_kind": "account",
        "recipient_id": carer.account_id,
        "purpose": "plan",
        "fields": ["plan.strategies"],
        "effective_at": now - timedelta(seconds=1),
        "expires_at": now + timedelta(minutes=10),
        "revoked_at": None,
        "grantor_id": owner.account_id,
        "grantor_identity_revision": 1,
        "grantor_role_revision": 1,
        "basis": "self",
        "authority_proof_id": str(uuid4()),
    }
    rows = Rows(
        {
            "persona": [{"id": subject, "account_id": owner.account_id, "kind": "pid"}],
            "subject": [{"subject_id": subject, "delete_state": "active"}],
            "principal": [
                {
                    "principal_id": owner.account_id,
                    "role": "pid",
                    "revoked": False,
                    "identity_revision": 1,
                    "role_revision": 1,
                }
            ],
            "session": [session],
            "consent": [grant],
        }
    )
    return cast(Transaction, rows), owner, carer, session, grant, now


def test_relationship_does_not_grant_authority():
    tx, _owner, carer, session, _grant, now = privacy_fixture()
    assert capability_access(tx, carer, "plan_read", session, now)
    assert not capability_access(tx, carer, "plan_field_append", session, now)
    assert not capability_access(tx, carer, "plan_retire", session, now)
    outsider = actor("professional_participant")
    assert not capability_access(tx, outsider, "plan_read", session, now)
    assert current_fields(tx, outsider, session, now) == set()


@pytest.mark.parametrize(
    "change", ["expired", "not_yet_effective", "revoked", "identity", "role", "deleted"]
)
def test_grant_rechecks_current_negative_rights(change):
    tx, _owner, carer, session, grant, now = privacy_fixture()
    assert current_fields(tx, carer, session, now) == {"plan.strategies"}
    if change == "expired":
        grant["expires_at"] = now
    elif change == "not_yet_effective":
        grant["effective_at"] = now + timedelta(seconds=1)
    elif change == "revoked":
        grant["revoked_at"] = now
    elif change in {"identity", "role"}:
        tx.get("principal", grant["grantor_id"])[change + "_revision"] = 2
    else:
        tx.get("subject", grant["subject_id"])["delete_state"] = "deleted"
    assert not grant_current(tx, grant, now)
    assert current_fields(tx, carer, session, now) == set()


def test_grants_match_exact_session_account_and_purpose():
    tx, _owner, carer, session, grant, now = privacy_fixture()
    for field, changed in [
        ("session_id", str(uuid4())),
        ("recipient_id", str(uuid4())),
        ("purpose", "referral"),
    ]:
        before = grant[field]
        grant[field] = changed
        assert current_fields(tx, carer, session, now) == set()
        grant[field] = before


def test_delegation_requires_preprovisioned_exact_fields_and_current_expiry():
    tx, _owner, _carer, _session, grant, now = privacy_fixture()
    grant["basis"] = "explicit_demo_delegation"
    assert not grant_current(tx, grant, now)
    record = {
        "id": grant["authority_proof_id"],
        "subject_id": grant["subject_id"],
        "grantor_id": grant["grantor_id"],
        "purposes": ["plan"],
        "fields": ["plan.strategies"],
        "expires_at": now + timedelta(minutes=1),
        "revoked_at": None,
    }
    cast(Rows, tx).records["delegation"] = [record]
    assert grant_current(tx, grant, now)
    record["fields"] = ["plan.contacts"]
    assert not grant_current(tx, grant, now)
    record["fields"] = ["plan.strategies"]
    record["revoked_at"] = now
    assert not grant_current(tx, grant, now)


def test_stale_pid_mfa_cannot_edit_but_can_revoke():
    tx, owner, _carer, session, _grant, now = privacy_fixture()
    stale = replace(owner, auth_time=now - timedelta(minutes=5))
    assert not capability_access(tx, stale, "plan_create", session, now)
    assert not capability_access(tx, stale, "consent_grant", session, now)
    assert capability_access(tx, stale, "consent_revoke", session, now)


def test_projection_discloses_only_current_shared_fields_and_preserves_attribution():
    tx, owner, carer, session, grant, now = privacy_fixture()
    service = object.__new__(Plans)
    service.clock = lambda: now
    service.cipher = AESGCMContentCipher(b"s" * 32)
    plan = {
        "id": str(uuid4()),
        "subject_id": session["persona_id"],
        "session_id": session["id"],
        "revision": 3,
        "state": "active",
        "retired_at": None,
    }
    fields = []
    for key in ["plan.strategies", "plan.medication_report"]:
        fields.append(
            {
                "id": str(uuid4()),
                "plan_id": plan["id"],
                "subject_id": plan["subject_id"],
                "field_key": key,
                "revision": 2,
                "author_id": owner.account_id,
                "value_ciphertext": service.cipher.encrypt(
                    canonical({"kind": "text", "text": key})
                ),
                "source": None,
                "verification": "unverified",
                "supersedes_id": None,
                "effective_at": now,
            }
        )
    # An actor's historic authorship cannot enlarge a newly narrowed share.
    fields[1]["author_id"] = carer.account_id
    cast(Rows, tx).records["plan_field"] = fields
    view = service.plan_projection(tx, carer, plan)
    validate_contract("PlanView", view)
    validate_contract("PlanView", service.plan_projection(tx, owner, plan))
    assert [field["field"] for field in view["fields"]] == ["plan.strategies"]
    assert view["fields"][0]["author_id"] == owner.account_id
    assert len(service.plan_projection(tx, owner, plan)["fields"]) == 2
    grant["revoked_at"] = now
    with pytest.raises(ManualError, match="not_found"):
        service.plan_projection(tx, carer, plan)


@pytest.fixture
def plans_harness(harness: Harness, monkeypatch):
    h = harness
    with psycopg.connect(h.database.admin) as connection:
        if not connection.execute("SELECT to_regclass('plans.plan')").fetchone()[0]:
            connection.execute(
                (
                    Path(__file__).resolve().parents[1]
                    / "migrations/003_plans_consent_directory.sql"
                ).read_text()
            )
    h.participant = replace(h.participant, mfa=True)
    proofs = {}

    def proof(current, proof_id, subject_id, session_id, purpose, basis):
        if proofs.pop(proof_id, None) != (
            current.account_id,
            subject_id,
            session_id,
            purpose,
            basis,
        ):
            raise ManualError("test.consent_proof_required")

    monkeypatch.setattr(h.authority, "consent_proof", proof, raising=False)
    return h, proofs


def create_plan(h):
    session = h.create()
    plan = h.service.plan_create(
        h.participant,
        str(uuid4()),
        {"subject_id": session["subject_id"], "expected_revision": session["revision"]},
    )
    return session, plan


def grant_body(h, proofs, session, recipient=None):
    current = h.service.session_read(h.participant, session["id"])
    proof = str(uuid4())
    proofs[proof] = (h.participant.account_id, current["subject_id"], current["id"], "plan", "self")
    now = datetime.now(UTC)
    return {
        "subject_id": current["subject_id"],
        "session_id": current["id"],
        "expected_revision": current["revision"],
        "purpose": "plan",
        "basis": "self",
        "authority_proof_id": proof,
        "recipient": {"kind": "account", "account_id": recipient or h.worker.account_id},
        "fields": ["plan.strategies"],
        "effective_at": stamp(now - timedelta(seconds=1)),
        "expires_at": stamp(now + timedelta(minutes=10)),
    }


def test_postgres_plan_versions_grant_filter_revoke_and_replay(plans_harness):
    h, proofs = plans_harness
    session, plan = create_plan(h)
    for field in ["plan.strategies", "plan.medication_report"]:
        plan = h.service.plan_field_append(
            h.participant,
            str(uuid4()),
            {
                "expected_revision": plan["revision"],
                "field": field,
                "value": {"kind": "text", "text": "Fictional " + field},
                "source": None,
                "safety_relevant": False,
            },
            plan["id"],
        )
    operation = str(uuid4())
    body = grant_body(h, proofs, session)
    grant = h.service.consent_grant(h.participant, operation, body)
    validate_contract("ConsentView", grant)
    assert h.service.consent_grant(h.participant, operation, body)["id"] == grant["id"]
    shared = h.service.plan_read(h.worker, plan["id"])
    assert [field["field"] for field in shared["fields"]] == ["plan.strategies"]
    h.service.consent_revoke(
        h.participant, str(uuid4()), {"expected_revision": grant["revision"]}, grant["id"]
    )
    with pytest.raises(ManualError):
        h.service.plan_read(h.worker, plan["id"])
    assert h.journal.records[-1]["restriction"]["kind"] == "consent_revoke"
    assert h.read("SELECT count(*) FROM consent.event WHERE grant_id=%s", (grant["id"],))[0][0] == 2


def test_postgres_invalid_proof_has_no_positive_effect(plans_harness):
    h, proofs = plans_harness
    session, _plan = create_plan(h)
    body = grant_body(h, proofs, session)
    body["authority_proof_id"] = str(uuid4())
    with pytest.raises(ManualError, match="consent_proof_required"):
        h.service.consent_grant(h.participant, str(uuid4()), body)
    assert h.read("SELECT count(*) FROM consent.current_grant")[0][0] == 0


def test_postgres_retirement_preserves_independent_plan_lifecycle(plans_harness):
    h, _proofs = plans_harness
    _session, plan = create_plan(h)
    retired = h.service.plan_retire(
        h.participant, str(uuid4()), {"expected_revision": plan["revision"]}, plan["id"]
    )
    anchors = h.read(
        "SELECT purpose,anchor_kind,state,expires_at-anchor_at "
        "FROM lifecycle.copy WHERE aggregate_id=%s",
        (plan["id"],),
    )
    assert anchors == [("plan", "plan_retired", "retained", timedelta(days=30))]
    assert h.read(
        "SELECT anchor_at=retired_at,expires_at=retired_at+interval '30 days' "
        "FROM lifecycle.copy JOIN plans.plan ON aggregate_id=plans.plan.id "
        "WHERE plans.plan.id=%s",
        (plan["id"],),
    ) == [(True, True)]
    assert retired["retired_at"] is not None


def test_postgres_active_plan_snapshot_survives_support_session_close(plans_harness):
    h, _proofs = plans_harness
    session, plan = create_plan(h)
    plan = h.service.plan_field_append(
        h.participant,
        str(uuid4()),
        {
            "expected_revision": plan["revision"],
            "field": "plan.strategies",
            "value": {"kind": "text", "text": "Fictional independent plan snapshot"},
            "source": None,
            "safety_relevant": False,
        },
        plan["id"],
    )
    current = h.service.session_read(h.participant, session["id"])
    h.service.session_end(
        h.participant,
        str(uuid4()),
        {"expected_revision": current["revision"], "reason": "user_choice"},
        session["id"],
    )
    active = h.service.plan_read(h.participant, plan["id"])
    assert active == plan
    assert active["state"] == "active"
    assert active["fields"][0]["value"] == {
        "kind": "text",
        "text": "Fictional independent plan snapshot",
    }
    assert h.read(
        "SELECT count(*) FROM lifecycle.copy WHERE session_id=%s AND purpose='plan' "
        "AND state='anchor_pending' AND anchor_at IS NULL AND expires_at IS NULL",
        (session["id"],),
    ) == [(2,)]
