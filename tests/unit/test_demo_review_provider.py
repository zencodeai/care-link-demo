"""Provider adapter fixture tests; real signed code exchange, no live provider mutations."""

import base64
import hashlib
import json
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from tools.demo.secrets import totp
from tools.imp03_shared.review_provider import (
    BASE,
    CLIENT,
    ISSUER,
    LEGACY_ORIGIN,
    REALM,
    ProviderAdmin,
    ReviewProviderError,
)


class ProviderFixture:
    def __init__(self) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.seed = base64.b32encode(b"12345678901234567890").decode()
        roles = {
            "participant": "pid",
            "worker": "worker",
            "worker2": "worker",
            "supervisor": "supervisor",
            "security": "security",
        }
        self.state = {
            "session": "imp03-003",
            "realm": REALM,
            "binding": str(uuid4()),
            "main_origin": LEGACY_ORIGIN,
            "client": {
                "id": str(uuid4()),
                "client_id": CLIENT,
                "secret": "private-client-secret-" * 3,
            },
            "users": {
                slot: {
                    "id": str(uuid4()),
                    "account_id": str(uuid4()),
                    "username": "imp03-" + slot,
                    "password": "old-provider-password-" * 3,
                    "totp_secret": self.seed,
                    "roles": [role],
                }
                for slot, role in roles.items()
            },
        }
        self.actor = self.state["users"]["worker"]
        self.client = {
            "id": self.state["client"]["id"],
            "clientId": CLIENT,
            "enabled": True,
            "protocol": "openid-connect",
            "publicClient": False,
            "standardFlowEnabled": True,
            "implicitFlowEnabled": False,
            "directAccessGrantsEnabled": False,
            "serviceAccountsEnabled": False,
            "fullScopeAllowed": False,
            "attributes": {"pkce.code.challenge.method": "S256"},
            "redirectUris": [LEGACY_ORIGIN + "/v1/auth/callback"],
            "webOrigins": [LEGACY_ORIGIN],
        }
        self.binding = self.state["binding"]
        self.origin_ack = 204
        self.password_ack = 204
        self.password = self.actor["password"]
        self.password_writes = 0
        self.origin_writes = 0
        self.revocations = 0
        self.fresh_proofs = 0
        self.wrong_subject = False
        self.reject_password = False
        self.foreign_form = False
        self.foreign_redirect = False
        self.callback_state_mismatch = False
        self.requests: list[httpx.Request] = []
        self.virtual_now = time.time()
        self.flow: dict[str, str] = {}

    def client_factory(self) -> httpx.Client:
        return httpx.Client(
            transport=httpx.MockTransport(self.request), follow_redirects=False, trust_env=False
        )

    def sleep(self, seconds: float) -> None:
        self.virtual_now += seconds

    def adapter(self, state=None) -> ProviderAdmin:
        return ProviderAdmin(
            state or self.state,
            "private-admin-password",
            Path("/not-used-fixture-ca"),
            client_factory=self.client_factory,
            clock=lambda: self.virtual_now,
            sleep=self.sleep,
        )

    def form(self, otp: bool = False) -> httpx.Response:
        target = (
            BASE
            + "/realms/"
            + REALM
            + "/login-actions/authenticate?execution="
            + ("otp" if otp else "password")
        )
        if self.foreign_form:
            target = "https://untrusted.invalid/collect"
        fields = (
            '<input name="otp"/>'
            if otp
            else '<input name="username"/><input type="password" name="password"/>'
        )
        return httpx.Response(
            200,
            text='<form method="post" action="'
            + target
            + '"><input type="hidden" name="credentialId" value="fixture"/>'
            + fields
            + "</form>",
            headers={"content-type": "text/html"},
        )

    def request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert str(request.url).startswith(BASE + "/")
        path = request.url.path
        realm_admin = "/admin/realms/" + REALM
        if path == "/realms/master/protocol/openid-connect/token":
            return httpx.Response(200, json={"access_token": "fixture-admin-token"})
        if path == realm_admin:
            return httpx.Response(
                200, json={"realm": REALM, "attributes": {"care-link.imp03-binding": self.binding}}
            )
        if path == realm_admin + "/clients/" + self.client["id"] + "/client-secret":
            return httpx.Response(200, json={"value": self.state["client"]["secret"]})
        if path == realm_admin + "/clients/" + self.client["id"]:
            if request.method == "PUT":
                self.origin_writes += 1
                if self.origin_ack == 204:
                    self.client = json.loads(request.content)
                    # Keycloak returns these set-valued fields in its own order.
                    self.client["redirectUris"].reverse()
                    self.client["webOrigins"].reverse()
                return httpx.Response(self.origin_ack)
            return httpx.Response(200, json=self.client)
        user_path = realm_admin + "/users/" + self.actor["id"]
        if path == user_path:
            return httpx.Response(
                200,
                json={
                    "id": self.actor["id"],
                    "username": self.actor["username"],
                    "enabled": True,
                    "requiredActions": [],
                },
            )
        if path == user_path + "/credentials":
            return httpx.Response(200, json=[{"type": "password"}, {"type": "otp"}])
        if path == user_path + "/reset-password":
            self.password_writes += 1
            if self.password_ack == 204:
                value = json.loads(request.content)
                assert value["type"] == "password" and value["temporary"] is False
                self.password = value["value"]
            return httpx.Response(self.password_ack)
        if path == "/realms/" + REALM + "/protocol/openid-connect/auth":
            self.flow = {
                key: values[0] for key, values in parse_qs(request.url.query.decode()).items()
            }
            assert self.flow["prompt"] == "login" and self.flow["max_age"] == "0"
            if self.foreign_redirect:
                return httpx.Response(
                    302, headers={"location": "https://untrusted.invalid/redirect"}
                )
            return self.form()
        if path == "/realms/" + REALM + "/login-actions/authenticate":
            values = parse_qs(request.content.decode())
            if request.url.params["execution"] == "password":
                assert values["username"] == [self.actor["username"]]
                if values["password"] != [self.password] or self.reject_password:
                    return self.form()
                return self.form(otp=True)
            assert values["otp"] == [totp(self.seed, now=self.virtual_now)[0]]
            params = {
                "code": "fixture-code",
                "state": "wrong-state" if self.callback_state_mismatch else self.flow["state"],
                "iss": ISSUER,
            }
            return httpx.Response(
                302, headers={"location": LEGACY_ORIGIN + "/v1/auth/callback?" + urlencode(params)}
            )
        if path.endswith("/protocol/openid-connect/token"):
            values = parse_qs(request.content.decode())
            assert values["grant_type"] == ["authorization_code"]
            assert (
                base64.urlsafe_b64encode(
                    hashlib.sha256(values["code_verifier"][0].encode()).digest()
                )
                .rstrip(b"=")
                .decode()
                == self.flow["code_challenge"]
            )
            self.fresh_proofs += 1
            now = int(time.time())
            subject = str(uuid4()) if self.wrong_subject else self.actor["id"]
            common = {
                "iss": ISSUER,
                "sub": subject,
                "iat": now,
                "exp": now + 120,
                "auth_time": now,
                "acr": "2",
                "amr": ["pwd", "otp"],
            }
            id_token = jwt.encode(
                {**common, "aud": CLIENT, "nonce": self.flow["nonce"]},
                self.key,
                algorithm="RS256",
                headers={"kid": "fixture", "typ": "JWT"},
            )
            access_token = jwt.encode(
                {**common, "aud": REALM + "-resource"},
                self.key,
                algorithm="RS256",
                headers={"kid": "fixture", "typ": "JWT"},
            )
            return httpx.Response(
                200,
                json={"id_token": id_token, "access_token": access_token, "token_type": "Bearer"},
            )
        if path.endswith("/protocol/openid-connect/certs"):
            key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
            return httpx.Response(
                200,
                json={
                    "keys": [
                        {
                            **key,
                            "kid": "fixture",
                            "alg": "RS256",
                            "use": "sig",
                            "key_ops": ["verify"],
                        }
                    ]
                },
            )
        if path.endswith("/protocol/openid-connect/token/introspect"):
            return httpx.Response(200, json={"active": True, "sub": self.actor["id"]})
        if path.endswith("/protocol/openid-connect/revoke"):
            self.revocations += 1
            return httpx.Response(200)
        raise AssertionError("unexpected fixture route")


