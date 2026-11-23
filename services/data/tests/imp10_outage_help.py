"""Independent Help, Identity and public fallback in the IMP-10 outage fixture."""

import base64
import secrets
import sqlite3
from contextlib import ExitStack, closing
from dataclasses import dataclass, field, replace
from datetime import timedelta
from pathlib import Path
from time import perf_counter_ns
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
from care_link_help.audit import verify_history
from care_link_identity import Custody, IdentityService, ReceiptSigner
from care_link_identity import create_app as create_identity_app
from care_link_identity.domain import stamp
from care_link_static import Publication, PublicationStore, PublicText, Review
from care_link_static import create_app as create_static_app
from care_link_static.publication import canonical
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import Request

from services.data.tests.conftest import Harness
from services.data.tests.imp10_outage_listeners import RoleTopology
from services.identity.tests.conftest import Clock, FakeProvider, MemoryStore, signed_in

COOKIE = "__Host-care_link_help"
REQUESTS = "/help/v1/requests"
KEY_ID = "imp10-outage-help"
HELP_WORKLOAD_HEADER = "X-Synthetic-Help-Workload"


@dataclass(frozen=True)
class Browser:
    account: str
    cookie: str = field(repr=False)
    csrf: str = field(repr=False)

    def headers(self, origin: str) -> dict[str, str]:
        return {"Cookie": f"{COOKIE}={self.cookie}", "Origin": origin, "X-CSRF-Token": self.csrf}


@dataclass(frozen=True)
class RecordedHelp:
    help_id: str
    operation_id: str
    locale: str


