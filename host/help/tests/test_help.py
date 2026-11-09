"""Behavioral help evidence; signed fake authority is not live identity proof."""

import base64
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import cast
from uuid import uuid4

import pytest
from care_link_help import (
    BrowserContext,
    HelpConfig,
    HelpError,
    HelpService,
    SignedReceipts,
    Spool,
    create_app,
)
from care_link_help.model import Action, Wire, canonical, digest, timestamp
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 8, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


class SignedAuthority:
    def __init__(self, clock: Clock) -> None:
        self.key = Ed25519PrivateKey.generate()
        self.clock = clock
        self.principal = str(uuid4())
        self.calls = 0
        self.unavailable = False
        self.last: Wire = {}

    def authorize(self, request: Wire) -> Wire:
        self.calls += 1
        if self.unavailable:
            raise HelpError("help.identity_unavailable", 503)
        receipt: Wire = {
            "operation_id": request["operation_id"],
            "help_id": request["help_id"],
            "request_digest": request["request_digest"],
            "principal_id": self.principal,
            "action": request["action"],
            "decision": "PERMIT",
            "identity_revision": "1",
            "role_revision": "1",
            "one_use_nonce": request["nonce"],
            "issued_at": timestamp(self.clock()),
            "expires_at": request["deadline"],
            "issuer_id": "care-link-identity",
            "audience": "care-link-help",
            "key_id": "test-1",
        }
        receipt["signature"] = (
            base64.urlsafe_b64encode(self.key.sign(canonical(receipt))).rstrip(b"=").decode()
        )
        self.last = receipt
        return receipt


class Harness:
    def __init__(self, tmp_path: Path) -> None:
        tmp_path.chmod(0o700)
        self.clock = Clock()
        self.authority = SignedAuthority(self.clock)
        self.owner = BrowserContext(self.authority.principal, "pid", "csrf")
        self.spool = Spool(tmp_path / "help.sqlite", clock=self.clock)
        self.verifier = SignedReceipts(
            {"test-1": self.authority.key.public_key()}, clock=self.clock
        )
        self.service = HelpService(self.spool, self.authority, self.verifier, clock=self.clock)

    def execute(
        self,
        action: Action,
        context: BrowserContext,
        *,
        target: str | None = None,
        revision: str = "1",
        key: str | None = None,
    ) -> Wire:
        self.authority.principal = context.account_id
        return self.service.execute(
            action=action,
            operation_id=key or str(uuid4()),
            help_id=target,
            body={"locale": "en-CA", "jurisdiction": None}
            if action == "create"
            else {}
            if action == "status"
            else {"expected_revision": revision},
            context=context,
            proof_ref=str(uuid4()),
        )


