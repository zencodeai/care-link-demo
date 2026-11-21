"""Real PostgreSQL scoped audit grants, evidence exports and aggregate controls."""

import secrets
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from care_link_data import PostgresStore
from care_link_data.governance.grants import grant_request_digest
from care_link_data.governance.metrics import COHORTS, COMPANIONS, release_digest, release_key
from care_link_data.values import stamp
from care_link_domain import ManualError
from psycopg.types.json import Jsonb


def new_human(harness, role, *, human_id=None, authorities=None):
    actor = replace(
        harness.operator,
        account_id=str(uuid4()),
        role=role,
        browser_session_digest=secrets.token_hex(32),
        identity_evidence_id=str(uuid4()),
    )
    PostgresStore(harness.database.admin).provision_principal(actor)
    with psycopg.connect(harness.database.admin) as tx:
        tx.execute(
            "INSERT INTO governance.human_registry VALUES(%s,%s,%s,true,%s)",
            (
                actor.account_id,
                human_id or str(uuid4()),
                authorities or ["security", "privacy"],
                actor.identity_revision,
            ),
        )
    return actor


def receipt(harness, reviewer, purpose, request_digest, scope, *, expires=None):
    receipt_id = str(uuid4())
    with psycopg.connect(harness.database.admin) as tx:
        human_id = tx.execute(
            "SELECT human_id FROM governance.human_registry WHERE account_id=%s",
            (reviewer.account_id,),
        ).fetchone()[0]
        tx.execute(
            "INSERT INTO governance.approval VALUES(%s,%s,%s,%s,%s,%s,true,%s)",
            (
                receipt_id,
                purpose,
                request_digest,
                reviewer.account_id,
                human_id,
                expires or datetime.now(UTC) + timedelta(minutes=10),
                Jsonb(scope),
            ),
        )
    return receipt_id


def audit_grant(harness, *, scope_session=None, same_human=False):
    shared_human = str(uuid4()) if same_human else None
    creator = new_human(harness, "governance", human_id=shared_human)
    reviewer = new_human(harness, "security", human_id=shared_human)
    auditor = new_human(harness, "auditor")
    now = datetime.now(UTC)
    window = {"from": stamp(now - timedelta(hours=1)), "to": stamp(now)}
    data = {
        "expected_revision": str(harness.read("SELECT epoch FROM control.guard")[0][0]),
        "grantee_id": auditor.account_id,
        "scope": {
            "session_id": scope_session,
            "subject_id": None,
            "purpose": "audit",
            "fields": [],
            "recipient_id": auditor.account_id,
        },
        "fields": [],
        "expires_at": stamp(now + timedelta(minutes=5)),
        "approval_receipt_id": str(uuid4()),
    }
    data["approval_receipt_id"] = receipt(
        harness, reviewer, "scoped_access_grant", grant_request_digest(data), window
    )
    result = harness.service.scoped_access_grant(creator, str(uuid4()), data)
    query = {"grant_id": result["resource_id"], "purpose": "audit", **window}
    return creator, reviewer, auditor, data, result, query


def test_granted_auditor_gets_only_scoped_canonical_metadata_and_pagination(harness):
    first = harness.create()
    harness.create()
    _, _, auditor, _, grant, query = audit_grant(harness, scope_session=first["id"])
    view = harness.service.audit_query(auditor, str(uuid4()), {**query, "limit": 1})
    assert len(view["items"]) == 1
    item = view["items"][0]
    assert item["action"] == "session_create"
    assert set(item) == {
        "id",
        "sequence",
        "operation_id",
        "action",
        "decision",
        "input_digest",
        "output_digest",
        "previous_hash",
        "hash",
        "created_at",
    }
    assert view["next_cursor"] is None
    assert grant["state"] == "committed"
    with psycopg.connect(harness.database.runtime) as tx:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            tx.execute("SELECT * FROM audit.event")


def test_global_audit_page_cursor_cannot_switch_grants_or_filters(harness):
    harness.create()
    harness.create()
    _, _, auditor, _, _, query = audit_grant(harness)
    page = harness.service.audit_query(auditor, str(uuid4()), {**query, "limit": 1})
    assert page["next_cursor"] is not None
    next_page = harness.service.audit_query(
        auditor, str(uuid4()), {**query, "limit": 1, "cursor": page["next_cursor"]}
    )
    assert next_page["items"][0]["sequence"] != page["items"][0]["sequence"]
    with pytest.raises(ManualError):
        harness.service.audit_query(
            auditor,
            str(uuid4()),
            {
                **query,
                "action": "session_create",
                "cursor": page["next_cursor"],
            },
        )


def test_two_accounts_of_one_human_cannot_issue_self_approved_grant(harness):
    with pytest.raises(ManualError):
        audit_grant(harness, same_human=True)
    assert harness.read("SELECT count(*) FROM access.audit_grant")[0][0] == 0


def test_operator_has_no_standing_audit_access(harness):
    _, _, _, _, _, query = audit_grant(harness)
    with pytest.raises(ManualError):
        harness.service.audit_query(harness.operator, str(uuid4()), query)