@dataclass
class HelpOutageFixture:
    browser: httpx.Client
    public: httpx.Client
    identity_origin: str
    help_origin: str
    static_url: str
    publication: Publication
    spool: Spool
    participant: Browser
    worker: Browser
    recorded: list[RecordedHelp] = field(default_factory=list)

    def assert_identity_available(self) -> None:
        current = self.browser.get(
            self.identity_origin + "/v1/auth/session",
            headers={"Cookie": f"{COOKIE}={self.participant.cookie}"},
        )
        current.raise_for_status()
        view = current.json()
        assert view["account_id"] == self.participant.account and view["role"] == "pid"

    def _submit(self, locale: str, operation_id: str) -> httpx.Response:
        return self.browser.post(
            self.help_origin + REQUESTS,
            json={"locale": locale, "jurisdiction": None},
            headers=self.participant.headers(self.help_origin) | {"Idempotency-Key": operation_id},
        )

    def probe(self, locale: str) -> dict[str, object]:
        started = perf_counter_ns()
        operation_id = str(uuid4())
        created = self._submit(locale, operation_id)
        assert created.status_code == 200, created.text
        view = created.json()
        assert view["state"] == "recorded" and view["connection_confirmed"] is False
        status = self.browser.get(
            f"{self.help_origin}{REQUESTS}/{view['id']}",
            headers={"Cookie": f"{COOKIE}={self.participant.cookie}"},
        )
        assert status.status_code == 200 and status.json() == view
        self.recorded.append(RecordedHelp(view["id"], operation_id, locale))
        return {
            "locale": locale,
            "create_and_read_elapsed_ms": (perf_counter_ns() - started) / 1_000_000,
            "help_state": view["state"],
            "connection_confirmed": view["connection_confirmed"],
        }

    def assert_identity_down(self) -> dict[str, object]:
        with pytest.raises(httpx.TransportError):
            self.assert_identity_available()
        latest = self.recorded[-1]
        before = self._durable_rows()
        path = f"{self.help_origin}{REQUESTS}/{latest.help_id}"
        denied = {
            "status": self.browser.get(path, headers=self.participant.headers(self.help_origin)),
            "new_create": self._submit(latest.locale, str(uuid4())),
            "retry_create": self._submit(latest.locale, latest.operation_id),
            "accept": self.browser.post(
                path + "/accept",
                json={"expected_revision": "1"},
                headers=self.worker.headers(self.help_origin) | {"Idempotency-Key": str(uuid4())},
            ),
        }
        for result in denied.values():
            assert result.status_code == 503 and result.json() == {
                "message_key": "help.identity_unavailable",
                "static_url": self.static_url,
            }
        static = self.verify_static()
        assert self._durable_rows() == before
        return {
            "private_operations": dict.fromkeys(denied, "typed_503"),
            "durable_spool_unchanged": True,
            **static,
        }

    def verify_static(self) -> dict[str, object]:
        static_url = self.static_url
        for text in self.publication.texts:
            page = self.public.get(static_url, params={"locale": text.locale})
            assert page.status_code == 200 and text.title in page.text and text.text in page.text
            assert page.headers["cache-control"] == "no-store"
            assert "cookie" not in page.request.headers
            manifest = self.public.get(
                static_url.removesuffix("/fallback") + "/demo-static/v1/manifest",
                params={"locale": text.locale},
            )
            assert manifest.status_code == 200
            assert manifest.json() == self.publication.owner_manifest(text.locale)
        return {
            "public_static_locales": [text.locale for text in self.publication.texts],
            "public_static_artifact_digest": self.publication.artifact_digest,
        }

    def _durable_rows(self) -> dict[str, list[tuple[object, ...]]]:
        with closing(sqlite3.connect(self.spool.path)) as connection:
            return {
                "requests": connection.execute("SELECT * FROM request ORDER BY id").fetchall(),
                "operations": connection.execute("SELECT * FROM operation ORDER BY id").fetchall(),
                "nonces": connection.execute(
                    "SELECT * FROM decision_nonce ORDER BY nonce"
                ).fetchall(),
                "audit": connection.execute(
                    "SELECT * FROM local_event ORDER BY sequence"
                ).fetchall(),
                "intents": connection.execute("SELECT * FROM create_intent").fetchall(),
            }

    def summary(self) -> dict[str, object]:
        with closing(sqlite3.connect(self.spool.path)) as connection:
            connection.row_factory = sqlite3.Row
            verify_history(connection)
            requests = connection.execute("SELECT * FROM request ORDER BY id").fetchall()
            operations = connection.execute("SELECT * FROM operation").fetchall()
            audit = connection.execute("SELECT * FROM local_event ORDER BY sequence").fetchall()
            nonce_count = connection.execute("SELECT count(*) FROM decision_nonce").fetchone()[0]
        assert self.spool.path.stat().st_mode & 0o077 == 0
        assert len(requests) == len(self.recorded)
        assert {row["id"] for row in requests} == {case.help_id for case in self.recorded}
        assert all(
            (row["owner_account"], row["status"], row["accepted_by"], row["revision"])
            == (self.participant.account, "recorded", None, 1)
            for row in requests
        )
        assert len(operations) == len(audit) == nonce_count == len(self.recorded) * 2
        for case in self.recorded:
            related = [row for row in operations if row["help_id"] == case.help_id]
            assert len(related) == 2
            assert {row["principal"] for row in related} == {self.participant.account}
            assert {row["action"] for row in related} == {"create", "status"}
            assert (
                next(row["id"] for row in related if row["action"] == "create") == case.operation_id
            )
            assert [row["action"] for row in audit if row["reference"] == case.help_id] == [
                "create",
                "status",
            ]
        return {
            "durable_local_request_count": len(requests),
            "durable_local_audit_actions": [row["action"] for row in audit],
            "durable_local_authority_receipts": nonce_count,
            "local_audit_chain_verified": True,
            "identity_provider": "synthetic OIDC with in-memory Identity custody",
            "help_workload_binding": "dedicated synthetic credential over pinned loopback TLS",
            "static_review_profile": self.publication.review.profile,
        }


