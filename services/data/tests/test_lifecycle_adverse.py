"""Independent durable lifecycle, migration and concurrent adverse verification.

Business PostgreSQL and the fsynced signed restriction journal are real. Identity
and policy doubles remain explicit here; the signed boundary suite tests those.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from uuid import uuid4

import psycopg
import pytest
from care_link_data import PostgresStore
from care_link_data.store import Transaction
from care_link_domain import ManualError
from care_link_recovery_control import FileJournal
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

from services.data.tests.test_imp07_lifecycle import execute, key, rights
from services.data.tests.test_imp07_lifecycle import life as configured_life

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def life(harness, monkeypatch):
    return configured_life.__wrapped__(harness, monkeypatch)


def governance(h):
    actor = replace(h.operator, account_id=key(), role="governance")
    PostgresStore(h.database.admin).provision_principal(actor)
    return actor


def hold(h, actor, session):
    epoch = h.read("SELECT epoch FROM control.guard WHERE key='demo'")[0][0]
    return h.service.hold_create(
        actor,
        key(),
        {
            "expected_revision": str(epoch),
            "scope": {
                "session_id": session["id"],
                "subject_id": session["subject_id"],
                "purpose": "rights",
                "fields": [],
                "recipient_id": None,
            },
            "reason": "rights_review",
            "authority_ref": key(),
            "expires_at": None,
        },
    )


def real_journal(h, tmp_path):
    journal = FileJournal.provision(tmp_path / "restrictions", Ed25519PrivateKey.generate(), "test")
    head = journal.head()
    with psycopg.connect(h.database.admin) as connection:
        connection.execute(
            "UPDATE control.guard SET journal_id=%s,journal_generation=%s,"
            "restriction_barrier=%s,journal_tip_seen=%s,serving_generation=%s WHERE key='demo'",
            (
                head.journal_id,
                head.generation,
                head.restriction_barrier,
                head.tip,
                head.serving_generation,
            ),
        )
    h.service.journal = journal
    return journal


def fail_transition_audit(monkeypatch, action):
    append = Transaction.audit_append

    def reject(tx, event):
        if event["action"] == action and event["decision"] == "PERMIT":
            raise ManualError("test.audit_unavailable", 503)
        return append(tx, event)

    monkeypatch.setattr(Transaction, "audit_append", reject)


def test_active_populated_plan_survives_expired_support_copy_cleanup(life):
    h = life
    session = h.create()
    plan = h.service.plan_create(
        h.participant,
        key(),
        {"subject_id": session["subject_id"], "expected_revision": session["revision"]},
    )
    plan = h.service.plan_field_append(
        h.participant,
        key(),
        {
            "expected_revision": plan["revision"],
            "field": "plan.strategies",
            "value": {"kind": "text", "text": "Synthetic independently retained strategy"},
            "source": None,
            "safety_relevant": False,
        },
        plan["id"],
    )
    current = h.service.session_read(h.participant, session["id"])
    h.service.session_end(
        h.participant,
        key(),
        {"expected_revision": current["revision"], "reason": "user_choice"},
        session["id"],
    )
    anchor = datetime.now(UTC) - timedelta(days=8)
    with psycopg.connect(h.database.admin) as connection:
        connection.execute(
            "UPDATE core.session SET closed_at=%s WHERE id=%s",
            (anchor, session["id"]),
        )
        connection.execute(
            "UPDATE lifecycle.copy SET anchor_at=%s,expires_at=%s,state='retained' "
            "WHERE session_id=%s AND purpose='support'",
            (anchor, anchor + timedelta(days=7), session["id"]),
        )
    execute(h, "person")
    assert h.read("SELECT state FROM lifecycle.copy WHERE purpose='support'") == [("purged",)]
    assert h.read(
        "SELECT count(*) FROM lifecycle.copy WHERE purpose='plan' AND state='purged'"
    ) == [(0,)]
    view = h.service.plan_read(h.participant, plan["id"])
    assert view["state"] == "active"
    assert view["fields"][0]["value"]["text"] == "Synthetic independently retained strategy"


def test_concurrent_hold_committed_after_preflight_prevents_every_purge(life, monkeypatch):
    h = life
    session = h.create()
    _operation, _body, request = rights(h, session, "delete")
    actor = governance(h)
    prepared, resume = Event(), Event()
    evaluate = h.policy.evaluate

    def interleave(value):
        result = evaluate(value)
        if value["action"] == "lifecycle_due":
            prepared.set()
            assert resume.wait(timeout=1), "test hold operation did not release the purge preflight"
        return result

    monkeypatch.setattr(h.policy, "evaluate", interleave)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(execute, h, "person")
        assert prepared.wait(timeout=1), "purge did not reach the controlled preflight point"
        try:
            retained = hold(h, actor, session)
        finally:
            resume.set()
        with pytest.raises(ManualError):
            pending.result(timeout=2)
    assert retained["state"] == "committed"
    assert h.read("SELECT count(*) FROM lifecycle.copy WHERE state='purged'") == [(0,)]
    monkeypatch.setattr(h.policy, "evaluate", evaluate)
    execute(h, "person")
    assert h.service.rights_read(h.participant, request["id"])["state"] == "held"
    assert h.read("SELECT count(*) FROM lifecycle.copy WHERE state='purged'") == [(0,)]


def test_carer_own_deletion_excludes_pid_and_other_author_private_report(life):
    h = life
    original = h.participant
    pid_session = h.create()
    carer = replace(original, account_id=key(), role="carer")
    PostgresStore(h.database.admin).provision_principal(carer)
    h.participant = carer
    session = h.service.session_create(
        carer,
        key(),
        {
            "tags": {"environment": "demo", "population": "synthetic"},
            "participant_kind": "carer",
            "jurisdiction": None,
            "locale": "en-CA",
            "channel": "web",
            "persona_id": None,
            "fixture_id": None,
        },
    )
    with pytest.raises(ManualError):
        rights(h, pid_session, "delete")
    assert h.read("SELECT count(*) FROM rights.request") == [(0,)]
    report = key()
    private = h.service.cipher.encrypt('{"kind":"text","text":"Synthetic worker private report"}')
    with psycopg.connect(h.database.admin) as connection:
        connection.execute(
            "INSERT INTO core.assertion VALUES(%s,%s,%s,1,'needs',%s,%s,"
            "'unverified',NULL,clock_timestamp(),clock_timestamp())",
            (report, session["id"], session["subject_id"], private, h.worker.account_id),
        )
        connection.execute(
            "INSERT INTO lifecycle.copy VALUES(%s,%s,%s,'support','assertion',%s,%s,"
            "'synthetic_content','synthetic-test-key','last_parent_closed',NULL,NULL,"
            "'anchor_pending',clock_timestamp())",
            (key(), session["subject_id"], session["id"], report, "assertion:" + report),
        )
    _operation, _body, request = rights(h, session, "delete")
    execute(h, "person")
    progress = h.service.rights_read(carer, request["id"])
    assert "other_author_private_content_retained" in progress["exceptions"]
    assert h.read("SELECT value_ciphertext FROM core.assertion WHERE id=%s", (report,)) == [
        (private,)
    ]
    assert (
        h.service.session_read(original, pid_session["id"])["subject_id"]
        == pid_session["subject_id"]
    )
    assert h.read(
        "SELECT delete_state FROM core.subject_guard WHERE subject_id=%s",
        (pid_session["subject_id"],),
    ) == [("active",)]


def test_real_journal_tombstone_precedes_rolled_back_delete_and_blocks_disclosure(
    life, tmp_path, monkeypatch
):
    h = life
    session = h.create()
    journal = real_journal(h, tmp_path)
    fail_transition_audit(monkeypatch, "rights_create")
    with pytest.raises(ManualError):
        rights(h, session, "delete")
    assert h.read("SELECT count(*) FROM rights.request") == [(0,)]
    assert h.read(
        "SELECT delete_state FROM core.subject_guard WHERE subject_id=%s", (session["subject_id"],)
    ) == [("active",)]
    assert journal.head().restriction_barrier == 1
    entries = journal.records()
    assert entries[0]["command"]["restriction"]["kind"] == "subject_delete"
    assert entries[0]["command"]["restriction"]["subject_id"] == session["subject_id"]
    reopened = FileJournal(
        journal.path, journal.private_key, journal.key_id, expected_journal_id=journal.journal_id
    )
    assert reopened.head().restriction_barrier == 1
    with pytest.raises(ManualError, match="journal_barrier"):
        h.service.session_read(h.participant, session["id"])
    assert h.read("SELECT count(*) FROM lifecycle.copy WHERE state='purged'") == [(0,)]


def test_real_journal_rolled_back_hold_release_never_relaxes_original_hold(
    life, tmp_path, monkeypatch
):
    h = life
    session = h.create()
    actor = governance(h)
    journal = real_journal(h, tmp_path)
    retained = hold(h, actor, session)
    first = journal.records()[0]["command"]["restriction"]
    fail_transition_audit(monkeypatch, "hold_release")
    with pytest.raises(ManualError):
        h.service.hold_release(
            actor, key(), {"expected_revision": retained["revision"]}, retained["resource_id"]
        )
    assert h.read(
        "SELECT released_at FROM lifecycle.hold WHERE id=%s", (retained["resource_id"],)
    ) == [(None,)]
    entries = journal.records()
    assert len(entries) == 2
    assert entries[1]["command"]["kind"] == "restrict_intent"
    assert entries[1]["command"]["restriction"] == first
    assert first["expires_at"] is None
    assert journal.head().restriction_barrier == 2
    assert h.read("SELECT restriction_barrier FROM control.guard") == [(1,)]
    with pytest.raises(ManualError, match="journal_barrier"):
        execute(h, "person")
    assert h.read("SELECT count(*) FROM lifecycle.copy WHERE state='purged'") == [(0,)]


def test_populated_predecessor_copy_classifications_survive_migration_008(life):
    h = life
    session = h.create()
    name = "imp07_upgrade_" + uuid4().hex
    settings = conninfo_to_dict(h.database.admin)
    snapshots = []
    with psycopg.connect(h.database.admin) as connection:
        for table in ("control.principal_guard", "core.persona", "core.session"):
            values = connection.execute(
                sql.SQL("SELECT row_to_json(t) FROM {} t").format(sql.Identifier(*table.split(".")))
            ).fetchall()
            snapshots.append((table, [row[0] for row in values]))
    with psycopg.connect(h.database.admin, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    target = make_conninfo(**{**settings, "dbname": name})
    try:
        with psycopg.connect(target) as connection:
            for filename in (
                "001_manual.sql",
                "003_plans_consent_directory.sql",
                "005_referrals.sql",
                "006_imp06_assistance.sql",
                "007_imp06_inference.sql",
            ):
                content = (ROOT / "services/data/migrations" / filename).read_text()
                if filename == "001_manual.sql":
                    # The shared disposable cluster already provisioned exactly
                    # these fixture roles; every remaining migration byte runs.
                    content = "\n".join(
                        line
                        for line in content.splitlines()
                        if not line.startswith("CREATE ROLE care_link_")
                    )
                connection.execute(content)
            for table, values in snapshots:
                for value in values:
                    connection.execute(
                        sql.SQL(
                            "INSERT INTO {} SELECT * FROM json_populate_record(NULL::{},%s::json)"
                        ).format(
                            sql.Identifier(*table.split(".")), sql.Identifier(*table.split("."))
                        ),
                        (Jsonb(value),),
                    )
            for kind in (
                "referral",
                "assistance_task",
                "assistance_draft",
                "assistance_observation",
            ):
                connection.execute(
                    "INSERT INTO lifecycle.copy VALUES(%s,%s,%s,%s,%s,%s,%s,"
                    "'synthetic_content','synthetic-fixture-key',%s,NULL,NULL,'anchor_pending',%s)",
                    (
                        key(),
                        session["subject_id"],
                        session["id"],
                        "referral" if kind == "referral" else "support",
                        kind,
                        key(),
                        "fixture:" + kind,
                        "referral_terminal_parent" if kind == "referral" else "last_parent_closed",
                        datetime.now(UTC),
                    ),
                )
            connection.execute(
                (ROOT / "services/data/migrations/008_imp07_lifecycle.sql").read_text()
            )
            assert connection.execute(
                "SELECT aggregate_type FROM lifecycle.copy ORDER BY aggregate_type"
            ).fetchall() == [
                ("assistance_draft",),
                ("assistance_observation",),
                ("assistance_task",),
                ("referral",),
            ]
    finally:
        with psycopg.connect(h.database.admin, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )
