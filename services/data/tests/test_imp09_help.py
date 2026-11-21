"""Minimal deduplicated help import with current authority and canonical audit."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from care_link_data.audit import verify_audit_chain
from care_link_data.recovery import HelpSnapshot, PostgresHelpReconciler
from care_link_domain import ManualError
from psycopg.rows import dict_row


class Authority:
    def __init__(self):
        self.snapshot = HelpSnapshot(
            str(uuid4()), 2, "accepted_unconnected", datetime.now(UTC), "b" * 64
        )
        self.fail = False

    def current(self, request):
        if self.fail:
            raise ManualError("test.help_authority_unavailable", 503)
        return self.snapshot


def test_help_import_audits_deduplicates_and_never_confirms_connection(harness):
    h, authority = harness, Authority()
    reconciler = PostgresHelpReconciler(
        h.database.runtime, authority, str(uuid4()), journal=h.journal
    )
    body = {
        "help_id": authority.snapshot.help_id,
        "spool_revision": "2",
        "local_event_digest": "b" * 64,
        "expected_revision": "0",
    }
    command = str(uuid4())
    first = reconciler.reconcile(body, command)
    assert first == reconciler.reconcile(body, command)
    assert first["state"] == "committed" and first["revision"] == "1"
    assert h.read("SELECT status,connection_confirmed FROM recovery.help_import") == [
        ("accepted_unconnected", False)
    ]
    assert h.read("SELECT count(*) FROM workforce.assignment") == [(0,)]
    assert h.read("SELECT count(*) FROM audit.event") == [(1,)]
    with psycopg.Connection[dict[str, object]].connect(
        h.database.admin, row_factory=dict_row
    ) as connection:
        events = [
            {k: str(v) if isinstance(v, type(uuid4())) else v for k, v in r.items()}
            for r in connection.execute("SELECT * FROM audit.event ORDER BY sequence")
        ]
    assert verify_audit_chain(events) == h.read("SELECT digest FROM audit.head")[0][0]
    authority.fail = True
    with pytest.raises(ManualError, match="authority_unavailable"):
        reconciler.reconcile(body, command)
    assert h.read("SELECT count(*) FROM audit.event") == [(1,)]


def test_changed_spool_or_audit_failure_does_not_import(harness):
    h, authority = harness, Authority()
    reconciler = PostgresHelpReconciler(
        h.database.runtime, authority, str(uuid4()), journal=h.journal
    )
    body = {
        "help_id": authority.snapshot.help_id,
        "spool_revision": "2",
        "local_event_digest": "b" * 64,
        "expected_revision": "0",
    }
    authority.snapshot = replace(authority.snapshot, revision=3)
    with pytest.raises(ManualError, match="snapshot_mismatch"):
        reconciler.reconcile(body, str(uuid4()))
    authority.snapshot = replace(authority.snapshot, revision=2)
    with psycopg.connect(h.database.admin) as connection:
        connection.execute("DELETE FROM audit.head")
    with pytest.raises(ManualError, match="audit_unavailable"):
        reconciler.reconcile(body, str(uuid4()))
    assert h.read("SELECT count(*) FROM recovery.help_import") == [(0,)]


def test_help_import_rejects_stale_generation_or_unapplied_restriction(harness):
    h, authority = harness, Authority()
    reconciler = PostgresHelpReconciler(
        h.database.runtime, authority, str(uuid4()), journal=h.journal
    )
    body = {
        "help_id": authority.snapshot.help_id,
        "spool_revision": "2",
        "local_event_digest": "b" * 64,
        "expected_revision": "0",
    }
    h.journal.state = replace(h.journal.state, restriction_barrier=1)
    with pytest.raises(ManualError, match="current_gate_required"):
        reconciler.reconcile(body, str(uuid4()))
    assert h.read("SELECT count(*) FROM recovery.help_import") == [(0,)]
