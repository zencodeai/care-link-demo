"""Read-only effect/privilege qualification of the exact new IMP-04 database."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import LiteralString, cast
from uuid import UUID

from psycopg.conninfo import conninfo_to_dict, make_conninfo

from tools.imp04_deployment import docker
from tools.imp04_deployment.config import PRIVATE, load, record, text


def host_dsn(role: str, *, admin: bool = False) -> str:
    inputs = load(PRIVATE / "inputs.json")
    raw = (
        text(record(inputs["admin"]), role + "_admin_dsn")
        if admin
        else text(record(record(inputs["binding"])[role]), "store_dsn")
    )
    settings = conninfo_to_dict(raw)
    expected = {"identity": "imp04_identity_002", "data": "imp04_runtime_002"}[role]
    if not admin and settings.get("dbname") != expected:
        raise ValueError("Exact new runtime database required")
    return make_conninfo(
        "",
        **{
            **settings,
            "host": "postgres.imp04.internal",
            "hostaddr": "127.0.0.1",
            "port": "25436",
            "dbname": expected,
            "sslrootcert": str(PRIVATE / "tls/ca.crt"),
            "sslmode": "verify-full",
        },
    )


def canonical_uuid(value: str) -> str:
    try:
        parsed = str(UUID(value))
    except ValueError:
        raise ValueError("Canonical UUID selector required") from None
    if parsed != value:
        raise ValueError("Canonical UUID selector required")
    return value


def absent_scope_failures(
    selected: dict[str, object],
    *,
    operation: str,
    subject: str,
    recipient: str,
    prior_grant: str,
) -> list[str]:
    """Correlate absence with the fresh browser scope, never a missing row alone.

    Network authorization status remains a separate strict browser assertion.
    Preflight rejection legitimately precedes creation of a durable command row.
    """
    failures: list[str] = []
    evidence = record(selected["absent_operation"])
    scope = record(selected["absent_scope"])
    prior = record(scope["prior_grant"])
    prior_row = record(prior["record"]) if prior["record"] is not None else {}
    prior_identity_bound = True
    for name in ("session_id", "grantor_id"):
        candidate = prior_row.get(name)
        try:
            if not isinstance(candidate, str) or canonical_uuid(candidate) != candidate:
                prior_identity_bound = False
        except ValueError:
            prior_identity_bound = False
    if (
        scope.get("subject_id") != subject
        or scope.get("recipient_id") != recipient
        or scope.get("prior_grant_id") != prior_grant
        or scope.get("purpose") != "plan"
    ):
        failures.append("absent_scope_binding_mismatch")
    if (
        prior.get("row_count") != 1
        or prior_row.get("grant_id") != prior_grant
        or prior_row.get("subject_id") != subject
        or prior_row.get("recipient_id") != recipient
        or prior_row.get("recipient_kind") != "account"
        or prior_row.get("purpose") != "plan"
        or prior_row.get("fields") != ["plan.strategies"]
        or prior_row.get("revoked_at") is None
        or not prior_identity_bound
    ):
        failures.append("absent_prior_grant_not_one_revoked_exact_scope")
    if (
        scope.get("prior_grant_created_event_count") != 1
        or scope.get("prior_grant_revoked_event_count") != 1
    ):
        failures.append("absent_prior_grant_events_not_one_grant_and_revoke")
    count = evidence.get("row_count")
    row = record(evidence["record"]) if evidence["record"] is not None else {}
    if not (
        count == 0
        and evidence["record"] is None
        or count == 1
        and row.get("operation_id") == operation
        and row.get("operation_name") == "consent_grant"
        and row.get("state") == "rejected"
        and row.get("resource_id") is None
        and row.get("session_id") == prior_row.get("session_id")
        and row.get("principal_id") == prior_row.get("grantor_id")
    ):
        failures.append("absent_operation_has_effect_or_incompatible_rejection")
    for counter, failure in (
        ("other_scope_grant_count", "absent_other_scope_grant_effect"),
        ("other_subject_grant_event_count", "absent_other_subject_grant_event"),
        ("pending_operation_grant_count", "absent_pending_operation_grant_effect"),
        ("pending_operation_grant_event_count", "absent_pending_operation_grant_event"),
        ("pending_operation_permit_audit_count", "absent_pending_operation_permit_audit"),
    ):
        if scope.get(counter) != 0:
            failures.append(failure)
    return failures


def verify(
    *,
    operation: str | None = None,
    field: str | None = None,
    absent_operation: str | None = None,
    absent_subject: str | None = None,
    absent_recipient: str | None = None,
    absent_prior_grant: str | None = None,
) -> dict[str, object]:
    selectors = {
        "operation": operation,
        "field": field,
        "absent_operation": absent_operation,
        "absent_subject": absent_subject,
        "absent_recipient": absent_recipient,
        "absent_prior_grant": absent_prior_grant,
    }
    for value in selectors.values():
        if value is not None:
            canonical_uuid(value)
    if field is not None and operation is None:
        raise ValueError("Field effect selector requires its operation UUID")
    scope_selectors = (absent_subject, absent_recipient, absent_prior_grant)
    if any(value is not None for value in scope_selectors) and (
        absent_operation is None or any(value is None for value in scope_selectors)
    ):
        raise ValueError(
            "Absent-scope proof requires operation, subject, recipient and prior grant"
        )
    failures: list[str] = []
    probes: list[dict[str, object]] = []
    statements: list[tuple[str, LiteralString]] = [
        ("runtime_ddl", "CREATE TABLE plans.imp04_qualification_forbidden_probe(id integer)"),
        (
            "delegation_insert",
            "INSERT INTO consent.delegation(id) VALUES ('00000000-0000-4000-8000-000000000001')",
        ),
        ("delegation_update", "UPDATE consent.delegation SET revoked_at=revoked_at WHERE false"),
        ("delegation_delete", "DELETE FROM consent.delegation WHERE false"),
        ("immutable_field_update", "UPDATE plans.field SET verification=verification WHERE false"),
        ("immutable_event_delete", "DELETE FROM consent.event WHERE false"),
        ("immutable_source_update", "UPDATE knowledge.service_version SET state=state WHERE false"),
    ]
    script = r"""
