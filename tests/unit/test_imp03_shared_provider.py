"""Source-only provider control checks; MockTransport is not issued identity evidence."""

import json

import httpx
import pytest

from tools.imp03_shared import provider


@pytest.fixture
def state_path(tmp_path):
    tmp_path.chmod(0o700)
    return tmp_path / "provider.json"


def operator_client(
    state,
    *,
    existing=False,
    foreign=False,
    creation_status=201,
    credential_types=("password", "otp"),
):
    requests = []
    document = provider.realm_document(state)
    created = existing

    def handle(request):
        nonlocal created
        requests.append(request)
        path = request.url.path
        if path == "/realms/master/protocol/openid-connect/token":
            return httpx.Response(200, json={"access_token": "fixture-admin-token"})
        if path == "/admin/realms/care-link-imp03":
            if not created:
                return httpx.Response(404, json={"error": "not found"})
            realm = dict(document)
            if foreign:
                realm["attributes"] = {"care-link.imp03-binding": "foreign-binding"}
            return httpx.Response(200, json=realm)
        if path == "/admin/realms" and request.method == "POST":
            created = creation_status == 201
            return httpx.Response(creation_status)
        client = state["client"]
        if path == f"/admin/realms/care-link-imp03/clients/{client['id']}":
            return httpx.Response(200, json=document["clients"][0])
        if path.endswith("/client-secret"):
            return httpx.Response(200, json={"value": client["secret"]})
        for actor in document["users"]:
            if path == f"/admin/realms/care-link-imp03/users/{actor['id']}":
                return httpx.Response(200, json=actor)
            if path == f"/admin/realms/care-link-imp03/users/{actor['id']}/credentials":
                return httpx.Response(200, json=[{"type": kind} for kind in credential_types])
        raise AssertionError("Unexpected provider endpoint")

    return httpx.Client(transport=httpx.MockTransport(handle)), requests


def test_private_state_is_stable_distinct_and_bound_to_exact_target(state_path):
    state = provider.private_state(state_path)
    assert state_path.stat().st_mode & 0o777 == 0o600
    assert provider.private_state(state_path) == state
    users = list(state["users"].values())
    assert len({user["account_id"] for user in users}) == 3
    assert len({user["id"] for user in users}) == 3
    assert len({user["password"] for user in users}) == 3
    assert len({user["totp_secret"] for user in users}) == 3
    assert [user["roles"] for user in users] == [["pid"], ["worker"], ["supervisor"]]
    with pytest.raises(ValueError, match="different immutable targets"):
        provider.private_state(state_path, "https://different.localhost:28443")


@pytest.mark.parametrize("mode", [0o644, 0o640])
def test_existing_nonprivate_state_is_refused(state_path, mode):
    provider.private_state(state_path)
    state_path.chmod(mode)
    with pytest.raises(ValueError, match="regular0600"):
        provider.private_state(state_path)


def test_state_symlink_and_nonprivate_parent_are_refused(state_path):
    target = state_path.parent / "target.json"
    state_path.symlink_to(target)
    with pytest.raises(ValueError, match="regular0600"):
        provider.private_state(state_path)
    state_path.unlink()
    state_path.parent.chmod(0o755)
    with pytest.raises(ValueError, match="owner-only0700"):
        provider.private_state(state_path)
    assert not state_path.exists()


def test_duplicate_or_reassigned_private_account_is_not_adopted(state_path):
    state = provider.private_state(state_path)
    state["users"]["worker"]["id"] = state["users"]["participant"]["id"]
    state_path.write_text(json.dumps(state))
    with pytest.raises(ValueError, match="must be distinct"):
        provider.private_state(state_path)


def test_import_uses_real_authenticators_and_distinct_audiences(state_path):
    state = provider.private_state(state_path)
    document = provider.realm_document(state)
    client = document["clients"][0]
    assert document["realm"] == "care-link-imp03"
    assert document["browserFlow"] == "care-link-imp03-browser"
    assert len(document["clients"]) == 1
    assert client["clientId"] == "care-link-imp03-browser"
    assert client["redirectUris"] == [provider.MAIN + "/v1/auth/callback"]
    assert client["directAccessGrantsEnabled"] is False
    assert client["serviceAccountsEnabled"] is False
    mapper_ids = {mapper["protocolMapper"] for mapper in client["protocolMappers"]}
    assert {"oidc-sub-mapper", "oidc-amr-mapper", "oidc-acr-mapper"} <= mapper_ids
    assert not any("hardcoded" in mapper for mapper in mapper_ids)
    assert [
        step["authenticator"]
        for step in document["authenticationFlows"][1]["authenticationExecutions"]
    ] == ["conditional-level-of-authentication", "auth-username-password-form", "auth-otp-form"]
    for actor in document["users"]:
        assert [credential["type"] for credential in actor["credentials"]] == ["password", "otp"]
    oidc = provider.oidc_settings(state)
    assert oidc["resource_audience"] != oidc["client_id"]
    assert oidc["issuer"] == provider.BASE + "/realms/care-link-imp03"
    assert oidc["mfa_acr"] == "2"