@pytest.mark.parametrize(
    "change", ["grant_expired", "receipt_revoked", "reviewer_disabled", "epoch_changed"]
)
def test_current_authority_rechecked_on_query_and_export_download(harness, change):
    harness.create()
    _, reviewer, auditor, data, _, query = audit_grant(harness)
    export = harness.service.evidence_export(auditor, str(uuid4()), query)
    page = harness.service.audit_export_read(auditor, export["resource_id"], query)
    assert page["items"]
    with psycopg.connect(harness.database.admin) as tx:
        if change == "grant_expired":
            tx.execute(
                "UPDATE access.audit_grant SET created_at=created_at-interval '10 minutes',"
                "expires_at=expires_at-interval '10 minutes' WHERE id=%s",
                (query["grant_id"],),
            )
        elif change == "receipt_revoked":
            tx.execute(
                "UPDATE governance.approval SET active=false WHERE id=%s",
                (data["approval_receipt_id"],),
            )
        elif change == "reviewer_disabled":
            tx.execute(
                "UPDATE control.principal_guard SET revoked=true WHERE principal_id=%s",
                (reviewer.account_id,),
            )
        else:
            tx.execute("UPDATE control.guard SET epoch=epoch+1")
    with pytest.raises(ManualError):
        harness.service.audit_query(auditor, str(uuid4()), query)
    with pytest.raises(ManualError):
        harness.service.audit_export_read(auditor, export["resource_id"], query)


def test_export_cannot_broaden_time_filter_or_change_grant(harness):
    harness.create()
    _, _, auditor, _, _, query = audit_grant(harness)
    export = harness.service.evidence_export(auditor, str(uuid4()), query)
    with pytest.raises(ManualError):
        harness.service.audit_export_read(
            auditor,
            export["resource_id"],
            {
                **query,
                "from": stamp(datetime.now(UTC) - timedelta(days=10)),
            },
        )


def metric_release(harness, *, small=False):
    reviewer = new_human(harness, "governance", authorities=["privacy"])
    auditor = new_human(harness, "auditor")
    end = datetime.now(UTC) - timedelta(days=1)
    query = {
        "definition_version": "synthetic-v1",
        "period_start": stamp(end - timedelta(days=30)),
        "period_end": stamp(end),
        "cohort": "all",
    }
    sizes = dict(zip(COHORTS, (120, 29 if small else 60, 60, 60, 60), strict=True))
    value = {
        "id": release_key(query),
        **{k: v for k, v in query.items() if k != "cohort"},
        "source_digest": "a" * 64,
        "cells": {
            cohort: {
                "cohort_size": n,
                **{
                    metric: {"numerator": 0, "denominator": 0, "unknown": n}
                    for metric in COMPANIONS
                },
            }
            for cohort, n in sizes.items()
        },
    }
    approval_id = receipt(harness, reviewer, "metrics_release", release_digest(value), {})
    with psycopg.connect(harness.database.admin) as tx:
        tx.execute(
            "INSERT INTO quality.metric_release VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                value["id"],
                query["definition_version"],
                query["period_start"],
                query["period_end"],
                Jsonb(value["cells"]),
                value["source_digest"],
                approval_id,
                datetime.now(UTC),
                datetime.now(UTC) + timedelta(days=1),
            ),
        )
    return auditor, query


@pytest.mark.parametrize("small", [False, True])
def test_metrics_release_is_coupled_and_whole_family_suppressed(harness, small):
    auditor, query = metric_release(harness, small=small)
    result = harness.service.metrics_query(auditor, str(uuid4()), query)
    assert result["suppressed"] is small
    assert all(name in result for name in COMPANIONS)
    if small:
        assert result["cohort_size"] is None
        assert all(result[name] is None for name in COMPANIONS)
    with pytest.raises(ManualError):
        harness.service.metrics_query(
            auditor,
            str(uuid4()),
            {**query, "period_start": stamp(datetime.now(UTC) - timedelta(days=15))},
        )
    with psycopg.connect(harness.database.runtime) as tx:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            tx.execute("DELETE FROM quality.metric_release")


def test_alternate_metric_definition_cannot_publish_overlapping_differencing_view(harness):
    _, query = metric_release(harness)
    with psycopg.connect(harness.database.admin) as tx:
        with pytest.raises(psycopg.errors.RaiseException, match="overlapping metric release"):
            tx.execute(
                "INSERT INTO quality.metric_release "
                "SELECT %s,'alternate-definition',period_start,period_end,cells,source_digest,"
                "disclosure_receipt_id,created_at,expires_at FROM quality.metric_release",
                ("b" * 64,),
            )
    assert query["definition_version"] == "synthetic-v1"


def test_expiry_after_canonical_audit_rolls_back_bytes_and_success(harness, monkeypatch):
    harness.create()
    _, _, auditor, _, _, query = audit_grant(harness)
    original = harness.service._audit
    now = datetime.now(UTC)

    def append_then_expire(*args, **kwargs):
        result = original(*args, **kwargs)
        if len(args) > 2 and args[2] == "audit_query":
            harness.service.clock = lambda: now + timedelta(minutes=6)
        return result

    monkeypatch.setattr(harness.service, "_audit", append_then_expire)
    with pytest.raises(ManualError):
        harness.service.audit_query(auditor, str(uuid4()), query)
    assert harness.read("SELECT count(*) FROM audit.event WHERE action='audit_query'")[0][0] == 0


def test_export_replay_keeps_same_reference_and_revision_without_renewal(harness):
    harness.create()
    _, _, auditor, _, _, query = audit_grant(harness)
    key = str(uuid4())
    first = harness.service.evidence_export(auditor, key, query)
    before = harness.read(
        "SELECT expires_at FROM audit.export_request WHERE id=%s", (first["resource_id"],)
    )[0][0]
    second = harness.service.evidence_export(auditor, key, query)
    assert first == second
    assert harness.read("SELECT count(*) FROM audit.export_request")[0][0] == 1
    assert (
        harness.read(
            "SELECT expires_at FROM audit.export_request WHERE id=%s", (first["resource_id"],)
        )[0][0]
        == before
    )