import json, sys, psycopg
from pathlib import Path
from tools.imp04_deployment.config import load

cfg = load(Path("/run/care-link-imp03-002/configuration/data/config.json"))
if cfg["imp04_target"] != "care-link-imp04-002":
    raise ValueError("Wrong target")
results = []
for name, statement in json.loads(sys.argv[1]):
    denied = False
    with psycopg.connect(cfg["store_dsn"]) as connection:
        try:
            with connection.transaction():
                connection.execute(statement)
                raise ValueError("Runtime privilege unexpectedly permitted")
        except psycopg.errors.InsufficientPrivilege:
            denied = True
        except (psycopg.Error, ValueError):
            pass
        finally:
            connection.rollback()
    results.append({"probe": name, "permission_denied": denied})
print(json.dumps(results))
"""
    probes = cast(
        list[dict[str, object]],
        json.loads(
            docker.exec(
                "care-link-imp04-002-data-app", ["python", "-c", script, json.dumps(statements)]
            )
        ),
    )
    failures.extend(str(probe["probe"]) for probe in probes if not probe["permission_denied"])
    script = r"""
import json, sys, psycopg
from pathlib import Path
from uuid import UUID
from psycopg import sql
from psycopg.conninfo import make_conninfo
from tools.imp04_deployment.config import load
from tools.imp03_shared.relay import ThreadedLoopbackBridge

selectors = json.loads(sys.argv[1])
if set(selectors) != {"operation", "field", "absent_operation", "absent_subject",
                      "absent_recipient", "absent_prior_grant"}:
    raise ValueError("Exact metadata selectors required")
for value in selectors.values():
    if value is not None and (not isinstance(value, str) or str(UUID(value)) != value):
        raise ValueError("Canonical metadata selector required")
