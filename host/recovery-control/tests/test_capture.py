from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from care_link_domain import ManualError
from care_link_recovery_control import CaptureMetadata, EncryptedCaptures, FileJournal
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

NOW = datetime(2026, 11, 9, tzinfo=UTC)
META = CaptureMetadata("imp03-001", "1" * 64, "2" * 64, "3" * 64, "0/12345678")


@pytest.fixture
def captures(tmp_path: Path) -> tuple[EncryptedCaptures, FileJournal, str]:
    key = Ed25519PrivateKey.generate()
    journal = FileJournal.provision(tmp_path / "journal", key, "journal", clock=lambda: NOW)
    path = tmp_path / "captures"
    EncryptedCaptures.provision(path)
    store = EncryptedCaptures(path, b"k" * 32, key, "capture", clock=lambda: NOW)
    identity = str(uuid4())
    store.capture(
        identity,
        {"database.dump": b"fictional dump bytes", "objects.bin": b"private artifact"},
        META,
        journal.head(),
        capture_at=NOW,
    )
    return store, journal, identity


def test_capture_encrypts_inventory_and_stages_quarantine_only(
    captures: tuple[EncryptedCaptures, FileJournal, str], tmp_path: Path
) -> None:
    store, journal, identity = captures
    assert (
        b"fictional dump bytes" not in (store.path / identity / "database.dump.aesgcm").read_bytes()
    )
    view = store.inspect(identity)
    assert view["state"] == "verified" and view["expires_at"] == "2026-11-16T00:00:00Z"
    restored = store.restore_quarantine(identity, tmp_path / "target", journal.head())
    assert restored.serving_allowed is False and restored.state == "quarantined_unvalidated"
    assert (restored.path / "database.dump").read_bytes() == b"fictional dump bytes"
    assert (
        b'"must_disable_restored_credentials":true'
        in (restored.path / "quarantine.json").read_bytes()
    )


def test_retry_keeps_original_expiry_and_conflicts_on_changed_capture(
    captures: tuple[EncryptedCaptures, FileJournal, str],
) -> None:
    store, journal, identity = captures
    before = store.inspect(identity)
    store.clock = lambda: NOW + timedelta(days=1)
    objects = {"database.dump": b"fictional dump bytes", "objects.bin": b"private artifact"}
    assert store.capture(identity, objects, META, journal.head(), capture_at=NOW) == before
    with pytest.raises(ManualError, match="idempotency_conflict"):
        store.capture(identity, objects, META, journal.head(), capture_at=store.clock())


@pytest.mark.parametrize("delta", [timedelta(days=7), timedelta(days=8)])
def test_expiry_equality_and_later_deny_restore(
    captures: tuple[EncryptedCaptures, FileJournal, str], tmp_path: Path, delta: timedelta
) -> None:
    store, journal, identity = captures
    store.clock = lambda: NOW + delta
    with pytest.raises(ManualError, match="expired"):
        store.restore_quarantine(identity, tmp_path / "target", journal.head())
    assert not (tmp_path / "target").exists()


@pytest.mark.parametrize("filename", ["database.dump.aesgcm", "manifest.json"])
def test_modified_ciphertext_or_manifest_denies(
    captures: tuple[EncryptedCaptures, FileJournal, str], filename: str
) -> None:
    store, _, identity = captures
    path = store.path / identity / filename
    value = path.read_bytes()
    path.write_bytes(value[:-1] + bytes([value[-1] ^ 1]))
    with pytest.raises(ManualError):
        store.inspect(identity)


def test_missing_extra_and_partial_inventory_are_not_accepted(
    captures: tuple[EncryptedCaptures, FileJournal, str],
) -> None:
    store, _, identity = captures
    (store.path / identity / "extra.aesgcm").write_bytes(b"unknown")
    with pytest.raises(ManualError, match="inventory_incomplete"):
        store.inspect(identity)
    (store.path / identity / "extra.aesgcm").unlink()
    (store.path / identity / "database.dump.aesgcm").unlink()
    with pytest.raises(ManualError, match="object_invalid"):
        store.inspect(identity)
    partial = str(uuid4())
    (store.path / partial).mkdir()
    with pytest.raises(ManualError, match="incomplete"):
        store.inspect(partial)


def test_wrong_encryption_key_denies(captures: tuple[EncryptedCaptures, FileJournal, str]) -> None:
    store, _, identity = captures
    other = EncryptedCaptures(store.path, b"z" * 32, store.signer, store.key_id, clock=lambda: NOW)
    with pytest.raises(ManualError, match="object_invalid"):
        other.inspect(identity)


def test_old_or_unrelated_journal_denies_before_staging(
    captures: tuple[EncryptedCaptures, FileJournal, str], tmp_path: Path
) -> None:
    store, journal, identity = captures
    head = journal.head()
    wrong = replace(head, journal_id=str(uuid4()))
    with pytest.raises(ManualError, match="current_journal_required"):
        store.restore_quarantine(identity, tmp_path / "target", wrong)
    wrong_digest = replace(head, tip_digest="f" * 64)
    with pytest.raises(ManualError, match="current_journal_required"):
        store.restore_quarantine(identity, tmp_path / "target", wrong_digest)
    assert not (tmp_path / "target").exists()


def test_target_reuse_and_path_traversal_are_denied(
    captures: tuple[EncryptedCaptures, FileJournal, str], tmp_path: Path
) -> None:
    store, journal, identity = captures
    store.restore_quarantine(identity, tmp_path / "target", journal.head())
    with pytest.raises(FileExistsError):
        store.restore_quarantine(identity, tmp_path / "target", journal.head())
    with pytest.raises(ValueError, match="object names"):
        store.capture(
            str(uuid4()),
            {"database.dump": b"dump", "../escape": b"bad"},
            META,
            journal.head(),
            capture_at=NOW,
        )
