"""Real PostgreSQL cloned-target/current signed journal qualification.

Clone import is explicit here; full encrypted pg_dump/pg_restore is verified by
the integration owner. Authentication and routing are outside this adapter.
"""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from care_link_data.assistance import AssistanceCoordinator
from care_link_data.recovery import PostgresQuarantineValidator
from care_link_data.values import stamp
from care_link_domain import ManualError, WorkloadPeer
from care_link_recovery_control import FileJournal
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

from services.data.tests.test_imp07_lifecycle import followup, grant
from services.data.tests.test_imp07_lifecycle import life as fixture_life

life = fixture_life


def key():
    return str(uuid4())


def append(journal, restriction):
    return journal.append(
        {
            "command_id": key(),
            "expected_tip": str(journal.head().tip),
            "kind": "restrict_intent",
            "scope": {
                "session_id": None,
                "subject_id": None,
                "purpose": "recovery",
                "fields": [],
                "recipient_id": None,
            },
            "restriction": restriction,
            "binding_digest": "a" * 64,
            "db_operation_id": None,
            "relaxation_evidence_digest": None,
        }
    )


@pytest.fixture
def target(life, tmp_path):
    h = life
    journal = FileJournal.provision(
        tmp_path / "journal", Ed25519PrivateKey.generate(), "recovery-test"
    )
    h.service.journal = journal
    with psycopg.connect(h.database.admin) as connection:
        connection.execute(
            "UPDATE control.guard SET journal_id=%s,journal_generation=1,"
            "restriction_barrier=0,journal_tip_seen=0",
            (journal.journal_id,),
        )
    session = h.create()
    h.service.continuation_bootstrap(h.participant, key(), session["id"])
    contact = grant(h, session)
    follow = followup(h, session, contact, pending=True)
    audit = h.read("SELECT digest FROM audit.head")[0][0]
    name = "imp09_quarantine_" + uuid4().hex
    with psycopg.connect(h.database.admin, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                sql.Identifier(name), sql.Identifier("imp03_manual")
            )
        )
        connection.execute(
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name))
        )
    dsn = make_conninfo(**{**conninfo_to_dict(h.database.admin), "dbname": name})
    try:
        with psycopg.connect(dsn) as connection:
            connection.execute("UPDATE control.guard SET mode='quarantine',serving_generation=0")
        validator = PostgresQuarantineValidator(
            dsn, name, key(), "a" * 64, "b" * 64, str(audit), h.operator.account_id
        )
        yield h, session, contact, follow, journal, validator
    finally:
        with psycopg.connect(h.database.admin, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )


def test_old_snapshot_cannot_revive_grants_tokens_or_delivery(target):
    h, session, contact, follow, journal, validator = target
    append(
        journal,
        {
            "kind": "subject_delete",
            "subject_id": session["subject_id"],
            "rights_request_id": key(),
            "subject_revision": "3",
            "effective_at": stamp(datetime.now(UTC)),
        },
    )
    append(
        journal,
        {
            "kind": "identity_revoke",
            "principal_id": h.participant.account_id,
            "identity_revision": "4",
            "disabled": True,
        },
    )
    replayed_hold = key()
    append(
        journal,
        {
            "kind": "hold",
            "hold_id": replayed_hold,
            "scope": {
                "session_id": session["id"],
                "subject_id": session["subject_id"],
                "purpose": "rights",
                "fields": [],
                "recipient_id": None,
            },
            "authority_ref": key(),
            "starts_at": stamp(datetime.now(UTC)),
            "expires_at": None,
        },
    )
    evidence = validator.reconcile(journal.head(), journal.records())
    assert evidence["uncertainties"] == []
    assert evidence["target_digest"] == validator.inspect()
    with psycopg.connect(validator.dsn) as connection:
        assert connection.execute(
            "SELECT delete_state,authority_revision FROM core.subject_guard"
        ).fetchone() == ("restricted", 3)
        assert connection.execute(
            "SELECT count(*) FROM consent.current_grant WHERE revoked_at IS NULL"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM core.session_acl WHERE revoked_at IS NULL"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM access.continuation_family WHERE status='active'"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM access.continuation_token WHERE consumed_at IS NULL"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT state FROM care.follow_up WHERE id=%s", (follow["id"],)
        ).fetchone() == ("reconciliation_needed",)
        assert connection.execute("SELECT count(*) FROM care.inbox_message").fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM lifecycle.hold WHERE id=%s AND released_at IS NULL",
            (replayed_hold,),
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT mode,serving_generation FROM control.guard"
        ).fetchone() == ("quarantine", 0)
        assert connection.execute(
            "SELECT revoked,identity_revision FROM control.principal_guard WHERE principal_id=%s",
            (h.participant.account_id,),
        ).fetchone() == (True, 4)
    # Original source is unchanged by target reconciliation.
    assert h.read("SELECT count(*) FROM consent.current_grant WHERE revoked_at IS NULL")[0][0] == 1


