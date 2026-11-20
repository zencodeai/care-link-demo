"""Semantic differential and guarded scan-cost checks for scheduled disposal."""

import copy
from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest
from care_link_identity import Custody, RetentionService
from care_link_identity.credential_disposal import (
    fence_session_material,
    locally_restricted,
    maintenance_restricted,
)
from care_link_identity.credential_sweep import _SweepTransaction
from care_link_identity.crypto import digest
from care_link_identity.domain import instant, stamp
from cryptography.fernet import Fernet

from services.identity.tests.conftest import MemoryStore


def legacy_sweep(store, now):
    """Frozen previous algorithm: an oracle for the changed batching strategy."""
    cleared = 0
    with store.transaction() as tx:
        for key, row in tx.items("session"):
            if locally_restricted(tx, row, now):
                if row.get("access_token") or row.get("revoked") is not True:
                    row.update({"access_token": "", "revoked": True})
                    tx.put("session", key, row)
                    cleared += 1
                fence_session_material(tx, key)
        for key, row in tx.items("intent"):
            if "expires_at" not in row:
                continue
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
                    tx.put("intent", key, row)
                    cleared += 1
                continue
            if instant(row["expires_at"]) <= now or row.get("state") in {
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
                    tx.put("intent", key, row)
                    cleared += 1
        for key, row in tx.items("proof"):
            if row.get("consumed") is True or instant(row["expires_at"]) <= now:
                tx.delete("proof", key)
                cleared += 1
    return cleared


class CountedStore(MemoryStore):
    def __init__(self):
        super().__init__()
        self.calls = Counter()

    def get(self, kind, key):
        self.calls["get:" + kind] += 1
        return super().get(kind, key)

    def items(self, kind):
        self.calls["items:" + kind] += 1
        return super().items(kind)

    def put(self, kind, key, value):
        self.calls["put:" + kind] += 1
        return super().put(kind, key, value)

    def delete(self, kind, key):
        self.calls["delete:" + kind] += 1
        return super().delete(kind, key)


def records(now):
    account = {
        "account_id": "account",
        "subject": "provider-subject",
        "enabled": True,
        "roles": ["pid", "worker", "operator"],
        "revision": "1",
        "role_revision": "1",
        "access_review_due_at": stamp(now + timedelta(days=1)),
    }
    session = {
        "account_id": "account",
        "subject": "provider-subject",
        "role": "pid",
        "mfa": True,
        "revision": "1",
        "role_revision": "1",
        "last_seen": stamp(now),
        "expires_at": stamp(now + timedelta(hours=1)),
        "revoked": False,
        "access_token": "encrypted-fixture-token",
        "csrf": "reauthentication-metadata",
    }
    intent = {
        "state": "pending",
        "verifier": "private-fixture-verifier",
        "nonce": "fixture-nonce",
        "access_token": "encrypted-fixture-token",
        "expires_at": stamp(now + timedelta(minutes=1)),
    }
    owner = {
        **intent,
        "purpose": "owner_access_review",
        "account_id": "account",
        "revision": "1",
        "role_revision": "1",
    }
    result = {
        ("account", digest("https://issuer.test\0provider-subject")): account,
        ("session", "active"): session,
        ("session", "revoked"): {**session, "revoked": True, "access_token": ""},
        ("session", "expired"): {**session, "expires_at": stamp(now)},
        ("session", "idle"): {
            **session,
            "role": "worker",
            "last_seen": stamp(now - timedelta(seconds=900)),
        },
        ("session", "malformed"): {"revoked": False, "expires_at": None},
        ("intent", "dependent"): {**intent, "session_hash": "revoked"},
        ("intent", "active"): {**intent, "session_hash": "active"},
        ("intent", "expired"): {**intent, "expires_at": stamp(now)},
        ("intent", "complete"): {**intent, "state": "completed"},
        ("intent", "uncertain"): {**intent, "state": "uncertain"},
        ("intent", "index"): {"reference": "actual-intent"},
        ("intent", "malformed-dependent"): {**intent, "session_hash": []},
        ("intent", "owner"): owner,
        ("intent", "owner-expired"): {**owner, "expires_at": stamp(now)},
        ("intent", "owner-consumed"): {**owner, "review_consumed": True},
        ("intent", "owner-dependent"): {**owner, "session_hash": "expired"},
        ("proof", "dependent"): {
            "session_hash": "revoked",
            "expires_at": stamp(now + timedelta(minutes=1)),
        },
        ("proof", "active"): {
            "session_hash": "active",
            "expires_at": stamp(now + timedelta(minutes=1)),
        },
        ("proof", "expired"): {"expires_at": stamp(now)},
        ("proof", "consumed"): {"consumed": True, "expires_at": stamp(now + timedelta(minutes=1))},
        ("proof", "malformed-dependent"): {
            "session_hash": [],
            "expires_at": stamp(now + timedelta(minutes=1)),
        },
        ("ceremony", "dependent"): {"session_hash": "revoked", "state": "verified"},
        ("ceremony", "active"): {"session_hash": "active", "state": "pending"},
        ("ceremony", "malformed-dependent"): {"session_hash": [], "state": "pending"},
        ("signal", "negative-source-head"): {"state": "applied", "sequence": "1"},
    }
    return result


def retention(store, now):
    return RetentionService(store, Custody(Fernet.generate_key()), None, clock=lambda: now)


@pytest.mark.parametrize(
    "restriction",
    [
        "none",
        "disabled",
        "blocked",
        "marker",
        "revision",
        "role_revision",
        "role_removed",
        "review_due",
        "issuer_quarantined",
        "foreign_issuer",
        "duplicate_account",
    ],
)
def test_batched_sweep_preserves_legacy_disposal_state_and_counter(restriction):
    now = datetime(2026, 11, 16, tzinfo=UTC)
    snapshot = records(now)
    account_key = next(key for key in snapshot if key[0] == "account")
    account = snapshot[account_key]
    if restriction == "disabled":
        account["enabled"] = False
    elif restriction == "blocked":
        account["blocked"] = True
    elif restriction == "marker":
        snapshot[("account_marker", "account")] = {"blocked": True}
    elif restriction in {"revision", "role_revision"}:
        account[restriction] = "2"
    elif restriction == "role_removed":
        account["roles"] = []
    elif restriction == "review_due":
        account["access_review_due_at"] = stamp(now)
    elif restriction == "issuer_quarantined":
        snapshot[("issuer", "https://issuer.test")] = {"quarantined": True}
    elif restriction == "foreign_issuer":
        snapshot[("issuer", "https://unrelated.test")] = {"quarantined": True}
    elif restriction == "duplicate_account":
        snapshot[("account", "duplicate")] = copy.deepcopy(account)
    old, new = CountedStore(), CountedStore()
    old.records, new.records = copy.deepcopy(snapshot), copy.deepcopy(snapshot)
    assert retention(new, now).expire_credentials() == legacy_sweep(old, now)
    assert new.records == old.records
    assert (
        new.records[("signal", "negative-source-head")]
        == snapshot[("signal", "negative-source-head")]
    )
    assert new.records[("session", "revoked")]["csrf"] == "reauthentication-metadata"
    # A second sweep remains state-idempotent and preserves counter semantics.
    assert retention(new, now).expire_credentials() == legacy_sweep(old, now)
    assert new.records == old.records


def test_disposed_session_cost_is_constant_in_number_of_full_kind_scans():
    now = datetime(2026, 11, 16, tzinfo=UTC)
    old, new = CountedStore(), CountedStore()
    snapshot = {
        ("session", str(index)): {"revoked": True, "access_token": "", "expires_at": stamp(now)}
        for index in range(100)
    }
    old.records, new.records = copy.deepcopy(snapshot), copy.deepcopy(snapshot)
    assert legacy_sweep(old, now) == retention(new, now).expire_credentials() == 0
    assert sum(count for key, count in old.calls.items() if key.startswith("items:")) == 303
    assert {key: count for key, count in new.calls.items() if key.startswith("items:")} == {
        "items:session": 1,
        "items:intent": 1,
        "items:proof": 1,
        "items:ceremony": 1,
    }
    assert not any(key.startswith("put:") for key in new.calls)
    assert new.records == old.records


def test_next_transaction_observes_new_negative_and_new_material_on_disposed_session():
    now = datetime(2026, 11, 16, tzinfo=UTC)
    store = CountedStore()
    store.records = records(now)
    service = retention(store, now)
    service.expire_credentials()
    assert store.records[("session", "active")]["access_token"]
    with store.transaction() as tx:
        tx.put("account_marker", "account", {"blocked": True})
        tx.put(
            "intent",
            "late-dependent",
            {
                "session_hash": "revoked",
                "state": "pending",
                "verifier": "new-material",
                "nonce": "new-nonce",
                "access_token": "new-token",
                "expires_at": stamp(now + timedelta(minutes=1)),
            },
        )
        tx.put(
            "proof",
            "late-dependent",
            {
                "session_hash": "revoked",
                "expires_at": stamp(now + timedelta(minutes=1)),
            },
        )
        tx.put("ceremony", "late-dependent", {"session_hash": "revoked", "state": "pending"})
    service.expire_credentials()
    assert store.records[("session", "active")]["access_token"] == ""
    assert store.records[("intent", "late-dependent")]["verifier"] == ""
    assert ("proof", "late-dependent") not in store.records
    assert store.records[("ceremony", "late-dependent")]["state"] == "expired"


def test_transaction_view_returns_copies_and_reads_its_own_put_delete():
    source = CountedStore()
    source.put("account", "one", {"roles": ["pid"]})
    with source.transaction() as transaction:
        view = _SweepTransaction(transaction)
        rows = list(view.items("account"))
        rows[0][1]["roles"].append("operator")
        assert view.get("account", "one") == {"roles": ["pid"]}
        view.put("account", "one", {"roles": []})
        assert list(view.items("account")) == [("one", {"roles": []})]
        assert view.get("account", "one") == {"roles": []}
        view.delete("account", "one")
        assert view.get("account", "one") is None
        assert list(view.items("account")) == []
        view.put("account", "two", {"roles": []})
        assert view.get("account", "two") == {"roles": []}
    assert source.records == {("account", "two"): {"roles": []}}