def test_fresh_bootstrap_preflights_and_only_creates_new_realm(state_path):
    state = provider.private_state(state_path)
    client, requests = operator_client(state)
    assert provider.bootstrap(client, "fixture-admin-password", state_path) == state
    writes = [request for request in requests if request.method != "GET"]
    assert [str(request.url) for request in writes] == [
        provider.BASE + "/realms/master/protocol/openid-connect/token",
        provider.BASE + "/admin/realms",
    ]
    assert requests[1].method == "GET" and requests[1].url.path.endswith("care-link-imp03")
    assert json.loads(writes[1].content)["realm"] == "care-link-imp03"
    assert not any("care-link-imp02" in str(request.url) for request in requests)


def test_existing_foreign_realm_is_refused_without_provider_mutation(state_path):
    state = provider.private_state(state_path)
    client, requests = operator_client(state, existing=True, foreign=True)
    with pytest.raises(ValueError, match="outside persisted IMP-03 binding"):
        provider.bootstrap(client, "fixture-admin-password", state_path)
    assert [request.method for request in requests] == ["POST", "GET"]


def test_existing_exact_binding_is_verified_without_reconciliation(state_path):
    state = provider.private_state(state_path)
    client, requests = operator_client(state, existing=True)
    provider.bootstrap(client, "fixture-admin-password", state_path)
    assert all(request.method == "GET" for request in requests[1:])


def test_creation_race_is_not_adopted_or_retried(state_path):
    state = provider.private_state(state_path)
    client, requests = operator_client(state, creation_status=409)
    with pytest.raises(ValueError, match="creation refused"):
        provider.bootstrap(client, "fixture-admin-password", state_path)
    assert len(requests) == 3


def test_provider_redirects_and_error_bodies_never_become_success(state_path):
    def rejected(request):
        return httpx.Response(
            302,
            headers={"location": "https://elsewhere.invalid/"},
            json={"private": "fixture-private-message"},
        )

    client = httpx.Client(transport=httpx.MockTransport(rejected), follow_redirects=True)
    with pytest.raises(ValueError, match="must not follow redirects"):
        provider.bootstrap(client, "fixture-admin-password", state_path)
    client = httpx.Client(transport=httpx.MockTransport(rejected))
    with pytest.raises(ValueError) as error:
        provider.bootstrap(client, "fixture-admin-password", state_path)
    assert "fixture-private-message" not in str(error.value)


def test_registry_and_private_browser_config_keep_subject_account_bindings(state_path):
    state = provider.private_state(state_path)
    registry = provider.actor_registry(state)
    browser = provider.browser_config(
        state,
        help_origin="https://help.localhost:19443",
        static_origin="https://static.localhost:21443",
    )
    assert browser["ignoreHTTPSErrors"] is False
    assert registry[0]["subject"] == state["users"]["participant"]["id"]
    assert registry[0]["account_id"] == browser["accounts"]["pid"]
    assert browser["participant"]["username"] != browser["supervisor"]["username"]
    summary = json.dumps(provider.public_summary(state))
    assert state["client"]["secret"] not in summary
    assert all(actor["password"] not in summary for actor in state["users"].values())
    with pytest.raises(ValueError, match="cookie hostnames"):
        provider.browser_config(
            state, help_origin=provider.MAIN, static_origin="https://static.localhost:21443"
        )


@pytest.mark.parametrize("credential_types", [("password",), ("otp",), ()])
def test_incomplete_issued_mfa_is_refused_without_provider_repair(state_path, credential_types):
    state = provider.private_state(state_path)
    client, requests = operator_client(state, existing=True, credential_types=credential_types)
    with pytest.raises(ValueError, match="password and OTP credentials required"):
        provider.bootstrap(client, "fixture-admin-password", state_path)
    assert all(request.method == "GET" for request in requests[1:])
