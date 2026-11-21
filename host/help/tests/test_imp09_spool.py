"""Minimal restore reconciliation export excludes actor identities and history."""

import sqlite3

import pytest
from care_link_help import HelpError
from test_help import Harness


def test_spool_snapshot_is_minimal_current_and_chain_verified(tmp_path):
    h = Harness(tmp_path)
    result = h.execute("create", h.owner)
    snapshot = h.spool.reconciliation_snapshot(result["id"])
    assert set(snapshot) == {
        "help_id",
        "revision",
        "status",
        "local_created_at",
        "local_event_digest",
    }
    assert snapshot["status"] == "requested"
    assert h.owner.account_id not in str(snapshot)
    with sqlite3.connect(h.spool.path) as connection:
        connection.execute("UPDATE local_event SET hash='bad'")
    with pytest.raises(HelpError, match="audit_chain_invalid"):
        h.spool.reconciliation_snapshot(result["id"])
