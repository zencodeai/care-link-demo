"""Actual encrypted temporary files, fsync paths and immutable backup expiry."""

import os
from datetime import timedelta
from uuid import uuid4

import pytest
from care_link_identity import EncryptedIdentityBackups, IdentityError
from conftest import signed_in
from test_retention import configured

pytestmark = pytest.mark.unit


def backup_fixture(identity, tmp_path):
    service, store, _provider, clock, _key = identity
    retention, authority, cleanup, _backups, account = configured(identity)
    path = tmp_path / "identity-backups"
    path.mkdir(mode=0o700)
    backups = EncryptedIdentityBackups(store, service.custody, path, os.getuid(), authority, clock)
    retention.backups = backups
    return backups, retention, account


def test_consistent_encrypted_capture_excludes_bearers_and_retries_do_not_renew_expiry(
    identity, tmp_path
):
    service, _store, _provider, clock, _key = identity
    signed_in(service)
    backups, retention, account = backup_fixture(identity, tmp_path)
    capture_id = str(uuid4())
    record = backups.capture(capture_id, "operator")
    assert record["state"] == "durable"
    raw = (backups.directory / (capture_id + ".enc")).read_bytes()
    assert b"provider-subject" not in raw and b"server-only-access-token" not in raw
    assert (backups.directory / (capture_id + ".enc")).stat().st_mode & 0o777 == 0o600
    quarantine = backups.restore_to_quarantine(capture_id, retention)
    assert not {kind for kind, _key, _row in quarantine} & {
        "session",
        "proof",
        "intent",
        "ceremony",
    }
    assert all(row["enabled"] is False for kind, _key, row in quarantine if kind == "account")
    expires = record["expires_at"]
    clock.advance(3600)
    assert backups.capture(capture_id, "operator")["expires_at"] == expires
    assert backups.clearance(account).restorable_copies == 1


def test_capture_reply_loss_recovers_same_bytes_and_original_expiry(
    identity, tmp_path, monkeypatch
):
    _service, store, _provider, _clock, _key = identity
    backups, _retention, _account = backup_fixture(identity, tmp_path)
    capture_id = str(uuid4())
    original = backups._reconcile_locked

    def lost_reply(*args):
        raise OSError("fixture lost ack after file fsync")

    monkeypatch.setattr(backups, "_reconcile_locked", lost_reply)
    with pytest.raises(IdentityError):
        backups.capture(capture_id, "operator")
    assert store.get("backup_capture", capture_id)["state"] == "pending"
    before = (backups.directory / (capture_id + ".enc")).read_bytes()
    monkeypatch.setattr(backups, "_reconcile_locked", original)
    assert backups.reconcile_capture(capture_id)["state"] == "durable"
    assert (backups.directory / (capture_id + ".enc")).read_bytes() == before


def test_profile_cleanup_waits_for_original_captured_copy_expiry_not_new_empty_captures(
    identity, tmp_path
):
    _service, _store, _provider, clock, _key = identity
    backups, retention, account = backup_fixture(identity, tmp_path)
    retention.deprovision(account, str(uuid4()), "operator")
    clock.advance(29 * 86400)
    old = str(uuid4())
    backups.capture(old, "operator")
    clock.advance(86400)
    assert retention.purge_due(account, "operator")["backup_state"] == "pending"
    after = str(uuid4())
    backups.capture(after, "operator")
    assert backups.clearance(account).restorable_copies == 1
    clock.advance(6 * 86400)
    assert backups.expire() == 1
    assert not (backups.directory / (old + ".enc")).exists()
    assert (backups.directory / (after + ".enc")).exists()
    result = retention.reconcile("profile:" + account, "operator")
    assert result["state"] == "active_profile_removed_known_copies_accounted"
    with pytest.raises(IdentityError):
        backups.restore_to_quarantine(old, retention)


def test_corrupt_unknown_or_unsafe_copies_never_clear_inventory(identity, tmp_path):
    _service, _store, _provider, _clock, _key = identity
    backups, retention, account = backup_fixture(identity, tmp_path)
    capture = str(uuid4())
    backups.capture(capture, "operator")
    path = backups.directory / (capture + ".enc")
    path.write_bytes(path.read_bytes()[:-5])
    assert not backups.clearance(account).fully_accounted
    with pytest.raises(IdentityError):
        backups.restore_to_quarantine(capture, retention)
    (backups.directory / "unknown.enc").write_bytes(b"unknown")
    assert not backups.clearance(account).fully_accounted
    backups.directory.chmod(0o755)
    with pytest.raises(IdentityError):
        backups.clearance(account)


def test_backup_expiry_never_touches_another_custody_directory(identity, tmp_path):
    service, store, _provider, clock, _key = identity
    backups, retention, account = backup_fixture(identity, tmp_path)
    other_path = tmp_path / "other-custody"
    other_path.mkdir(mode=0o700)
    other = EncryptedIdentityBackups(
        store, service.custody, other_path, os.getuid(), retention.authority, clock
    )
    capture = str(uuid4())
    other.capture(capture, "operator")
    assert not backups.clearance(account).fully_accounted
    clock.advance(7 * 86400 + 1)
    assert backups.expire() == 0 and (other_path / (capture + ".enc")).exists()
    assert other.expire() == 1


