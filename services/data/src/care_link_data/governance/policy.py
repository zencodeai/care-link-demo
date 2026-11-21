"""Current server-side metadata bindings for governance PEPs."""

from care_link_domain import Actor, ManualError

from ..engine import Engine
from ..store import Record, Transaction, number
from ..values import digest, dt, object_value
from .authority import approval, current_human


def governance_policy(
    service: Engine,
    tx: Transaction,
    actor: Actor,
    action: str,
    arguments: Record,
    snapshot: Record,
    request: Record,
) -> None:
    del snapshot
    facts = object_value(request["authority_facts"])
    scope = object_value(request["scope"])
    scope["purpose"] = (
        "service_operations"
        if action == "health_read"
        else "security"
        if action.startswith("incident_")
        else "governance"
    )
    try:
        current_human(tx, actor, service.clock())
    except ManualError:
        facts["resource_owned_or_assigned"] = False
        facts["field_scope_allowed"] = False
    repository = None
    target = None
    if action in {"activation_read", "activation_commit"}:
        repository = "gov_activation"
        target = arguments.get("activation_id")
    elif action in {"incident_read", "incident_transition"}:
        repository = "gov_incident"
        target = arguments.get("incident_id")
    elif action in {"artifact_review", "artifact_context", "activation_create"}:
        repository = "gov_artifact"
        target = arguments.get("artifact_digest")
    elif action == "artifact_register":
        repository = "gov_candidate"
        target = arguments.get("digest")
    if repository:
        row = tx.peek(repository, target) if isinstance(target, str) else None
        if row is None:
            facts["resource_owned_or_assigned"] = False
            facts["field_scope_allowed"] = False
        else:
            if "revision" in row:
                object_value(request["versions"])["resource"] = str(number(row, "revision"))
            artifact = row.get("bundle_digest", row.get("digest"))
            if isinstance(artifact, str):
                request["artifact_digests"] = [artifact]


def check_controls_output(
    service: Engine,
    tx: Transaction,
    actor: Actor,
    action: str,
    result: Record,
    arguments: Record | None = None,
) -> None:
    current_human(tx, actor, service.clock())
    if action in {"activation_create", "activation_read", "activation_commit"}:
        row = tx.peek("gov_activation", str(result["id"]))
        if row is None:
            raise ManualError("governance.not_found", 404)
        # Do not release stale green readiness after an enforcer boot changes.
        from .projections import activation_view

        if activation_view(tx, row) != result:
            raise ManualError("governance.enforcer_state_changed", 409)

    if action == "artifact_review" and arguments:
        if arguments.get("expires_at") is None or dt(arguments["expires_at"]) <= service.clock():
            raise ManualError("governance.current_exact_approval_required")
    if action in {"exception_create", "incident_transition"} and arguments:
        field = "approver_receipt_id" if action == "exception_create" else "recovery_approval_id"
        receipt = arguments.get(field)
        if isinstance(receipt, str):
            approval(
                tx,
                actor,
                receipt,
                action,
                digest({k: v for k, v in arguments.items() if k != field}),
                service.clock(),
            )
        if action == "exception_create" and dt(arguments["expires_at"]) <= service.clock():
            raise ManualError("governance.exception_expired")

    if action == "activation_commit":
        from .artifacts import reviews_current, verified_candidate
        from .projections import required

        activation = required(tx, "gov_activation", str(result["id"]))
        control = required(tx, "control", "demo")
        if (
            activation["state"] != "active"
            or activation["epoch"] != control["epoch"]
            or activation["bundle_digest"] != control["bundle_digest"]
        ):
            raise ManualError("governance.superseded_activation", 409)
        artifact = dict(required(tx, "gov_artifact", str(result["bundle_digest"])))
        verified_candidate(tx, object_value(artifact["metadata"]))
        # The guarded commit just set this timestamp. The pre-commit handler
        # already required receipts newer than a previous activation; recheck
        # current expiry/identity/decision without rejecting its own timestamp.
        artifact["last_activated_at"] = None
        reviews_current(tx, artifact, service.clock())