def test_origin_registration_preserves_exact_old_origins_and_is_idempotent() -> None:
    fixture = ProviderFixture()
    origins = ["https://r" + uuid4().hex + "-worker1.qualification.localhost:29443"]
    adapter = fixture.adapter()
    assert adapter.install_origins(origins)["verified"] is True
    assert sorted(fixture.client["redirectUris"]) == sorted(
        [LEGACY_ORIGIN + "/v1/auth/callback", origins[0] + "/v1/auth/callback"]
    )
    adapter.install_origins(origins)
    assert fixture.origin_writes == 1
    assert fixture.client["directAccessGrantsEnabled"] is False


def test_foreign_realm_or_wildcard_callback_refuses_before_write() -> None:
    fixture = ProviderFixture()
    with pytest.raises(ReviewProviderError, match="provider_realm_outside_lease"):
        fixture.adapter({**fixture.state, "realm": "care-link-imp02"})
    fixture.client["redirectUris"] = [LEGACY_ORIGIN + "/*"]
    with pytest.raises(ReviewProviderError, match="provider_origins_invalid"):
        fixture.adapter().install_origins([LEGACY_ORIGIN])
    assert fixture.origin_writes == 0
    assert fixture.password_writes == 0


def test_changed_persisted_binding_denies_without_write() -> None:
    fixture = ProviderFixture()
    fixture.binding = str(uuid4())
    with pytest.raises(ReviewProviderError, match="provider_realm_binding_changed"):
        fixture.adapter().install_origins([LEGACY_ORIGIN])
    assert fixture.origin_writes == 0


