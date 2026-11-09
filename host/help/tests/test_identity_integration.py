"""HTTP composition proof with fake provider/store/peer and real signed spool.

This proves adapter compatibility, not Keycloak/PostgreSQL/mTLS/CNI deployment.
"""

import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

import httpx
import pytest
from care_link_help import (
    HelpConfig,
    HelpService,
    HttpAuthority,
    HttpBrowserSessions,
    SignedReceipts,
    Spool,
)
from care_link_help import create_app as create_help_app
from care_link_identity import Custody, IdentityService, Principal, ReceiptSigner
from care_link_identity import create_app as create_identity_app
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

pytestmark = pytest.mark.contract


class MemoryTransaction:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], dict[str, object]] = {}

    def get(self, kind: str, key: str) -> dict[str, object] | None:
        return deepcopy(self.records.get((kind, key)))

    def put(self, kind: str, key: str, value: dict[str, object]) -> None:
        self.records[(kind, key)] = deepcopy(value)

    def delete(self, kind: str, key: str) -> None:
        self.records.pop((kind, key), None)

    def items(self, kind: str) -> Iterator[tuple[str, dict[str, object]]]:
        for (record_kind, key), value in list(self.records.items()):
            if record_kind == kind:
                yield key, deepcopy(value)


class MemoryStore:
    def __init__(self) -> None:
        self.tx = MemoryTransaction()

    @contextmanager
    def transaction(self) -> Iterator[MemoryTransaction]:
        before = deepcopy(self.tx.records)
        try:
            yield self.tx
        except Exception:
            self.tx.records = before
            raise


class FakeProvider:
    def __init__(self, now: datetime) -> None:
        self.now = now
        self.subject = "fictional-participant"
        self.server_credential = secrets.token_urlsafe(32)
        self.available = True

    def authorization_url(self, state: str, nonce: str, verifier: str, fresh: bool) -> str:
        return "https://provider.test/auth?" + urlencode({"state": state, "nonce": nonce})

    def exchange(self, code: str, verifier: str, nonce: str, fresh: bool) -> Principal:
        return Principal(
            self.subject,
            self.now,
            True,
            ("otp",),
            self.server_credential,
            self.now + timedelta(hours=1),
        )

    def active(self, access_token: str, subject: str) -> bool:
        return self.available and access_token == self.server_credential and subject == self.subject

    def revoke(self, access_token: str) -> None:
        self.available = False


def test_http_identity_proof_to_signed_spool_and_identity_loss(tmp_path: Path) -> None:
    now = datetime(2026, 11, 8, tzinfo=UTC)
    provider, key = FakeProvider(now), Ed25519PrivateKey.generate()
    identity = IdentityService(
        MemoryStore(),
        provider,
        Custody(Fernet.generate_key()),
        ReceiptSigner(key, "integration"),
        "https://provider.test",
        "https://help.test",
        clock=lambda: now,
    )
    identity.provision(provider.subject, str(uuid4()), ["pid"])
    _, state = identity.login_start("pid", "binding")
    _, raw_cookie, _ = identity.callback(state, "provider-code", "binding")
    assert raw_cookie
    app = create_identity_app(
        identity,
        workload_verifier=lambda _request, peer: peer == "help",
        session_cookie="__Host-care_link_help",
    )
    tmp_path.chmod(0o700)
    spool = Spool(tmp_path / "help.sqlite", clock=lambda: now)
    with TestClient(app, base_url="https://identity.test") as internal:

        def relay(request: httpx.Request) -> httpx.Response:
            return internal.request(
                request.method, request.url.path, content=request.content, headers=request.headers
            )

        with httpx.Client(transport=httpx.MockTransport(relay)) as workload:
            sessions = HttpBrowserSessions(workload, "https://identity.test", "https://help.test")
            authority = HttpAuthority(workload, "https://identity.test")
            verifier = SignedReceipts({"integration": key.public_key()}, clock=lambda: now)
            help_app = create_help_app(
                HelpConfig("https://help.test"),
                HelpService(spool, authority, verifier, clock=lambda: now),
                sessions,
            )
            with TestClient(help_app, base_url="https://help.test") as browser:
                browser.cookies.set("__Host-care_link_help", raw_cookie)
                context = sessions.context(raw_cookie)
                prepare_headers = {
                    "Origin": "https://help.test",
                    "X-CSRF-Token": context.csrf_token,
                }
                first_intent = browser.post(
                    "/help/v1/create-intent",
                    json={"locale": "en-CA", "jurisdiction": None},
                    headers=prepare_headers,
                )
                assert first_intent.status_code == 200
                operation_id = first_intent.json()["operation_id"]
                response = browser.post(
                    "/help/v1/requests",
                    json={"locale": "en-CA", "jurisdiction": None},
                    headers={
                        "Origin": "https://help.test",
                        "X-CSRF-Token": context.csrf_token,
                        "Idempotency-Key": operation_id,
                    },
                )
                assert response.status_code == 200
                assert response.json()["state"] == "recorded"
                denied = browser.post(
                    "/help/v1/requests/" + response.json()["id"] + "/accept",
                    json={"expected_revision": "1"},
                    headers={
                        "Origin": "https://help.test",
                        "X-CSRF-Token": context.csrf_token,
                        "Idempotency-Key": str(uuid4()),
                    },
                )
                # Real identity HTTP role denial retains403 across the adapter;
                # it must not turn into an apparent provider outage503.
                assert denied.status_code == 403
                assert denied.json()["message_key"] == "help.authority_denied"
                # A complete new OIDC login rotates the BFF cookie. Treat the
                # create response above as lost and recover the durable key.
                _, second_state = identity.login_start("pid", "second-binding")
                _, second_cookie, _ = identity.callback(second_state, "new-code", "second-binding")
                assert second_cookie and second_cookie != raw_cookie
                browser.cookies.clear()
                browser.cookies.set("__Host-care_link_help", second_cookie)
                new_context = sessions.context(second_cookie)
                recovered = browser.post(
                    "/help/v1/create-intent",
                    json={"locale": "en-CA", "jurisdiction": None},
                    headers={"Origin": "https://help.test", "X-CSRF-Token": new_context.csrf_token},
                )
                assert recovered.status_code == 200
                assert recovered.json()["operation_id"] == operation_id
                retried = browser.post(
                    "/help/v1/requests",
                    json={"locale": "en-CA", "jurisdiction": None},
                    headers={
                        "Origin": "https://help.test",
                        "X-CSRF-Token": new_context.csrf_token,
                        "Idempotency-Key": operation_id,
                    },
                )
                assert retried.status_code == 200
                assert retried.json()["id"] == response.json()["id"]
                provider.available = False
                assert browser.get("/help/v1/requests/" + response.json()["id"]).status_code == 503
    # A header alone cannot cross an unconfigured workload verifier.
    with TestClient(create_identity_app(identity)) as untrusted:
        assert (
            untrusted.post(
                "/internal/v1/identity/help-browser-context", headers={"X-Help-Session": raw_cookie}
            ).status_code
            == 403
        )
