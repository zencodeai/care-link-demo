"""Mock HTTP and actual identity-use-case seams; no live bootstrap is performed."""

import base64
import copy
import hashlib
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlencode
from uuid import uuid4

import httpx
import pytest
from care_link_identity import Custody, IdentityService, Principal, ReceiptSigner
from care_link_identity.provider import OIDCConfig, OIDCProvider
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tools.imp04_review.operator_login import (
    PrivilegedCredentials,
    PrivilegedLoginError,
    _fresh_totp,
    login_privileged,
)


class MemoryStore:
    def __init__(self):
        self.rows = {}

    def get(self, kind, key):
        return copy.deepcopy(self.rows.get((kind, key)))

    def put(self, kind, key, value):
        self.rows[kind, key] = copy.deepcopy(value)

    def delete(self, kind, key):
        self.rows.pop((kind, key), None)

    def items(self, kind):
        return [
            (key, copy.deepcopy(row)) for (table, key), row in self.rows.items() if table == kind
        ]

    @contextmanager
    def transaction(self):
        before = copy.deepcopy(self.rows)
        try:
            yield self
        except BaseException:
            self.rows = before
            raise


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 20, 2, 0, 28, tzinfo=UTC)
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def setup(monkeypatch):
    clock, store = Clock(), MemoryStore()
    credentials = PrivilegedCredentials(
        "operator",
        str(uuid4()),
        str(uuid4()),
        "private-fixture-username",
        "private-fixture-password",
        "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ",
    )
    other_account, other_subject = str(uuid4()), str(uuid4())
    issuer, origin = (
        "https://id.bootstrap.localhost/realms/fresh-synthetic",
        "https://plans.localhost:30443",
    )
    base = issuer + "/protocol/openid-connect/"
    config = OIDCConfig(
        issuer,
        "client",
        "private-fixture-client-secret",
        origin + "/v1/auth/callback",
        base + "auth",
        base + "token",
        base + "certs",
        base + "token/introspect",
        base + "revoke",
        "business",
        "fixture-mfa",
    )
    observed = {"mode": "happy", "requests": [], "exchanges": 0, "revokes": 0}

    def callback():
        values = {"state": observed["state"], "code": "private-one-time-code", "iss": issuer}
        if observed["mode"] == "bad_state":
            values["state"] = "wrong-private-state"
        if observed["mode"] == "bad_issuer":
            values["iss"] = "https://foreign.example/realms/fresh-synthetic"
        url = config.redirect_uri + "?" + urlencode(values)
        if observed["mode"] == "duplicate_state":
            url += "&state=duplicate"
        return httpx.Response(302, headers={"location": url})

    def form(otp=False):
        action = (
            issuer
            + "/login-actions/authenticate?session_code=opaque&amp;execution="
            + ("otp" if otp else "password")
        )
        if observed["mode"] == "foreign_form":
            action = "https://foreign.example/realms/fresh-synthetic/login-actions/authenticate"
        method = "get" if observed["mode"] == "get_form" else "post"
        fields = (
            '<input autocomplete="one-time-code" name="otp">'
            if otp
            else (
                '<input name="username" autocomplete="username">'
                '<input name="password" type="password">'
            )
        )
        if observed["mode"] == "missing_password":
            fields = '<input name="username">'
        document = (
            f'<form method="{method}" action="{action}">'
            '<input type="hidden" name="csrf" value="opaque">'
            f'{fields}<input type="checkbox" name="rememberMe" value="on"></form>'
        )
        if observed["mode"] == "ambiguous":
            document += document
        if observed["mode"] == "oversize":
            document += "x" * (256 * 1024)
        return httpx.Response(
            200,
            text=document,
            headers={
                "content-type": "text/html; charset=utf-8",
                "set-cookie": (
                    "KC_AUTH_SESSION=private-cookie; Path=/realms/fresh-synthetic; Secure; HttpOnly"
                ),
            },
        )

    def route(request):
        observed["requests"].append(request)
        assert request.url.host == "id.bootstrap.localhost"
        if request.method == "GET":
            query = parse_qs(request.url.query.decode())
            if request.url.path.endswith("/auth"):
                observed["state"] = query["state"][0]
                observed["nonce"] = query["nonce"][0]
                observed["challenge"] = query["code_challenge"][0]
                assert query["prompt"] == ["login"] and query["max_age"] == ["0"]
                assert "ambient-cookie" not in request.headers.get("cookie", "")
                return form()
            return httpx.Response(302, headers={"location": str(request.url)})
        if request.url.path.endswith("/introspect"):
            return httpx.Response(
                200,
                json={
                    "active": True,
                    "sub": other_subject
                    if observed["mode"] == "wrong_actor"
                    else credentials.subject,
                },
            )
        if request.url.path.endswith("/revoke"):
            observed["revokes"] += 1
            return httpx.Response(200)
        values = parse_qs(request.content.decode())
        assert "private-cookie" in request.headers.get("cookie", "")
        assert "ambient-cookie" not in request.headers.get("cookie", "")
        assert "rememberMe" not in values
        execution = parse_qs(request.url.query.decode())["execution"][0]
        if execution == "password":
            if observed["mode"] == "loop":
                return httpx.Response(302, headers={"location": issuer + "/login-actions/restart"})
            if observed["mode"] != "missing_password":
                assert values["username"] == [credentials.username]
                assert values["password"] == [credentials.password]
            if observed["mode"] == "foreign_redirect":
                return httpx.Response(
                    302, headers={"location": "https://foreign.example/elsewhere"}
                )
            if observed["mode"] in {"missing_password", "missing_otp"}:
                return callback()
            return form(True)
        assert len(values["otp"][0]) == 6 and values["otp"][0].isdigit()
        return callback()

    client = httpx.Client(transport=httpx.MockTransport(route), follow_redirects=True)
    client.cookies.set("ambient-cookie", "not-for-bootstrap", domain="id.bootstrap.localhost")
    provider = OIDCProvider(config, client)
    service = IdentityService(
        store,
        provider,
        Custody(Fernet.generate_key()),
        ReceiptSigner(Ed25519PrivateKey.generate(), "fixture-key"),
        issuer,
        origin,
        clock,
    )
    service.provision(credentials.subject, credentials.account_id, ["operator", "security"])
    service.provision(other_subject, other_account, ["operator", "security"])

    def exchange(code, verifier, nonce, fresh):
        observed["exchanges"] += 1
        assert code == "private-one-time-code" and nonce == observed["nonce"] and fresh is True
        assert (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
            == observed["challenge"]
        )
        return Principal(
            other_subject if observed["mode"] == "wrong_actor" else credentials.subject,
            clock() - timedelta(seconds=301) if observed["mode"] == "stale_auth" else clock(),
            True,
            ("pwd", "webauthn") if observed["mode"] == "wrong_factors" else ("pwd", "otp"),
            "private-fixture-access",
            clock() + timedelta(hours=1),
        )

    monkeypatch.setattr(provider, "exchange", exchange)
    yield service, credentials, clock, observed, store
    client.close()


