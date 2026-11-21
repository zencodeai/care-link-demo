"""Exact lifecycle policy facts, rebuilt under the final ordered guard set."""

from typing import cast

from care_link_domain import Actor

from ..consent import grant_current
from ..engine import Engine
from ..store import Record, Transaction, instant, number, text
from ..values import object_value, stamp


def enrich_lifecycle_policy(
    service: Engine,
    tx: Transaction,
    actor: Actor,
    action: str,
    arguments: Record,
    snapshot: Record,
    request: Record,
) -> None:
    facts = object_value(request["authority_facts"])
    scope = object_value(request["scope"])
    versions = object_value(request["versions"])
    scope["purpose"] = (
        "rights"
        if action.startswith(("rights_", "export_", "hold_"))
        else "support"
        if action.startswith("outcome")
        else "follow_up"
    )
    allowed = bool(facts["resource_owned_or_assigned"])
    target: Record | None = None
    repository = (
        "rights"
        if action in {"rights_read", "export_download"}
        else "inbox"
        if action == "inbox_message_read"
        else "followup"
        if action in {"followup_read", "followup_cancel", "followup_bind_anchor"}
        else "hold"
        if action == "hold_release"
        else None
    )
    parameter = (
        "rights_id"
        if repository == "rights"
        else "message_id"
        if repository == "inbox"
        else "followup_id"
        if repository == "followup"
        else "hold_id"
    )
    if repository:
        value = arguments.get(parameter)
        target = tx.peek(repository, value) if isinstance(value, str) else None
        allowed = allowed and target is not None
        if target:
            if repository == "rights":
                allowed = allowed and target["requester_id"] == actor.account_id
            if repository == "inbox":
                allowed = (
                    allowed
                    and target["recipient_account_id"] == actor.account_id
                    and instant(target, "expires_at") > service.clock()
                )
            if "revision" in target:
                versions["resource"] = str(number(target, "revision"))
            if "subject_id" in target:
                scope["subject_id"] = target["subject_id"]
            if "session_id" in target:
                scope["session_id"] = target["session_id"]
    if action == "rights_create":
        subject_id = arguments.get("subject_id")
        persona = tx.get("persona", subject_id) if isinstance(subject_id, str) else None
        allowed = allowed and bool(
            persona and persona["account_id"] == actor.account_id and persona["kind"] == actor.role
        )
        scope["subject_id"] = subject_id
    subject_id = scope["subject_id"]
    if isinstance(subject_id, str):
        subject = tx.get("subject", subject_id)
        replay_allowed = False
        if action == "rights_create" and arguments.get("ceremony_id"):
            prior = tx.get("operation", text(request, "operation_id"))
            replay_allowed = bool(
                prior
                and prior["principal_id"] == actor.account_id
                and prior["operation_name"] == action
                and prior["state"] == "committed"
            )
        allowed = allowed and bool(
            subject
            and (subject["delete_state"] == "active" or action == "rights_read" or replay_allowed)
        )
        if subject:
            versions["subject"] = str(number(subject, "authority_revision"))
    if action in {"followup_create", "followup_bind_anchor"}:
        grant_id = arguments.get("contact_grant_id")
        grant = tx.get("consent", grant_id) if isinstance(grant_id, str) else None
        recipient = (
            arguments.get("recipient_account_id")
            if action == "followup_create"
            else target["recipient_account_id"]
            if target
            else None
        )
        scope["recipient_id"] = recipient
        scope["fields"] = ["summary"]
        valid = bool(
            grant
            and grant["purpose"] == "follow_up"
            and grant["recipient_kind"] == "account"
            and grant["recipient_id"] == recipient
            and grant["subject_id"] == scope["subject_id"]
            and grant["session_id"] == scope["session_id"]
            and "summary" in cast(list[str], grant["fields"])
            and grant_current(tx, grant, service.clock())
        )
        request["consent_id"] = grant_id
        facts["consent"] = {
            "required": True,
            "valid": valid,
            "grant_id": grant_id,
            "subject_revision": versions["subject"] if grant else "0",
            "subject_id": grant["subject_id"] if grant else None,
            "session_id": grant["session_id"] if grant else None,
            "purpose": grant["purpose"] if grant else None,
            "scope_digest": grant["scope_hash"] if grant else None,
            "effective_at": stamp(instant(grant, "effective_at")) if grant else None,
            "expires_at": stamp(instant(grant, "expires_at")) if grant else None,
            "recipient_id": recipient,
            "fields": ["summary"],
        }
        allowed = allowed and valid
    facts["resource_owned_or_assigned"] = allowed
    facts["field_scope_allowed"] = allowed
