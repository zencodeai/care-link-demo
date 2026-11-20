"""Independent IMP-04 negative-rights, absence-race and durable privilege evidence."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import uuid4

import psycopg
import pytest
from care_link_data import PostgresStore
from care_link_domain import ManualError

from services.data.tests.test_plans_consent import (
    create_plan,
    grant_body,
)
from services.data.tests.test_plans_consent import (
    plans_harness as base_plans_harness,
)

adverse_harness = base_plans_harness


def append_strategy(h, plan):
    return h.service.plan_field_append(
        h.participant,
        str(uuid4()),
        {
            "expected_revision": plan["revision"],
            "field": "plan.strategies",
            "value": {"kind": "text", "text": "Fictional self-authored strategy"},
            "source": None,
            "safety_relevant": True,
        },
        plan["id"],
    )


def pause_action(h, monkeypatch, action):
    prepared, resume = Event(), Event()
    original = h.policy.evaluate

    def evaluate(request):
        if request["action"] == action:
            prepared.set()
            assert resume.wait(timeout=5), "test did not release paused policy evaluation"
        return original(request)

    monkeypatch.setattr(h.policy, "evaluate", evaluate)
    return prepared, resume


def test_missing_new_grant_cannot_commit_across_subject_revoke(adverse_harness, monkeypatch):
    h, proofs = adverse_harness
    session, _plan = create_plan(h)
    old = h.service.consent_grant(h.participant, str(uuid4()), grant_body(h, proofs, session))
    body = grant_body(h, proofs, session, h.supervisor.account_id)
    operation = str(uuid4())
    prepared, resume = pause_action(h, monkeypatch, "consent_grant")
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(h.service.consent_grant, h.participant, operation, body)
        assert prepared.wait(timeout=5)
        try:
            # No row for the pending grant exists; its authorization must still
            # be fenced by the pre-existing subject guard, not a grant-row lock.
            assert h.read("SELECT count(*) FROM consent.current_grant")[0][0] == 1
            h.service.consent_revoke(
                h.participant, str(uuid4()), {"expected_revision": old["revision"]}, old["id"]
            )
        finally:
            resume.set()
        with pytest.raises(ManualError, match="stale_authority"):
            pending.result(timeout=5)
    assert h.read("SELECT count(*) FROM consent.current_grant")[0][0] == 1
    assert h.read("SELECT state FROM durable.operation WHERE operation_id=%s", (operation,)) == [
        ("rejected",)
    ]
    assert h.read("SELECT count(*) FROM consent.event WHERE kind='grant'")[0][0] == 1
    assert h.read("SELECT count(*) FROM consent.event WHERE kind='revoke'")[0][0] == 1


def test_pending_shared_projection_rechecks_revoke_before_content(adverse_harness, monkeypatch):
    h, proofs = adverse_harness
    session, plan = create_plan(h)
    plan = append_strategy(h, plan)
    grant = h.service.consent_grant(h.participant, str(uuid4()), grant_body(h, proofs, session))
    prepared, resume = pause_action(h, monkeypatch, "plan_read")
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(h.service.plan_read, h.worker, plan["id"])
        assert prepared.wait(timeout=5)
        try:
            h.service.consent_revoke(
                h.participant,
                str(uuid4()),
                {"expected_revision": grant["revision"]},
                grant["id"],
            )
        finally:
            resume.set()
        with pytest.raises(ManualError, match="stale_authority"):
            pending.result(timeout=5)
    assert h.read("SELECT count(*) FROM plans.field WHERE plan_id=%s", (plan["id"],))[0][0] == 1
    assert (
        h.read("SELECT count(*) FROM audit.event WHERE action='plan_read' AND decision='PERMIT'")[
            0
        ][0]
        == 0
    )


def test_share_expiring_during_projection_releases_no_content(adverse_harness, monkeypatch):
    h, proofs = adverse_harness
    session, plan = create_plan(h)
    plan = append_strategy(h, plan)
    body = grant_body(h, proofs, session)
    expires = datetime.now(UTC) + timedelta(milliseconds=200)
    body["expires_at"] = expires.isoformat().replace("+00:00", "Z")
    h.service.consent_grant(h.participant, str(uuid4()), body)
    decrypt = h.service.cipher.decrypt

    def expire_while_decrypting(ciphertext):
        value = decrypt(ciphertext)
        # Injected clock is the service's security clock. This puts the final
        # release exactly at expiry while the separate PDP permit remains live.
        monkeypatch.setattr(h.service, "clock", lambda: expires)
        return value

    monkeypatch.setattr(h.service.cipher, "decrypt", expire_while_decrypting)
    with pytest.raises(ManualError):
        h.service.plan_read(h.worker, plan["id"])
    assert (
        h.read("SELECT count(*) FROM audit.event WHERE action='plan_read' AND decision='PERMIT'")[
            0
        ][0]
        == 0
    )


@pytest.mark.parametrize("role", ["carer", "professional_participant"])
def test_relationship_actor_cannot_self_grant_or_write_pid_plan(adverse_harness, role):
    h, proofs = adverse_harness
    session, plan = create_plan(h)
    outsider = replace(h.worker, account_id=str(uuid4()), role=role)
    PostgresStore(h.database.admin).provision_principal(outsider)
    body = grant_body(h, proofs, session)
    with pytest.raises(ManualError):
        h.service.plan_read(outsider, plan["id"])
    with pytest.raises(ManualError, match="grantor_authority_required"):
        h.service.consent_grant(outsider, str(uuid4()), body)
    body["basis"], body["authority_proof_id"] = "explicit_demo_delegation", str(uuid4())
    with pytest.raises(ManualError, match="delegation_not_provisioned"):
        h.service.consent_grant(outsider, str(uuid4()), body)
    with pytest.raises(ManualError):
        h.service.plan_field_append(
            outsider,
            str(uuid4()),
            {
                "expected_revision": plan["revision"],
                "field": "plan.advance_wishes",
                "value": {"kind": "text", "text": "Fictional relationship override attempt"},
                "source": None,
                "safety_relevant": True,
            },
            plan["id"],
        )
    assert h.read("SELECT count(*) FROM consent.current_grant")[0][0] == 0
    assert h.read("SELECT count(*) FROM plans.field")[0][0] == 0


def test_mutation_key_cannot_be_replayed_against_another_plan(adverse_harness):
    h, _proofs = adverse_harness
    session, plan = create_plan(h)
    operation = str(uuid4())
    body = {"expected_revision": plan["revision"]}
    h.service.plan_retire(h.participant, operation, body, plan["id"])
    current = h.service.session_read(h.participant, session["id"])
    replacement = h.service.plan_create(
        h.participant,
        str(uuid4()),
        {"subject_id": current["subject_id"], "expected_revision": current["revision"]},
    )
    with pytest.raises(ManualError, match="idempotency_conflict"):
        h.service.plan_retire(h.participant, operation, body, replacement["id"])
    assert h.read("SELECT state FROM plans.plan WHERE id=%s", (replacement["id"],)) == [("active",)]


def test_runtime_cannot_rewrite_append_only_or_provision_delegation(adverse_harness):
    h, proofs = adverse_harness
    session, plan = create_plan(h)
    plan = append_strategy(h, plan)
    grant = h.service.consent_grant(h.participant, str(uuid4()), grant_body(h, proofs, session))
    forbidden = [
        ("UPDATE plans.field SET verification='verified' WHERE plan_id=%s", (plan["id"],)),
        ("UPDATE consent.event SET kind='expire' WHERE grant_id=%s", (grant["id"],)),
        ("DELETE FROM consent.event WHERE grant_id=%s", (grant["id"],)),
        (
            "INSERT INTO consent.delegation VALUES(%s,%s,%s,ARRAY['plan'],"
            "ARRAY['plan.strategies'],now()+interval '1 hour',NULL)",
            (str(uuid4()), session["subject_id"], h.worker.account_id),
        ),
    ]
    for statement, parameters in forbidden:
        with psycopg.connect(h.database.runtime) as connection:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(statement, parameters)
    with psycopg.connect(h.database.runtime) as connection:
        connection.execute("SELECT set_config('care_link.session',%s,true)", (session["id"],))
        with pytest.raises(psycopg.errors.RaiseException, match="grant scope is immutable"):
            connection.execute(
                "UPDATE consent.current_grant SET fields=ARRAY['plan.contacts'],"
                "revoked_at=now(),revision=revision+1 WHERE grant_id=%s",
                (grant["id"],),
            )
    assert h.read("SELECT verification FROM plans.field WHERE plan_id=%s", (plan["id"],)) == [
        ("unverified",)
    ]
    assert h.read("SELECT count(*) FROM consent.event WHERE kind='grant'")[0][0] == 1
    assert h.read("SELECT count(*) FROM consent.delegation")[0][0] == 0


def test_narrow_surviving_grant_cannot_release_fields_from_expired_grant(
    adverse_harness, monkeypatch
):
    h, proofs = adverse_harness
    session, plan = create_plan(h)
    plan = append_strategy(h, plan)
    plan = h.service.plan_field_append(
        h.participant,
        str(uuid4()),
        {
            "expected_revision": plan["revision"],
            "field": "plan.contacts",
            "value": {"kind": "text", "text": "Fictional private contact"},
            "source": None,
            "safety_relevant": False,
        },
        plan["id"],
    )
    broad = grant_body(h, proofs, session)
    expires = datetime.now(UTC) + timedelta(milliseconds=300)
    broad["expires_at"] = expires.isoformat().replace("+00:00", "Z")
    broad["fields"] = ["plan.strategies", "plan.contacts"]
    h.service.consent_grant(h.participant, str(uuid4()), broad)
    narrow = grant_body(h, proofs, session)
    h.service.consent_grant(h.participant, str(uuid4()), narrow)
    decrypt = h.service.cipher.decrypt

    def expire_broad(ciphertext):
        value = decrypt(ciphertext)
        monkeypatch.setattr(h.service, "clock", lambda: expires)
        return value

    monkeypatch.setattr(h.service.cipher, "decrypt", expire_broad)
    with pytest.raises(ManualError, match="field_scope_denied"):
        h.service.plan_read(h.worker, plan["id"])
    assert (
        h.read("SELECT count(*) FROM audit.event WHERE action='plan_read' AND decision='PERMIT'")[
            0
        ][0]
        == 0
    )


def test_live_delegation_restriction_stops_existing_shared_projection(adverse_harness):
    h, proofs = adverse_harness
    session, plan = create_plan(h)
    plan = append_strategy(h, plan)
    delegate = replace(h.worker, account_id=str(uuid4()), role="carer")
    PostgresStore(h.database.admin).provision_principal(delegate)
    proof_id = str(uuid4())
    with psycopg.connect(h.database.admin) as connection:
        connection.execute(
            "INSERT INTO consent.delegation VALUES(%s,%s,%s,ARRAY['plan'],"
            "ARRAY['plan.strategies'],now()+interval '1 hour',NULL)",
            (proof_id, session["subject_id"], delegate.account_id),
        )
    body = grant_body(h, proofs, session, h.supervisor.account_id)
    body["basis"], body["authority_proof_id"] = "explicit_demo_delegation", proof_id
    grant = h.service.consent_grant(delegate, str(uuid4()), body)
    assert grant["grantor_id"] == delegate.account_id
    assert len(h.service.plan_read(h.supervisor, plan["id"])["fields"]) == 1
    with psycopg.connect(h.database.admin) as connection:
        connection.execute(
            "UPDATE consent.delegation SET revoked_at=now() WHERE id=%s", (proof_id,)
        )
    with pytest.raises(ManualError):
        h.service.plan_read(h.supervisor, plan["id"])
    assert h.read(
        "SELECT revoked_at IS NULL FROM consent.current_grant WHERE grant_id=%s", (grant["id"],)
    ) == [(True,)]
    # The historical scope remains intact; current delegation authority ended.
    assert h.read("SELECT count(*) FROM consent.event WHERE grant_id=%s", (grant["id"],))[0][0] == 1


def test_grantor_role_revision_change_removes_current_share(adverse_harness):
    h, proofs = adverse_harness
    session, plan = create_plan(h)
    plan = append_strategy(h, plan)
    grant = h.service.consent_grant(h.participant, str(uuid4()), grant_body(h, proofs, session))
    assert len(h.service.plan_read(h.worker, plan["id"])["fields"]) == 1
    with psycopg.connect(h.database.admin) as connection:
        connection.execute(
            "UPDATE control.principal_guard SET role_revision=role_revision+1 "
            "WHERE principal_id=%s",
            (h.participant.account_id,),
        )
    with pytest.raises(ManualError):
        h.service.plan_read(h.worker, plan["id"])
    assert h.read(
        "SELECT revoked_at IS NULL FROM consent.current_grant WHERE grant_id=%s", (grant["id"],)
    ) == [(True,)]
