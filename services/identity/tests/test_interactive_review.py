"""Explicit simulated review HTTP flows; these are not real provider MFA evidence."""

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from care_link_identity.app import BINDING_COOKIE, SESSION_COOKIE, create_app
from care_link_identity.crypto import digest
from care_link_identity.domain import IdentityError, stamp
from care_link_identity.interactive_provider import AutomaticReviewProvider
from care_link_identity.retention import RetentionService
from care_link_identity.review import ReviewIdentityRegistry
from care_link_identity.review_context import ReviewContext
from care_link_identity.service import IdentityService
from care_link_identity.session_policy import marked_interactive_session, policy_for_context
from conftest import signed_in
from starlette.testclient import TestClient


@pytest.fixture
def automatic(identity):
    base, store, _provider, clock, _key = identity
    run = str(uuid4())
    contexts = {}
    for slot, role in (
        ("pid", "pid"),
        ("carer", "carer"),
        ("professional", "professional_participant"),
        ("worker1", "worker"),
    ):
        origin = f"https://r{run.replace('-', '')}-{slot}.plans.localhost:30443"
        subject, account = str(uuid4()), str(uuid4())
        base.provision(subject, account, [role])
        contexts[origin] = ReviewContext(
            origin,
            run,
            slot,
            account,
            role,
            subject,
            mode="plans",
            authentication_mode="automatic_review",
            environment="synthetic-review",
            started_at=stamp(clock()),
            expires_at=stamp(clock() + timedelta(hours=3)),
        )
    registry = ReviewIdentityRegistry(
        base,
        lambda: contexts,
        interactive_policy_for_origin=lambda origin: policy_for_context(
            contexts[origin], enabled=True
        ),
    )
    return registry, contexts, store, clock


def client_for(automatic, slot="pid"):
    registry, contexts, _store, _clock = automatic
    context = next(value for value in contexts.values() if value.slot_id == slot)
    service = registry.browser_service(context.origin)
    return TestClient(create_app(service), base_url=context.origin), service, context


def post(client, path, body):
    csrf = client.get("/v1/auth/csrf")
    assert csrf.status_code == 200
    return client.post(
        path,
        json=body,
        headers={
            "Origin": str(client.base_url).rstrip("/"),
            "X-CSRF-Token": csrf.json()["csrf_token"],
        },
    )


@pytest.mark.parametrize("slot", ["pid", "carer", "professional", "worker1"])
def test_automatic_login_is_exact_actor_bound_and_explicitly_simulated(automatic, slot):
    client, service, context = client_for(automatic, slot)
    response = post(client, "/v1/auth/review/login", {})
    assert response.status_code == 200
    assert response.json()["account_id"] == context.account_id
    assert response.json()["role"] == context.role
    assert response.json()["review_slot_id"] == slot
    assert response.json()["expires_at"] == context.expires_at
    assert response.headers["X-Care-Link-Authentication-Mode"] == "automatic_review"
    for cookie in response.headers.get_list("set-cookie"):
        assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
        assert "Domain=" not in cookie
    raw = client.cookies.get(SESSION_COOKIE)
    assert raw and client.cookies.get(BINDING_COOKIE)
    record = service.current(raw)
    assert record["factors"] == ["simulated_review"]
    assert record["authentication_mode"] == "automatic_review"
    assert client.get("/v1/auth/session").status_code == 200


def test_verify_uses_normal_bound_ceremony_and_rotates_cookie_and_csrf(automatic):
    client, service, _context = client_for(automatic)
    view = post(client, "/v1/auth/review/login", {}).json()
    old = client.cookies.get(SESSION_COOKIE)
    old_csrf = client.get("/v1/auth/csrf").json()["csrf_token"]
    resource = str(uuid4())
    result = post(
        client,
        "/v1/auth/review/verify",
        {"purpose": "plan_edit", "resource_id": resource, "expected_revision": view["revision"]},
    )
    assert result.status_code == 200 and result.json()["state"] == "verified"
    assert result.json()["authorization_url"] is None
    new = client.cookies.get(SESSION_COOKIE)
    assert new and new != old
    assert client.get("/v1/auth/csrf").json()["csrf_token"] != old_csrf
    with pytest.raises(IdentityError):
        service.current(old)
    with service.store.transaction() as tx:
        ceremony = tx.get("ceremony", result.json()["ceremony_id"])
        assert ceremony["session_hash"] == digest(new)
        assert ceremony["purpose"] == "plan_edit" and ceremony["resource_id"] == resource
        intents = [
            row
            for _, row in tx.items("intent")
            if row.get("ceremony_id") == result.json()["ceremony_id"]
        ]
        assert len(intents) == 1 and intents[0]["proof_consumed"] is True
    assert service.current(new)["factors"] == ["simulated_review"]