def test_terminal_inventory_minimizes_links_only_ninety_days_after_actual_unlink(
    identity, tmp_path
):
    _service, store, _provider, clock, _key = identity
    backups, _retention, account = backup_fixture(identity, tmp_path)
    capture = str(uuid4())
    original = backups.capture(capture, "operator")
    clock.advance(7 * 86400)
    assert backups.expire() == 1
    clock.advance(89 * 86400)
    assert backups.minimize_terminal_inventory() == 0
    assert account in store.get("backup_capture", capture)["account_ids"]
    clock.advance(86400)
    assert backups.minimize_terminal_inventory() == 1
    minimized = store.get("backup_capture", capture)
    assert minimized["account_ids"] == minimized["profile_account_ids"] == []
    assert account not in str(minimized)
    assert minimized["ciphertext_digest"] == original["ciphertext_digest"]
    assert minimized["expires_at"] == original["expires_at"]
    assert minimized["reason"] == "expired_capture_replay_restriction"
    assert minimized["owner"] == "main" and "review_date" in minimized
    assert backups.minimize_terminal_inventory() == 0
    assert backups.capture(capture, "operator") == minimized
    assert not (backups.directory / (capture + ".enc")).exists()


def test_terminal_inventory_holds_and_reviewer_dependencies_are_rechecked(identity, tmp_path):
    _service, _store, _provider, clock, _key = identity
    backups, retention, account = backup_fixture(identity, tmp_path)
    capture = str(uuid4())
    backups.capture(capture, "operator")
    hold = retention.add_hold(account, "copy_review", clock() + timedelta(days=1), "operator")
    evidence = retention.register_record(
        account,
        "reviewer_evidence",
        {"action": "copy_review"},
        clock(),
        "operator",
        frozenset({"copy-dependent-review"}),
    )
    clock.advance(7 * 86400)
    backups.expire()
    clock.advance(90 * 86400)
    assert backups.minimize_terminal_inventory() == 0
    retention.release_hold(hold, "operator")
    assert backups.minimize_terminal_inventory() == 0
    retention.end_dependency(evidence, "copy-dependent-review", "operator")
    assert backups.minimize_terminal_inventory() == 1


def test_terminal_inventory_retains_linkage_while_related_foreign_copy_outstanding(
    identity, tmp_path
):
    service, store, _provider, clock, _key = identity
    backups, retention, account = backup_fixture(identity, tmp_path)
    capture = str(uuid4())
    backups.capture(capture, "operator")
    clock.advance(7 * 86400)
    backups.expire()
    clock.advance(90 * 86400)
    foreign_path = tmp_path / "foreign-custody"
    foreign_path.mkdir(mode=0o700)
    foreign = EncryptedIdentityBackups(
        store, service.custody, foreign_path, os.getuid(), retention.authority, clock
    )
    foreign.capture(str(uuid4()), "operator")
    assert backups.minimize_terminal_inventory() == 0
    assert account in store.get("backup_capture", capture)["account_ids"]
    clock.advance(7 * 86400)
    foreign.expire()
    assert backups.minimize_terminal_inventory() == 1


def test_returned_terminal_file_never_clears_after_inventory_link_minimization(identity, tmp_path):
    _service, _store, _provider, clock, _key = identity
    backups, _retention, account = backup_fixture(identity, tmp_path)
    capture = str(uuid4())
    backups.capture(capture, "operator")
    path = backups.directory / (capture + ".enc")
    bytes_before = path.read_bytes()
    clock.advance(7 * 86400)
    backups.expire()
    clock.advance(90 * 86400)
    assert backups.minimize_terminal_inventory() == 1
    path.write_bytes(bytes_before)
    assert not backups.clearance(account).fully_accounted
    assert not backups.clearance(str(uuid4())).fully_accounted
    with pytest.raises(IdentityError):
        backups.restore_to_quarantine(capture, _retention)


def test_terminal_inventory_unknown_unlink_anchor_and_unknown_files_stay_pending(
    identity, tmp_path
):
    _service, store, _provider, clock, _key = identity
    backups, _retention, account = backup_fixture(identity, tmp_path)
    capture = str(uuid4())
    backups.capture(capture, "operator")
    clock.advance(7 * 86400)
    backups.expire()
    clock.advance(90 * 86400)
    (backups.directory / "unmanaged-copy.enc").write_bytes(b"unknown")
    assert backups.minimize_terminal_inventory() == 0
    (backups.directory / "unmanaged-copy.enc").unlink()
    with store.transaction() as tx:
        record = tx.get("backup_capture", capture)
        del record["unlinked_at"]
        tx.put("backup_capture", capture, record)
    assert backups.minimize_terminal_inventory() == 0
    assert account in store.get("backup_capture", capture)["account_ids"]
