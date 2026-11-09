"""Real SQLite lifecycle, terminal anchors, negative retry markers and checkpoints."""

from contextlib import closing
from datetime import timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from care_link_help import BrowserContext, HelpError, Spool
from care_link_help.audit import verify_history
from care_link_help.lifecycle_schema import key_digest
from test_help import Harness

pytestmark = pytest.mark.unit


def _managed_bytes(path: Path) -> bytes:
    return b"".join(
        item.read_bytes()
        for item in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm"))
        if item.exists()
    )


def test_terminal_cleanup_removes_actual_owner_worker_principal_bytes_from_database_and_wal(
    tmp_path,
):
    h = Harness(tmp_path)
    worker = BrowserContext(str(uuid4()), "worker", "csrf")
    # An open idle connection keeps the real WAL available for inspection,
    # without pinning a reader snapshot or forcing the last-close checkpoint.
    with closing(h.spool._connect()) as keeper:
        assert keeper.execute("PRAGMA secure_delete").fetchone()[0] == 1
        target = cast(str, h.execute("create", h.owner)["id"])
        h.execute("accept", worker, target=target)
        h.execute("cancel", h.owner, target=target, revision="2")
        before = _managed_bytes(h.spool.path)
        for account in (h.owner.account_id, worker.account_id):
            assert account.encode() in before
        h.clock.now += timedelta(days=91)
        result = h.spool.lifecycle.run()
        assert result["managed_copy_cleanup"] == "complete"
        assert result["managed_copy_reader_pending"] is False
        assert result["physical_erasure_claim"] is False
        assert result["backup_cleanup"] == "pending_separate_spool_copy_inventory"
        after = _managed_bytes(h.spool.path)
        for account in (h.owner.account_id, worker.account_id):
            assert account.encode() not in after
        assert h.spool.lifecycle.status()["managed_copy_cleanup"] == "complete"


def test_pinned_reader_leaves_managed_copy_pending_then_retry_cleans_bytes(tmp_path):
    h = Harness(tmp_path)
    target = cast(str, h.execute("create", h.owner)["id"])
    h.execute("cancel", h.owner, target=target)
    h.clock.now += timedelta(days=91)
    with closing(h.spool._connect()) as reader:
        reader.execute("BEGIN")
        assert (
            reader.execute("SELECT owner_account FROM request").fetchone()[0] == h.owner.account_id
        )
        result = h.spool.lifecycle.run()
        assert result["terminal_linkages_removed"] == 1
        assert result["managed_copy_cleanup"] == "pending_busy_or_reader"
        assert result["managed_copy_reader_pending"] is True
        assert h.owner.account_id.encode() in _managed_bytes(h.spool.path)
        assert (
            reader.execute("SELECT owner_account FROM request").fetchone()[0] == h.owner.account_id
        )
        assert h.spool.lifecycle.status()["managed_copy_cleanup"] == "pending_busy_or_reader"
        reader.rollback()
    result = h.spool.lifecycle.run()
    assert result["managed_copy_cleanup"] == "complete"
    assert h.owner.account_id.encode() not in _managed_bytes(h.spool.path)
    restarted = Spool(h.spool.path, clock=h.clock)
    assert restarted.lifecycle.status()["managed_copy_cleanup"] == "complete"


def test_vacuum_cleans_legacy_free_pages_created_before_secure_delete(tmp_path):
    h = Harness(tmp_path)
    legacy_owner = str(uuid4())
    with closing(h.spool._connect()) as keeper:
        keeper.execute("PRAGMA secure_delete=OFF")
        keeper.execute("CREATE TABLE legacy_deleted_profile (account TEXT)")
        keeper.execute("INSERT INTO legacy_deleted_profile VALUES (?)", (legacy_owner,))
        keeper.execute("DELETE FROM legacy_deleted_profile")
        assert legacy_owner.encode() in _managed_bytes(h.spool.path)
        assert h.spool.lifecycle.run()["managed_copy_cleanup"] == "complete"
        assert legacy_owner.encode() not in _managed_bytes(h.spool.path)


