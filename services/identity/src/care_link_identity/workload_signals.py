"""Authenticated workload restrictions reconcile durable identity and host custody.

No cross-store atomicity is claimed: identity persists pending intent first, host
fence fsync precedes accepted sequence acknowledgement, and retries reconcile by
stable command identity. This module never grants or releases workload rights.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Protocol, cast
from uuid import UUID

from .crypto import canonical, digest
from .domain import IdentityError, Store, stamp, text


class SourceConflict(IdentityError):
    def __init__(self) -> None:
        super().__init__("identity.signed_source_conflict")


class FenceSnapshot(Protocol):
    @property
    def generation(self) -> int: ...


class FenceReceipt(Protocol):
    @property
    def command_id(self) -> str: ...
    @property
    def peer(self) -> str: ...
    @property
    def generation(self) -> int: ...
    @property
    def durable(self) -> bool: ...


class RestrictiveFence(Protocol):
    def current(self) -> FenceSnapshot: ...
    def restrict(self, peer: str, command_id: str, expected_generation: int) -> FenceReceipt: ...
    def receipt(self, command_id: str) -> FenceReceipt | None: ...


@dataclass(frozen=True)
class WorkloadBindings:
    """Release-configured immutable map; issuer claims cannot create mappings."""

    issuer_id: str
    subjects: Mapping[str, str]

    def __post_init__(self) -> None:
        if not self.issuer_id or not 1 <= len(self.subjects) <= 64:
            raise ValueError("bounded trusted workload bindings required")
        copied = dict(self.subjects)
        for subject, peer in copied.items():
            if (
                str(UUID(subject)) != subject
                or re.fullmatch(
                    r"spiffe://care-link\.demo/[a-z][a-z0-9_-]{0,31}/[a-z][a-z0-9_-]{0,63}", peer
                )
                is None
            ):
                raise ValueError("canonical workload UUID and exact demo SPIFFE identity required")
        if len(set(copied.values())) != len(copied):
            raise ValueError("one immutable workload UUID per SPIFFE identity required")
        object.__setattr__(self, "subjects", MappingProxyType(copied))


class WorkloadSignals:
    def __init__(self, store: Store, bindings: WorkloadBindings, fences: RestrictiveFence) -> None:
        self.store, self.bindings, self.fences = store, bindings, fences
        self.mapping_digest = digest(canonical(dict(bindings.subjects)).decode())

    def submit(
        self, signal: dict[str, object], now: datetime, age_seconds: float
    ) -> dict[str, object]:
        subject, issuer = text(signal, "subject_id"), text(signal, "issuer_id")
        peer = self.bindings.subjects.get(subject)
        if issuer != self.bindings.issuer_id or peer is None:
            raise IdentityError("identity.workload_mapping_denied")
        key = digest(issuer + "\0" + text(signal, "jti"))
        head_key = digest(issuer + "\0" + subject)
        operation_key = "workload:" + key
        with self.store.transaction() as tx:
            head = tx.get("head", head_key) or {"sequence": "0", "digest": "0" * 64}
            prior = tx.get("signal", key)
            quarantined = False
            if prior and prior["digest"] != signal["digest"]:
                raise SourceConflict()
            elif prior and prior.get("state") in {"applied", "gap_blocked", "quarantined"}:
                return {
                    "jti": signal["jti"],
                    "state": "duplicate",
                    "accepted_sequence": head["sequence"],
                }
            operation = tx.get("operation", operation_key)
            if operation is None:
                outcome = "applied"
                if quarantined or (tx.get("issuer", issuer) or {}).get("quarantined") is True:
                    outcome = "quarantined"
                elif not -5 <= age_seconds <= 60 or (
                    int(text(signal, "source_sequence")) != int(text(head, "sequence")) + 1
                    or signal["previous_digest"] != head["digest"]
                ):
                    outcome = "gap_blocked"
                targets = (
                    sorted(set(self.bindings.subjects.values()))
                    if outcome == "quarantined"
                    else [peer]
                )
                operation = {
                    "action": "workload_restrict",
                    "state": "pending",
                    "outcome": outcome,
                    "signal_key": key,
                    "jti": signal["jti"],
                    "digest": signal["digest"],
                    "subject_id": subject,
                    "issuer": issuer,
                    "head_key": head_key,
                    "source_sequence": signal["source_sequence"],
                    "previous_digest": signal["previous_digest"],
                    "expected_sequence": head["sequence"],
                    "expected_digest": head["digest"],
                    "event_at": signal["event_at"],
                    "received_at": stamp(now),
                    "targets": targets,
                    "mapping_digest": self.mapping_digest,
                }
                tx.put("operation", operation_key, operation)
                tx.put(
                    "workload_state",
                    head_key,
                    {
                        "subject_id": subject,
                        "peer": peer,
                        "blocked": True,
                        "recovery_required": outcome != "applied",
                        "operation_key": operation_key,
                    },
                )
                if not quarantined:
                    tx.put(
                        "signal",
                        key,
                        {
                            "digest": signal["digest"],
                            "state": "pending",
                            "event_type": "workload_compromised",
                            "operation_key": operation_key,
                        },
                    )
        return self.reconcile(operation_key)

    def quarantine_source(self, signal: dict[str, object], now: datetime) -> dict[str, object]:
        if signal.get("issuer_id") != self.bindings.issuer_id:
            raise IdentityError("identity.workload_source_denied")
        operation_key = "workload-source:" + digest(self.bindings.issuer_id + self.mapping_digest)
        subject = text(signal, "subject_id")
        head_key = digest(self.bindings.issuer_id + "\0" + subject)
        with self.store.transaction() as tx:
            operation = tx.get("operation", operation_key)
            head = tx.get("head", head_key) or {"sequence": "0", "digest": "0" * 64}
            if operation is None:
                operation = {
                    "action": "workload_restrict",
                    "state": "pending",
                    "outcome": "quarantined",
                    "signal_key": digest(self.bindings.issuer_id + "\0" + text(signal, "jti")),
                    "jti": signal["jti"],
                    "digest": signal["digest"],
                    "subject_id": subject,
                    "issuer": self.bindings.issuer_id,
                    "head_key": head_key,
                    "source_sequence": signal["source_sequence"],
                    "previous_digest": signal["previous_digest"],
                    "expected_sequence": head["sequence"],
                    "expected_digest": head["digest"],
                    "event_at": signal["event_at"],
                    "received_at": stamp(now),
                    "targets": sorted(self.bindings.subjects.values()),
                    "mapping_digest": self.mapping_digest,
                }
                tx.put("operation", operation_key, operation)
            for mapped_subject, peer in self.bindings.subjects.items():
                tx.put(
                    "workload_state",
                    digest(self.bindings.issuer_id + "\0" + mapped_subject),
                    {
                        "subject_id": mapped_subject,
                        "peer": peer,
                        "blocked": True,
                        "recovery_required": True,
                        "operation_key": operation_key,
                    },
                )
        self.reconcile(operation_key)
        with self.store.transaction() as tx:
            head = tx.get("head", head_key) or {"sequence": "0"}
        return {"jti": signal["jti"], "state": "quarantined", "accepted_sequence": head["sequence"]}

    def reconcile(self, operation_key: str) -> dict[str, object]:
        with self.store.transaction() as tx:
            operation = tx.get("operation", operation_key)
            if operation is None or operation.get("action") != "workload_restrict":
                raise IdentityError("identity.workload_operation_denied")
            if operation.get("mapping_digest") != self.mapping_digest:
                raise IdentityError("identity.workload_mapping_changed", 503)
            if operation.get("state") == "completed":
                head = tx.get("head", text(operation, "head_key")) or {"sequence": "0"}
                return {
                    "jti": operation["jti"],
                    "state": operation["outcome"],
                    "accepted_sequence": head["sequence"],
                }
            targets = cast(list[str], operation["targets"])
        receipts: list[dict[str, object]] = []
        for peer in targets:
            command_id = digest(operation_key + "\0" + peer)
            try:
                receipt = self.fences.receipt(command_id)
                if receipt is None:
                    current = self.fences.current()
                    receipt = self.fences.restrict(peer, command_id, current.generation)
                if (
                    not receipt.durable
                    or receipt.command_id != command_id
                    or receipt.peer != peer
                    or receipt.generation < 1
                ):
                    raise IdentityError("identity.workload_fence_uncertain", 503)
                receipts.append(
                    {"peer": peer, "command_id": command_id, "generation": receipt.generation}
                )
            except (OSError, TimeoutError, ValueError) as error:
                # The pending DB intent survives a lost fsync ACK. No SignalAck
                # is returned until query/retry establishes the durable command.
                raise IdentityError("identity.workload_fence_pending", 503) from error
        with self.store.transaction() as tx:
            latest = tx.get("operation", operation_key)
            if latest is None or latest.get("digest") != operation["digest"]:
                raise IdentityError("identity.workload_operation_changed", 503)
            head_key = text(operation, "head_key")
            head = tx.get("head", head_key) or {"sequence": "0", "digest": "0" * 64}
            if latest.get("state") != "completed":
                if operation["outcome"] == "applied":
                    if (
                        head["sequence"] != operation["expected_sequence"]
                        or head["digest"] != operation["expected_digest"]
                    ):
                        # A competing accepted restriction can only turn this
                        # receipt into a recovery gap, never rewind the head.
                        latest["outcome"] = "gap_blocked"
                    else:
                        head = {
                            "sequence": operation["source_sequence"],
                            "digest": operation["digest"],
                            "event_at": operation["event_at"],
                            "received_at": operation["received_at"],
                        }
                        tx.put("head", head_key, head)
                latest.update({"state": "completed", "fence_receipts": receipts})
                tx.put("operation", operation_key, latest)
                signal = tx.get("signal", text(operation, "signal_key"))
                if signal and signal.get("digest") == operation["digest"]:
                    signal["state"] = latest["outcome"]
                    tx.put("signal", text(operation, "signal_key"), signal)
            return {
                "jti": operation["jti"],
                "state": latest["outcome"],
                "accepted_sequence": head["sequence"],
            }