if selectors["field"] is not None and selectors["operation"] is None:
    raise ValueError("Field effect requires operation binding")
scope_selectors = [selectors[name] for name in
                   ("absent_subject", "absent_recipient", "absent_prior_grant")]
if any(value is not None for value in scope_selectors) and (
        selectors["absent_operation"] is None or any(value is None for value in scope_selectors)):
    raise ValueError("Complete absent-scope selectors required")
root = Path("/run/care-link-imp03-002/configuration")
admin = load(root / "admin.json")["data_admin_dsn"]
bridge = ThreadedLoopbackBridge(
    Path("/run/care-link-imp03-002/connectors/data-db/forward.sock"), 5432, server_uid=22042
)
bridge.start()
try:
    with psycopg.connect(make_conninfo(admin, dbname="imp04_runtime_002")) as connection:
        connection.execute(
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
            if selectors["absent_subject"] is not None else "SET TRANSACTION READ ONLY"
        )
        flags = connection.execute(
            "SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM pg_roles WHERE rolname=%s",
            ("imp04_data_runtime_002",),
        ).fetchone()
        counts = {}
        for table in [
            "plans.plan",
            "plans.field",
            "plans.review_work",
            "consent.current_grant",
            "consent.event",
            "knowledge.service_version",
            "knowledge.quarantine",
        ]:
            counts[table] = connection.execute(
                sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(*table.split(".")))
            ).fetchone()[0]
        anchors = connection.execute(
            "SELECT count(*) FILTER (WHERE anchor_kind='plan_retired'),"
            "count(*) FILTER (WHERE anchor_at IS NOT NULL "
            "AND expires_at=anchor_at+interval '30 days'),"
            "count(*) FILTER (WHERE purpose='plan' AND anchor_at IS NULL) "
            "FROM lifecycle.copy WHERE purpose='plan'"
        ).fetchone()
        rls = connection.execute(
            "SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class "
            "WHERE oid IN ('plans.plan'::regclass,'plans.field'::regclass,"
            "'consent.current_grant'::regclass) ORDER BY relname"
        ).fetchall()
        copies = connection.execute(
            "SELECT aggregate_id,anchor_kind,anchor_at,expires_at,state "
            "FROM lifecycle.copy WHERE purpose='plan' AND aggregate_type='plan' "
            "ORDER BY aggregate_id"
        ).fetchall()
        reviews = connection.execute(
            "SELECT plan_id,count(*) FROM plans.review_work GROUP BY plan_id ORDER BY plan_id"
        ).fetchall()
        control = connection.execute(
            "SELECT journal_id,journal_generation,serving_generation,mode,restriction_barrier "
            "FROM control.guard WHERE key='demo'"
        ).fetchone()
        selected = {}
        operation_columns = ("operation_id", "principal_id", "operation_name", "state",
                             "session_id", "resource_id", "result_type", "canonical_audit_id")
        def operation_metadata(operation_id):
            rows = connection.execute(
                "SELECT operation_id,principal_id,operation_name,state,session_id,resource_id,"
                "result_type,canonical_audit_id FROM durable.operation WHERE operation_id=%s",
                (operation_id,),
            ).fetchall()
            return {"row_count": len(rows), "record":
                    dict(zip(operation_columns, rows[0], strict=True)) if rows else None}
        if selectors["operation"] is not None:
            selected["operation"] = operation_metadata(selectors["operation"])
        if selectors["field"] is not None:
            columns = ("id", "plan_id", "author_id", "session_id", "revision", "field_key",
                       "verification", "supersedes_id", "safety_relevant")
            rows = connection.execute(
                "SELECT id,plan_id,author_id,session_id,revision,field_key,verification,"
                "supersedes_id,safety_relevant FROM plans.field WHERE id=%s",
                (selectors["field"],),
            ).fetchall()
            correlated = connection.execute(
                "SELECT count(*) FROM plans.field f JOIN durable.operation o "
                "ON f.plan_id=o.resource_id AND f.author_id=o.principal_id "
                "AND f.session_id=o.session_id WHERE o.operation_id=%s AND f.id=%s",
                (selectors["operation"], selectors["field"]),
            ).fetchone()[0]
            selected["field"] = {"row_count": len(rows), "record":
                dict(zip(columns, rows[0], strict=True)) if rows else None,
                "operation_plan_author_session_correlation_count": correlated}
        if selectors["absent_operation"] is not None:
            absent = operation_metadata(selectors["absent_operation"])
            resource_id = absent["record"]["resource_id"] if absent["record"] else None
            absent["grant_count_for_resource"] = connection.execute(
                "SELECT count(*) FROM consent.current_grant WHERE grant_id=%s", (resource_id,)
            ).fetchone()[0] if resource_id is not None else None
            absent["grant_count_scope"] = (
                "Exact operation resource_id only; null resource is no recorded grant resource, "
                "not evidence about unrelated grants")
            selected["absent_operation"] = absent
        if selectors["absent_subject"] is not None:
            subject, recipient, prior_id, pending = [selectors[name] for name in
                ("absent_subject", "absent_recipient", "absent_prior_grant", "absent_operation")]
            columns = ("grant_id", "subject_id", "session_id", "recipient_id", "recipient_kind",
                       "purpose", "fields", "grantor_id", "revoked_at")
            prior = connection.execute(
                "SELECT grant_id,subject_id,session_id,recipient_id,recipient_kind,purpose,"
                "fields,grantor_id,revoked_at FROM consent.current_grant WHERE grant_id=%s",
                (prior_id,),
            ).fetchall()
            other_grants = connection.execute(
                "SELECT count(*) FROM consent.current_grant WHERE subject_id=%s "
                "AND recipient_id=%s AND recipient_kind='account' AND purpose='plan' "
                "AND grant_id<>%s", (subject, recipient, prior_id),
            ).fetchone()[0]
            other_events = connection.execute(
                "SELECT count(*) FROM consent.event WHERE subject_id=%s "
                "AND kind='grant' AND grant_id<>%s", (subject, prior_id),
            ).fetchone()[0]
            prior_events = connection.execute(
                "SELECT count(*) FILTER (WHERE kind='grant'),"
                "count(*) FILTER (WHERE kind='revoke') FROM consent.event "
                "WHERE subject_id=%s AND grant_id=%s", (subject, prior_id),
            ).fetchone()
            pending_grants = connection.execute(
                "SELECT count(*) FROM durable.operation o JOIN consent.current_grant g "
                "ON g.grant_id=o.resource_id WHERE o.operation_id=%s "
                "AND o.operation_name='consent_grant'", (pending,),
            ).fetchone()[0]
            pending_events = connection.execute(
                "SELECT count(*) FROM durable.operation o JOIN consent.event e "
                "ON e.grant_id=o.resource_id WHERE o.operation_id=%s "
                "AND o.operation_name='consent_grant' AND e.kind='grant'", (pending,),
            ).fetchone()[0]
            pending_permits = connection.execute(
                "SELECT count(*) FROM audit.event WHERE operation_id=%s "
                "AND action='consent_grant' AND decision='PERMIT'", (pending,),
            ).fetchone()[0]
            selected["absent_scope"] = {
                "subject_id": subject, "recipient_id": recipient, "purpose": "plan",
                "prior_grant_id": prior_id,
                "prior_grant": {"row_count": len(prior), "record":
                    dict(zip(columns, prior[0], strict=True)) if prior else None},
                "other_scope_grant_count": other_grants,
                "other_subject_grant_event_count": other_events,
                "prior_grant_created_event_count": prior_events[0],
                "prior_grant_revoked_event_count": prior_events[1],
                "pending_operation_grant_count": pending_grants,
                "pending_operation_grant_event_count": pending_events,
                "pending_operation_permit_audit_count": pending_permits,
                "correlation_limit": "consent.event has no operation_id; pending command "
                    "joins through durable.operation.resource_id, alongside exact fresh "
                    "subject/recipient exclusion counts. Fresh scope comes from browser evidence.",
            }
    print(json.dumps({"flags": flags, "counts": counts, "anchors": anchors, "rls": rls,
                      "plan_copy_metadata": copies, "pending_review_counts": reviews,
                      "control_metadata": control, "selected_effect_metadata": selected},
                     default=str))
