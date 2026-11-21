"""Closed safe metadata projections for operational workspaces."""

from datetime import UTC, datetime
from typing import cast

from ..store import Record, Transaction, instant, number, text
from ..values import stamp


def artifact_view(row: Record) -> Record:
    return {
        "digest": row["digest"],
        "kind": row["kind"],
        "version": row["version"],
        "state": row["state"],
    }


def activation_view(tx: Transaction, row: Record) -> Record:
    from care_link_domain import ManualError

    required_rows = tx.rows("gov_instance", required=True, limit=33)
    if len(required_rows) > 32:
        raise ManualError("governance.required_instances_unknown", 503)
    expected = set(cast(list[str], row["required_instances"]))
    current = {text(item, "instance_id") for item in required_rows}
    missing = sorted(current - expected)
    for name in sorted(expected):
        instance = tx.peek("gov_instance", name)
        ack = tx.rows("gov_ack", activation_id=row["id"], instance_id=name, limit=1)
        if (
            instance is None
            or instance["healthy"] is not True
            or instance["required"] is not True
            or not 0 <= (datetime.now(UTC) - instant(instance, "observed_at")).total_seconds() <= 30
            or not ack
            or ack[0]["boot_id"] != instance["boot_id"]
            or ack[0]["status"] != "ready"
            or ack[0]["epoch"] != row["epoch"]
            or ack[0]["bundle_digest"] != row["bundle_digest"]
        ):
            missing.append(name)
    if len(missing) > 32:
        raise ManualError("governance.instance_set_changed", 409)
    return {
        "id": row["id"],
        "epoch": str(number(row, "epoch")),
        "bundle_digest": row["bundle_digest"],
        "state": row["state"],
        "missing_instances": missing,
        "revision": str(number(row, "revision")),
    }


def incident_view(row: Record) -> Record:
    return {
        "id": row["id"],
        "revision": str(number(row, "revision")),
        "state": row["state"],
        "kind": row["kind"],
        "review_due_at": stamp(instant(row, "review_due_at")),
    }


def command(key: str, resource: str, revision: int = 1) -> Record:
    return {
        "operation_id": key,
        "state": "committed",
        "resource_id": resource,
        "revision": str(revision),
        "audit_ref": key,
    }


def required(tx: Transaction, repository: str, key: str) -> Record:
    from care_link_domain import ManualError

    row = tx.get(repository, key)
    if row is None:
        raise ManualError("governance.not_found", 404)
    return row
