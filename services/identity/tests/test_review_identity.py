"""Review actors share durable custody, never browser origin/session authority."""

from dataclasses import replace
from uuid import uuid4

import pytest
from care_link_core.manual_identity import actor_record, parse_actor
from care_link_identity import Principal
from care_link_identity.app import BINDING_COOKIE, create_app
from care_link_identity.crypto import digest
from care_link_identity.domain import IdentityError
from care_link_identity.manual import ManualIdentityAuthority
from care_link_identity.manual_runtime import PREFIX, create_manual_identity_app
from care_link_identity.review import ReviewIdentityRegistry
from care_link_identity.review_context import ReviewContext
from starlette.testclient import TestClient


class ReviewProvider:
    def __init__(self, clock, subject):
        self.clock, self.subject = clock, subject
        self.fresh = []
        self.revoked = set()
        self.exchanges = 0

    def authorization_url(self, state, nonce, verifier, fresh):
        self.fresh.append(fresh)
        return "https://issuer.test/authorize?state=" + state

    def exchange(self, code, verifier, nonce, fresh):
        self.fresh.append(fresh)
        self.exchanges += 1
        return Principal(
            self.subject,
            self.clock(),
            True,
            ("pwd", "otp"),
            "access-" + self.subject + "-" + str(self.exchanges),
            self.clock().replace(year=self.clock().year + 1),
        )

    def active(self, access_token, subject):
        return access_token not in self.revoked and subject == self.subject

    def revoke(self, access_token):
        self.revoked.add(access_token)


@pytest.fixture
def review(identity):
    base, store, _provider, clock, _key = identity
    run = str(uuid4())
    contexts, providers = {}, {}
    for slot, role in (("participant", "pid"), ("worker1", "worker"), ("worker2", "worker")):
        origin, account, subject = "https://" + slot + ".test", str(uuid4()), "subject-" + slot
        base.provision(subject, account, [role])
        contexts[origin] = ReviewContext(origin, run, slot, account, role, subject)
        providers[origin] = ReviewProvider(clock, subject)
    registry = ReviewIdentityRegistry(base, lambda: contexts, providers.__getitem__)
    return registry, contexts, providers, store


def login(service, binding="binding"):
    _view, state = service.login_start(service.review_context.role, binding)
    view, raw, _proof = service.callback(state, "code", binding)
    assert raw
    return view, raw


def test_exact_actor_context_survives_fresh_service_and_actor_serialization(review):
    registry, contexts, providers, _store = review
    service = registry.browser_service("https://participant.test")
    view, raw = login(service)
    assert providers[service.origin].fresh == [True, True]
    assert view["review_run_id"] == contexts[service.origin].run_id
    actor = ManualIdentityAuthority(registry.session_service(raw)).authenticate(raw)
    assert actor.review_origin == service.origin
    assert actor.review_slot_id == "participant"
    assert parse_actor(actor_record(actor)) == actor
    with pytest.raises(IdentityError):
        registry.base.current(raw)


def test_role_and_same_role_wrong_account_never_replace_existing_session(review):
    registry, _contexts, providers, store = review
    service = registry.browser_service("https://worker1.test")
    _view, raw = login(service)
    with pytest.raises(IdentityError, match="review_actor_mismatch"):
        service.login_start("pid", "binding")
    _intent, state = service.login_start("worker", "binding", previous_raw_session=raw)
    providers[service.origin].subject = "subject-worker2"
    with pytest.raises(IdentityError, match="account_unavailable"):
        service.callback(state, "wrong-account-code", "binding")
    assert store.get("session", digest(raw))["revoked"] is False


def test_callback_cannot_cross_origin_even_with_copied_binding(review):
    registry, _contexts, _providers, _store = review
    participant = registry.browser_service("https://participant.test")
    worker = registry.browser_service("https://worker1.test")
    _intent, state = participant.login_start("pid", "shared-binding")
    with pytest.raises(IdentityError, match="invalid_login_intent"):
        worker.callback(state, "code", "shared-binding")
    _view, raw, _proof = participant.callback(state, "code", "shared-binding")
    assert raw


def test_abandoned_same_slot_login_is_superseded_by_explicit_restart(review):
    registry, _contexts, _providers, store = review
    service = registry.browser_service("https://worker1.test")
    _first, old_state = service.login_start("worker", "binding")
    _second, new_state = service.login_start("worker", "binding")
    assert store.get("intent", digest(old_state))["state"] == "superseded"
    with pytest.raises(IdentityError, match="invalid_login_intent"):
        service.callback(old_state, "late-old-code", "binding")
    _view, raw, _proof = service.callback(new_state, "current-code", "binding")
    assert raw and service.current(raw)["review_slot_id"] == "worker1"


def test_slot_signout_does_not_revoke_another_origin(review):
    registry, _contexts, _providers, _store = review
    participant, worker = [
        registry.browser_service(origin)
        for origin in ["https://participant.test", "https://worker1.test"]
    ]
    _pv, participant_raw = login(participant)
    _wv, worker_raw = login(worker)
    participant.logout(participant_raw, str(uuid4()))
    assert worker.current(worker_raw)["review_slot_id"] == "worker1"
    with pytest.raises(IdentityError):
        participant.current(participant_raw)


def test_current_registry_rebinding_cannot_reuse_old_session(review):
    registry, contexts, _providers, _store = review
    service = registry.browser_service("https://participant.test")
    _view, raw = login(service)
    contexts[service.origin] = replace(contexts[service.origin], run_id=str(uuid4()))
    with pytest.raises(IdentityError, match="review_context_changed"):
        registry.session_service(raw)