finally:
    bridge.close()
"""
    operator = "care-link-imp04-002-operator-seed"
    docker.start(operator)
    try:
        metadata = record(
            json.loads(
                docker.exec(operator, ["python", "-c", script, json.dumps(selectors)], root=True)
            )
        )
    finally:
        docker.stop(operator)
    flags = tuple(cast(list[bool], metadata["flags"]))
    counts = metadata["counts"]
    anchors = metadata["anchors"]
    rls = cast(list[list[object]], metadata["rls"])
    if flags != (False, False, False, False):
        failures.append("runtime_role_flags")
    if not all(row[1] and row[2] for row in rls) or len(rls) != 3:
        failures.append("forced_rls")
    selected = record(metadata["selected_effect_metadata"])
    if operation is not None:
        evidence = record(selected["operation"])
        row = record(evidence["record"]) if evidence["record"] is not None else {}
        if evidence["row_count"] != 1 or row.get("state") != "committed":
            failures.append("selected_operation_not_one_committed_effect")
        if field is not None and row.get("operation_name") != "plan_field_append":
            failures.append("selected_operation_not_plan_field_append")
    if field is not None:
        evidence = record(selected["field"])
        if (
            evidence["row_count"] != 1
            or evidence["operation_plan_author_session_correlation_count"] != 1
        ):
            failures.append("selected_field_not_one_correlated_effect")
    if absent_operation is not None and absent_subject is not None:
        failures.extend(
            absent_scope_failures(
                selected,
                operation=absent_operation,
                subject=absent_subject,
                recipient=cast(str, absent_recipient),
                prior_grant=cast(str, absent_prior_grant),
            )
        )
    elif absent_operation is not None:
        evidence = record(selected["absent_operation"])
        row = record(evidence["record"]) if evidence["record"] is not None else {}
        if (
            evidence["row_count"] != 1
            or row.get("state") != "rejected"
            or row.get("resource_id") is not None
        ):
            failures.append("absent_operation_not_rejected_without_resource")
    result: dict[str, object] = {
        "target": "care-link-imp04-002",
        "database": "imp04_runtime_002",
        "probes": probes,
        "runtime_superuser_createdb_createrole_bypassrls": flags,
        "forced_rls": rls,
        "effect_counts": counts,
        "plan_anchor_total_retired_30day_active_counts": anchors,
        "status": "passed" if not failures else "failed",
        "failures": failures,
        "plan_copy_metadata": metadata["plan_copy_metadata"],
        "pending_review_counts": metadata["pending_review_counts"],
        "control_metadata": metadata["control_metadata"],
        "content_returned": False,
    }
    if any(value is not None for value in selectors.values()):
        result["selected_effect_metadata"] = selected
    if absent_subject is not None:
        result["absent_proof_mode"] = "correlated_exact_subject_recipient_and_pending_operation"
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--operation", type=canonical_uuid)
    parser.add_argument("--field", type=canonical_uuid)
    parser.add_argument("--absent-operation", type=canonical_uuid)
    parser.add_argument("--absent-subject", type=canonical_uuid)
    parser.add_argument("--absent-recipient", type=canonical_uuid)
    parser.add_argument("--absent-prior-grant", type=canonical_uuid)
    args = parser.parse_args()
    value = verify(
        operation=args.operation,
        field=args.field,
        absent_operation=args.absent_operation,
        absent_subject=args.absent_subject,
        absent_recipient=args.absent_recipient,
        absent_prior_grant=args.absent_prior_grant,
    )
    args.output.write_text(json.dumps(value, indent=2) + "\n")
    print(json.dumps(value, indent=2))
    if value["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
