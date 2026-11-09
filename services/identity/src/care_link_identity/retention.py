"""Option B: reusable accounts, immediate negative rights and bounded metadata.

These guarded use cases expose no public admin route and claim no physical
storage erasure. Owner/custodian labels are main per the actual user decision;
operator identity still comes from a separately verified authority port.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from .credential_disposal import fence_session_material, locally_restricted, maintenance_restricted
from .crypto import Custody
from .domain import IdentityError, Store, Transaction, instant, stamp, text
from .retention_ports import (
    AccountCleanup,
    BackupCustody,
    RecordClass,
    RetentionAuthority,
    RetentionGrant,
    validate_grant,
)

DAYS = {"security_log": 30, "minimal_audit": 90, "reviewer_evidence": 90}
PROFILE_FIELDS = {
    "subject",
    "profile",
    "display_name",
    "email",
    "phone",
    "oidc_linkage",
    "reviewed_by",
}


class RetentionService:
    def __init__(
        self,
        store: Store,
        custody: Custody,
        authority: RetentionAuthority | None,
        cleanup: AccountCleanup | None = None,
        backups: BackupCustody | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store, self.custody, self.authority = store, custody, authority
        self.cleanup, self.backups, self.clock = cleanup, backups, clock

    def _operator(self, proof: str, action: str, account_id: str) -> RetentionGrant:
        if self.authority is None:
            raise IdentityError("identity.retention_authority_unavailable", 503)
        operator = self.authority.authorize(proof, action, account_id)
        if (
            str(UUID(operator.operator_id)) != operator.operator_id
            or operator.action != action
            or operator.target_account_id != account_id
        ):
            raise IdentityError("identity.retention_operator_denied")
        return operator

    @staticmethod
    def _account(tx: Transaction, account_id: str) -> tuple[str, dict[str, object]]:
        for key, record in tx.items("account"):
            if record.get("account_id") == account_id:
                return key, record
        raise IdentityError("identity.account_not_found", 404)

    @staticmethod
    def _fence_credentials(tx: Transaction, account_id: str, subject: str, now: datetime) -> None:
        sessions: set[str] = set()
        for key, record in tx.items("session"):
            if record.get("account_id") == account_id:
                sessions.add(key)
                record.update(
                    {"revoked": True, "access_token": "", "csrf": "", "expires_at": stamp(now)}
                )
                tx.put("session", key, record)
        for key, record in tx.items("intent"):
            if (
                record.get("account_id") == account_id
                or record.get("session_hash") in sessions
                or record.get("previous_session_hash") in sessions
                or record.get("proof_subject") == subject
            ):
                record.update({"state": "failed", "verifier": "", "nonce": "", "access_token": ""})
                tx.put("intent", key, record)
        for key, record in tx.items("proof"):
            if record.get("account_id") == account_id or record.get("session_hash") in sessions:
                tx.delete("proof", key)
        for key, record in tx.items("ceremony"):
            if record.get("session_hash") in sessions:
                record["state"] = "expired"
                tx.put("ceremony", key, record)

    def deprovision(self, account_id: str, command_id: str, actor_proof: str) -> dict[str, object]:
        operator, now = self._operator(actor_proof, "deprovision", account_id), self.clock()
        if account_id == operator.operator_id:
            raise IdentityError("identity.owner_self_deprovision_denied")
        UUID(command_id)
        with self.store.transaction() as tx:
            validate_grant(tx, operator, self.clock())
            previous = tx.get("retention_operation", command_id)
            if previous:
                if (
                    previous.get("action") != "deprovision"
                    or previous.get("account_id") != account_id
                ):
                    raise IdentityError("identity.retention_command_conflict", 409)
            else:
                key, account = self._account(tx, account_id)
                subject = text(account, "subject")
                if account.get("deprovisioned_at") is None:
                    account.update(
                        {
                            "enabled": False,
                            "roles": [],
                            "deprovisioned_at": stamp(now),
                            "profile_purge_due_at": stamp(now + timedelta(days=30)),
                            "revision": str(int(text(account, "revision")) + 1),
                            "role_revision": str(int(text(account, "role_revision")) + 1),
                        }
                    )
                self._fence_credentials(tx, account_id, subject, now)
                tx.put("account", key, account)
                tx.put(
                    "account_marker",
                    account_id,
                    {
                        "account_id": account_id,
                        "account_key": key,
                        "deprovisioned_at": account["deprovisioned_at"],
                        "profile_purge_due_at": account["profile_purge_due_at"],
                        "blocked": True,
                        "profile_removed": False,
                        "owner": "main",
                        "reason": "deprovisioned",
                        "review_date": stamp(now + timedelta(days=30)),
                        "backup_state": "pending",
                    },
                )
                tx.put(
                    "retention_operation",
                    command_id,
                    {
                        "action": "deprovision",
                        "account_id": account_id,
                        "state": "pending",
                        "provider_state": "pending",
                        "local_access": "fenced",
                        "created_at": stamp(now),
                        "operator_id": operator.operator_id,
                        "owner": "main",
                        "subject_ciphertext": self.custody.encrypt(subject),
                    },
                )
        return self.reconcile(command_id, actor_proof)

    def reconcile(self, command_id: str, actor_proof: str) -> dict[str, object]:
        with self.store.transaction() as tx:
            operation = tx.get("retention_operation", command_id)
            if operation is None:
                raise IdentityError("identity.retention_operation_missing", 404)
        operator = self._operator(actor_proof, "reconcile_retention", text(operation, "account_id"))
        if operation.get("provider_state") != "confirmed":
            if operation["action"] == "profile_purge":
                # This is the external effect's current authorization boundary.
                # A later hold can be too late for that bounded in-flight call,
                # but every retry obtains a new grant and checks current guards.
                with self.store.transaction() as tx:
                    validate_grant(tx, operator, self.clock())
                    held = any(
                        row.get("account_id") == operation["account_id"]
                        and row.get("released") is not True
                        for _key, row in tx.items("retention_hold")
                    )
                    marker = tx.get("account_marker", text(operation, "account_id"))
                    dependencies = bool((marker or {}).get("profile_dependencies"))
                    if held or dependencies:
                        latest = tx.get("retention_operation", command_id)
                        if latest is None:
                            raise IdentityError("identity.retention_operation_changed", 503)
                        latest.update(
                            {
                                "state": "held_pending",
                                "reason": "current_hold_or_profile_dependency",
                                "owner": "main",
                                "review_date": stamp(self.clock() + timedelta(days=1)),
                            }
                        )
                        tx.put("retention_operation", command_id, latest)
                        return {
                            key: value
                            for key, value in latest.items()
                            if key not in {"subject_ciphertext", "operator_id"}
                        }
            try:
                subject = self.custody.decrypt(text(operation, "subject_ciphertext"))
                complete = (
                    False
                    if self.cleanup is None
                    else (
                        self.cleanup.disable(subject, command_id)
                        if operation["action"] == "deprovision"
                        else self.cleanup.delete_profile(subject, command_id)
                    )
                )
            except (OSError, TimeoutError, IdentityError):
                complete = False
            operator = self._operator(
                actor_proof, "reconcile_retention", text(operation, "account_id")
            )
            with self.store.transaction() as tx:
                validate_grant(tx, operator, self.clock())
                latest = tx.get("retention_operation", command_id)
                if latest is None or latest.get("account_id") != operation["account_id"]:
                    raise IdentityError("identity.retention_operation_changed", 503)
                if complete:
                    latest.update({"provider_state": "confirmed", "subject_ciphertext": ""})
                else:
                    latest.update(
                        {
                            "owner": "main",
                            "reason": "provider_cleanup_pending",
                            "review_date": stamp(self.clock() + timedelta(days=1)),
                        }
                    )
                tx.put("retention_operation", command_id, latest)
                operation = latest
        if operation["action"] == "profile_purge":
            backup_state = "pending"
            if self.backups is not None:
                try:
                    clearance = self.backups.clearance(text(operation, "account_id"))
                    age = (self.clock() - clearance.checked_at).total_seconds()
                    if (
                        clearance.account_id == operation["account_id"]
                        and clearance.fully_accounted
                        and clearance.restorable_copies == 0
                        and clearance.immutable_expiries_preserved
                        and 0 <= age <= 1
                    ):
                        backup_state = "known_copies_accounted"
                except (OSError, TimeoutError, IdentityError):
                    pass
            operator = self._operator(
                actor_proof, "reconcile_retention", text(operation, "account_id")
            )
            with self.store.transaction() as tx:
                validate_grant(tx, operator, self.clock())
                marker = tx.get("account_marker", text(operation, "account_id"))
                if marker is None:
                    raise IdentityError("identity.retention_marker_missing", 503)
                marker["backup_state"] = backup_state
                tx.put("account_marker", text(operation, "account_id"), marker)
            operation["backup_state"] = backup_state
        operation["state"] = (
            "local_fence_provider_confirmed"
            if operation["action"] == "deprovision" and operation["provider_state"] == "confirmed"
            else (
                "active_profile_removed_known_copies_accounted"
                if operation.get("backup_state") == "known_copies_accounted"
                and operation["provider_state"] == "confirmed"
                else "active_profile_removed_backup_pending"
                if operation["action"] == "profile_purge"
                else "pending"
            )
        )
        operator = self._operator(actor_proof, "reconcile_retention", text(operation, "account_id"))
        with self.store.transaction() as tx:
            validate_grant(tx, operator, self.clock())
            tx.put("retention_operation", command_id, operation)
        return {
            key: value
            for key, value in operation.items()
            if key not in {"subject_ciphertext", "operator_id"}
        }

    def review_access(self, account_id: str, actor_proof: str, expected_revision: str) -> None:
        operator, now = self._operator(actor_proof, "review_access", account_id), self.clock()
        with self.store.transaction() as tx:
            validate_grant(tx, operator, self.clock())
            key, account = self._account(tx, account_id)
            if (
                account.get("deprovisioned_at") is not None
                or account.get("revision") != expected_revision
            ):
                raise IdentityError("identity.retention_review_conflict", 409)
            account.update(
                {
                    "reviewed_at": stamp(now),
                    "access_review_due_at": stamp(now + timedelta(days=30)),
                }
            )
            tx.put("account", key, account)
            tx.put(
                "retention_record",
                str(uuid4()),
                {
                    "account_id": account_id,
                    "record_class": "minimal_audit",
                    "payload": {"action": "access_review", "actor_id": operator.operator_id},
                    "event_at": stamp(now),
                    "dependencies": [],
                    "last_dependency_ended_at": None,
                    "owner": "main",
                    "state": "active",
                },
            )

    def profile_dependency(
        self, account_id: str, dependency: str, actor_proof: str, *, remove: bool = False
    ) -> None:
        if not dependency or len(dependency) > 128:
            raise IdentityError("identity.retention_dependency_invalid")
        operator = self._operator(
            actor_proof,
            "remove_profile_dependency" if remove else "add_profile_dependency",
            account_id,
        )
        with self.store.transaction() as tx:
            validate_grant(tx, operator, self.clock())
            marker = tx.get("account_marker", account_id)
            if marker is None:
                raise IdentityError("identity.retention_marker_missing", 404)
            dependencies = set(cast(list[str], marker.get("profile_dependencies", [])))
            if remove:
                if dependency not in dependencies:
                    raise IdentityError("identity.retention_dependency_missing", 409)
                dependencies.remove(dependency)
            else:
                dependencies.add(dependency)
            marker.update(
                {
                    "profile_dependencies": sorted(dependencies),
                    "owner": "main",
                    "reason": "profile_dependency" if dependencies else "deprovisioned",
                    "review_date": stamp(self.clock() + timedelta(days=1)),
                }
            )
            tx.put("account_marker", account_id, marker)

    def add_hold(self, account_id: str, reason: str, review_at: datetime, actor_proof: str) -> str:
        operator = self._operator(actor_proof, "retention_hold", account_id)
        now = self.clock()
        if not reason or len(reason) > 256 or not now < review_at <= now + timedelta(days=30):
            raise IdentityError("identity.invalid_retention_hold")
        hold_id = str(uuid4())
        with self.store.transaction() as tx:
            validate_grant(tx, operator, self.clock())
            self._account(tx, account_id)
            tx.put(
                "retention_hold",
                hold_id,
                {
                    "account_id": account_id,
                    "owner": "main",
                    "reason": reason,
                    "review_date": stamp(review_at),
                    "released": False,
                },
            )
        return hold_id

    def release_hold(self, hold_id: str, actor_proof: str) -> None:
        with self.store.transaction() as tx:
            hold = tx.get("retention_hold", hold_id)
            if hold is None:
                raise IdentityError("identity.hold_missing", 404)
        operator = self._operator(actor_proof, "release_retention_hold", text(hold, "account_id"))
        with self.store.transaction() as tx:
            validate_grant(tx, operator, self.clock())
            current = tx.get("retention_hold", hold_id)
            if current is None:
                raise IdentityError("identity.hold_missing", 404)
            # Releasing a hold does not grant access or dispose restriction markers.
            current.update({"released": True, "released_at": stamp(self.clock())})
            tx.put("retention_hold", hold_id, current)

    def register_record(
        self,
        account_id: str,
        record_class: RecordClass,
        payload: dict[str, object],
        event_at: datetime,
        actor_proof: str,
        dependencies: frozenset[str] = frozenset(),
    ) -> str:
        operator = self._operator(actor_proof, "inventory_retention", account_id)
        if record_class not in DAYS or event_at > self.clock():
            raise IdentityError("identity.retention_record_invalid")
        allowed = {
            "action",
            "resource_id",
            "receipt_digest",
            "purpose",
            "outcome",
            "operation_id",
            "artifact_digest",
            "actor_id",
            "event_type",
            "reason_key",
        }
        if not set(payload) <= allowed or any(
            not isinstance(value, str) or len(value) > 256 for value in payload.values()
        ):
            raise IdentityError("identity.retention_minimization_required")
        record_id = str(uuid4())
        with self.store.transaction() as tx:
            validate_grant(tx, operator, self.clock())
            self._account(tx, account_id)
            tx.put(
                "retention_record",
                record_id,
                {
                    "account_id": account_id,
                    "record_class": record_class,
                    "payload": payload,
                    "event_at": stamp(event_at),
                    "dependencies": sorted(dependencies),
                    "last_dependency_ended_at": None,
                    "owner": "main",
                    "state": "active",
                },
            )
        return record_id

    def add_dependency(self, record_id: str, dependency: str, actor_proof: str) -> None:
        if not dependency or len(dependency) > 128:
            raise IdentityError("identity.retention_dependency_invalid")
        with self.store.transaction() as tx:
            record = tx.get("retention_record", record_id)
            if record is None:
                raise IdentityError("identity.retention_record_missing", 404)
        operator = self._operator(
            actor_proof, "add_retention_dependency", text(record, "account_id")
        )
        with self.store.transaction() as tx:
            validate_grant(tx, operator, self.clock())
            record = tx.get("retention_record", record_id)
            if record is None or record.get("state") != "active":
                raise IdentityError("identity.retention_record_removed", 409)
            dependencies = set(cast(list[str], record["dependencies"]))
            dependencies.add(dependency)
            record.update({"dependencies": sorted(dependencies), "last_dependency_ended_at": None})
            tx.put("retention_record", record_id, record)

    def end_dependency(self, record_id: str, dependency: str, actor_proof: str) -> None:
        with self.store.transaction() as tx:
            record = tx.get("retention_record", record_id)
            if record is None:
                raise IdentityError("identity.retention_record_missing", 404)
        operator = self._operator(
            actor_proof, "end_retention_dependency", text(record, "account_id")
        )
        with self.store.transaction() as tx:
            validate_grant(tx, operator, self.clock())
            record = tx.get("retention_record", record_id)
            if record is None:
                raise IdentityError("identity.retention_record_missing", 404)
            dependencies = set(cast(list[str], record["dependencies"]))
            if dependency not in dependencies:
                raise IdentityError("identity.retention_dependency_missing", 409)
            dependencies.remove(dependency)
            record["dependencies"] = sorted(dependencies)
            if not dependencies:
                record["last_dependency_ended_at"] = stamp(self.clock())
            tx.put("retention_record", record_id, record)

    def purge_due(self, account_id: str, actor_proof: str) -> dict[str, object]:
        operator, now = self._operator(actor_proof, "purge_retention", account_id), self.clock()
        profile_command = "profile:" + account_id
        with self.store.transaction() as tx:
            validate_grant(tx, operator, self.clock())
            key, account = self._account(tx, account_id)
            holds = [
                hold
                for _id, hold in tx.items("retention_hold")
                if hold.get("account_id") == account_id and hold.get("released") is not True
            ]
            if holds:
                return {
                    "state": "held",
                    "owner": "main",
                    "review_overdue": any(instant(h["review_date"]) <= now for h in holds),
                }
            for record_id, record in tx.items("retention_record"):
                if record.get("account_id") != account_id or record.get("state") != "active":
                    continue
                dependencies = cast(list[str], record["dependencies"])
                if dependencies:
                    continue
                anchor = record["event_at"]
                if record["record_class"] == "reviewer_evidence":
                    anchor = record["last_dependency_ended_at"] or record["event_at"]
                if instant(anchor) + timedelta(days=DAYS[text(record, "record_class")]) <= now:
                    record.update(
                        {
                            "payload": {},
                            "state": "active_removed_backup_pending",
                            "removed_at": stamp(now),
                            "owner": "main",
                            "reason": "backup_copy_accounting_pending",
                            "review_date": stamp(now + timedelta(days=7)),
                        }
                    )
                    tx.put("retention_record", record_id, record)
            due = account.get("profile_purge_due_at")
            if due is None or instant(due) > now:
                return {"state": "not_due"}
            command: dict[str, object] | None = tx.get("retention_operation", profile_command)
            if command is None:
                subject = text(account, "subject")
                command = {
                    "action": "profile_purge",
                    "account_id": account_id,
                    "state": "pending",
                    "provider_state": "pending",
                    "created_at": stamp(now),
                    "operator_id": operator.operator_id,
                    "owner": "main",
                    "subject_ciphertext": self.custody.encrypt(subject),
                }
                tx.put("retention_operation", profile_command, command)
                for field in PROFILE_FIELDS:
                    account.pop(field, None)
                account.update({"enabled": False, "roles": [], "profile_removed_at": stamp(now)})
                tx.put("account", key, account)
                marker = tx.get("account_marker", account_id)
                if marker is None:
                    raise IdentityError("identity.retention_marker_missing", 503)
                marker.update(
                    {
                        "profile_removed": True,
                        "profile_removed_at": stamp(now),
                        "backup_state": "pending",
                    }
                )
                tx.put("account_marker", account_id, marker)
        return self.reconcile(profile_command, actor_proof)

    def expire_credentials(self) -> int:
        """Restriction-only scheduled maintenance; never grants account authority."""
        now, cleared = self.clock(), 0
        with self.store.transaction() as tx:
            for key, record in tx.items("session"):
                if locally_restricted(tx, record, now):
                    if record.get("access_token") or record.get("revoked") is not True:
                        record.update({"access_token": "", "revoked": True})
                        tx.put("session", key, record)
                        cleared += 1
                    fence_session_material(tx, key)
            for key, record in tx.items("intent"):
                if "expires_at" not in record:
                    continue
                if record.get("purpose") == "owner_access_review":
                    restricted = maintenance_restricted(tx, record)
                    if (
                        instant(record["expires_at"]) <= now
                        or record.get("review_consumed") is True
                        or record.get("state") in {"failed", "uncertain"}
                        or restricted
                    ):
                        record.update({"verifier": "", "nonce": "", "access_token": ""})
                        if restricted:
                            record["state"] = "failed"
                        tx.put("intent", key, record)
                        cleared += 1
                    continue
                if instant(record["expires_at"]) <= now or record.get("state") in {
                    "completed",
                    "failed",
                    "uncertain",
                }:
                    if record.get("verifier") or record.get("nonce"):
                        record.update(
                            {
                                "verifier": "",
                                "nonce": "",
                                "state": "failed"
                                if record.get("state") == "pending"
                                else record["state"],
                            }
                        )
                        tx.put("intent", key, record)
                        cleared += 1
            for key, record in tx.items("proof"):
                if record.get("consumed") is True or instant(record["expires_at"]) <= now:
                    tx.delete("proof", key)
                    cleared += 1
        return cleared

    def purge_expired_protocol_metadata(self) -> int:
        """Dispose expired protocol metadata after its class window.

        Pending cross-custodian operations/negative source heads and restriction
        markers are excluded. No new access or external effect is authorized.
        """
        now, removed = self.clock(), 0
        with self.store.transaction() as tx:
            for kind in (
                "session",
                "intent",
                "ceremony",
                "operation",
                "signal",
                "retention_operation",
            ):
                for key, record in tx.items(kind):
                    if kind == "intent" and "created_at" not in record:
                        continue  # reference is disposed with its actual intent
                    if (
                        kind in {"operation", "retention_operation"}
                        and record.get("state") == "pending"
                    ):
                        continue
                    if kind == "retention_operation" and (
                        record.get("provider_state") != "confirmed"
                        or record.get("subject_ciphertext")
                    ):
                        continue
                    anchor = (
                        record.get("created_at")
                        or record.get("received_at")
                        or record.get("event_at")
                        or record.get("expires_at")
                    )
                    if anchor is None:
                        continue  # unknown old anchor requires inventory/review
                    days = 30 if kind in {"session", "intent", "ceremony"} else 90
                    if instant(anchor) + timedelta(days=days) > now:
                        continue
                    if (
                        kind == "session"
                        and record.get("revoked") is not True
                        and instant(record["expires_at"]) > now
                    ):
                        continue
                    if kind == "intent" and isinstance(record.get("id"), str):
                        tx.delete("intent", text(record, "id"))
                    tx.delete(kind, key)
                    removed += 1
        return removed

    def quarantine_restore(
        self, records: Sequence[tuple[str, str, dict[str, object]]], immutable_capture_at: datetime
    ) -> list[tuple[str, str, dict[str, object]]]:
        now = self.clock()
        if not immutable_capture_at <= now < immutable_capture_at + timedelta(days=7):
            raise IdentityError("identity.backup_expired")
        allowed = {
            "account",
            "account_marker",
            "retention_hold",
            "retention_record",
            "head",
            "issuer",
            "workload_state",
        }
        restored: dict[tuple[str, str], dict[str, object]] = {}
        with self.store.transaction() as tx:
            for kind, key, source in records:
                if kind not in allowed:
                    # Never restore bearer, ceremony, provider-cleanup secret or
                    # pending command authority from a historical snapshot.
                    continue
                record = dict(source)
                current = tx.get(kind, key)
                if kind == "account":
                    marker = tx.get("account_marker", text(record, "account_id"))
                    record.update(
                        {"enabled": False, "roles": [], "blocked": True, "recovery_required": True}
                    )
                    if marker:
                        record["deprovisioned_at"] = marker["deprovisioned_at"]
                        record["profile_purge_due_at"] = marker["profile_purge_due_at"]
                        if marker.get("profile_removed") is True:
                            for field in PROFILE_FIELDS:
                                record.pop(field, None)
                elif current is not None:
                    # Live restriction/hold/copy deletion metadata wins over the
                    # snapshot. A restore cannot release holds or restore bytes
                    # already removed from the active retention inventory.
                    record = current
                restored[(kind, key)] = record
            for kind in ("account_marker", "retention_hold", "workload_state", "issuer", "head"):
                for key, current in tx.items(kind):
                    restored[(kind, key)] = current
        return [(kind, key, record) for (kind, key), record in restored.items()]