def test_corrupt_audit_and_incomplete_head_deny_without_partial_reconciliation(target):
    _h, _session, _contact, _follow, journal, validator = target
    append(
        journal,
        {
            "kind": "identity_revoke",
            "principal_id": key(),
            "identity_revision": "4",
            "disabled": True,
        },
    )
    with pytest.raises(ManualError, match="journal_incomplete"):
        validator.reconcile(journal.head(), ())
    with psycopg.connect(validator.dsn) as connection:
        connection.execute("UPDATE audit.head SET digest=repeat('f',64)")
    with pytest.raises(ManualError, match="audit_checkpoint_mismatch"):
        validator.reconcile(journal.head(), journal.records())
    with psycopg.connect(validator.dsn) as connection:
        assert connection.execute(
            "SELECT count(*) FROM access.continuation_family WHERE status='active'"
        ).fetchone() == (1,)


def test_stale_head_changed_target_and_serving_target_are_detected(target):
    _h, _session, _contact, _follow, journal, validator = target
    head = journal.head()
    with pytest.raises(ManualError, match="current_head_required"):
        validator.reconcile(replace(head, observed_at=head.observed_at - timedelta(seconds=2)), ())
    evidence = validator.reconcile(journal.head(), ())
    with psycopg.connect(validator.dsn) as connection:
        connection.execute("UPDATE core.session SET revision=revision+1")
    assert validator.inspect() != evidence["target_digest"]
    with psycopg.connect(validator.dsn) as connection:
        connection.execute("UPDATE control.guard SET mode='normal',serving_generation=2")
    with pytest.raises(ManualError, match="target_not_quarantined"):
        validator.reconcile(journal.head(), ())


def test_normal_database_name_cannot_be_reconciled():
    with pytest.raises(ValueError, match="quarantine"):
        PostgresQuarantineValidator(
            "dbname=production", "production", key(), "a" * 64, "b" * 64, "c" * 64, key()
        )


def test_fresh_external_principals_only_and_no_old_acl_or_revision_rollback(target):
    h, _session, _contact, _follow, journal, validator = target
    fresh = replace(h.participant, account_id=key(), identity_evidence_id=key())
    validator.current_principals = lambda: (fresh,)
    evidence = validator.reconcile(journal.head(), ())
    assert evidence["target_digest"] == validator.inspect()
    with psycopg.connect(validator.dsn) as connection:
        assert connection.execute(
            "SELECT revoked FROM control.principal_guard WHERE principal_id=%s", (fresh.account_id,)
        ).fetchone() == (False,)
        assert connection.execute(
            "SELECT revoked FROM control.principal_guard WHERE principal_id=%s",
            (h.participant.account_id,),
        ).fetchone() == (True,)
    # The prior validation revoked this unproven old principal; equal revision
    # cannot undo that fence. Explicit stronger current identity may re-admit
    # basic identity alone, never restore ACL or consent.
    validator.current_principals = lambda: (h.participant,)
    with pytest.raises(ManualError, match="stronger_current_identity_required"):
        validator.reconcile(journal.head(), ())
    current = replace(h.participant, identity_revision=2, identity_evidence_id=key())
    validator.current_principals = lambda: (current,)
    validator.reconcile(journal.head(), ())
    with psycopg.connect(validator.dsn) as connection:
        assert connection.execute(
            "SELECT revoked,identity_revision FROM control.principal_guard WHERE principal_id=%s",
            (current.account_id,),
        ).fetchone() == (False, 2)
        assert connection.execute(
            "SELECT count(*) FROM core.session_acl WHERE revoked_at IS NULL"
        ).fetchone() == (0,)
    validator.current_principals = lambda: (h.participant,)
    with pytest.raises(ManualError, match="stronger_current_identity_required"):
        validator.reconcile(journal.head(), ())


def test_current_kill_for_different_artifact_requires_reconciliation(target):
    _h, _session, _contact, _follow, journal, validator = target
    append(journal, {"kind": "kill", "mode": "restricted", "epoch": "3", "bundle_digest": "f" * 64})
    evidence = validator.reconcile(journal.head(), journal.records())
    assert len(evidence["uncertainties"]) == 1


@pytest.mark.parametrize("mode", ["restricted", "quarantine"])
def test_matching_artifact_operational_kill_still_blocks_promotion(target, mode):
    _h, _session, _contact, _follow, journal, validator = target
    append(journal, {"kind": "kill", "mode": mode, "epoch": "3", "bundle_digest": "a" * 64})
    evidence = validator.reconcile(journal.head(), journal.records())
    assert len(evidence["uncertainties"]) == 1
    with psycopg.connect(validator.dsn) as connection:
        assert connection.execute(
            "SELECT disposition FROM recovery.restriction WHERE kind='kill'"
        ).fetchone() == ("unresolved",)
        # An older snapshot's applied marker never establishes current release.
        connection.execute(
            "UPDATE recovery.restriction SET disposition='applied' WHERE kind='kill'"
        )
    # Retrying validation cannot turn a successful restrictive replay into release.
    again = validator.reconcile(journal.head(), journal.records())
    assert again["uncertainties"] == evidence["uncertainties"]


