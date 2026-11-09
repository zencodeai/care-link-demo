"""Security invariants with a declared provider/store fixture, not OIDC lab proof."""

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from care_link_contracts import validate_contract
from care_link_identity import ExchangeUncertain, IdentityError, create_app, stepup
from care_link_identity.crypto import canonical, digest
from care_link_identity.domain import stamp
from conftest import signed_in
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


def test_callback_bound_once_and_server_only_credentials(identity):
    service, store, provider, _clock, _key = identity
    intent, state = service.login_start("pid", "browser-a")
    validate_contract("LoginIntent", intent)
    with pytest.raises(IdentityError):
        service.callback(state, "code", "browser-b")
    assert provider.exchanges == 0
    view, raw, proof = service.callback(state, "code", "browser-a")
    validate_contract("BrowserSession", view)
    assert raw and proof is None
    assert "server-only-access-token" not in str(store.records)
    assert raw not in str(store.records)
    with pytest.raises(IdentityError):
        service.callback(state, "code", "browser-a")
    assert provider.exchanges == 1


def test_two_callback_threads_redeem_only_once(identity):
    service, _store, provider, _clock, _key = identity
    _intent, state = service.login_start("pid", "browser")

    def invoke():
        try:
            return service.callback(state, "code", "browser")[1]
        except IdentityError:
            return None

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: invoke(), range(2)))
    assert sum(value is not None for value in results) == 1
    assert provider.exchanges == 1


def test_wrong_issuer_cancels_without_exchange(identity):
    service, _store, provider, _clock, _key = identity
    _intent, state = service.login_start("pid", "browser")
    with pytest.raises(IdentityError):
        service.callback(state, "code", "browser", "https://evil.test")
    with pytest.raises(IdentityError):
        service.callback(state, "code", "browser")
    assert provider.exchanges == 0


def test_expired_and_provider_cancelled_login(identity):
    service, _store, provider, clock, _key = identity
    _intent, state = service.login_start("pid", "browser")
    clock.advance(301)
    with pytest.raises(IdentityError):
        service.callback(state, "code", "browser")
    _intent, state = service.login_start("pid", "browser")
    with pytest.raises(IdentityError):
        service.callback(state, "", "browser", provider_error=True)
    assert provider.exchanges == 0


def test_timeout_is_uncertain_and_cannot_redeem_again(identity):
    service, store, provider, _clock, _key = identity
    _intent, state = service.login_start("pid", "browser")
    provider.exchange_error = ExchangeUncertain()
    with pytest.raises(ExchangeUncertain):
        service.callback(state, "code", "browser")
    record = store.records[("intent", digest(state))]
    assert record["state"] == "uncertain" and record["verifier"] == ""
    with pytest.raises(IdentityError):
        service.callback(state, "code", "browser")
    assert provider.exchanges == 1


def test_claimed_role_and_missing_mfa_cannot_create_privilege(identity):
    service, _store, provider, _clock, _key = identity
    with pytest.raises(IdentityError):
        signed_in(service, "operator")
    provider.mfa = False
    with pytest.raises(IdentityError):
        signed_in(service, "worker")
    assert signed_in(service, "pid")


def test_current_provider_outage_and_local_revoke_after_introspection_deny(identity):
    service, store, provider, _clock, _key = identity
    raw = signed_in(service)
    service.session_view(raw)
    service.session_view(raw)
    assert provider.active_checks == 2
    provider.is_active = False
    with pytest.raises(IdentityError):
        service.session_view(raw)
    provider.is_active = True

    def revoke_during_check():
        with store.transaction() as tx:
            record = tx.get("session", digest(raw))
            record["revoked"] = True
            tx.put("session", digest(raw), record)

    provider.on_active = revoke_during_check
    with pytest.raises(IdentityError):
        service.session_view(raw)


def test_privileged_idle_expiry(identity):
    service, _store, _provider, clock, _key = identity
    raw = signed_in(service, "worker")
    clock.advance(900)
    with pytest.raises(IdentityError):
        service.session_view(raw)


def help_request(service, raw, clock, action="create"):
    return {
        "operation_id": str(uuid4()),
        "help_id": str(uuid4()),
        "action": action,
        "request_digest": "a" * 64,
        "browser_proof_ref": service.issue_help_proof(raw, service.origin),
        "nonce": str(uuid4()),
        "deadline": stamp(clock() + timedelta(milliseconds=900)),
    }


