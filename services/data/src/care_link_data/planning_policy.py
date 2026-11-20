"""Current server-derived scope and evidence for IMP-04 policy decisions.

Transport target hints never provide authority. Every fact below is rebuilt
under the same guard set for preliminary policy and final guarded validation.
"""

from datetime import datetime
from typing import cast

from care_link_domain import Actor, ManualError

from .consent import current_fields, grant_current, owns_subject
from .directory import admission_reason
from .store import Record, Transaction, instant, number, text
from .values import digest, object_value, stamp

PLAN_KEYS = frozenset(
    {
        "plan.warning_signs",
        "plan.strategies",
        "plan.responders",
        "plan.medication_report",
        "plan.advance_wishes",
        "plan.contacts",
        "plan.substitute_decision_maker",
    }
)


def directory_policy_binding(
    tx: Transaction,
    service_id: str,
    request: Record,
    manifests: dict[str, Record],
    now: datetime,
) -> None:
    versions = object_value(request["versions"])
    facts = object_value(request["authority_facts"])
    guard = tx.peek("service_guard", service_id)
    versions["directory"] = str(number(guard, "current_revision")) if guard else "0"
    if guard is None:
        facts["source_current"], facts["artifact_admitted"] = False, False
        return
    rows = tx.rows("directory", service_id=service_id, revision=guard["current_revision"], limit=1)
    if not rows:
        raise ManualError("manual.directory_corrupt", 503)
    row = rows[0]
    request["artifact_digests"] = [row["artifact_digest"]]
    manifest = manifests.get(text(row, "artifact_digest"))
    facts["artifact_admitted"] = bool(
        manifest
        and manifest["service_id"] == service_id
        and manifest["payload_digest"]
        == digest(
            {
                "service_id": service_id,
                "facts": row["facts"],
                "sources": row["sources"],
            }
        )
    )
    facts["source_current"] = bool(
        row["state"] == "verified"
        and not guard["suspended"]
        and now < instant(row, "expires_at")
        and facts["artifact_admitted"]
    )
    request["directory_bindings"] = [
        {
            "service_id": service_id,
            "revision": versions["directory"],
            "artifact_digest": row["artifact_digest"],
            "suspended": guard["suspended"],
            "current": facts["source_current"],
        }
    ]
    versions["directory_set_digest"] = digest(
        {
            "guard": guard,
            "artifact": row["artifact_digest"],
        }
    )


