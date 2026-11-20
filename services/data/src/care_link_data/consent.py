"""Exact consent scopes and current field permissions under subject guards."""

from datetime import datetime, timedelta
from typing import cast
from uuid import uuid4

from care_link_contracts import validate_contract
from care_link_domain import Actor, ManualError

from .engine import Engine
from .store import Record, Transaction, instant, number, text
from .values import Outcome, digest, dt, integer, object_value, stamp


def owns_subject(tx: Transaction, actor: Actor, session: Record) -> bool:
    persona = tx.get("persona", text(session, "persona_id"))
    return bool(
        persona
        and actor.role == "pid"
        and persona["kind"] == "pid"
        and persona["account_id"] == actor.account_id
        and session["participant_account_id"] == actor.account_id
    )


def delegation_current(
    tx: Transaction,
    proof_id: str,
    grantor_id: str,
    subject_id: str,
    purpose: str,
    fields: set[str],
    now: datetime,
) -> bool:
    delegation = tx.get("delegation", proof_id)
    return bool(
        delegation
        and delegation["subject_id"] == subject_id
        and delegation["grantor_id"] == grantor_id
        and purpose in cast(list[str], delegation["purposes"])
        and fields.issubset(cast(list[str], delegation["fields"]))
        and delegation["revoked_at"] is None
        and now < instant(delegation, "expires_at")
    )


def grant_current(tx: Transaction, grant: Record, now: datetime) -> bool:
    """No positive cache; absence and negative rights are protected by the subject lock."""
    principal = tx.get("principal", text(grant, "grantor_id"))
    subject = tx.get("subject", text(grant, "subject_id"))
    persona = tx.get("persona", text(grant, "subject_id"))
    return bool(
        grant["revoked_at"] is None
        and instant(grant, "effective_at") <= now < instant(grant, "expires_at")
        and principal
        and principal["revoked"] is False
        and number(principal, "identity_revision") == number(grant, "grantor_identity_revision")
        and number(principal, "role_revision") == number(grant, "grantor_role_revision")
        and subject
        and subject["delete_state"] == "active"
        and persona
        and (
            grant["basis"] == "self"
            and persona["account_id"] == grant["grantor_id"]
            and persona["kind"] == "pid"
            and principal["role"] == "pid"
            or grant["basis"] == "explicit_demo_delegation"
            and delegation_current(
                tx,
                text(grant, "authority_proof_id"),
                text(grant, "grantor_id"),
                text(grant, "subject_id"),
                text(grant, "purpose"),
                set(cast(list[str], grant["fields"])),
                now,
            )
        )
    )


def current_fields(tx: Transaction, actor: Actor, session: Record, now: datetime) -> set[str]:
    fields: set[str] = set()
    for grant in tx.rows(
        "consent",
        subject_id=session["persona_id"],
        session_id=session["id"],
        recipient_kind="account",
        recipient_id=actor.account_id,
        purpose="plan",
        limit=100,
    ):
        if grant_current(tx, grant, now):
            fields.update(cast(list[str], grant["fields"]))
    return fields


def capability_access(
    tx: Transaction, actor: Actor, action: str, session: Record | None, now: datetime
) -> bool:
    if session is None:
        return False
    owner = owns_subject(tx, actor, session)
    fresh_al2 = (
        actor.mfa
        and actor.auth_time <= now + timedelta(seconds=1)
        and now < actor.auth_time + timedelta(minutes=5)
    )
    if action in {"plan_create", "plan_retire"}:
        return owner and fresh_al2
    if action == "consent_grant":
        # Delegation cannot be manufactured from relationship text. Separately
        # provisioned delegation requires its own current authority adapter.
        return actor.role in {"pid", "carer", "professional_participant"} and fresh_al2
    if action == "consent_revoke":
        return actor.role in {"pid", "carer", "professional_participant"}
    if action == "consent_read":
        return owner or any(
            grant["grantor_id"] == actor.account_id
            or (
                grant["recipient_kind"] == "account"
                and grant["recipient_id"] == actor.account_id
                and grant_current(tx, grant, now)
            )
            for grant in tx.rows("consent", session_id=session["id"], limit=100)
        )
    if action == "plan_read":
        return owner or bool(current_fields(tx, actor, session, now))
    if action == "plan_field_append":
        if not fresh_al2:
            return False
        if owner:
            return True
        if actor.role != "worker" or not current_fields(tx, actor, session, now):
            return False
        return any(
            row["worker_id"] == actor.account_id and row["status"] in {"accepted", "connected"}
            for row in tx.rows("assignment", session_id=session["id"], limit=100)
        )
    return False