@pytest.mark.parametrize("slot", ["pid", "worker1"])
def test_review_survives_normal_hour_and_idle_but_expires_at_run_bound(automatic, slot):
    _registry, _contexts, store, clock = automatic
    client, service, _context = client_for(automatic, slot)
    assert post(client, "/v1/auth/review/login", {}).status_code == 200
    raw = client.cookies.get(SESSION_COOKIE)
    clock.advance(3601)
    RetentionService(store, service.custody, None, clock=clock).expire_credentials()
    assert service.current(raw)["revoked"] is False
    assert marked_interactive_session(store.get("session", digest(raw)), clock())
    clock.advance(7200)
    assert client.get("/v1/auth/session").status_code == 401
    assert post(client, "/v1/auth/review/login", {}).status_code == 401


@pytest.mark.parametrize("change", ["closed", "closing", "account", "subject", "run", "missing"])
def test_live_registry_change_denies_existing_service_and_old_session(automatic, change):
    registry, contexts, _store, _clock = automatic
    client, service, context = client_for(automatic)
    assert post(client, "/v1/auth/review/login", {}).status_code == 200
    raw = client.cookies.get(SESSION_COOKIE)
    if change == "missing":
        del contexts[context.origin]
    else:
        values = {
            "closed": {"state": "closed"},
            "closing": {"state": "closing"},
            "account": {"account_id": str(uuid4())},
            "subject": {"provider_subject": str(uuid4())},
            "run": {"run_id": str(uuid4())},
        }[change]
        contexts[context.origin] = replace(context, **values)
    with pytest.raises(IdentityError):
        service.current(raw)
    assert client.get("/v1/auth/session").status_code == 401


def test_csrf_origin_actor_and_purpose_cannot_be_selected_by_browser(automatic):
    client, _service, context = client_for(automatic)
    assert client.post("/v1/auth/review/login", json={}).status_code == 403
    token = client.get("/v1/auth/csrf").json()["csrf_token"]
    assert (
        client.post(
            "/v1/auth/review/login",
            json={},
            headers={"Origin": "https://wrong.plans.localhost", "X-CSRF-Token": token},
        ).status_code
        == 403
    )
    assert (
        post(client, "/v1/auth/review/login", {"account_id": context.account_id}).status_code == 422
    )
    view = post(client, "/v1/auth/review/login", {}).json()
    for purpose in ("export", "plan_view", "delete"):
        assert (
            post(
                client,
                "/v1/auth/review/verify",
                {
                    "purpose": purpose,
                    "resource_id": str(uuid4()),
                    "expected_revision": view["revision"],
                },
            ).status_code
            == 403
        )
    assert (
        post(
            client,
            "/v1/auth/review/verify",
            {"purpose": "plan_edit", "resource_id": str(uuid4()), "expected_revision": "999"},
        ).status_code
        == 409
    )


@pytest.mark.parametrize("negative", ["enabled", "blocked", "revision", "role_revision", "roles"])
def test_account_negatives_still_restrict_review_and_sweeper(automatic, negative):
    _registry, _contexts, store, clock = automatic
    client, service, context = client_for(automatic, "worker1")
    assert post(client, "/v1/auth/review/login", {}).status_code == 200
    raw = client.cookies.get(SESSION_COOKIE)
    key = digest(service.issuer + "\0" + context.provider_subject)
    account = store.get("account", key)
    account[negative] = {
        "enabled": False,
        "blocked": True,
        "revision": "2",
        "role_revision": "2",
        "roles": [],
    }[negative]
    store.put("account", key, account)
    with pytest.raises(IdentityError):
        service.current(raw)
    RetentionService(store, service.custody, None, clock=clock).expire_credentials()
    assert store.get("session", digest(raw))["revoked"] is True


def test_simulation_is_disabled_by_default_and_cannot_be_attached_to_real_provider(
    identity, automatic
):
    base, _store, _provider, clock, _key = identity
    registry, contexts, _s, _c = automatic
    context = next(iter(contexts.values()))
    with pytest.raises(ValueError):
        policy_for_context(context)
    service = registry.browser_service(context.origin)
    with pytest.raises(ValueError):
        IdentityService(
            base.store,
            service.provider,
            base.custody,
            base.signer,
            base.issuer,
            context.origin,
            clock,
            review_context=context,
        )
    client = TestClient(create_app(base), base_url=base.origin)
    assert post(client, "/v1/auth/review/login", {}).status_code == 404
    raw = signed_in(base, "worker")
    clock.advance(901)
    with pytest.raises(IdentityError):
        base.current(raw)


@pytest.mark.parametrize(
    "changes",
    [
        {"origin": "https://outside.example"},
        {"environment": "production"},
        {"authentication_mode": "provider_mfa"},
        {"mode": "normal"},
        {"expires_at": None},
        {"provider_subject": "unbound"},
    ],
)
def test_policy_requires_exact_explicit_localhost_synthetic_configuration(automatic, changes):
    _registry, contexts, _store, _clock = automatic
    with pytest.raises((ValueError, IdentityError)):
        policy_for_context(replace(next(iter(contexts.values())), **changes), enabled=True)


