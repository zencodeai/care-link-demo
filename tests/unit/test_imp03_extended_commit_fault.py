"""Source-only connection lifecycle proves real-commit-before-unknown ordering."""

import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from tools.imp03_shared import commit_fault


def marker(directory, **changes):
    value = {
        "session": "imp03-002",
        "journal_id": str(uuid4()),
        "operation_id": str(uuid4()),
        "principal_id": str(uuid4()),
        "operation_name": "session_human_request",
        "expires_at": (datetime.now(UTC) + timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
    }
    value.update(changes)
    path = directory / commit_fault.MARKER
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    return value


class Cursor:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class Connection:
    def __init__(self, value=None, *, commit_error=False):
        self.closed = False
        self.committed = False
        self.commit_error = commit_error
        self.events = []
        self.journal = {"journal_id": value["journal_id"]} if value else None
        self.operation = (
            {
                **{key: value[key] for key in ("operation_id", "principal_id", "operation_name")},
                "born_xid": 123,
                "current_xid": 123,
            }
            if value
            else None
        )

    def __enter__(self):
        self.events.append("enter")
        return self

    def __exit__(self, kind, _error, _traceback):
        if kind is not None:
            self.events.append("rollback")
            self.closed = True
            return False
        self.events.append("commit")
        self.closed = True
        if self.commit_error:
            raise psycopg.OperationalError("synthetic real driver commit failure")
        self.committed = True
        return False

    def execute(self, query, params=None):
        if "control.guard" in query:
            self.events.append("journal")
            return Cursor(self.journal)
        if "durable.operation" in query:
            self.events.append("operation")
            assert params is not None
            return Cursor(self.operation)
        raise AssertionError("Unexpected SQL in commit-ack control")


def factory(directory, monkeypatch, connection):
    directory.chmod(0o700)
    calls = []

    def connect(_cls, dsn, **kwargs):
        calls.append((dsn, kwargs))
        return connection

    monkeypatch.setattr(psycopg.Connection, "connect", classmethod(connect))
    result = commit_fault.connection_factory(directory)
    return result, calls


def test_absent_marker_keeps_real_connection_and_exit_unchanged(tmp_path, monkeypatch):
    connection = Connection()
    connect, calls = factory(tmp_path, monkeypatch, connection)
    with connect("private-dsn") as actual:
        assert actual is connection
    assert connection.events == ["enter", "commit"]
    assert connection.committed
    assert calls[0][1] == {"connect_timeout": 1, "row_factory": commit_fault.dict_row}
    assert not list(tmp_path.iterdir())


def test_matching_operation_commits_then_exclusively_consumes_and_raises(tmp_path, monkeypatch):
    value = marker(tmp_path)
    connection = Connection(value)
    connect, _calls = factory(tmp_path, monkeypatch, connection)
    original_link = os.link

    def link(source, target, **kwargs):
        assert connection.committed
        connection.events.append("consume")
        return original_link(source, target, **kwargs)

    monkeypatch.setattr(commit_fault.os, "link", link)
    with pytest.raises(
        psycopg.OperationalError, match="committed transaction acknowledgement lost"
    ):
        with connect("private-dsn") as actual:
            assert actual is connection
    assert connection.events == ["enter", "journal", "operation", "commit", "consume"]
    assert not (tmp_path / commit_fault.MARKER).exists()
    assert json.loads((tmp_path / commit_fault.CONSUMED).read_text()) == value
    assert (tmp_path / commit_fault.CONSUMED).stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("case", ["absent", "replay", "principal", "operation"])
def test_other_transactions_and_replays_do_not_trigger(tmp_path, monkeypatch, case):
    value = marker(tmp_path)
    connection = Connection(value)
    if case == "absent":
        connection.operation = None
    elif case == "replay":
        connection.operation["born_xid"] = 122
    elif case == "principal":
        connection.operation["principal_id"] = str(uuid4())
    else:
        connection.operation["operation_name"] = "message_send"
    connect, _calls = factory(tmp_path, monkeypatch, connection)
    with connect("private-dsn"):
        pass
    assert connection.committed
    assert (tmp_path / commit_fault.MARKER).exists()
    assert not (tmp_path / commit_fault.CONSUMED).exists()


def test_failed_real_commit_does_not_consume_or_claim_injected_loss(tmp_path, monkeypatch):
    value = marker(tmp_path)
    connection = Connection(value, commit_error=True)
    connect, _calls = factory(tmp_path, monkeypatch, connection)
    with pytest.raises(psycopg.OperationalError, match="real driver commit failure"):
        with connect("private-dsn"):
            pass
    assert connection.committed is False
    assert (tmp_path / commit_fault.MARKER).exists()
    assert not (tmp_path / commit_fault.CONSUMED).exists()


@pytest.mark.parametrize("case", ["expired", "mode", "symlink", "duplicate", "oversize", "journal"])
def test_invalid_control_rolls_back_with_constant_error(tmp_path, monkeypatch, case):
    value = marker(tmp_path)
    path = tmp_path / commit_fault.MARKER
    if case == "expired":
        value["expires_at"] = "2000-01-01T00:00:00Z"
        path.write_text(json.dumps(value))
    elif case == "mode":
        path.chmod(0o644)
    elif case == "symlink":
        path.rename(tmp_path / "elsewhere.json")
        path.symlink_to(tmp_path / "elsewhere.json")
    elif case == "duplicate":
        path.write_text('{"session":"imp03-002","session":"other"}')
    elif case == "oversize":
        path.write_text("x" * (commit_fault.MAX_MARKER_BYTES + 1))
    connection = Connection(value)
    if case == "journal":
        connection.journal["journal_id"] = str(uuid4())
    connect, _calls = factory(tmp_path, monkeypatch, connection)
    with pytest.raises(psycopg.OperationalError) as raised:
        with connect("private-dsn"):
            pass
    assert str(raised.value) == commit_fault.REJECTED
    assert connection.committed is False
    assert connection.events[-1] == "rollback"
    assert path.exists()
    assert not (tmp_path / commit_fault.CONSUMED).exists()


def test_existing_consumed_receipt_is_not_overwritten(tmp_path, monkeypatch):
    value = marker(tmp_path)
    consumed = tmp_path / commit_fault.CONSUMED
    consumed.write_bytes(b"original receipt")
    consumed.chmod(0o600)
    connection = Connection(value)
    connect, _calls = factory(tmp_path, monkeypatch, connection)
    with pytest.raises(psycopg.OperationalError, match="control rejected"):
        with connect("private-dsn"):
            pass
    assert not connection.committed
    assert consumed.read_bytes() == b"original receipt"


def test_existing_body_error_rolls_back_without_attempting_hook(tmp_path, monkeypatch):
    value = marker(tmp_path)
    connection = Connection(value)
    connect, _calls = factory(tmp_path, monkeypatch, connection)
    with pytest.raises(ValueError, match="actual body error"):
        with connect("private-dsn"):
            raise ValueError("actual body error")
    assert connection.events == ["enter", "rollback"]
    assert (tmp_path / commit_fault.MARKER).exists()


def test_one_shot_does_not_trigger_again_after_success(tmp_path, monkeypatch):
    value = marker(tmp_path)
    first = Connection(value)
    connect, _calls = factory(tmp_path, monkeypatch, first)
    with pytest.raises(psycopg.OperationalError, match="acknowledgement lost"):
        with connect("private-dsn"):
            pass
    second = Connection(value)
    connect, _calls = factory(tmp_path, monkeypatch, second)
    with connect("private-dsn"):
        pass
    assert second.events == ["enter", "commit"]
