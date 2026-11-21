"""Current process readiness is an inline fence, independently of dashboards."""

from care_link_domain import ManualError

from .store import Record, Transaction, number
from .values import GOVERNANCE_ACTIONS, object_value

EVIDENCE_ACTIONS = frozenset(
    {"audit_query", "audit_export_read", "evidence_export", "metrics_query", "scoped_access_grant"}
)
RECOVERY_ACTIONS = (GOVERNANCE_ACTIONS - EVIDENCE_ACTIONS) | {
    "control_change",
    "manual_identity_restrict",
}


def requires_activation(action: str) -> bool:
    return action not in RECOVERY_ACTIONS


def activation_current(tx: Transaction, control: Record) -> bool:
    # Pre-IMP08 databases retain their established bootstrap boundary. Once a
    # governed activation takes effect, absence/staleness cannot restore it.
    available = tx.connection.execute("SELECT to_regclass('governance.activation')").fetchone()
    if available is None or next(iter(available.values())) is None:
        return True
    rows = tx.rows("gov_activation", limit=100)
    if len(rows) == 100:
        return False
    current = [
        row
        for row in rows
        if row["state"] == "active"
        and number(row, "epoch") <= number(control, "epoch")
        and row["bundle_digest"] == control["bundle_digest"]
    ]
    if current:
        latest_epoch = max(number(row, "epoch") for row in current)
        current = [row for row in current if number(row, "epoch") == latest_epoch]
    if len(current) == 1:
        from .governance.projections import activation_view

        row = current[0]
        if not activation_effective(tx, control, row):
            return False
        from .governance.artifacts import verified_candidate

        artifact = tx.peek("gov_artifact", str(row["bundle_digest"]))
        if artifact is None:
            return False
        try:
            verified_candidate(tx, object_value(artifact["metadata"]))
        except ManualError:
            return False
        return not activation_view(tx, row)["missing_instances"]
    return not any(number(row, "epoch") <= number(control, "epoch") for row in rows)


def bind_activation_fence(tx: Transaction, request: Record, snapshot: Record) -> None:
    if not activation_current(tx, object_value(snapshot["control"])):
        object_value(request["authority_facts"])["workload_unfenced"] = False


def activation_effective(tx: Transaction, control: Record, row: Record) -> bool:
    if row["bundle_digest"] != control["bundle_digest"]:
        return False
    if row["epoch"] == control["epoch"]:
        return True
    # Restrictive control epochs retain exactly the loaded evaluator bytes.
    if number(row, "epoch") > number(control, "epoch") or control["mode"] == "normal":
        return False
    artifact = tx.peek("gov_artifact", str(row["bundle_digest"]))
    ranks = {"normal": 0, "ai_disabled": 1, "restricted": 2, "quarantine": 3}
    return bool(
        artifact
        and ranks[str(control["mode"])] >= ranks[str(object_value(artifact["manifest"])["mode"])]
    )