def test_anonymous_bootstrap_preserves_existing_review_binding(review):
    registry, _contexts, _providers, _store = review
    service = registry.browser_service("https://participant.test")
    client = TestClient(create_app(service), base_url=service.origin)
    first = client.get("/v1/auth/csrf")
    binding = client.cookies.get(BINDING_COOKIE)
    second = client.get("/v1/auth/csrf")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert client.cookies.get(BINDING_COOKIE) == binding
    assert "set-cookie" not in second.headers


def test_internal_authentication_selects_durable_origin(review):
    registry, contexts, _providers, _store = review
    _view, raw = login(registry.browser_service("https://worker2.test"))
    app = create_manual_identity_app(
        registry.base,
        lambda _request, _peer: True,
        service_for_session=registry.session_service,
    )
    client = TestClient(app)
    response = client.post(PREFIX + "authenticate", json={"raw_session": raw})
    assert response.status_code == 200
    actor = parse_actor(response.json())
    assert actor.account_id == contexts["https://worker2.test"].account_id
    assert actor.review_slot_id == "worker2"
    assert actor.review_origin == "https://worker2.test"


@pytest.mark.parametrize(
    "change", [{"origin": "http://worker1.test"}, {"slot_id": "supervisor"}, {"state": "reset"}]
)
def test_review_context_rejects_ambiguous_authority(review, change):
    _registry, contexts, _providers, _store = review
    with pytest.raises(ValueError):
        replace(contexts["https://worker1.test"], **change)


def test_browser_session_exposes_verified_context_and_host_only_cookie(review):
    registry, contexts, _providers, _store = review
    origin = "https://participant.test"
    service = registry.browser_service(origin)
    _view, raw = login(service)
    client = TestClient(create_app(service), base_url=origin)
    response = client.get("/v1/auth/session", headers={"Cookie": "__Host-care-link-session=" + raw})
    assert response.status_code == 200
    assert response.json()["review_run_id"] == contexts[origin].run_id
    assert response.json()["review_slot_id"] == "participant"
    assert response.json()["review_origin"] == origin


def test_signed_identity_proof_keeps_context_and_rejects_current_rebinding(review):
    registry, contexts, _providers, _store = review
    origin = "https://worker1.test"
    _view, raw = login(registry.browser_service(origin))
    app = create_manual_identity_app(
        registry.base,
        lambda _request, _peer: True,
        service_for_session=registry.session_service,
    )
    client = TestClient(app)
    response = client.post(
        PREFIX + "evidence",
        json={
            "raw_session": raw,
            "transport_generation": "17",
            "action": "session_read",
            "request_digest": "a" * 64,
            "nonce": str(uuid4()),
            "resource_id": str(uuid4()),
        },
    )
    assert response.status_code == 200, response.text
    evidence = response.json()
    assert evidence["review_run_id"] == contexts[origin].run_id
    response = client.post(PREFIX + "resolve", json={"evidence": evidence})
    assert response.status_code == 200
    actor = parse_actor(response.json())
    assert actor.review_run_id == contexts[origin].run_id
    assert actor.review_slot_id == "worker1"
    assert actor.review_origin == origin
    changed = {**evidence, "review_run_id": str(uuid4())}
    assert client.post(PREFIX + "resolve", json={"evidence": changed}).status_code == 403
    contexts[origin] = replace(contexts[origin], run_id=str(uuid4()))
    assert (
        client.post(PREFIX + "current", json={"credential_ref": evidence["id"]}).status_code == 401
    )


def test_late_redeeming_callback_cannot_revoke_or_replace_newer_session(review, monkeypatch):
    registry, _contexts, providers, store = review
    service = registry.browser_service("https://worker1.test")
    _view, predecessor = login(service)
    _intent, old_state = service.login_start("worker", "binding", previous_raw_session=predecessor)
    provider = providers[service.origin]
    exchange = provider.exchange
    newer = {}

    def interleaved(code, verifier, nonce, fresh):
        principal = exchange(code, verifier, nonce, fresh)
        if code == "old-code":
            newer["discarded_token"] = principal.access_token
            _next_intent, new_state = service.login_start(
                "worker", "binding", previous_raw_session=predecessor
            )
            _next_view, new_raw, _proof = service.callback(new_state, "new-code", "binding")
            newer["raw"] = new_raw
        return principal

    monkeypatch.setattr(provider, "exchange", interleaved)
    with pytest.raises(IdentityError, match="login_superseded"):
        service.callback(old_state, "old-code", "binding")
    assert newer["discarded_token"] in provider.revoked
    assert store.get("session", digest(predecessor))["revoked"] is True
    assert store.get("session", digest(newer["raw"]))["revoked"] is False
    assert service.current(newer["raw"])["account_id"] == service.review_context.account_id


def test_wrong_account_callback_returns_fixed_token_free_review_page(review):
    registry, _contexts, providers, _store = review
    service = registry.browser_service("https://worker1.test")
    _intent, state = service.login_start("worker", "binding")
    providers[service.origin].subject = "subject-worker2"
    client = TestClient(
        create_app(service, ui_return_url=service.origin + "/"), base_url=service.origin
    )
    client.cookies.set(BINDING_COOKIE, "binding", domain="worker1.test")
    response = client.get(
        "/v1/auth/callback",
        params={"state": state, "code": "synthetic-private-code"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == service.origin + "/?auth_error=sign_in_interrupted"
    assert "synthetic-private-code" not in response.text + response.headers["location"]
    assert state not in response.headers["location"]
    assert "__Host-care-link-session" not in response.headers.get("set-cookie", "")
    assert response.headers["referrer-policy"] == "no-referrer"
