"""Source-only lease, complete-effect comparison, audit and capture behavior."""

import copy
import json
import secrets
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from care_link_data.values import digest, stamp
from care_link_domain import ManualError
from care_link_recovery_control import EncryptedCaptures, FileJournal
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tools.imp03_verification import extended


def lease():
    return extended.TargetLease(
        "care-link-imp03-003-cont1-postgres-ingress",
        "a" * 64,
        "dbname=postgres user=postgres password=private-test-password host=postgres.test "
        "hostaddr=127.0.0.1 port=25435 sslmode=verify-full sslrootcert=/private/test-ca.crt",
        str(uuid4()),
        "b" * 64,
    )


def event():
    row = {
        "stream_id": "demo",
        "sequence": 1,
        "event_id": str(uuid4()),
        "operation_id": str(uuid4()),
        "principal_id": str(uuid4()),
        "action": "session_create",
        "decision": "PERMIT",
        "input_digest": "1" * 64,
        "output_digest": "2" * 64,
        "versions": {},
        "previous_hash": "0" * 64,
        "created_at": datetime.now(UTC),
        "actor_context": None,
    }
    encoded = {key: value for key, value in row.items() if key != "actor_context"}
    encoded.update(sequence="1", created_at=stamp(row["created_at"]), encoding="care.audit.v1")
    row["hash"] = digest(encoded)
    return row


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class Database:
    def __init__(self, target):
        self.target = target
        self.audit = event()
        self.open = False
        self.autocommit = False
        self.queries = []

    def __enter__(self):
        self.open = True
        return self

    def __exit__(self, *_args):
        self.open = False

    def execute(self, statement, params=None):
        text = statement if isinstance(statement, str) else statement.as_string()
        self.queries.append((text, params))
        if "current_database() AS database" in text:
            return Cursor(
                [
                    {
                        "database": extended.DATABASE,
                        "journal_id": self.target.journal_id,
                        "journal_generation": 1,
                        "bundle_digest": self.target.policy_digest,
                    }
                ]
            )
        if "pg_stat_ssl" in text:
            return Cursor([{"ssl": True, "version": "TLSv1.3"}])
        if "FROM pg_tables" in text:
            return Cursor(
                [
                    {"schema": schema, "name": name}
                    for schema, name in [
                        ("core", "message"),
                        ("control", "guard"),
                        ("durable", "event"),
                        ("durable", "due_job"),
                        ("durable", "duty_operation"),
                        ("durable", "operation"),
                        ("recovery", "command"),
                        ("audit", "head"),
                        ("audit", "event"),
                    ]
                ]
            )
        if "row_to_json" in text:
            return Cursor([{"row": '{"text_ciphertext":"private-row-do-not-export"}'}])
        if "SELECT * FROM audit.event" in text:
            return Cursor([self.audit])
        if "SELECT next_sequence,digest FROM audit.head" in text:
            return Cursor([{"next_sequence": 2, "digest": self.audit["hash"]}])
        if "pg_export_snapshot" in text:
            return Cursor(
                [
                    {
                        "snapshot": "00000001-00000002-1",
                        "wal": "0/1234",
                        "captured_at": datetime.now(UTC),
                    }
                ]
            )
        if "AS quarantine," in text:
            return Cursor(
                [
                    {
                        "quarantine": True,
                        "principals_disabled": True,
                        "tokens_disabled": True,
                        "runtime_connect_denied": True,
                    }
                ]
            )
        return Cursor([])


@pytest.mark.parametrize(
    "field,value",
    [
        ("container_name", "care-link-imp03-003-postgres"),
        ("container_id", "short"),
        ("admin_dsn", "host=postgres port=5432 user=postgres sslmode=disable"),
        ("journal_id", "not-a-receipt"),
    ],
)
def test_lease_rejects_other_target_or_unverified_connection(field, value):
    with pytest.raises(ValueError):
        replace(lease(), **{field: value})


def test_inspection_checks_exact_id_and_host_publication(monkeypatch):
    target = lease()
    metadata = {
        "Id": target.container_id,
        "HostConfig": {
            "PortBindings": {
                "5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "25435"}],
            }
        },
    }
    monkeypatch.setattr(extended.owned_docker, "inspect_container", lambda _name: metadata)
    target.inspect()
    metadata["Id"] = "c" * 64
    with pytest.raises(ValueError, match="identity/publication"):
        target.inspect()
    assert "private-test-password" not in repr(target)