def test_help_receipt_is_fresh_exact_signed_and_one_use(identity):
    service, _store, provider, clock, key = identity
    raw = signed_in(service)
    request = help_request(service, raw, clock)
    checks = provider.active_checks
    receipt = service.help_authorize(request)
    validate_contract("FreshHelpAuthority", receipt)
    signature = receipt.pop("signature")
    key.public_key().verify(
        base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)), canonical(receipt)
    )
    assert receipt["one_use_nonce"] == request["nonce"]
    assert receipt["help_id"] == request["help_id"]
    assert provider.active_checks == checks + 1
    with pytest.raises(IdentityError):
        service.help_authorize(request)


def test_help_worker_predicate_deadline_expiry_and_outage(identity):
    service, _store, provider, clock, _key = identity
    raw = signed_in(service)
    with pytest.raises(IdentityError):
        service.help_authorize(help_request(service, raw, clock, "accept"))
    request = help_request(service, raw, clock)
    request["deadline"] = stamp(clock() + timedelta(seconds=2))
    with pytest.raises(IdentityError):
        service.help_authorize(request)
    request = help_request(service, raw, clock)
    clock.advance(1)
    with pytest.raises(IdentityError):
        service.help_authorize(request)
    request = help_request(service, raw, clock)
    provider.is_active = False
    with pytest.raises(IdentityError):
        service.help_authorize(request)


def test_logout_fences_even_when_provider_lost_and_replays_same_result(identity):
    service, _store, provider, _clock, _key = identity
    raw = signed_in(service)
    provider.is_active = False
    operation = str(uuid4())
    result = service.logout(raw, operation)
    validate_contract("CommandResult", result)
    assert service.logout(raw, operation) == result
    with pytest.raises(IdentityError):
        service.current(raw)
    other = signed_in(service)
    with pytest.raises(IdentityError):
        service.logout(other, operation)


def test_al3_requires_cooling_then_distinct_fresh_mfa_after_cooling(identity):
    service, store, _provider, clock, _key = identity
    raw = signed_in(service)
    request = {"purpose": "delete", "resource_id": str(uuid4()), "expected_revision": "1"}
    ceremony = stepup.start(service, raw, "test-binding", request)
    state_hashes = [key for kind, key in store.records if kind == "intent" and len(key) == 64]
    # Resolve state from the fake provider authorization URL, as the real browser does.
    state = str(ceremony["authorization_url"]).split("state=")[1]
    previous_raw = raw
    _view, raw, proof = service.callback(state, "mfa-code", "test-binding")
    assert raw
    with pytest.raises(IdentityError):
        service.current(previous_raw)
    confirm = {
        "ceremony_id": ceremony["ceremony_id"],
        "proof_intent_id": proof,
        "expected_revision": "1",
    }
    first = stepup.confirm(service, raw, confirm)
    assert first["state"] == "cooling_off" and state_hashes
    with pytest.raises(IdentityError):
        stepup.confirm(service, raw, confirm)
    clock.advance(301)
    assert service.session_view(raw)["assurance"] == "AL1"
    second = stepup.start(service, raw, "test-binding", request)
    assert second["ceremony_id"] == ceremony["ceremony_id"]
    state = str(second["authorization_url"]).split("state=")[1]
    _view, raw, proof2 = service.callback(state, "second-mfa-code", "test-binding")
    assert raw
    confirm["proof_intent_id"] = proof2
    assert stepup.confirm(service, raw, confirm)["state"] == "verified"
    assert service.session_view(raw)["assurance"] != "AL3"


