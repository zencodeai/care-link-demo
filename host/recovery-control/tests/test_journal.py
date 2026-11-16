import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from care_link_domain import ManualError
from care_link_recovery_control import FileJournal
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

NOW = datetime(2026, 11, 9, tzinfo=UTC)


def command(tip: int = 0, kind: str = "restrict_intent") -> dict[str, object]:
    return {
        "command_id": str(uuid4()),
        "expected_tip": str(tip),
        "kind": kind,
        "scope": {
            "session_id": None,
            "subject_id": None,
            "purpose": "security",
            "fields": [],
            "recipient_id": None,
        },
        "restriction": {
            "kind": "identity_revoke",
            "principal_id": str(uuid4()),
            "identity_revision": "2",
            "disabled": True,
        }
        if kind == "restrict_intent"
        else {"kind": "none"},
        "binding_digest": "1" * 64,
        "db_operation_id": None,
        "relaxation_evidence_digest": None,
    }


@pytest.fixture
def journal(tmp_path: Path) -> FileJournal:
    return FileJournal.provision(
        tmp_path / "journal", Ed25519PrivateKey.generate(), "host-key", clock=lambda: NOW
    )


def reopen(journal: FileJournal) -> FileJournal:
    return FileJournal(
        journal.path,
        journal.private_key,
        journal.key_id,
        expected_journal_id=journal.journal_id,
        clock=lambda: NOW,
    )


def test_restrictive_barrier_and_terminal_tip_survive_restart(journal: FileJournal) -> None:
    initial = journal.head()
    assert initial.tip == initial.restriction_barrier == 0
    first = command()
    restricted = journal.append(first)
    assert restricted.tip == restricted.restriction_barrier == 1
    terminal = command(1, "db_commit_observed")
    terminal["db_operation_id"] = first["command_id"]
    finished = journal.append(terminal)
    assert finished.tip == 2 and finished.restriction_barrier == 1
    assert reopen(journal).head() == finished
    raw = (journal.path / "records.jsonl").read_text()
    assert "identity_revoke" in raw and "disabled" in raw


def test_acknowledgment_retry_is_idempotent_but_changed_request_conflicts(
    journal: FileJournal,
) -> None:
    request = command()
    state = journal.append(request)
    assert journal.append(request) == state
    with pytest.raises(ManualError, match="idempotency_conflict"):
        journal.append({**request, "binding_digest": "2" * 64})
    assert journal.head().tip == 1


def test_same_tip_two_concurrent_writers_only_one_append(journal: FileJournal) -> None:
    other = reopen(journal)

    def run(writer: FileJournal) -> str:
        try:
            writer.append(command())
            return "committed"
        except ManualError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, [journal, other]))
    assert sorted(results) == ["committed", "journal.stale_tip"]
    assert journal.head().tip == 1


@pytest.mark.parametrize("point", ["after_record_fsync", "after_head_fsync"])
def test_interrupted_record_head_gap_quarantines_without_trimming(
    journal: FileJournal, point: str
) -> None:
    def crash(at: str) -> None:
        if at == point:
            raise RuntimeError("crash")

    journal.crash_hook = crash
    with pytest.raises(RuntimeError, match="crash"):
        journal.append(command())
    raw = (journal.path / "records.jsonl").read_bytes()
    with pytest.raises(ManualError, match="head_mismatch"):
        reopen(journal)
    assert (journal.path / "records.jsonl").read_bytes() == raw


def test_lost_ack_after_durable_head_reconciles_existing_command(journal: FileJournal) -> None:
    request = command()

    def crash(at: str) -> None:
        if at == "after_directory_fsync":
            raise RuntimeError("reply lost")

    journal.crash_hook = crash
    with pytest.raises(RuntimeError, match="reply lost"):
        journal.append(request)
    restored = reopen(journal)
    assert restored.append(request).tip == 1
    assert len(restored.records()) == 1