def test_accept_is_unconnected_and_retry_projects_current_state(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    key = str(uuid4())
    initial = h.execute("create", h.owner, key=key)
    worker = BrowserContext(str(uuid4()), "worker", "csrf")
    accepted = h.execute("accept", worker, target=cast(str, initial["id"]))
    assert accepted["state"] == "accepted_unconnected"
    assert accepted["connection_confirmed"] is False
    assert h.execute("create", h.owner, key=key) == accepted
    assert h.authority.calls == 3
    with sqlite3.connect(h.spool.path) as connection:
        assert connection.execute("SELECT count(*) FROM request").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM local_event").fetchone() == (3,)
        assert connection.execute("SELECT count(*) FROM decision_nonce").fetchone() == (3,)
        names = [row[1] for row in connection.execute("PRAGMA table_info(request)")]
        assert not {"story", "transcript", "phone", "plan", "pid"} & set(names)
    assert h.spool.path.stat().st_mode & 0o077 == 0


def test_owner_and_role_predicates_deny_direct_access(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    target = cast(str, h.execute("create", h.owner)["id"])
    cases: list[tuple[Action, BrowserContext]] = [
        ("status", BrowserContext(str(uuid4()), "pid", "csrf")),
        ("accept", h.owner),
        ("accept", BrowserContext(h.owner.account_id, "worker", "csrf")),
        ("cancel", BrowserContext(str(uuid4()), "worker", "csrf")),
    ]
    for action, context in cases:
        with pytest.raises(HelpError):
            h.execute(action, context, target=target)
    assert h.execute("status", h.owner, target=target)["revision"] == "1"


def test_racing_accepts_commit_exactly_one_owner(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    target = cast(str, h.execute("create", h.owner)["id"])
    prepared = []
    for _ in range(2):
        context = BrowserContext(str(uuid4()), "worker", "csrf")
        h.authority.principal = context.account_id
        request: Wire = {
            "operation_id": str(uuid4()),
            "help_id": target,
            "action": "accept",
            "request_digest": digest({"expected_revision": "1"}),
            "browser_proof_ref": str(uuid4()),
            "nonce": str(uuid4()),
            "deadline": timestamp(h.clock() + timedelta(seconds=1)),
        }
        receipt = h.authority.authorize(request)
        prepared.append((context, request, h.verifier.verify(request, receipt, context.account_id)))

    def accept(index: int) -> bool:
        context, request, decision = prepared[index]
        try:
            h.spool.apply(
                action="accept",
                help_id=target,
                operation_id=cast(str, request["operation_id"]),
                body_digest=cast(str, request["request_digest"]),
                context=context,
                decision=decision,
                expected_revision="1",
            )
            return True
        except HelpError as error:
            assert error.code == "help.revision_conflict"
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(accept, [0, 1])) == [False, True]
    with sqlite3.connect(h.spool.path) as connection:
        assert connection.execute("SELECT status,revision FROM request").fetchone() == (
            "accepted_unconnected",
            2,
        )
        assert connection.execute("SELECT count(*) FROM local_event").fetchone() == (2,)
        assert connection.execute("SELECT count(*) FROM decision_nonce").fetchone() == (2,)


def test_outage_never_uses_old_positive_receipt(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    initial = h.execute("create", h.owner)
    h.authority.unavailable = True
    with pytest.raises(HelpError, match="identity_unavailable"):
        h.execute("status", h.owner, target=cast(str, initial["id"]))
    with sqlite3.connect(h.spool.path) as connection:
        assert connection.execute("SELECT count(*) FROM local_event").fetchone() == (1,)


def test_consumed_nonce_and_expired_spool_commit_have_no_effect(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    target = cast(str, h.execute("create", h.owner)["id"])
    request: Wire = {
        "operation_id": str(uuid4()),
        "help_id": target,
        "action": "cancel",
        "request_digest": digest({"expected_revision": "1"}),
        "browser_proof_ref": str(uuid4()),
        "nonce": str(uuid4()),
        "deadline": timestamp(h.clock() + timedelta(seconds=1)),
    }
    decision = h.verifier.verify(request, h.authority.authorize(request), h.owner.account_id)
    arguments = dict(
        action="cancel",
        help_id=target,
        operation_id=cast(str, request["operation_id"]),
        body_digest=cast(str, request["request_digest"]),
        context=h.owner,
        decision=decision,
        expected_revision="1",
    )
    h.spool.apply(**arguments)
    with pytest.raises(HelpError, match="replayed_decision"):
        h.spool.apply(**arguments)
    h.clock.now += timedelta(seconds=1)
    with pytest.raises(HelpError, match="authority_expired"):
        h.spool.apply(**arguments)
    with sqlite3.connect(h.spool.path) as connection:
        assert connection.execute("SELECT status,revision FROM request").fetchone() == (
            "cancelled",
            2,
        )
        assert connection.execute("SELECT count(*) FROM local_event").fetchone() == (2,)


def test_receipt_signature_expiry_and_exact_binding(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    initial = h.execute("create", h.owner)
    receipt = h.authority.last
    request: Wire = {
        "operation_id": receipt["operation_id"],
        "help_id": initial["id"],
        "request_digest": receipt["request_digest"],
        "action": "create",
        "nonce": receipt["one_use_nonce"],
        "browser_proof_ref": str(uuid4()),
        "deadline": receipt["expires_at"],
    }
    assert h.verifier.verify(request, receipt, h.owner.account_id)
    for field, value in [
        ("principal_id", str(uuid4())),
        ("audience", "other"),
        ("signature", "invalid"),
        ("request_digest", "0" * 64),
    ]:
        with pytest.raises(HelpError):
            h.verifier.verify(request, receipt | {field: value}, h.owner.account_id)
    with pytest.raises(HelpError):
        h.verifier.verify(request | {"nonce": str(uuid4())}, receipt, h.owner.account_id)
    h.clock.now += timedelta(seconds=1)
    with pytest.raises(HelpError):
        h.verifier.verify(request, receipt, h.owner.account_id)


def test_http_session_csrf_and_closed_opaque_body(tmp_path: Path) -> None:
    h = Harness(tmp_path)

    class Sessions:
        def context(self, cookie: str) -> BrowserContext:
            if cookie != "secret-cookie":
                raise HelpError("help.login_required", 401)
            return h.owner

        def proof(self, cookie: str, origin: str) -> str:
            assert cookie == "secret-cookie" and origin == "https://help.test"
            return str(uuid4())

    with TestClient(
        create_app(HelpConfig("https://help.test"), h.service, Sessions()),
        base_url="https://help.test",
    ) as client:
        headers = {
            "Origin": "https://help.test",
            "X-CSRF-Token": "csrf",
            "Idempotency-Key": str(uuid4()),
        }
        assert client.post("/help/v1/requests", json={}, headers=headers).status_code == 401
        client.cookies.set("__Host-care_link_help", "secret-cookie")
        assert (
            client.post(
                "/help/v1/create-intent",
                json={"locale": "en-CA", "jurisdiction": None},
                headers={"Origin": "https://evil.test", "X-CSRF-Token": "csrf"},
            ).status_code
            == 403
        )
        intent = client.post(
            "/help/v1/create-intent",
            json={"locale": "en-CA", "jurisdiction": None},
            headers={"Origin": "https://help.test", "X-CSRF-Token": "csrf"},
        )
        assert intent.status_code == 200
        assert set(intent.json()) == {"operation_id"}
        assert (
            client.post(
                "/help/v1/requests", json={}, headers=headers | {"Origin": "https://evil.test"}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/help/v1/requests",
                json={"locale": "en-CA", "jurisdiction": None, "story": "private"},
                headers=headers,
            ).status_code
            == 400
        )
        response = client.post(
            "/help/v1/requests", json={"locale": "en-CA", "jurisdiction": None}, headers=headers
        )
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        h.authority.unavailable = True
        response = client.get("/help/v1/requests/" + response.json()["id"])
        assert response.status_code == 503
        assert response.json()["static_url"] == "/static/"
    with TestClient(create_app(HelpConfig("https://help.test"))) as client:
        assert client.post("/help/v1/requests").status_code == 503


def test_create_intent_survives_restart_reauthentication_and_unknown_create(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    body: Wire = {"locale": "en-CA", "jurisdiction": None}
    first = h.service.prepare_create(body, h.owner, lambda: str(uuid4()))
    key = cast(str, first["operation_id"])
    created = h.execute("create", h.owner, key=key)  # Drop this successful response.
    new_context = BrowserContext(h.owner.account_id, "pid", "rotated-csrf")
    restarted = HelpService(
        Spool(h.spool.path, clock=h.clock), h.authority, h.verifier, clock=h.clock
    )
    recovered = restarted.prepare_create(body, new_context, lambda: str(uuid4()))
    assert recovered == first
    assert (
        restarted.execute(
            action="create",
            operation_id=key,
            help_id=None,
            body=body,
            context=new_context,
            proof_ref=str(uuid4()),
        )
        == created
    )
    with sqlite3.connect(h.spool.path) as connection:
        assert connection.execute("SELECT count(*) FROM create_intent").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM request").fetchone() == (1,)
    with pytest.raises(HelpError, match="intent_body_conflict"):
        restarted.prepare_create(body | {"locale": "fr-CA"}, new_context, lambda: str(uuid4()))
    h.execute("cancel", h.owner, target=cast(str, created["id"]))
    after_cancel = restarted.prepare_create(
        body | {"locale": "fr-CA"}, new_context, lambda: str(uuid4())
    )
    assert after_cancel["operation_id"] != key


def test_concurrent_prepare_reauthorizes_one_stable_winner(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    barrier = Barrier(2)

    class ConcurrentAuthority:
        def authorize(self, request: Wire) -> Wire:
            receipt = h.authority.authorize(request)
            if h.authority.calls <= 2:
                barrier.wait(timeout=5)
            return receipt

    service = HelpService(h.spool, ConcurrentAuthority(), h.verifier, clock=h.clock)

    def prepare(_index: int) -> Wire:
        return service.prepare_create(
            {"locale": "en-CA", "jurisdiction": None}, h.owner, lambda: str(uuid4())
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(prepare, [0, 1]))
    assert results[0] == results[1]
    assert h.authority.calls == 3  # Loser acquires fresh authority for winner's target.
    with sqlite3.connect(h.spool.path) as connection:
        assert connection.execute("SELECT count(*) FROM create_intent").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM decision_nonce").fetchone() == (2,)
        assert connection.execute("SELECT count(*) FROM local_event").fetchone() == (2,)
        assert connection.execute("SELECT count(*) FROM request").fetchone() == (0,)


def test_prepare_without_authority_has_no_private_intent_effect(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    h.authority.unavailable = True
    with pytest.raises(HelpError, match="identity_unavailable"):
        h.service.prepare_create(
            {"locale": "en-CA", "jurisdiction": None}, h.owner, lambda: str(uuid4())
        )
    with sqlite3.connect(h.spool.path) as connection:
        assert connection.execute("SELECT count(*) FROM create_intent").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM decision_nonce").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM local_event").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM request").fetchone() == (0,)
