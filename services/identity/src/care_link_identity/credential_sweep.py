"""Linear restriction-only disposal within one already guarded transaction.

This view lives only for a single scheduled sweep. It is never used by request
identity verification and retains no authority or records across transactions.
"""

import copy
from collections.abc import Iterator
from datetime import datetime

from .credential_disposal import locally_restricted, maintenance_restricted
from .domain import Transaction, instant

Record = dict[str, object]


class _SweepTransaction:
    """Read own writes while avoiding repeated identical SQL under the guard."""

    def __init__(self, source: Transaction) -> None:
        self.source = source
        self.rows: dict[str, dict[str, Record]] = {}
        self.points: dict[tuple[str, str], Record | None] = {}

    def get(self, kind: str, key: str) -> Record | None:
        if kind in self.rows:
            return copy.deepcopy(self.rows[kind].get(key))
        identity = kind, key
        if identity not in self.points:
            self.points[identity] = copy.deepcopy(self.source.get(kind, key))
        return copy.deepcopy(self.points[identity])

    def items(self, kind: str) -> Iterator[tuple[str, Record]]:
        if kind not in self.rows:
            self.rows[kind] = {key: copy.deepcopy(row) for key, row in self.source.items(kind)}
        # Like the underlying store, enumeration is stable while rows are
        # updated/deleted, and callers must explicitly put their changes.
        for key, row in list(self.rows[kind].items()):
            yield key, copy.deepcopy(row)

    def put(self, kind: str, key: str, value: Record) -> None:
        self.source.put(kind, key, value)
        self.points[(kind, key)] = copy.deepcopy(value)
        if kind in self.rows:
            self.rows[kind][key] = copy.deepcopy(value)

    def delete(self, kind: str, key: str) -> None:
        self.source.delete(kind, key)
        self.points[(kind, key)] = None
        if kind in self.rows:
            self.rows[kind].pop(key, None)


def _restricted_dependency(row: Record, sessions: set[str]) -> bool:
    # The store is JSON-shaped; a malformed list/dict must compare unequal,
    # matching the former per-session equality predicate without a hash error.
    session_hash = row.get("session_hash")
    return isinstance(session_hash, str) and session_hash in sessions


def sweep_credentials(source: Transaction, now: datetime) -> int:
    """Apply the existing disposal predicates with at most one scan per kind.

    The caller holds its original store transaction/global guard throughout.
    Already revoked sessions remain in the restricted set so newly attached
    positive material is still fenced on every sweep.
    """
    tx = _SweepTransaction(source)
    cleared = 0
    restricted_sessions: set[str] = set()
    for key, row in tx.items("session"):
        if locally_restricted(tx, row, now):
            restricted_sessions.add(key)
            if row.get("access_token") or row.get("revoked") is not True:
                row.update({"access_token": "", "revoked": True})
                tx.put("session", key, row)
                cleared += 1

    for key, row in tx.items("intent"):
        original = copy.deepcopy(row)
        if _restricted_dependency(row, restricted_sessions) and (
            row.get("state") != "failed"
            or row.get("verifier")
            or row.get("nonce")
            or row.get("access_token")
        ):
            row.update({"state": "failed", "verifier": "", "nonce": "", "access_token": ""})
        if "expires_at" in row:
            if row.get("purpose") == "owner_access_review":
                restricted = maintenance_restricted(tx, row)
                if (
                    instant(row["expires_at"]) <= now
                    or row.get("review_consumed") is True
                    or row.get("state") in {"failed", "uncertain"}
                    or restricted
                ):
                    row.update({"verifier": "", "nonce": "", "access_token": ""})
                    if restricted:
                        row["state"] = "failed"
                    # Preserve the prior public counter, including an already
                    # empty matching owner-review row, without a no-op SQL put.
                    cleared += 1
            elif instant(row["expires_at"]) <= now or row.get("state") in {
                "completed",
                "failed",
                "uncertain",
            }:
                if row.get("verifier") or row.get("nonce"):
                    row.update(
                        {
                            "verifier": "",
                            "nonce": "",
                            "state": "failed" if row.get("state") == "pending" else row["state"],
                        }
                    )
                    cleared += 1
        if row != original:
            tx.put("intent", key, row)

    for key, row in tx.items("proof"):
        if _restricted_dependency(row, restricted_sessions):
            tx.delete("proof", key)
        elif row.get("consumed") is True or instant(row["expires_at"]) <= now:
            tx.delete("proof", key)
            cleared += 1

    for key, row in tx.items("ceremony"):
        if _restricted_dependency(row, restricted_sessions) and row.get("state") != "expired":
            row["state"] = "expired"
            tx.put("ceremony", key, row)
    return cleared