def consent_view(grant: Record) -> Record:
    return {
        "id": grant["grant_id"],
        "revision": str(number(grant, "revision")),
        "scope": grant["scope"],
        "recipient": grant["recipient"],
        "grantor_id": grant["grantor_id"],
        "scope_digest": grant["scope_hash"],
        "effective_at": stamp(instant(grant, "effective_at")),
        "expires_at": stamp(instant(grant, "expires_at")),
        "revoked_at": stamp(instant(grant, "revoked_at")) if grant["revoked_at"] else None,
    }


class Consent(Engine):
    def _consent_session(self, actor: Actor, grant_id: str) -> str:
        with self.store.transaction(actor, None, locked=False) as tx:
            grant = tx.get("consent", grant_id)
            if grant is None:
                raise ManualError("manual.not_found", 404)
            return text(grant, "session_id")

    def consent_grant(self, actor: Actor, key: str, data: Record) -> Record:
        def grant(
            tx: Transaction,
            current: Actor,
            body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, current_guard = self.require_session(session, guard)
            if not current.mfa:
                raise ManualError("manual.grantor_authority_required")
            if body["subject_id"] != row["persona_id"] or body["session_id"] != row["id"]:
                raise ManualError("manual.subject_scope", 404)
            self.expected(body, row)
            recipient = object_value(body["recipient"])
            if body["purpose"] == "plan" and recipient["kind"] != "account":
                raise ManualError("manual.plan_account_required", 422)
            recipient_id = text(
                recipient, "account_id" if recipient["kind"] == "account" else "service_id"
            )
            if recipient["kind"] == "account":
                target = tx.get("principal", recipient_id)
                if target is None or target["revoked"] is not False:
                    raise ManualError("manual.recipient_unavailable", 404)
            if recipient["kind"] == "service":
                service_guard = tx.get("service_guard", recipient_id)
                if (
                    service_guard is None
                    or service_guard["suspended"] is True
                    or str(service_guard["current_revision"]) != recipient["directory_revision"]
                ):
                    raise ManualError("manual.directory_stale", 409)
            effective, expires = dt(body["effective_at"]), dt(body["expires_at"])
            if not effective <= self.clock() < expires or expires <= effective:
                raise ManualError("manual.consent_interval", 422)
            if body["purpose"] == "referral" and (
                expires > self.clock() + timedelta(minutes=15)
                or expires > effective + timedelta(minutes=15)
            ):
                raise ManualError("manual.consent_interval", 422)
            fields = sorted(cast(list[str], body["fields"]))
            if body["basis"] == "self":
                if not owns_subject(tx, current, row):
                    raise ManualError("manual.grantor_authority_required")
                self.authority.consent_proof(
                    current,
                    text(body, "authority_proof_id"),
                    text(body, "subject_id"),
                    text(body, "session_id"),
                    text(body, "purpose"),
                    text(body, "basis"),
                )
            elif not delegation_current(
                tx,
                text(body, "authority_proof_id"),
                current.account_id,
                text(body, "subject_id"),
                text(body, "purpose"),
                set(fields),
                self.clock(),
            ):
                raise ManualError("manual.delegation_not_provisioned")
            subject = tx.get("subject", text(row, "persona_id"))
            if subject is None:
                raise ManualError("manual.subject_scope", 404)
            scope: Record = {
                "session_id": row["id"],
                "subject_id": row["persona_id"],
                "purpose": body["purpose"],
                "fields": fields,
                "recipient_id": recipient_id,
            }
            scope_hash = digest(
                {
                    "version": "care.consent.v1",
                    "scope": scope,
                    "recipient": recipient,
                    "grantor_id": current.account_id,
                    "basis": body["basis"],
                    "authority_proof_id": body["authority_proof_id"],
                    "effective_at": stamp(effective),
                    "expires_at": stamp(expires),
                    "source_revisions": {
                        "subject": str(number(subject, "authority_revision")),
                        "session": str(number(row, "revision")),
                    },
                }
            )
            value: Record = {
                "grant_id": str(uuid4()),
                "subject_id": row["persona_id"],
                "session_id": row["id"],
                "recipient_kind": recipient["kind"],
                "recipient_id": recipient_id,
                "recipient": recipient,
                "purpose": body["purpose"],
                "fields": fields,
                "effective_at": effective,
                "expires_at": expires,
                "scope_hash": scope_hash,
                "scope": scope,
                "revision": 1,
                "revoked_at": None,
                "grantor_id": current.account_id,
                "basis": body["basis"],
                "authority_proof_id": body["authority_proof_id"],
                "grantor_identity_revision": current.identity_revision,
                "grantor_role_revision": current.role_revision,
                "subject_revision": number(subject, "authority_revision"),
            }
            tx.put("consent", value)
            tx.put(
                "consent_event",
                {
                    "id": str(uuid4()),
                    "grant_id": value["grant_id"],
                    "subject_id": row["persona_id"],
                    "kind": "grant",
                    "sequence": 1,
                    "scope_hash": scope_hash,
                    "created_at": self.clock(),
                },
            )
            subject["authority_revision"] = number(subject, "authority_revision") + 1
            tx.put("subject", subject)
            self.bump(tx, row, current_guard)
            return Outcome(
                "ConsentView", consent_view(value), text(value, "grant_id"), text(row, "id")
            )

        return self._run(
            actor,
            "consent_grant",
            key,
            data,
            text(data, "session_id"),
            grant,
            contract="ConsentGrant",
        )

    def consent_read(self, actor: Actor, grant_id: str) -> Record:
        def read(
            tx: Transaction,
            current: Actor,
            _data: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, _ = self.require_session(session, guard)
            grant = tx.get("consent", grant_id)
            if grant is None or grant["session_id"] != row["id"]:
                raise ManualError("manual.not_found", 404)
            if (
                not owns_subject(tx, current, row)
                and grant["grantor_id"] != current.account_id
                and not (
                    grant["recipient_kind"] == "account"
                    and grant["recipient_id"] == current.account_id
                    and grant_current(tx, grant, self.clock())
                )
            ):
                raise ManualError("manual.not_found", 404)
            return Outcome("ConsentView", consent_view(grant))

        return self._run(
            actor,
            "consent_read",
            None,
            {"grant_id": grant_id},
            self._consent_session(actor, grant_id),
            read,
        )

    def consent_revoke(self, actor: Actor, key: str, data: Record, grant_id: str) -> Record:
        def revoke(
            tx: Transaction,
            current: Actor,
            body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, current_guard = self.require_session(session, guard)
            grant = tx.get("consent", grant_id)
            if (
                grant is None
                or grant["session_id"] != row["id"]
                or not (owns_subject(tx, current, row) or grant["grantor_id"] == current.account_id)
            ):
                raise ManualError("manual.not_found", 404)
            if integer(body["expected_revision"]) != number(grant, "revision"):
                raise ManualError("manual.stale_revision", 409)
            subject = tx.get("subject", text(grant, "subject_id"))
            control = tx.get("control", "demo")
            if subject is None or control is None:
                raise ManualError("manual.bootstrap_missing", 503)
            if grant["revoked_at"] is None:
                next_revision = number(subject, "authority_revision") + 1
                self.append_restriction(
                    tx,
                    key,
                    control,
                    {
                        "kind": "consent_revoke",
                        "grant_id": grant_id,
                        "subject_id": grant["subject_id"],
                        "subject_revision": str(next_revision),
                        "effective_at": stamp(self.clock()),
                    },
                    object_value(grant["scope"]),
                )
                grant["revoked_at"] = self.clock()
                grant["revision"] = number(grant, "revision") + 1
                subject["authority_revision"] = next_revision
                tx.put("consent", grant)
                tx.put("subject", subject)
                tx.put(
                    "consent_event",
                    {
                        "id": str(uuid4()),
                        "grant_id": grant_id,
                        "subject_id": grant["subject_id"],
                        "kind": "revoke",
                        "sequence": number(grant, "revision"),
                        "scope_hash": grant["scope_hash"],
                        "created_at": self.clock(),
                    },
                )
                current_guard["access_revision"] = number(current_guard, "access_revision") + 1
                self.bump(tx, row, current_guard)
            return Outcome(
                "CommandResult",
                {
                    "operation_id": key,
                    "state": "committed",
                    "resource_id": grant_id,
                    "revision": str(number(grant, "revision")),
                    "audit_ref": str(uuid4()),
                },
                grant_id,
                text(row, "id"),
            )

        validate_contract("RevisionCommand", data)
        return self._run(
            actor,
            "consent_revoke",
            key,
            {**data, "grant_id": grant_id},
            self._consent_session(actor, grant_id),
            revoke,
        )