def test_transport_csrf_closed_shapes_cookie_callback_and_default_deny(identity):
    service, _store, provider, _clock, _key = identity
    client = TestClient(
        create_app(service, ui_return_url="https://app.test/private-help"), base_url=service.origin
    )
    bootstrap = client.get("/v1/auth/csrf")
    csrf = bootstrap.json()["csrf_token"]
    assert (
        "Secure" in bootstrap.headers["set-cookie"]
        and "HttpOnly" in bootstrap.headers["set-cookie"]
    )
    payload = {"role": "pid", "return_route": "participant", "locale": "en-CA"}
    assert client.post("/v1/auth/login", json=payload).status_code == 403
    headers = {"Origin": service.origin, "X-CSRF-Token": csrf}
    bad = client.post(
        "/v1/auth/login",
        content='{"role":"pid","role":"worker"}',
        headers=headers | {"Content-Type": "application/json"},
    )
    assert bad.status_code == 422
    result = client.post("/v1/auth/login", json=payload, headers=headers)
    assert result.status_code == 200
    state = result.json()["authorization_url"].split("state=")[1]
    callback = client.get(
        "/v1/auth/callback",
        params={"state": state, "code": "code"},
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert (
        callback.status_code == 303
        and callback.headers["location"] == "https://app.test/private-help"
    )
    assert client.get("/v1/auth/session").json()["role"] == "pid"
    assert (
        client.post(
            "/internal/v1/identity/help-authorize", json={}, headers={"x-workload": "help"}
        ).status_code
        == 403
    )
    assert provider.exchanges == 1
    assert TestClient(create_app()).get("/v1/auth/csrf").status_code == 503


def test_http_logout_csrf_remains_available_during_provider_outage(identity):
    service, _store, provider, _clock, _key = identity
    client = TestClient(create_app(service), base_url=service.origin)
    csrf = client.get("/v1/auth/csrf").json()["csrf_token"]
    login = client.post(
        "/v1/auth/login",
        json={"role": "pid", "return_route": "participant", "locale": "en-CA"},
        headers={"Origin": service.origin, "X-CSRF-Token": csrf},
    ).json()
    state = login["authorization_url"].split("state=")[1]
    assert (
        client.get("/v1/auth/callback", params={"state": state, "code": "code"}).status_code == 200
    )
    raw = client.cookies.get("__Host-care-link-session")
    provider.is_active = False
    assert client.get("/v1/auth/session").status_code == 503
    csrf_response = client.get("/v1/auth/csrf")
    assert csrf_response.status_code == 200
    logout = client.post(
        "/v1/auth/logout",
        json={},
        headers={
            "Origin": service.origin,
            "X-CSRF-Token": csrf_response.json()["csrf_token"],
            "Idempotency-Key": str(uuid4()),
        },
    )
    assert logout.status_code == 200 and logout.json()["state"] == "committed"
    assert raw
    with pytest.raises(IdentityError):
        service.current(raw)


@pytest.mark.parametrize("role,advance", [("pid", 3601), ("worker", 901)])
def test_current_rechecks_expiry_and_idle_after_slow_provider(identity, role, advance):
    service, _store, provider, clock, _key = identity
    raw = signed_in(service, role)
    provider.on_active = lambda: clock.advance(advance)
    with pytest.raises(IdentityError):
        service.browser_context(raw)


def test_help_rechecks_original_proof_expiry_after_provider(identity):
    service, _store, provider, clock, _key = identity
    raw = signed_in(service, "worker")
    request = help_request(service, raw, clock, "accept")
    provider.on_active = lambda: clock.advance(2)
    with pytest.raises(IdentityError):
        service.help_authorize(request)


@pytest.mark.parametrize("expired", [True, False])
def test_local_csrf_allows_fresh_bound_login_with_stale_cookie_or_provider_outage(
    identity, expired
):
    service, store, provider, clock, _key = identity
    client = TestClient(create_app(service), base_url=service.origin)
    raw = signed_in(service, binding="retained-browser-binding")
    client.cookies.set("__Host-care-link-session", raw)
    client.cookies.set("__Host-care-link-binding", "retained-browser-binding")
    if expired:
        clock.advance(3601)
        assert client.get("/v1/auth/session").status_code == 401
    else:
        provider.is_active = False
        assert client.get("/v1/auth/session").status_code == 503
    csrf = client.get("/v1/auth/csrf")
    assert csrf.status_code == 200
    login = client.post(
        "/v1/auth/login",
        json={"role": "pid", "return_route": "participant", "locale": "en-CA"},
        headers={"Origin": service.origin, "X-CSRF-Token": csrf.json()["csrf_token"]},
    )
    assert login.status_code == 200
    state = login.json()["authorization_url"].split("state=")[1]
    provider.is_active = True
    callback = client.get("/v1/auth/callback", params={"state": state, "code": "new-code"})
    assert callback.status_code == 200
    assert client.get("/v1/auth/session").status_code == 200


def test_successful_relogin_fences_only_exact_previous_browser_and_help_proof(identity):
    service, _store, _provider, clock, _key = identity
    old = signed_in(service, binding="browser-a")
    unrelated = signed_in(service, binding="browser-b")
    old_proof = help_request(service, old, clock)
    _intent, state = service.login_start("pid", "browser-a", previous_raw_session=old)
    _view, new, _proof = service.callback(state, "replacement-code", "browser-a")
    assert new and new != old
    with pytest.raises(IdentityError):
        service.current(old)
    with pytest.raises(IdentityError):
        service.help_authorize(old_proof)
    assert service.current(new) and service.current(unrelated)


def test_failed_login_or_unrelated_binding_does_not_revoke_another_session(identity):
    service, _store, _provider, _clock, _key = identity
    old = signed_in(service, binding="browser-a")
    _intent, state = service.login_start("pid", "browser-a", previous_raw_session=old)
    with pytest.raises(IdentityError):
        service.callback(state, "", "browser-a", provider_error=True)
    assert service.current(old)
    _intent, state = service.login_start("pid", "browser-b", previous_raw_session=old)
    service.callback(state, "other-browser-code", "browser-b")
    assert service.current(old)


def http_sign_in(service):
    client = TestClient(create_app(service), base_url=service.origin)
    csrf = client.get("/v1/auth/csrf").json()["csrf_token"]
    intent = client.post(
        "/v1/auth/login",
        json={"role": "pid", "return_route": "participant", "locale": "en-CA"},
        headers={"Origin": service.origin, "X-CSRF-Token": csrf},
    ).json()
    state = intent["authorization_url"].split("state=")[1]
    assert (
        client.get("/v1/auth/callback", params={"state": state, "code": "code"}).status_code == 200
    )
    return client


@pytest.mark.parametrize("empty_csrf", [False, True])
def test_idle_disposal_keeps_bootstrap_and_fresh_login_available(identity, empty_csrf):
    from test_retention import configured

    service, store, _provider, clock, _key = identity
    retention, _authority, _cleanup, _backups, _account = configured(identity)
    raw = signed_in(service, "worker")
    clock.advance(901)
    retention.expire_credentials()
    if empty_csrf:
        with store.transaction() as tx:
            session = tx.get("session", digest(raw))
            session["csrf"] = ""
            tx.put("session", digest(raw), session)
    client = TestClient(create_app(service), base_url=service.origin)
    client.cookies.set("__Host-care-link-session", raw)
    bootstrap = client.get("/v1/auth/csrf")
    assert bootstrap.status_code == 200
    intent = client.post(
        "/v1/auth/login",
        json={"role": "worker", "return_route": "workforce", "locale": "en-CA"},
        headers={"Origin": service.origin, "X-CSRF-Token": bootstrap.json()["csrf_token"]},
    )
    assert intent.status_code == 200
    state = intent.json()["authorization_url"].split("state=")[1]
    callback = client.get("/v1/auth/callback", params={"state": state, "code": "fresh-code"})
    assert callback.status_code == 200
    assert client.get("/v1/auth/session").status_code == 200


def test_logout_after_disposal_does_not_claim_unperformed_provider_revocation(identity):
    from test_retention import configured

    service, store, provider, clock, _key = identity
    retention, _authority, _cleanup, _backups, _account = configured(identity)
    raw = signed_in(service, "worker")
    clock.advance(901)
    retention.expire_credentials()
    assert service.logout(raw, str(uuid4()))["state"] == "committed"
    assert store.get("session", digest(raw))["upstream_revocation"] == "pending"
    assert provider.is_active is True  # no absent bearer was sent for revocation


def test_logout_preserves_previously_confirmed_provider_revocation(identity):
    service, store, _provider, _clock, _key = identity
    raw = signed_in(service)
    service.logout(raw, str(uuid4()))
    assert store.get("session", digest(raw))["upstream_revocation"] == "confirmed"
    service.logout(raw, str(uuid4()))
    assert store.get("session", digest(raw))["upstream_revocation"] == "confirmed"


def test_stepup_callback_renews_same_validated_browser_binding_with_session(identity):
    service, _store, _provider, clock, _key = identity
    client = http_sign_in(service)
    initial_binding = client.cookies.get("__Host-care-link-binding")
    clock.advance(3000)
    csrf = client.get("/v1/auth/csrf").json()["csrf_token"]
    ceremony = client.post(
        "/v1/auth/step-up",
        json={"purpose": "plan_view", "resource_id": str(uuid4()), "expected_revision": "1"},
        headers={"Origin": service.origin, "X-CSRF-Token": csrf},
    ).json()
    state = ceremony["authorization_url"].split("state=")[1]
    response = client.get("/v1/auth/callback", params={"state": state, "code": "mfa-code"})
    assert response.status_code == 200
    cookies = response.headers.get_list("set-cookie")
    binding_cookie = next(
        value for value in cookies if value.startswith("__Host-care-link-binding=")
    )
    session_cookie = next(
        value for value in cookies if value.startswith("__Host-care-link-session=")
    )
    assert "Max-Age=3600" in binding_cookie and "Max-Age=3600" in session_cookie
    assert "Secure" in binding_cookie and "HttpOnly" in binding_cookie
    assert client.cookies.get("__Host-care-link-binding") == initial_binding


def test_missing_browser_binding_bootstrap_allows_bound_relogin_and_rotates_previous(identity):
    service, _store, _provider, _clock, _key = identity
    client = http_sign_in(service)
    old = client.cookies.get("__Host-care-link-session")
    old_csrf = client.get("/v1/auth/csrf").json()["csrf_token"]
    client.cookies.delete("__Host-care-link-binding")
    payload = {"role": "pid", "return_route": "participant", "locale": "en-CA"}
    missing = client.post(
        "/v1/auth/login", json=payload, headers={"Origin": service.origin, "X-CSRF-Token": old_csrf}
    )
    assert missing.status_code == 403
    bootstrap = client.get("/v1/auth/csrf")
    assert bootstrap.status_code == 200 and client.cookies.get("__Host-care-link-binding")
    intent = client.post(
        "/v1/auth/login",
        json=payload,
        headers={"Origin": service.origin, "X-CSRF-Token": bootstrap.json()["csrf_token"]},
    )
    assert intent.status_code == 200
    state = intent.json()["authorization_url"].split("state=")[1]
    callback = client.get("/v1/auth/callback", params={"state": state, "code": "replacement-code"})
    assert callback.status_code == 200 and old
    with pytest.raises(IdentityError):
        service.current(old)
    assert client.get("/v1/auth/session").status_code == 200


def test_captured_previous_session_retires_even_if_local_bootstrap_rebinds_it(identity):
    service, _store, _provider, _clock, _key = identity
    old = signed_in(service, binding="original-browser-binding")
    _intent, state = service.login_start(
        "pid", "original-browser-binding", previous_raw_session=old
    )
    # Another local browser context holding the same old session lost its binding
    # cookie. Bootstrap renews protocol metadata after the predecessor was bound.
    recovery = TestClient(create_app(service), base_url=service.origin)
    recovery.cookies.set("__Host-care-link-session", old)
    assert recovery.get("/v1/auth/csrf").status_code == 200
    assert recovery.cookies.get("__Host-care-link-binding") != "original-browser-binding"
    _view, replacement, _proof = service.callback(
        state, "replacement-code", "original-browser-binding"
    )
    assert replacement
    with pytest.raises(IdentityError):
        service.current(old)
    assert service.current(replacement)


@pytest.mark.parametrize(
    "query",
    [
        "ceremony_id=x",
        "ceremony_id=00000000-0000-0000-0000-000000000000&ceremony_id=00000000-0000-0000-0000-000000000001",
        "ceremony_id=00000000-0000-0000-0000-000000000000&unknown=1",
        "ceremony_id=00000000000000000000000000000000",
    ],
)
def test_stepup_proof_query_is_single_exact_canonical_uuid(identity, query):
    service, _store, _provider, _clock, _key = identity
    client = http_sign_in(service)
    assert client.get("/v1/auth/step-up/proof?" + query).status_code == 403


def test_callback_never_combines_code_and_provider_error(identity):
    service, _store, provider, _clock, _key = identity
    client = TestClient(create_app(service), base_url=service.origin)
    assert (
        client.get("/v1/auth/callback?state=" + "x" * 32 + "&code=code&error=cancelled").status_code
        == 403
    )
    assert provider.exchanges == 0