@pytest.mark.parametrize("role", ["operator", "security"])
def test_real_identity_usecases_and_bounded_http_forms_return_exact_actor_session(
    setup, role, capsys
):
    service, credentials, clock, observed, _store = setup
    credentials = replace(credentials, role=role)
    raw = login_privileged(service, credentials, clock=clock, sleep=clock.sleep)
    assert raw and service.current(raw)["account_id"] == credentials.account_id
    assert service.current(raw)["role"] == role
    assert observed["exchanges"] == 1 and observed["revokes"] == 0
    assert len(clock.sleeps) == 1 and 0 < clock.sleeps[0] <= 30.1
    assert credentials.password not in repr(credentials) and credentials.totp_secret not in repr(
        credentials
    )
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "mode",
    [
        "foreign_form",
        "foreign_redirect",
        "bad_state",
        "bad_issuer",
        "duplicate_state",
        "missing_password",
        "missing_otp",
        "get_form",
        "ambiguous",
        "oversize",
        "loop",
    ],
)
def test_foreign_or_incomplete_provider_flows_fail_before_callback_without_secrets(setup, mode):
    service, credentials, clock, observed, store = setup
    observed["mode"] = mode
    with pytest.raises(PrivilegedLoginError) as error:
        login_privileged(service, credentials, clock=clock, sleep=clock.sleep)
    assert observed["exchanges"] == 0
    assert not list(store.items("session"))
    assert len(observed["requests"]) <= 12
    assert credentials.password not in str(error.value) and credentials.username not in str(
        error.value
    )
    assert "https://" not in str(error.value)


@pytest.mark.parametrize("mode", ["wrong_actor", "wrong_factors", "stale_auth"])
def test_post_issuance_actor_or_freshness_mismatch_revokes_only_issued_session(setup, mode):
    service, credentials, clock, observed, store = setup
    observed["mode"] = mode
    with pytest.raises(PrivilegedLoginError, match="issued_actor_mismatch"):
        login_privileged(service, credentials, clock=clock, sleep=clock.sleep)
    sessions = list(store.items("session"))
    assert len(sessions) == 1 and sessions[0][1]["revoked"] is True
    assert sessions[0][1]["access_token"] == "" and observed["revokes"] == 1


def test_totp_waits_for_next_window_and_matches_known_sha1_counter_one():
    clock = Clock()
    clock.now = datetime.fromtimestamp(29, UTC)
    assert _fresh_totp("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", clock, clock.sleep) == "287082"
    assert clock.sleeps == [1.1]
    with pytest.raises(PrivilegedLoginError, match="invalid_clock"):
        _fresh_totp("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", clock, lambda _seconds: None)


def test_review_mode_and_foreign_realm_configuration_are_rejected_before_http(setup):
    service, credentials, clock, observed, _store = setup
    service.interactive_policy = object()
    with pytest.raises(PrivilegedLoginError, match="ordinary_provider_required"):
        login_privileged(service, credentials, clock=clock, sleep=clock.sleep)
    service.interactive_policy = None
    service.provider.config = replace(
        service.provider.config,
        authorization_endpoint="https://id.bootstrap.localhost/realms/foreign/protocol/openid-connect/auth",
    )
    with pytest.raises(PrivilegedLoginError, match="invalid_provider_configuration"):
        login_privileged(service, credentials, clock=clock, sleep=clock.sleep)
    assert observed["requests"] == []
