"""Current boot/resource drift and paused permits are denied before business effects."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from care_link_domain import ManualError
from test_imp08_controls import (
    activation,
    instance,
    key,
    provision_ack,
    register,
    review_all,
    signed_enforcer,
)


def active(h):
    data = register(h)
    review_all(h, data)
    instance(h)
    proposed = activation(h, data)
    provision_ack(h, proposed)
    return h.service.activation_commit(
        h.operator, key(), {"expected_revision": proposed["revision"]}, proposed["id"]
    )


@pytest.mark.parametrize("drift", ["boot", "stale", "resource_unhealthy"])
def test_current_instance_drift_fences_business_until_fresh_ack(harness, drift):
    h = harness
    proposed = active(h)
    assert h.create()["id"]
    with psycopg.connect(h.database.admin) as connection:
        if drift == "boot":
            connection.execute("UPDATE governance.instance SET boot_id=%s", (str(uuid4()),))
        elif drift == "stale":
            connection.execute(
                "UPDATE governance.instance SET observed_at=%s",
                (datetime.now(UTC) - timedelta(seconds=31),),
            )
        else:
            connection.execute("UPDATE governance.instance SET healthy=false")
    before = h.read("SELECT count(*) FROM core.session")[0][0]
    with pytest.raises(ManualError):
        h.create()
    assert h.read("SELECT count(*) FROM core.session")[0][0] == before
    with psycopg.connect(h.database.admin) as connection:
        connection.execute("UPDATE governance.instance SET healthy=true,observed_at=now()")
    commands, actor, operation, payload = signed_enforcer(h, proposed)
    commands.activation_ack(actor, operation, payload)
    assert h.create()["id"]


def test_old_permit_paused_before_final_guard_cannot_survive_boot_change(harness):
    h = harness
    active(h)
    reached, release = threading.Event(), threading.Event()
    evaluate = h.policy.evaluate

    def paused(request):
        result = evaluate(request)
        if request["action"] == "session_create":
            reached.set()
            if not release.wait(2):
                raise RuntimeError("Test barrier timeout")
        return result

    h.policy.evaluate = paused
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(h.create)
        try:
            assert reached.wait(2)
            with psycopg.connect(h.database.admin) as connection:
                connection.execute("UPDATE governance.instance SET boot_id=%s", (str(uuid4()),))
        finally:
            release.set()
        with pytest.raises(ManualError, match="manual.stale_authority"):
            result.result(timeout=3)
    assert h.read("SELECT count(*) FROM core.session")[0][0] == 0
    assert h.read("SELECT count(*) FROM audit.event WHERE decision='DENY'")[0][0] >= 1


def test_ai_disable_preserves_manual_service_with_current_boot(harness):
    h = harness
    proposed = active(h)
    epoch = h.read("SELECT epoch FROM control.guard")[0][0]
    h.service.control_change(
        h.operator,
        key(),
        {
            "expected_revision": str(epoch),
            "mode": "ai_disabled",
            "reason": "operator_request",
            "approval_id": None,
        },
    )
    assert h.create()["id"]
    assert h.service.health_read(h.operator)["ready"] is True
    with psycopg.connect(h.database.admin) as connection:
        connection.execute("UPDATE governance.instance SET boot_id=%s", (str(uuid4()),))
    with pytest.raises(ManualError):
        h.create()
    commands, actor, operation, payload = signed_enforcer(h, proposed)
    commands.activation_ack(actor, operation, payload)
    assert h.create()["id"]


def test_custody_writer_waits_for_final_business_commit(harness, monkeypatch):
    h = harness
    active(h)
    original = h.service._check_output_authority
    attempted = []

    def mutate_boot():
        with psycopg.connect(h.database.admin) as connection:
            connection.execute("SET LOCAL lock_timeout='100ms'")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                connection.execute("UPDATE governance.instance SET boot_id=%s", (str(uuid4()),))
            attempted.append(True)

    def check_then_attempt(*args, **kwargs):
        original(*args, **kwargs)
        if args[2] == "session_create":
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(mutate_boot).result(timeout=2)

    monkeypatch.setattr(h.service, "_check_output_authority", check_then_attempt)
    assert h.create()["id"]
    assert attempted == [True]
    with psycopg.connect(h.database.admin) as connection:
        connection.execute("UPDATE governance.instance SET boot_id=%s", (str(uuid4()),))
    with pytest.raises(ManualError):
        h.create()


def test_stale_boot_blocks_evidence_download_and_grants(harness):
    from test_imp08_evidence_postgres import audit_grant

    h = harness
    active(h)
    h.create()
    creator, _reviewer, auditor, request, _grant, query = audit_grant(h)
    export = h.service.evidence_export(auditor, key(), query)
    with psycopg.connect(h.database.admin) as connection:
        connection.execute("UPDATE governance.instance SET boot_id=%s", (str(uuid4()),))
    with pytest.raises(ManualError):
        h.service.audit_export_read(auditor, export["resource_id"], query)
    with pytest.raises(ManualError):
        h.service.scoped_access_grant(creator, key(), request)


def test_approver_role_loss_invalidates_previously_issued_audit_grant(harness):
    from test_imp08_evidence_postgres import audit_grant

    h = harness
    h.create()
    _creator, reviewer, auditor, _request, _grant, query = audit_grant(h)
    assert h.service.audit_query(auditor, key(), query)["items"]
    with psycopg.connect(h.database.admin) as connection:
        connection.execute(
            "UPDATE control.principal_guard SET role='worker',role_revision=role_revision+1 "
            "WHERE principal_id=%s",
            (reviewer.account_id,),
        )
    with pytest.raises(ManualError):
        h.service.audit_query(auditor, key(), query)


def test_receipt_revocation_is_ordered_after_final_audit_read(harness, monkeypatch):
    from test_imp08_evidence_postgres import audit_grant

    h = harness
    h.create()
    _creator, _reviewer, auditor, request, _grant, query = audit_grant(h)
    original = h.service._check_output_authority

    def revoke_while_read_is_committing():
        with psycopg.connect(h.database.admin) as connection:
            connection.execute("SET LOCAL lock_timeout='100ms'")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                connection.execute(
                    "UPDATE governance.approval SET active=false WHERE id=%s",
                    (request["approval_receipt_id"],),
                )

    def final_check(*args, **kwargs):
        original(*args, **kwargs)
        if args[2] == "audit_query":
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(revoke_while_read_is_committing).result(timeout=2)

    monkeypatch.setattr(h.service, "_check_output_authority", final_check)
    assert h.service.audit_query(auditor, key(), query)["items"]
    with psycopg.connect(h.database.admin) as connection:
        connection.execute(
            "UPDATE governance.approval SET active=false WHERE id=%s",
            (request["approval_receipt_id"],),
        )
    with pytest.raises(ManualError):
        h.service.audit_query(auditor, key(), query)


def test_rejected_ack_replay_cannot_become_a_success_after_boot_change(harness):
    h = harness
    data = register(h)
    instance(h)
    proposed = activation(h, data)
    commands, actor, operation, payload = signed_enforcer(h, proposed, boot=key())
    with pytest.raises(ManualError, match="exact_current_boot"):
        commands.activation_ack(actor, operation, payload)
    assert h.read("SELECT count(*) FROM audit.event WHERE action='activation_ack.denied'") == [(1,)]
    with psycopg.connect(h.database.admin) as connection:
        connection.execute("UPDATE governance.instance SET boot_id=%s", (payload["boot_id"],))
    with pytest.raises(ManualError, match="operation_rejected"):
        commands.activation_ack(actor, operation, payload)
    assert h.read("SELECT count(*) FROM governance.ack") == [(0,)]


def test_revoked_active_artifact_signer_cannot_keep_business_serving(harness):
    h = harness
    active(h)
    assert h.create()["id"]
    with psycopg.connect(h.database.admin) as connection:
        connection.execute("UPDATE governance.signer SET active=false")
    with pytest.raises(ManualError):
        h.create()
    assert h.service.health_read(h.operator)["ready"] is False