def enrich_planning_policy(
    tx: Transaction,
    actor: Actor,
    action: str,
    data: Record,
    snapshot: Record,
    request: Record,
    now: datetime,
    manifests: dict[str, Record],
) -> None:
    scope, facts, versions = [
        object_value(request[key]) for key in ("scope", "authority_facts", "versions")
    ]
    session = object_value(snapshot["session"]) if snapshot["session"] else None
    if action.startswith("plan_") and session is not None:
        scope["purpose"] = "plan"
        owner = owns_subject(tx, actor, session)
        allowed = PLAN_KEYS if owner else current_fields(tx, actor, session, now)
        plan = tx.peek("plan", text(data, "plan_id")) if "plan_id" in data else None
        if action == "plan_create":
            prior = tx.peek("operation", text(request, "operation_id"))
            if (
                prior is not None
                and prior["principal_id"] == actor.account_id
                and prior["operation_name"] == action
                and isinstance(prior["resource_id"], str)
            ):
                plan = tx.peek("plan", text(prior, "resource_id"))
        if plan is not None:
            versions["resource"] = str(number(plan, "revision"))
        selected: set[str] = set()
        if plan is not None:
            rows = tx.rows("plan_field", plan_id=plan["id"], limit=100)
            if len(rows) == 100:
                raise ManualError("manual.plan_history_limit", 503)
            selected = {text(row, "field_key") for row in rows if row["field_key"] in allowed}
        if action == "plan_field_append":
            # Append returns a complete permitted PlanView, so policy binds
            # both the requested edit and every field in that disclosure.
            selected.add(text(data, "field"))
        scope["fields"] = sorted(selected)
        facts["field_scope_allowed"] = selected.issubset(allowed)
        if not owner:
            scope["recipient_id"] = actor.account_id
            grants = [
                grant
                for grant in tx.rows(
                    "consent",
                    subject_id=session["persona_id"],
                    session_id=session["id"],
                    recipient_kind="account",
                    recipient_id=actor.account_id,
                    purpose="plan",
                    limit=100,
                )
                if grant_current(tx, grant, now)
            ]
            if len(grants) > 32:
                raise ManualError("manual.consent_projection_limit", 503)
            evidence: list[Record] = [
                {
                    "required": True,
                    "valid": True,
                    "grant_id": grant["grant_id"],
                    "subject_revision": versions["subject"],
                    "scope_digest": grant["scope_hash"],
                    "effective_at": stamp(instant(grant, "effective_at")),
                    "expires_at": stamp(instant(grant, "expires_at")),
                    "recipient_id": actor.account_id,
                    "subject_id": grant["subject_id"],
                    "session_id": grant["session_id"],
                    "purpose": "plan",
                    "fields": sorted(cast(list[str], grant["fields"])),
                }
                for grant in grants
            ]
            request["disclosure_grants"] = evidence
            consent = object_value(facts["consent"])
            consent["required"], consent["valid"] = True, bool(evidence)
            if evidence:
                facts["consent"] = evidence[0]
                request["consent_id"] = evidence[0]["grant_id"]
    elif action.startswith("consent_"):
        grant = tx.peek("consent", text(data, "grant_id")) if "grant_id" in data else None
        if grant is not None:
            versions["resource"] = str(number(grant, "revision"))
            request["consent_id"] = grant["grant_id"]
            scope.update(object_value(grant["scope"]))
            # Consent management is distinct from disclosure under that grant.
            scope["purpose"] = "support"
        elif action == "consent_grant":
            recipient = object_value(data["recipient"])
            scope["recipient_id"] = (
                recipient["account_id"]
                if recipient["kind"] == "account"
                else recipient["service_id"]
            )
            scope["fields"] = sorted(cast(list[str], data["fields"]))
            facts["field_scope_allowed"] = bool(scope["fields"]) and (
                data["purpose"] != "plan" or set(scope["fields"]).issubset(PLAN_KEYS)
            )
            if recipient["kind"] == "service":
                directory_policy_binding(tx, text(recipient, "service_id"), request, manifests, now)
    elif action.startswith("directory_"):
        if action == "directory_search":
            guards: list[Record] = []
            after = None
            for _ in range(2):
                batch = tx.directory_page(after, 51)
                guards.extend(batch)
                if len(batch) < 51:
                    break
                after = text(batch[-1], "service_id")
            if len(guards) > 100:
                raise ManualError("manual.directory_projection_limit", 503)
            artifacts: set[str] = set()
            directory_bindings: list[Record] = []
            source_current = True
            admitted = True
            for guard in guards:
                binding: Record = {"versions": {}, "authority_facts": {}, "artifact_digests": []}
                directory_policy_binding(tx, text(guard, "service_id"), binding, manifests, now)
                artifacts.update(cast(list[str], binding["artifact_digests"]))
                directory_bindings.extend(cast(list[Record], binding["directory_bindings"]))
                source_current = (
                    source_current
                    and object_value(binding["authority_facts"])["source_current"] is True
                )
                admitted = (
                    admitted
                    and object_value(binding["authority_facts"])["artifact_admitted"] is True
                )
            if len(artifacts) > 32:
                raise ManualError("manual.directory_projection_limit", 503)
            request["artifact_digests"] = sorted(artifacts)
            request["directory_bindings"] = directory_bindings
            versions["directory"] = str(
                max((number(row, "current_revision") for row in guards), default=0)
            )
            versions["directory_set_digest"] = digest(guards)
            facts["source_current"], facts["artifact_admitted"] = source_current, admitted
        else:
            service_id = text(data, "service_id")
            scope["recipient_id"] = service_id
            directory_policy_binding(tx, service_id, request, manifests, now)
            if action == "directory_ingest":
                request["artifact_digests"] = [data["feed_artifact_digest"]]
                admitted = admission_reason(data, manifests, now) is None
                facts["source_current"], facts["artifact_admitted"] = admitted, admitted