def _static_publication(directory: Path, clock: Clock) -> tuple[PublicationStore, Publication]:
    directory.mkdir(mode=0o700)
    key = Ed25519PrivateKey.generate()
    owner = str(uuid4())
    review = Review(
        receipt_id=str(uuid4()),
        reviewer_id=owner,
        operator_id=owner,
        artifact_digest="",
        verified_at=stamp(clock()),
        review_due_at=stamp(clock() + timedelta(days=1)),
        signature="",
        profile="owner_review_local_demo",
    )
    publication = Publication(
        (
            PublicText("en-CA", "Synthetic fallback", "Public demonstration content."),
            PublicText("fr-CA", "Secours fictif", "Contenu public de démonstration."),
        ),
        review,
    )
    review = replace(review, artifact_digest=publication.artifact_digest)
    signature = base64.b64encode(key.sign(canonical(review.payload()))).decode()
    publication = replace(publication, review=replace(review, signature=signature))
    store = PublicationStore(directory, key.public_key(), clock, allow_owner_demo=True)
    store.publish(publication, None, owner, str(uuid4()))
    return store, publication


def start_help(
    topology: RoleTopology, h: Harness, tmp_path: Path, stack: ExitStack
) -> HelpOutageFixture:
    clock = Clock()
    help_origin, identity_origin = topology.origin("help"), topology.origin("identity")
    static_url = topology.origin("static") + "/fallback"
    key = Ed25519PrivateKey.generate()
    provider = FakeProvider(clock)
    identity = IdentityService(
        MemoryStore(),
        provider,
        Custody(Fernet.generate_key()),
        ReceiptSigner(key, KEY_ID),
        "https://issuer.test",
        help_origin,
        clock=clock,
    )
    workload_credential = secrets.token_urlsafe(32)

    def verify_workload(request: Request, peer: str) -> bool:
        return peer == "help" and secrets.compare_digest(
            request.headers.get(HELP_WORKLOAD_HEADER, ""), workload_credential
        )

    topology.start(
        "identity",
        create_identity_app(identity, workload_verifier=verify_workload, session_cookie=COOKIE),
    )
    workload = stack.enter_context(
        topology.client(headers={HELP_WORKLOAD_HEADER: workload_credential})
    )
    sessions = HttpBrowserSessions(workload, identity_origin, help_origin)

    def login(account: str, role: str) -> Browser:
        provider.subject = f"synthetic-help-{role}"
        identity.provision(provider.subject, account, [role])
        raw = signed_in(identity, role=role, binding=f"synthetic-help-browser-{role}")
        context = sessions.context(raw)
        assert context.account_id == account and context.role == role
        return Browser(account, raw, context.csrf_token)

    participant = login(h.participant.account_id, "pid")
    worker = login(h.worker.account_id, "worker")
    browser = stack.enter_context(topology.client())
    public = stack.enter_context(topology.client())
    without_workload = browser.post(
        identity_origin + "/internal/v1/identity/help-browser-context",
        headers={"X-Help-Session": participant.cookie, "X-Help-Origin": help_origin},
        json={},
    )
    assert without_workload.status_code == 403

    store, publication = _static_publication(tmp_path / "static-publication", clock)
    topology.start("static", create_static_app(store, allow_owner_demo=True))
    spool_dir = tmp_path / "private-help"
    spool_dir.mkdir(mode=0o700)
    spool = Spool(spool_dir / "help.sqlite", clock=clock)
    help_service = HelpService(
        spool,
        HttpAuthority(workload, identity_origin),
        SignedReceipts({KEY_ID: key.public_key()}, clock=clock),
        clock=clock,
    )
    topology.start(
        "help",
        create_help_app(HelpConfig(help_origin, static_url=static_url), help_service, sessions),
    )
    fixture = HelpOutageFixture(
        browser,
        public,
        identity_origin,
        help_origin,
        static_url,
        publication,
        spool,
        participant,
        worker,
    )
    fixture.assert_identity_available()
    return fixture
