"""Real signed-token validation for private same-authority per-slot issuer profiles."""

import json
from dataclasses import asdict, replace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
from care_link_identity import IdentityService
from care_link_identity.crypto import digest
from care_link_identity.domain import IdentityError
from care_link_identity.manual_runtime import PREFIX, create_manual_identity_app
from care_link_identity.review import ReviewIdentityRegistry
from care_link_identity.review_context import ReviewContext
from care_link_identity.review_providers import ReviewProviders
from starlette.testclient import TestClient
from test_provider import jwt_fixture


def configured(identity, tmp_path):
    original, _store, _fake, clock, _key = identity
    provider, data = jwt_fixture()
    base = IdentityService(
        original.store,
        provider,
        original.custody,
        original.signer,
        provider.config.issuer,
        original.origin,
        clock,
    )
    subject, account = str(uuid4()), str(uuid4())
    context = ReviewContext(
        "https://worker.test", str(uuid4()), "worker1", account, "worker", subject
    )
    contexts = {context.origin: context}
    profile = replace(
        provider.config,
        issuer="https://issuer.test/realms/review-worker1",
        client_id="review-worker1-browser",
        client_secret=uuid4().hex,
        resource_audience="review-worker1-resource",
        authorization_endpoint="https://issuer.test/realms/review-worker1/auth",
    )
    path = tmp_path / "private-providers.json"
    path.write_text(json.dumps({subject: asdict(profile)}))
    path.chmod(0o600)
    selection = ReviewProviders(provider, lambda: contexts, path)
    registry = ReviewIdentityRegistry(base, lambda: contexts, selection)
    data["id_claims"].update(iss=profile.issuer, aud=profile.client_id, sub=subject)
    data["access_claims"].update(iss=profile.issuer, aud=profile.resource_audience, sub=subject)
    return registry, selection, context, profile, path, data


def test_context_selects_exact_issuer_client_and_callback(identity, tmp_path):
    registry, _selection, context, profile, _path, _data = configured(identity, tmp_path)
    selected = registry.browser_service(context.origin)
    assert selected.issuer == profile.issuer != registry.base.issuer
    assert selected.provider.config.client_id == profile.client_id
    query = parse_qs(
        urlsplit(selected.provider.authorization_url("state", "nonce", "verifier", True)).query
    )
    assert query["redirect_uri"] == [context.origin + "/v1/auth/callback"]
    assert query["client_id"] == [profile.client_id]
    assert (
        urlsplit(selected.provider.authorization_url("state", "nonce", "verifier", True)).path
        == "/realms/review-worker1/auth"
    )


def test_real_tokens_bind_issuer_audience_and_issued_slot_subject(identity, tmp_path):
    registry, _selection, context, profile, _path, data = configured(identity, tmp_path)
    selected = registry.browser_service(context.origin)
    assert (
        selected.provider.exchange("code", "verifier", "nonce", True).subject
        == context.provider_subject
    )
    data["id_claims"]["iss"] = registry.base.issuer
    with pytest.raises(IdentityError):
        selected.provider.exchange("wrong-realm", "verifier", "nonce", True)
    data["id_claims"]["iss"] = profile.issuer
    data["id_claims"]["aud"] = "other-slot-client"
    with pytest.raises(IdentityError):
        selected.provider.exchange("wrong-client", "verifier", "nonce", True)
    data["id_claims"]["aud"] = profile.client_id
    data["access_claims"]["sub"] = str(uuid4())
    with pytest.raises(IdentityError):
        selected.provider.exchange("wrong-subject", "verifier", "nonce", True)