def test_full_snapshot_includes_durable_recovery_and_validates_audit_without_rows():
    target = lease()
    connection = Database(target)
    value = extended.snapshot_connection(connection, target)
    assert {
        "durable.event",
        "durable.due_job",
        "durable.duty_operation",
        "recovery.command",
    } <= set(value["tables"])
    assert value["audit"]["valid"]
    assert "private-row-do-not-export" not in json.dumps(value)
    connection.audit["action"] = "tampered"
    with pytest.raises(ManualError, match="audit_chain_invalid"):
        extended.snapshot_connection(connection, target)


@pytest.mark.parametrize("table", ["durable.event", "durable.due_job", "recovery.command"])
def test_effect_comparison_detects_previously_unobserved_durable_changes(table):
    target = lease()
    before = extended.snapshot_connection(Database(target), target)
    after = copy.deepcopy(before)
    after["tables"][table]["sha256"] = "changed"
    result = extended.compare_snapshots(before, after)
    assert result["no_prohibited_observed_effect"] is False
    assert result["prohibited_changed_tables"] == [table]


def test_effect_comparison_allows_denial_audit_but_rejects_positive_effect_or_rewrite():
    target = lease()
    before = extended.snapshot_connection(Database(target), target)
    after = copy.deepcopy(before)
    after["audit"]["events"].append(
        {"hash": "3" * 64, "action": "message_send", "decision": "DENY"}
    )
    after["tables"]["audit.event"]["sha256"] = "new-denial"
    assert extended.compare_snapshots(before, after)["no_prohibited_observed_effect"] is True
    after["committed_operations"]["duty_operation"]["sha256"] = "new-effect"
    assert extended.compare_snapshots(before, after)["no_prohibited_observed_effect"] is False
    after = copy.deepcopy(before)
    after["audit"]["events"][0]["hash"] = "rewritten"
    assert extended.compare_snapshots(before, after)["audit_chain_append_only"] is False


def captures(tmp_path, target):
    path = tmp_path / "captures"
    EncryptedCaptures.provision(path)
    result = EncryptedCaptures(
        path, secrets.token_bytes(32), Ed25519PrivateKey.generate(), "test-key"
    )
    journal = FileJournal.provision(
        tmp_path / "journal",
        Ed25519PrivateKey.generate(),
        "journal-key",
        journal_id=target.journal_id,
    )
    return result, journal


def test_capture_holds_snapshot_and_stages_authenticated_bytes(tmp_path, monkeypatch):
    target = lease()
    connection = Database(target)
    monkeypatch.setattr(extended.TargetLease, "inspect", lambda _self: None)
    monkeypatch.setattr(extended, "_connection", lambda _lease: connection)
    store, journal = captures(tmp_path, target)
    schema = tmp_path / "schema.sql"
    schema.write_text("synthetic schema")

    def dump(snapshot_id):
        assert connection.open
        assert snapshot_id == "00000001-00000002-1"
        return b"PGDMPfictional fixture bytes"

    view = extended.capture_target(target, store, journal, schema, "1" * 64, dump=dump)
    assert connection.open is False
    assert store.inspect(view["id"])["audit_digest"] == connection.audit["hash"]
    staged = store.restore_quarantine(view["id"], tmp_path / "quarantine", journal.head())
    assert staged.serving_allowed is False
    assert (staged.path / "database.dump").read_bytes() == b"PGDMPfictional fixture bytes"


def test_failed_import_retains_new_target_and_never_drops_or_mutates_source(tmp_path, monkeypatch):
    target = lease()
    connection = Database(target)
    monkeypatch.setattr(extended.TargetLease, "inspect", lambda _self: None)
    monkeypatch.setattr(extended, "_connection", lambda _lease, _db="": connection)
    monkeypatch.setattr(extended, "docker", lambda: "/existing/docker")
    invocations = []

    def fail_import(argv, **_kwargs):
        invocations.append(argv)
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(extended.subprocess, "run", fail_import)
    store, journal = captures(tmp_path, target)
    from care_link_recovery_control import CaptureMetadata

    view = store.capture(
        str(uuid4()),
        {"database.dump": b"PGDMPfixture"},
        CaptureMetadata("001_manual", "a" * 64, "b" * 64, "c" * 64, "0/1234"),
        journal.head(),
        capture_at=datetime.now(UTC),
    )
    staged = store.restore_quarantine(view["id"], tmp_path / "quarantine", journal.head())
    with pytest.raises(RuntimeError, match="partial target retained"):
        extended.restore_target(target, staged, expected_audit_digest="c" * 64)
    assert len(invocations) == 1
    assert invocations[0][2:4] == ["-i", target.container_id]
    assert invocations[0][-1].startswith("--dbname=imp03_cont1_quarantine_")
    assert all(
        "DROP" not in statement and "UPDATE" not in statement for statement, _ in connection.queries
    )
    assert (
        len([statement for statement, _ in connection.queries if "CREATE DATABASE" in statement])
        == 1
    )
