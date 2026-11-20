"""Durable isolated receiver. Actor service authority is deployment configuration."""

import hashlib
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import psycopg
from care_link_contracts import validate_contract
from care_link_domain import Actor, AuthorityPort, CipherPort, ManualError
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

Record = dict[str, object]


def canonical(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def text(row: Record, key: str) -> str:
    value = row[key]
    if not isinstance(value, str):
        raise ManualError("receiver.corrupt_state", 503)
    return value


class ReceiverService:
    def __init__(
        self,
        dsn: str,
        cipher: CipherPort,
        authority: AuthorityPort,
        *,
        actor_services: dict[str, str],
        services: frozenset[str],
        scenario: str = "normal",
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        settings = conninfo_to_dict(dsn)
        if settings.get("sslmode") != "verify-full" or not settings.get("sslrootcert"):
            raise ValueError("Receiver storage requires explicit verified TLS")
        if scenario not in {"normal", "drop_after_store", "timeout_before_store", "unavailable"}:
            raise ValueError("Closed synthetic scenario required")
        if not set(actor_services.values()).issubset(services):
            raise ValueError("Receiver actors must map only to admitted simulator services")
        key_ref = getattr(cipher, "key_ref", None)
        if not isinstance(key_ref, str) or not key_ref:
            raise ValueError("Receiver content requires registered encryption custody")
        self.content_key_ref = key_ref
        self.dsn, self.cipher, self.authority = dsn, cipher, authority
        self.actor_services, self.services, self.scenario, self.clock = (
            dict(actor_services),
            services,
            scenario,
            clock,
        )

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection[Record]]:
        with psycopg.Connection[Record].connect(
            self.dsn, row_factory=dict_row, connect_timeout=1
        ) as connection:
            connection.execute("SET LOCAL statement_timeout='750ms'")
            yield connection

    def _service(self, actor: Actor) -> str:
        current = self.authority.current(actor)
        now = self.clock()
        service_id = self.actor_services.get(actor.account_id)
        if (
            service_id is None
            or actor.role != "receiver"
            or (actor.request_deadline is not None and actor.request_deadline <= now)
            or current.browser_session_digest != actor.browser_session_digest
            or current.transport_generation != actor.transport_generation
            or current.account_id != actor.account_id
            or current.role != "receiver"
            or current.identity_revision != actor.identity_revision
            or current.role_revision != actor.role_revision
            or not current.mfa
            or current.expires_at <= now
            or not now - timedelta(minutes=5) < current.auth_time <= now + timedelta(seconds=1)
        ):
            raise ManualError("receiver.service_authority_required")
        return service_id

    def _mapping(self, service_id: str) -> None:
        if service_id not in self.services:
            raise ManualError("receiver.mapping_denied")

    def _receipt(
        self, service_id: str, dispatch_id: str, payload_digest: str, status: str
    ) -> Record:
        return {
            "id": str(uuid4()),
            "dispatch_id": dispatch_id,
            "recipient_service_id": service_id,
            "payload_digest": payload_digest,
            "status": status,
            "accepted_fields": [],
            "observed_at": self.clock().isoformat().replace("+00:00", "Z"),
        }

    def send(self, service_id: str, package: Record) -> Record:
        """Called only through a composition-bound, workload-authenticated transport."""
        self._mapping(service_id)
        validate_contract("SimulatorSend", package)
        payload = cast(Record, package["payload"])
        if (
            payload["recipient_service_id"] != service_id
            or digest(payload) != package["payload_digest"]
        ):
            raise ManualError("receiver.payload_binding_mismatch", 409)
        if self.scenario in {"timeout_before_store", "unavailable"}:
            raise TimeoutError("Synthetic receiver unavailable before storage")
        dispatch_id, payload_digest = text(package, "dispatch_id"), text(package, "payload_digest")
        receipt = self._receipt(service_id, dispatch_id, payload_digest, "received")
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO receiver.package(recipient_service_id,dispatch_id,payload_digest,"
                "payload_ciphertext,authorization_id,receipt) "
                "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (
                    service_id,
                    dispatch_id,
                    payload_digest,
                    self.cipher.encrypt(canonical(payload)),
                    package["authorization_id"],
                    Jsonb(receipt),
                ),
            )
            row = connection.execute(
                "SELECT * FROM receiver.package WHERE recipient_service_id=%s "
                "AND dispatch_id=%s FOR UPDATE",
                (service_id, dispatch_id),
            ).fetchone()
            if row is None or row["payload_digest"] != payload_digest:
                raise ManualError("receiver.dispatch_digest_conflict", 409)
            connection.execute(
                "INSERT INTO receiver.copy VALUES(%s,%s,%s,%s,'referral',%s,'synthetic_content',"
                "%s,'parent_and_delivery_terminal',7,NULL,NULL,'anchor_pending',%s) "
                "ON CONFLICT DO NOTHING",
                (
                    service_id,
                    dispatch_id,
                    payload["subject_id"],
                    payload["session_id"],
                    "receiver:package:" + dispatch_id,
                    self.content_key_ref,
                    self.clock(),
                ),
            )
            receipt = cast(Record, row["receipt"])
        if self.scenario == "drop_after_store":
            raise TimeoutError("Synthetic lost reply after durable receiver storage")
        return receipt

    def lookup(self, service_id: str, dispatch_id: str, payload_digest: str) -> Record:
        self._mapping(service_id)
        if self.scenario == "unavailable":
            return self._receipt(service_id, dispatch_id, payload_digest, "unavailable")
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM receiver.package WHERE recipient_service_id=%s AND dispatch_id=%s",
                (service_id, dispatch_id),
            ).fetchone()
            if row is None:
                return self._receipt(service_id, dispatch_id, payload_digest, "not_found")
            if row["payload_digest"] != payload_digest:
                raise ManualError("receiver.dispatch_digest_conflict", 409)
            return cast(Record, row["receipt"])

    def receiver_inbox(self, actor: Actor, data: Record) -> Record:
        validate_contract("ReceiverPackageQuery", data)
        service_id = self._service(actor)
        cursor = data.get("cursor")
        if cursor is not None:
            try:
                if str(UUID(str(cursor))) != cursor:
                    raise ValueError("noncanonical")
            except ValueError as error:
                raise ManualError("receiver.invalid_cursor", 400) from error
        limit = cast(int, data.get("limit", 50))
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT dispatch_id FROM receiver.package WHERE recipient_service_id=%s "
                "AND dispatch_id>%s ORDER BY dispatch_id LIMIT %s",
                (service_id, cursor or "00000000-0000-0000-0000-000000000000", limit + 1),
            ).fetchall()
        self._service(actor)
        ids = [str(row["dispatch_id"]) for row in rows[:limit]]
        return {"dispatch_ids": ids, "next_cursor": ids[-1] if len(rows) > limit else None}

    def receiver_detail(self, actor: Actor, dispatch_id: str) -> Record:
        service_id = self._service(actor)
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM receiver.package WHERE recipient_service_id=%s AND dispatch_id=%s",
                (service_id, dispatch_id),
            ).fetchone()
            if row is None:
                raise ManualError("receiver.not_found", 404)
            payload = cast(Record, json.loads(self.cipher.decrypt(text(row, "payload_ciphertext"))))
            result: Record = {
                "payload": payload,
                "revision": str(row["revision"]),
                "receipt": row["receipt"],
            }
        self._service(actor)
        return result

    def receiver_package(self, actor: Actor, dispatch_id: str) -> Record:
        return cast(Record, self.receiver_detail(actor, dispatch_id)["payload"])

    def receiver_decide(self, actor: Actor, key: str, data: Record) -> Record:
        validate_contract("ReceiverDecision", data)
        service_id = self._service(actor)
        request_digest = digest(data)
        with self.connection() as connection:
            # The package row also protects the absence of this command key.
            row = connection.execute(
                "SELECT * FROM receiver.package WHERE recipient_service_id=%s "
                "AND dispatch_id=%s FOR UPDATE",
                (service_id, data["dispatch_id"]),
            ).fetchone()
            if row is None:
                raise ManualError("receiver.not_found", 404)
            old = connection.execute(
                "SELECT * FROM receiver.decision WHERE operation_id=%s", (key,)
            ).fetchone()
            if old:
                if (
                    old["request_digest"] != request_digest
                    or str(old["recipient_service_id"]) != service_id
                    or str(old["principal_id"]) != actor.account_id
                ):
                    raise ManualError("receiver.idempotency_conflict", 409)
                self._service(actor)
                return cast(Record, old["receipt"])
            if (
                str(row["revision"]) != data["expected_revision"]
                or row["payload_digest"] != data["payload_digest"]
            ):
                raise ManualError("receiver.stale_revision", 409)
            payload = cast(Record, json.loads(self.cipher.decrypt(text(row, "payload_ciphertext"))))
            fields = {
                cast(Record, field)["field"] for field in cast(list[object], payload["fields"])
            }
            accepted = set(cast(list[str], data["accepted_fields"]))
            decision = data["decision"]
            if (
                not accepted.issubset(fields)
                or decision == "accept"
                and accepted != fields
                or decision == "partial"
                and not (set() < accepted < fields)
                or decision in {"reject", "clarify"}
                and accepted
            ):
                raise ManualError("receiver.decision_fields_invalid", 422)
            status = {
                "accept": "accepted",
                "partial": "partial",
                "reject": "rejected",
                "clarify": "clarification_requested",
            }[cast(str, decision)]
            receipt = self._receipt(
                service_id, text(data, "dispatch_id"), text(data, "payload_digest"), status
            )
            receipt["accepted_fields"] = sorted(accepted)
            self._service(actor)
            connection.execute(
                "UPDATE receiver.package SET receipt=%s,revision=revision+1 "
                "WHERE recipient_service_id=%s AND dispatch_id=%s",
                (Jsonb(receipt), service_id, data["dispatch_id"]),
            )
            connection.execute(
                "INSERT INTO receiver.decision VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (
                    key,
                    actor.account_id,
                    service_id,
                    data["dispatch_id"],
                    request_digest,
                    Jsonb(receipt),
                    self.clock(),
                ),
            )
            self._service(actor)
        self._service(actor)
        return receipt