@pytest.mark.parametrize("filename", ["head.json", "origin.json", "records.jsonl"])
def test_modified_signed_bytes_deny(journal: FileJournal, filename: str) -> None:
    journal.append(command())
    path = journal.path / filename
    value = path.read_bytes()
    path.write_bytes(value.replace(b"host-key", b"evil-key"))
    with pytest.raises(ManualError):
        reopen(journal)


def test_wrong_key_or_journal_identity_deny(journal: FileJournal) -> None:
    with pytest.raises(ManualError, match="signature_invalid"):
        FileJournal(
            journal.path,
            Ed25519PrivateKey.generate(),
            journal.key_id,
            expected_journal_id=journal.journal_id,
        )
    with pytest.raises(ManualError, match="identity_mismatch"):
        FileJournal(
            journal.path,
            journal.private_key,
            journal.key_id,
            expected_journal_id=str(uuid4()),
        )


@pytest.mark.parametrize("tail", [b"{", b"{}\n", b" "])
def test_torn_or_unverified_tail_is_not_ignored(journal: FileJournal, tail: bytes) -> None:
    journal.append(command())
    with (journal.path / "records.jsonl").open("ab") as handle:
        handle.write(tail)
    with pytest.raises(ManualError):
        reopen(journal)


def test_truncated_records_do_not_match_acknowledged_head(journal: FileJournal) -> None:
    journal.append(command())
    (journal.path / "records.jsonl").write_bytes(b"")
    with pytest.raises(ManualError, match="head_mismatch"):
        reopen(journal)


def test_same_process_complete_state_rollback_is_detected(journal: FileJournal) -> None:
    old_head = (journal.path / "head.json").read_bytes()
    journal.append(command())
    (journal.path / "head.json").write_bytes(old_head)
    (journal.path / "records.jsonl").write_bytes(b"")
    with pytest.raises(ManualError, match="rollback_suspected"):
        journal.head()


def test_provisioning_never_overwrites_existing_state(journal: FileJournal) -> None:
    with pytest.raises(FileExistsError):
        FileJournal.provision(journal.path, journal.private_key, journal.key_id)


def test_serving_fence_denies_generation_and_switch_is_unavailable(journal: FileJournal) -> None:
    request = command(0, "serving_fence")
    request["restriction"] = {
        "kind": "serving_fence",
        "generation": "1",
        "target_id": str(uuid4()),
        "promotion_id": str(uuid4()),
    }
    state = journal.append(request)
    assert state.serving_generation == 0 and state.restriction_barrier == 1
    with pytest.raises(ManualError, match="serving_promotion_unavailable"):
        journal.append(command(1, "serving_switch"))


def test_relaxation_never_lowers_restriction_barrier(journal: FileJournal) -> None:
    journal.append(command())
    request = command(1, "relax_intent")
    with pytest.raises(ManualError, match="relaxation_evidence_required"):
        journal.append(request)
    request["relaxation_evidence_digest"] = "2" * 64
    assert journal.append(request).restriction_barrier == 1


def test_duplicate_json_keys_are_rejected(journal: FileJournal) -> None:
    (journal.path / "head.json").write_text('{"tip":"0","tip":"1"}')
    with pytest.raises(ManualError, match="corrupt"):
        reopen(journal)


def test_lock_symlink_and_missing_origin_fail_closed(journal: FileJournal, tmp_path: Path) -> None:
    (journal.path / "writer.lock").unlink()
    (journal.path / "writer.lock").symlink_to(tmp_path / "other")
    with pytest.raises(ManualError, match="custody_unavailable"):
        journal.head()


def test_record_hash_is_independent_of_signature_and_valid_json(journal: FileJournal) -> None:
    journal.append(command())
    value = json.loads((journal.path / "records.jsonl").read_text())
    assert value["format_version"] == "care.journal.v1"
    assert len(value["hash"]) == 64 and value["sequence"] == "1"