def test_missing_admin_ack_does_not_become_verification() -> None:
    fixture = ProviderFixture()
    fixture.password_ack = 500
    with pytest.raises(ReviewProviderError, match="provider_password_update_unconfirmed"):
        fixture.adapter().rotate(
            fixture.actor["account_id"], "new-private-password-" * 3, fixture.seed
        )
    assert fixture.fresh_proofs == 0


def test_password_rotation_requires_fresh_signed_subject_and_mfa_flow() -> None:
    fixture = ProviderFixture()
    result = fixture.adapter().rotate(
        fixture.actor["account_id"], "new-private-password-" * 3, fixture.seed
    )
    assert result == {
        "account_id": fixture.actor["account_id"],
        "provider_subject": fixture.actor["id"],
        "rotated_fields": ["password"],
        "verified": True,
    }
    assert fixture.password_writes == 1
    assert fixture.fresh_proofs == 1
    assert fixture.revocations == 1
    assert fixture.state["users"]["worker"]["totp_secret"] == fixture.seed
    assert all("private" not in str(request.url) for request in fixture.requests)


@pytest.mark.parametrize(
    "failure",
    [
        "reject_password",
        "wrong_subject",
        "callback_state_mismatch",
        "foreign_form",
        "foreign_redirect",
    ],
)
def test_admin_ack_alone_cannot_claim_verified_password(failure: str) -> None:
    fixture = ProviderFixture()
    setattr(fixture, failure, True)
    with pytest.raises(ReviewProviderError) as result:
        fixture.adapter().rotate(
            fixture.actor["account_id"], "new-private-password-" * 3, fixture.seed
        )
    assert "private" not in str(result.value)
    assert fixture.password_writes == 1
    assert all(request.url.host == "id.localhost" for request in fixture.requests)
    if failure == "wrong_subject":
        assert fixture.revocations == 1


def test_seed_change_or_unissued_account_denies_before_any_provider_request() -> None:
    fixture = ProviderFixture()
    with pytest.raises(ReviewProviderError, match="provider_rotation_parameters_invalid"):
        fixture.adapter().rotate(
            fixture.actor["account_id"], "new-private-password-" * 3, "CHANGED"
        )
    with pytest.raises(ReviewProviderError, match="provider_actor_outside_lease"):
        fixture.adapter().rotate(str(uuid4()), "new-private-password-" * 3, fixture.seed)
    assert not fixture.requests


@pytest.mark.parametrize(
    "path",
    [
        "/realms/" + REALM + "/login-actions/../../other-realm",
        "/realms/" + REALM + "/login-actions/%2e%2e/other-realm",
        "/realms/" + REALM + "/login-actions/%252e%252e/other-realm",
    ],
)
def test_provider_form_path_traversal_is_denied(path: str) -> None:
    with pytest.raises(ReviewProviderError, match="provider_form_outside_lease"):
        ProviderAdmin._provider_url(BASE + path)