def test_provider_exchange_binds_nonce_pkce_once_and_does_not_claim_real_factors(automatic):
    registry, contexts, _store, clock = automatic
    context = next(iter(contexts.values()))
    provider = registry.browser_service(context.origin).provider
    assert isinstance(provider, AutomaticReviewProvider)
    url = provider.authorization_url("state", "nonce", "verifier", True)
    _state, code = provider.complete(url)
    with pytest.raises(IdentityError):
        provider.exchange(code, "wrong-verifier", "nonce", True)
    with pytest.raises(IdentityError):
        provider.exchange(code, "verifier", "nonce", True)


def test_default_provider_login_and_cookie_policy_are_unchanged(identity):
    service, _store, _provider, _clock, _key = identity
    client = TestClient(create_app(service), base_url=service.origin)
    response = post(
        client, "/v1/auth/login", {"role": "pid", "return_route": "participant", "locale": "en-CA"}
    )
    assert response.status_code == 200
    assert response.json()["authorization_url"].startswith("https://issuer.test/")
    assert "X-Care-Link-Authentication-Mode" not in response.headers


def test_four_hour_cap_and_future_window_are_fail_closed(automatic):
    registry, contexts, _store, clock = automatic
    context = next(iter(contexts.values()))
    with pytest.raises(ValueError):
        policy_for_context(context, enabled=True, lifetime=timedelta(hours=4, seconds=1))
    too_long = replace(context, expires_at=stamp(clock() + timedelta(hours=5)))
    with pytest.raises(ValueError):
        policy_for_context(too_long, enabled=True)
    future = replace(context, started_at=stamp(clock() + timedelta(minutes=1)))
    policy = policy_for_context(future, enabled=True)
    with pytest.raises(IdentityError):
        policy.check(future, clock())


@pytest.mark.parametrize("mutation", ["missing_mode", "wrong_origin", "unbounded", "wrong_subject"])
def test_malformed_markers_never_exempt_privileged_idle_cleanup(automatic, mutation):
    _registry, _contexts, store, clock = automatic
    client, service, _context = client_for(automatic, "worker1")
    assert post(client, "/v1/auth/review/login", {}).status_code == 200
    raw = client.cookies.get(SESSION_COOKIE)
    row = store.get("session", digest(raw))
    if mutation == "missing_mode":
        del row["authentication_mode"]
    elif mutation == "wrong_origin":
        row["origin"] = "https://normal.example"
    elif mutation == "unbounded":
        row["review_expires_at"] = stamp(clock() + timedelta(days=20))
    else:
        row["subject"] = "unbound"
    store.put("session", digest(raw), row)
    clock.advance(901)
    assert marked_interactive_session(row, clock()) is False
    RetentionService(store, service.custody, None, clock=clock).expire_credentials()
    assert store.get("session", digest(raw))["revoked"] is True


def test_run_closed_during_exchange_cannot_replace_existing_session(automatic, monkeypatch):
    _registry, contexts, store, _clock = automatic
    client, service, context = client_for(automatic)
    assert post(client, "/v1/auth/review/login", {}).status_code == 200
    old = client.cookies.get(SESSION_COOKIE)
    exchange = service.provider.exchange

    def close_after_exchange(*args):
        result = exchange(*args)
        contexts[context.origin] = replace(context, state="closed")
        return result

    monkeypatch.setattr(service.provider, "exchange", close_after_exchange)
    result = post(client, "/v1/auth/review/login", {})
    assert result.status_code == 401
    assert client.cookies.get(SESSION_COOKIE) == old
    assert store.get("session", digest(old))["revoked"] is False


def test_revocation_is_local_to_one_automatic_slot_and_session(automatic):
    first, service, _context = client_for(automatic, "pid")
    other, other_service, _other_context = client_for(automatic, "carer")
    assert post(first, "/v1/auth/review/login", {}).status_code == 200
    assert post(other, "/v1/auth/review/login", {}).status_code == 200
    raw = first.cookies.get(SESSION_COOKIE)
    service.logout(raw, str(uuid4()))
    with pytest.raises(IdentityError):
        service.current(raw)
    assert other_service.current(other.cookies.get(SESSION_COOKIE))["role"] == "carer"


def test_idle_exemption_never_exempts_missing_simulated_mfa_marker(automatic):
    _registry, _contexts, store, clock = automatic
    client, service, _context = client_for(automatic, "worker1")
    assert post(client, "/v1/auth/review/login", {}).status_code == 200
    raw = client.cookies.get(SESSION_COOKIE)
    row = store.get("session", digest(raw))
    row["mfa"] = False
    store.put("session", digest(raw), row)
    assert marked_interactive_session(row, clock()) is False
    with pytest.raises(IdentityError):
        service.current(raw)
    RetentionService(store, service.custody, None, clock=clock).expire_credentials()
    assert store.get("session", digest(raw))["revoked"] is True
