"""Explicit in-memory identity fixture; never used by deployment composition."""

import copy
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from care_link_identity import Custody, IdentityService, Principal, ReceiptSigner, Transaction
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class MemoryStore:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], dict[str, object]] = {}
        self.lock = threading.RLock()

    def get(self, kind: str, key: str) -> dict[str, object] | None:
        value = self.records.get((kind, key))
        return copy.deepcopy(value) if value is not None else None

    def put(self, kind: str, key: str, value: dict[str, object]) -> None:
        self.records[(kind, key)] = copy.deepcopy(value)

    def delete(self, kind: str, key: str) -> None:
        self.records.pop((kind, key), None)

    def items(self, kind: str) -> Iterator[tuple[str, dict[str, object]]]:
        for (record_kind, key), value in list(self.records.items()):
            if record_kind == kind:
                yield key, copy.deepcopy(value)

    @contextmanager
    def transaction(self) -> Iterator[Transaction]:
        with self.lock:
            old = copy.deepcopy(self.records)
            try:
                yield self
            except BaseException:
                self.records = old
                raise


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class FakeProvider:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.subject = "provider-subject"
        self.mfa = True
        self.is_active = True
        self.exchanges = 0
        self.active_checks = 0
        self.exchange_error: Exception | None = None
        self.on_active = lambda: None
        self.nonce = ""

    def authorization_url(self, state: str, nonce: str, verifier: str, fresh: bool) -> str:
        self.nonce = nonce
        return f"https://issuer.test/authorize?state={state}"

    def exchange(self, code: str, verifier: str, nonce: str, fresh: bool) -> Principal:
        self.exchanges += 1
        if self.exchange_error:
            raise self.exchange_error
        return Principal(
            self.subject,
            self.clock(),
            self.mfa,
            ("pwd", "otp"),
            "server-only-access-token",
            self.clock() + timedelta(hours=1),
        )

    def active(self, access_token: str, subject: str) -> bool:
        self.active_checks += 1
        self.on_active()
        return self.is_active

    def revoke(self, access_token: str) -> None:
        self.is_active = False


@pytest.fixture
def identity():
    clock, store = Clock(), MemoryStore()
    provider = FakeProvider(clock)
    key = Ed25519PrivateKey.generate()
    service = IdentityService(
        store,
        provider,
        Custody(Fernet.generate_key()),
        ReceiptSigner(key, "test-identity-key"),
        "https://issuer.test",
        "https://app.test",
        clock,
    )
    service.provision(provider.subject, str(uuid4()), ["pid", "worker"])
    return service, store, provider, clock, key


def signed_in(service: IdentityService, role: str = "pid", binding: str = "test-binding") -> str:
    _intent, state = service.login_start(role, binding)
    _view, raw, _proof = service.callback(state, "one-code", binding)
    assert raw is not None
    return raw