def test_restored_encrypted_task_lease_proposal_and_review_are_fenced(target):
    h, session, _contact, _follow, journal, validator = target
    tid, did, step = key(), key(), key()
    certificate_expiry = datetime.now(UTC) + timedelta(hours=1)
    peer = WorkloadPeer("spiffe://care-link.demo/demo/runtime", 1, "e" * 64, certificate_expiry)
    task = {
        "id": tid,
        "state": "planning",
        "revision": "3",
        "fence": 4,
        "draft_id": did,
        "proposal_reservation": key(),
        "deadline": stamp(certificate_expiry),
        "steps_used": 3,
        "tools_used": 2,
        "proposals_used": 1,
        "source_vector": {},
        "function": "worker_summary",
        "safe_reason": None,
        "lease": {
            "step_id": step,
            "owner": peer.workload_id,
            "owner_generation": 1,
            "owner_certificate": peer.certificate_digest,
            "owner_certificate_expires_at": stamp(certificate_expiry),
            "expires_at": stamp(datetime.now(UTC) + timedelta(seconds=90)),
        },
    }
    draft = {
        "id": did,
        "task_id": tid,
        "state": "accepted",
        "revision": "2",
        "task_revision": "3",
        "task_fence": 4,
        "review": {"id": key(), "decision": "accept"},
        "expires_at": stamp(certificate_expiry),
        "ai_provenance": True,
        "text_ciphertext": h.service.cipher.encrypt("Fictional draft"),
    }

    def encode(value):
        return Jsonb({"ciphertext": h.service.cipher.encrypt(json.dumps(value))})

    with psycopg.connect(validator.dsn) as connection:
        connection.execute(
            "INSERT INTO assistance.task(id,principal_id,session_id,body) VALUES(%s,%s,%s,%s)",
            (tid, h.worker.account_id, session["id"], encode(task)),
        )
        connection.execute(
            "INSERT INTO assistance.draft VALUES(%s,%s,%s,%s,%s)",
            (did, h.worker.account_id, session["id"], tid, encode(draft)),
        )
    coordinator = AssistanceCoordinator(
        h.service, admitted=lambda _: True, runtime_current=lambda _: True
    )
    old_command = {"expected_task_revision": "3", "fence": "4", "step_id": step}
    assert coordinator._lease(task, old_command, peer)["step_id"] == step
    with pytest.raises(ManualError, match="content_key_required"):
        validator.reconcile(journal.head(), ())
    validator.content_cipher = h.service.cipher
    evidence = validator.reconcile(journal.head(), ())
    assert evidence["uncertainties"] == []
    with psycopg.connect(validator.dsn) as connection:
        task_after = json.loads(
            h.service.cipher.decrypt(
                connection.execute(
                    "SELECT body->>'ciphertext' FROM assistance.task WHERE id=%s", (tid,)
                ).fetchone()[0]
            )
        )
        draft_after = json.loads(
            h.service.cipher.decrypt(
                connection.execute(
                    "SELECT body->>'ciphertext' FROM assistance.draft WHERE id=%s", (did,)
                ).fetchone()[0]
            )
        )
    assert (
        task_after["state"] == "cancelled"
        and task_after["revision"] == "4"
        and task_after["fence"] == 5
    )
    assert (
        task_after["lease"] is task_after["draft_id"] is task_after["proposal_reservation"] is None
    )
    assert (task_after["steps_used"], task_after["tools_used"], task_after["proposals_used"]) == (
        3,
        2,
        1,
    )
    assert (
        draft_after["state"] == "stale"
        and draft_after["review"] is None
        and draft_after["revision"] == "3"
    )
    assert draft_after["ai_provenance"] is True
    assert h.service.cipher.decrypt(draft_after["text_ciphertext"]) == "Fictional draft"
    with pytest.raises(ManualError, match="stale_lease"):
        coordinator._lease(task_after, old_command, peer)
    assert not coordinator.current_draft(task_after, draft_after)


def test_current_existing_identity_rebinds_without_restoring_old_grants(target):
    h, _session, _contact, _follow, journal, validator = target
    validator.current_principals = lambda: (h.participant,)
    evidence = validator.reconcile(journal.head(), ())
    assert evidence["uncertainties"] == []
    with psycopg.connect(validator.dsn) as connection:
        assert connection.execute(
            "SELECT revoked FROM control.principal_guard WHERE principal_id=%s",
            (h.participant.account_id,),
        ).fetchone() == (False,)
        assert connection.execute(
            "SELECT count(*) FROM consent.current_grant WHERE revoked_at IS NULL"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM core.session_acl WHERE revoked_at IS NULL"
        ).fetchone() == (0,)


def test_missing_postcapture_service_suspend_guard_remains_unresolved(target):
    _h, _session, _contact, _follow, journal, validator = target
    append(
        journal,
        {
            "kind": "service_suspend",
            "service_id": key(),
            "directory_revision": "4",
            "suspended": True,
        },
    )
    evidence = validator.reconcile(journal.head(), journal.records())
    assert len(evidence["uncertainties"]) == 1