def test_only_cancelled_terminal_anchor_can_remove_linkage_after_ninety_days(tmp_path):
    h = Harness(tmp_path)
    key = str(uuid4())
    created = h.execute("create", h.owner, key=key)
    help_id = cast(str, created["id"])
    h.clock.now += timedelta(days=89)
    cancelled = h.execute("cancel", h.owner, target=help_id)
    assert cancelled["state"] == "cancelled"
    h.clock.now += timedelta(days=89)
    assert h.spool.lifecycle.run()["terminal_linkages_removed"] == 0
    h.clock.now += timedelta(days=1)
    result = h.spool.lifecycle.run()
    assert result["terminal_linkages_removed"] == 1
    with closing(h.spool._connect()) as connection:
        assert connection.execute("SELECT count(*) FROM request").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM operation").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM operation_lifecycle").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM retired_help_key").fetchone()[0] >= 3
        assert connection.execute(
            "SELECT 1 FROM retired_help_key WHERE key_digest=?", (key_digest("help", help_id),)
        ).fetchone()
    with pytest.raises(HelpError, match="operation_retired"):
        h.execute("create", h.owner, key=key)
    with pytest.raises(HelpError, match="operation_retired"):
        h.execute("status", h.owner, target=help_id)


def test_recent_terminal_status_operation_keeps_its_own_ninety_day_attribution(tmp_path):
    h = Harness(tmp_path)
    target = cast(str, h.execute("create", h.owner)["id"])
    h.execute("cancel", h.owner, target=target)
    h.clock.now += timedelta(days=89)
    h.execute("status", h.owner, target=target)
    h.clock.now += timedelta(days=1)
    assert h.spool.lifecycle.run()["terminal_linkages_removed"] == 0
    h.clock.now += timedelta(days=88)
    assert h.spool.lifecycle.run()["terminal_linkages_removed"] == 0
    h.clock.now += timedelta(days=1)
    assert h.spool.lifecycle.run()["terminal_linkages_removed"] == 1


def test_recorded_and_accepted_unconnected_ownership_never_age_out(tmp_path):
    h = Harness(tmp_path)
    first = h.execute("create", h.owner)
    other = BrowserContext(str(uuid4()), "pid", "csrf")
    second = h.execute("create", other)
    worker = BrowserContext(str(uuid4()), "worker", "csrf")
    h.execute("accept", worker, target=cast(str, second["id"]))
    h.clock.now += timedelta(days=400)
    assert h.spool.lifecycle.run()["terminal_linkages_removed"] == 0
    status = h.spool.lifecycle.status()
    assert status["active_requests"] == 2 and status["active_review_overdue"] == 2
    h.spool.lifecycle.review_active(cast(str, first["id"]))
    assert h.spool.lifecycle.status()["active_review_overdue"] == 1
    assert (
        h.execute("status", other, target=cast(str, second["id"]))["state"]
        == "accepted_unconnected"
    )


def test_overdue_hold_is_explicit_and_never_silently_released(tmp_path):
    h = Harness(tmp_path)
    created = h.execute("create", h.owner)
    help_id = cast(str, created["id"])
    h.execute("cancel", h.owner, target=help_id)
    hold = h.spool.lifecycle.hold(help_id, "pending_copy_recovery", h.clock() + timedelta(days=2))
    h.clock.now += timedelta(days=100)
    assert h.spool.lifecycle.run()["terminal_linkages_removed"] == 0
    assert h.spool.lifecycle.status()["overdue_holds"] == 1
    h.spool.lifecycle.release_hold(hold)
    assert h.spool.lifecycle.run()["terminal_linkages_removed"] == 1