def test_current_session_uses_per_issuer_account_and_provider(identity, tmp_path, monkeypatch):
    registry, _selection, context, profile, _path, data = configured(identity, tmp_path)
    selected = registry.browser_service(context.origin)
    selected.provision(context.provider_subject, context.account_id, [context.role])
    intent, state = selected.login_start("worker", "binding")
    data["id_claims"]["nonce"] = selected.store.get("intent", digest(state))["nonce"]
    _view, raw, _proof = selected.callback(state, "code", "binding", returned_issuer=profile.issuer)
    assert raw
    observed = []
    post = registry.base.provider.client.post

    def introspect(url, *args, **kwargs):
        if str(url).endswith("/introspect"):
            observed.append(str(url))
            return httpx.Response(
                200,
                json={"active": True, "sub": context.provider_subject},
                request=httpx.Request("POST", str(url)),
            )
        return post(url, *args, **kwargs)

    monkeypatch.setattr(registry.base.provider.client, "post", introspect)
    current = registry.session_service(raw)
    assert current.issuer == profile.issuer
    assert current.current(raw)["account_id"] == context.account_id
    assert current.store.get("session", digest(raw))["provider_issuer"] == profile.issuer
    assert observed == [profile.introspection_endpoint]
    client = TestClient(
        create_manual_identity_app(
            registry.base,
            lambda _request, _peer: True,
            service_for_session=registry.session_service,
        )
    )
    proof = client.post(
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
    assert proof.status_code == 200
    resolved = client.post(PREFIX + "resolve", json={"evidence": proof.json()})
    assert resolved.status_code == 200
    assert resolved.json()["review_slot_id"] == context.slot_id
    current_response = client.post(PREFIX + "current", json={"credential_ref": proof.json()["id"]})
    assert current_response.status_code == 200
    assert current_response.json()["review_origin"] == context.origin
    assert all(url == profile.introspection_endpoint for url in observed)
    assert intent["authorization_url"].startswith(profile.authorization_endpoint)
    with pytest.raises(IdentityError):
        registry.base.current(raw)


def test_updated_private_catalog_cannot_reinterpret_an_old_review_session(identity, tmp_path):
    registry, _selection, context, profile, path, data = configured(identity, tmp_path)
    selected = registry.browser_service(context.origin)
    selected.provision(context.provider_subject, context.account_id, [context.role])
    _intent, state = selected.login_start("worker", "binding")
    data["id_claims"]["nonce"] = selected.store.get("intent", digest(state))["nonce"]
    _view, raw, _proof = selected.callback(state, "code", "binding")
    replacement = replace(profile, issuer="https://issuer.test/realms/review-worker2")
    path.write_text(json.dumps({context.provider_subject: asdict(replacement)}))
    current = registry.session_service(raw)
    assert current.issuer == replacement.issuer
    with pytest.raises(IdentityError, match="session_unavailable"):
        current.current(raw)


def test_unlisted_subject_retains_base_provider_for_participant_compatibility(identity, tmp_path):
    registry, selection, context, _profile, path, _data = configured(identity, tmp_path)
    path.write_text("{}")
    assert selection(context.origin).config.issuer == registry.base.issuer
    assert registry.browser_service(context.origin).issuer == registry.base.issuer


@pytest.mark.parametrize("change", ["permissions", "symlink", "different_origin", "unknown_field"])
def test_private_catalog_rejects_unowned_or_broadened_configuration(identity, tmp_path, change):
    _registry, selection, context, profile, path, _data = configured(identity, tmp_path)
    if change == "permissions":
        path.chmod(0o644)
    elif change == "symlink":
        real = path.with_suffix(".retained")
        path.rename(real)
        path.symlink_to(real)
    else:
        value = asdict(profile)
        if change == "different_origin":
            value["issuer"] = "https://different-provider.test/realms/worker"
            for key in (
                "authorization_endpoint",
                "token_endpoint",
                "jwks_uri",
                "introspection_endpoint",
                "revocation_endpoint",
            ):
                value[key] = value[key].replace("issuer.test", "different-provider.test")
        else:
            value["caller_selected_issuer"] = "https://different-provider.test"
        path.write_text(json.dumps({context.provider_subject: value}))
    with pytest.raises(IdentityError, match="review_provider_catalog_unavailable"):
        selection(context.origin)


def test_public_offline_provisioning_needs_only_owned_store_and_exact_binding(identity):
    from care_link_identity import provision_account
    from conftest import MemoryStore

    store = MemoryStore()
    issuer, subject, account = "https://issuer.test/realms/new-worker", str(uuid4()), str(uuid4())
    provision_account(store, issuer, subject, account, ["worker"], clock=identity[3])
    saved = store.get("account", digest(issuer + "\0" + subject))
    assert saved["account_id"] == account and saved["roles"] == ["worker"]
    with pytest.raises(IdentityError, match="provision_conflict") as error:
        provision_account(store, issuer, subject, account, ["worker"], clock=identity[3])
    assert error.value.status == 409
    with pytest.raises(IdentityError, match="invalid_role"):
        provision_account(store, issuer, str(uuid4()), str(uuid4()), ["invented-authority"])