def test_audit_prefix_checkpoint_survives_restart_and_append_without_references(tmp_path):
    h = Harness(tmp_path)
    created = h.execute("create", h.owner)
    help_id = cast(str, created["id"])
    h.execute("cancel", h.owner, target=help_id)
    with closing(h.spool._connect()) as connection:
        last = connection.execute(
            "SELECT sequence,hash FROM local_event ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
    h.clock.now += timedelta(days=91)
    result = h.spool.lifecycle.run()
    assert result["audit_prefix_pruned"] == 2
    with closing(h.spool._connect()) as connection:
        checkpoint = connection.execute("SELECT * FROM help_audit_checkpoint").fetchone()
        assert (
            checkpoint["last_deleted_sequence"] == last["sequence"]
            and checkpoint["last_deleted_hash"] == last["hash"]
        )
        assert help_id not in str(tuple(checkpoint)) and h.owner.account_id not in str(
            tuple(checkpoint)
        )
        assert connection.execute("SELECT count(*) FROM local_event").fetchone()[0] == 0
        verify_history(connection)
    restarted = Spool(h.spool.path, clock=h.clock)
    h.spool = restarted
    h.service.spool = restarted
    h.execute("create", h.owner)
    with closing(restarted._connect()) as connection:
        next_event = connection.execute("SELECT * FROM local_event").fetchone()
        assert (
            next_event["sequence"] == last["sequence"] + 1
            and next_event["previous_hash"] == last["hash"]
        )
        verify_history(connection)
    assert restarted.lifecycle.status()["audit_scope"] == "checkpoint_to_current_only"


def test_expired_nonce_metadata_prunes_but_old_authority_still_denies(tmp_path):
    h = Harness(tmp_path)
    h.execute("create", h.owner)
    h.clock.now += timedelta(days=91)
    assert h.spool.lifecycle.run()["expired_nonces_removed"] == 1
    with closing(h.spool._connect()) as connection:
        assert connection.execute("SELECT count(*) FROM decision_nonce").fetchone()[0] == 0
    from care_link_help.model import Decision

    decision = Decision(h.owner.account_id, str(uuid4()), h.clock() - timedelta(days=90), "a" * 64)
    with pytest.raises(HelpError, match="authority_expired"):
        h.spool.apply(
            action="create",
            help_id=str(uuid4()),
            operation_id=str(uuid4()),
            body_digest="a" * 64,
            context=h.owner,
            decision=decision,
            expected_revision=None,
        )


def test_legacy_unknown_anchors_are_migration_pending_not_fabricated(tmp_path):
    h = Harness(tmp_path)
    help_id, operation_id = str(uuid4()), str(uuid4())
    with closing(h.spool._connect()) as connection:
        connection.execute(
            "INSERT INTO request VALUES (?,?,?,'cancelled',NULL,2,?)",
            (help_id, h.owner.account_id, "2020-01-01T00:00:00Z", "a" * 64),
        )
        connection.execute(
            "INSERT INTO operation VALUES (?,?, 'create',?,?)",
            (operation_id, h.owner.account_id, help_id, "b" * 64),
        )
        connection.execute("INSERT INTO decision_nonce VALUES (?)", (str(uuid4()),))
    h.clock.now += timedelta(days=400)
    restarted = Spool(h.spool.path, clock=h.clock)
    assert restarted.lifecycle.status()["migration_pending"] >= 3
    assert restarted.lifecycle.run()["terminal_linkages_removed"] == 0
    with closing(restarted._connect()) as connection:
        assert connection.execute("SELECT * FROM request WHERE id=?", (help_id,)).fetchone()
        assert connection.execute("SELECT count(*) FROM request_lifecycle").fetchone()[0] == 0


def test_retirement_capacity_rolls_back_instead_of_reenabling_old_keys(tmp_path):
    h = Harness(tmp_path)
    created = h.execute("create", h.owner)
    h.execute("cancel", h.owner, target=cast(str, created["id"]))
    h.clock.now += timedelta(days=91)
    h.spool.lifecycle.max_retired_keys = 1
    with pytest.raises(HelpError, match="retirement_capacity"):
        h.spool.lifecycle.run()
    with closing(h.spool._connect()) as connection:
        assert connection.execute("SELECT count(*) FROM request").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM retired_help_key").fetchone()[0] == 0


def test_offline_lifecycle_requires_effective_custodian_and_private_files(tmp_path, monkeypatch):
    import os

    h = Harness(tmp_path)
    actual = os.geteuid()
    monkeypatch.setattr(os, "geteuid", lambda: actual + 1)
    with pytest.raises(HelpError, match="custody_denied"):
        h.spool.lifecycle.run()
    monkeypatch.setattr(os, "geteuid", lambda: actual)
    h.spool.path.chmod(0o644)
    with pytest.raises(HelpError, match="custody_denied"):
        h.spool.lifecycle.status()


def test_unmaterialized_create_intent_is_an_explicit_active_dependency_reviewable_offline(tmp_path):
    h = Harness(tmp_path)
    intent = h.service.prepare_create(
        {"locale": "en-CA", "jurisdiction": None}, h.owner, lambda: str(uuid4())
    )
    with closing(h.spool._connect()) as connection:
        help_id = connection.execute(
            "SELECT help_id FROM create_intent WHERE operation_id=?", (intent["operation_id"],)
        ).fetchone()[0]
    h.clock.now += timedelta(days=91)
    assert h.spool.lifecycle.run()["terminal_linkages_removed"] == 0
    status = h.spool.lifecycle.status()
    assert (
        status["unmaterialized_create_dependencies"] == 1
        and status["unmaterialized_review_overdue"] == 1
    )
    h.spool.lifecycle.review_active(help_id)
    assert h.spool.lifecycle.status()["unmaterialized_review_overdue"] == 0
    assert (
        h.service.prepare_create(
            {"locale": "en-CA", "jurisdiction": None}, h.owner, lambda: str(uuid4())
        )
        == intent
    )


def test_known_terminal_anchor_does_not_invent_legacy_operation_anchor(tmp_path):
    h = Harness(tmp_path)
    target = cast(str, h.execute("create", h.owner)["id"])
    h.execute("cancel", h.owner, target=target)
    with closing(h.spool._connect()) as connection:
        connection.execute(
            "DELETE FROM operation_lifecycle WHERE operation_id="
            "(SELECT id FROM operation WHERE action='create')"
        )
    h.clock.now += timedelta(days=91)
    assert h.spool.lifecycle.status()["migration_pending"] >= 1
    assert h.spool.lifecycle.run()["terminal_linkages_removed"] == 0


def test_active_audit_prefix_never_holes_the_chain_to_prune_later_closed_events(tmp_path):
    h = Harness(tmp_path)
    h.execute("create", h.owner)
    other = BrowserContext(str(uuid4()), "pid", "csrf")
    target = cast(str, h.execute("create", other)["id"])
    h.execute("cancel", other, target=target)
    h.clock.now += timedelta(days=91)
    result = h.spool.lifecycle.run()
    assert result["terminal_linkages_removed"] == 1 and result["audit_prefix_pruned"] == 0
    with closing(h.spool._connect()) as connection:
        verify_history(connection)
        assert connection.execute("SELECT count(*) FROM local_event").fetchone()[0] == 3


def test_corrupt_audit_checkpoint_denies_maintenance_and_new_private_effect(tmp_path):
    h = Harness(tmp_path)
    with closing(h.spool._connect()) as connection:
        connection.execute("UPDATE help_audit_checkpoint SET last_deleted_hash='invalid'")
    with pytest.raises(HelpError, match="checkpoint_invalid"):
        h.spool.lifecycle.run()
    with pytest.raises(HelpError, match="checkpoint_invalid"):
        h.execute("create", h.owner)
    with closing(h.spool._connect()) as connection:
        assert connection.execute("SELECT count(*) FROM request").fetchone()[0] == 0
