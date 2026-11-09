"""Real JWT cryptography through a mock HTTP provider transport."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import jwt
import pytest
from care_link_identity import ExchangeUncertain, IdentityError, OIDCConfig, OIDCProvider
from cryptography.hazmat.primitives.asymmetric import rsa

pytestmark = pytest.mark.unit


def jwt_fixture():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid": "key-a", "alg": "RS256", "use": "sig"})
    config = OIDCConfig(
        "https://issuer.test",
        "client",
        "secret",
        "https://app.test/v1/auth/callback",
        "https://issuer.test/auth",
        "https://issuer.test/token",
        "https://issuer.test/keys",
        "https://issuer.test/introspect",
        "https://issuer.test/revoke",
        "api",
        "mfa-profile",
    )
    now = int(datetime.now(UTC).timestamp())
    claims = {
        "iss": config.issuer,
        "aud": "client",
        "sub": "subject",
        "nonce": "nonce",
        "exp": now + 300,
        "iat": now,
        "nbf": now,
        "auth_time": now,
        "acr": "mfa-profile",
        "amr": ["pwd", "otp"],
    }
    access_claims = {
        "iss": config.issuer,
        "aud": "api",
        "sub": "subject",
        "exp": now + 300,
        "iat": now,
    }
    responses = {
        "id_claims": claims,
        "access_claims": access_claims,
        "id_headers": {"kid": "key-a"},
        "access_headers": {"kid": "key-a", "typ": "at+jwt"},
        "keys": [jwk],
        "key_requests": 0,
    }

    def route(request):
        if request.url.path == "/keys":
            responses["key_requests"] += 1
            return httpx.Response(200, json={"keys": responses["keys"]})
        if request.url.path == "/token":
            return httpx.Response(
                200,
                json={
                    "token_type": "Bearer",
                    "id_token": jwt.encode(
                        responses["id_claims"],
                        key,
                        algorithm="RS256",
                        headers=responses["id_headers"],
                    ),
                    "access_token": jwt.encode(
                        responses["access_claims"],
                        key,
                        algorithm="RS256",
                        headers=responses["access_headers"],
                    ),
                },
            )
        if request.url.path == "/introspect":
            return httpx.Response(200, json={"active": True, "sub": "subject"})
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(route))
    return OIDCProvider(config, client), responses


def test_valid_signed_token_pkce_and_uncached_provider_status():
    provider, data = jwt_fixture()
    url = provider.authorization_url("state", "nonce", "verifier", True)
    assert "code_challenge_method=S256" in url and "response_mode=query" in url
    assert "max_age=0" in url and "verifier" not in url
    principal = provider.exchange("code", "verifier", "nonce", True)
    assert principal.subject == "subject" and principal.mfa
    assert provider.active(principal.access_token, "subject")
    assert not provider.active(principal.access_token, "wrong")
    assert data["key_requests"] == 1


@pytest.mark.parametrize(
    "claim,value",
    [
        ("iss", "https://evil.test"),
        ("aud", "wrong"),
        ("azp", "wrong"),
        ("nonce", "wrong"),
        ("exp", 1),
        ("iat", 9999999999),
        ("nbf", 9999999999),
        ("sub", None),
        ("auth_time", 1),
        ("auth_time", True),
    ],
)
def test_wrong_or_stale_oidc_claims_fail(claim, value):
    provider, data = jwt_fixture()
    data["id_claims"][claim] = value
    with pytest.raises(IdentityError):
        provider.exchange("code", "verifier", "nonce", True)


@pytest.mark.parametrize(
    "header,value",
    [
        ("jku", "https://evil.test/keys"),
        ("x5u", "https://evil.test/cert"),
        ("kid", "unknown"),
        ("crit", ["unsupported"]),
    ],
)
def test_token_supplied_key_urls_and_unknown_kid_denied(header, value):
    provider, data = jwt_fixture()
    data["id_headers"][header] = value
    with pytest.raises(IdentityError):
        provider.exchange("code", "verifier", "nonce", True)


def test_multi_audience_requires_exact_azp_and_id_is_not_access_token():
    provider, data = jwt_fixture()
    data["id_claims"]["aud"] = ["client", "second"]
    with pytest.raises(IdentityError):
        provider.exchange("code", "verifier", "nonce", True)
    data["id_claims"]["azp"] = "client"
    assert provider.exchange("code", "verifier", "nonce", True)
    data["access_headers"]["typ"] = "JWT"
    with pytest.raises(IdentityError):
        provider.exchange("code", "verifier", "nonce", True)


def test_access_audience_keeps_resource_and_introspecting_client_with_exact_azp():
    provider, data = jwt_fixture()
    data["access_claims"]["aud"] = ["api", "client"]
    with pytest.raises(IdentityError):
        provider.exchange("code", "verifier", "nonce", True)
    data["access_claims"]["azp"] = "client"
    assert provider.exchange("code", "verifier", "nonce", True)
    data["access_claims"]["azp"] = "other-bff"
    with pytest.raises(IdentityError):
        provider.exchange("code", "verifier", "nonce", True)
    data["access_claims"]["azp"] = "client"
    data["access_claims"]["aud"] = ["client"]
    with pytest.raises(IdentityError):
        provider.exchange("code", "verifier", "nonce", True)


@pytest.mark.parametrize("started", [0.0, 30.0, 1000.0])
def test_provider_key_failure_cannot_reuse_expired_cache(monkeypatch, started):
    now = started
    monkeypatch.setattr("care_link_identity.provider.time", SimpleNamespace(monotonic=lambda: now))
    provider, data = jwt_fixture()
    assert provider.exchange("code", "verifier", "nonce", False)
    data["keys"] = []
    now = started + 299
    assert provider.exchange("code", "verifier", "nonce", False)
    assert data["key_requests"] == 1
    now = started + 300
    with pytest.raises(IdentityError, match="unknown_key"):
        provider.exchange("code", "verifier", "nonce", False)
    assert data["key_requests"] == 2


def test_exchange_timeout_is_uncertain():
    provider, _data = jwt_fixture()

    def timeout(request):
        raise httpx.ReadTimeout("fixture timeout", request=request)

    provider.client = httpx.Client(transport=httpx.MockTransport(timeout))
    with pytest.raises(ExchangeUncertain):
        provider.exchange("code", "verifier", "nonce", False)


def test_https_same_origin_fixed_endpoints_required():
    provider, _data = jwt_fixture()
    data = dict(vars(provider.config))
    data["token_endpoint"] = "https://evil.test/token"  # noqa: S105 - attack endpoint fixture
    with pytest.raises(ValueError):
        OIDCConfig(**data)


def test_hmac_and_unsigned_tokens_cannot_satisfy_rsa_validation():
    provider, data = jwt_fixture()
    for algorithm, key in [
        ("HS256", "attacker-secret-of-more-than-thirty-two-bytes"),
        ("none", None),
    ]:
        raw = jwt.encode(data["id_claims"], key, algorithm=algorithm, headers={"kid": "key-a"})
        with pytest.raises(IdentityError):
            provider._claims(raw, "client", True)


def test_keycloak_mixed_encryption_and_signing_jwks_admits_only_signing_key():
    provider, data = jwt_fixture()
    signing = data["keys"][0]
    encryption = {
        **signing,
        "kid": "encryption-key",
        "use": "enc",
        "alg": "RSA-OAEP",
        "key_ops": ["encrypt", "wrapKey"],
    }
    data["keys"] = [encryption, signing]
    assert provider.exchange("code", "verifier", "nonce", True).mfa
    assert set(provider._keys) == {"key-a"}
    # Even using the same RSA material cannot convert its encryption profile
    # into an accepted signature verifier via a caller-selected kid.
    data["id_headers"]["kid"] = "encryption-key"
    with pytest.raises(IdentityError, match="unknown_key"):
        provider.exchange("code", "verifier", "nonce", True)


@pytest.mark.parametrize("algorithm", ["RS384", "RS512", "PS256", "none"])
def test_unsupported_signing_key_profiles_are_never_verifiers(algorithm):
    provider, data = jwt_fixture()
    signing = data["keys"][0]
    data["keys"] = [{**signing, "kid": "other-profile", "alg": algorithm}, signing]
    assert provider.exchange("code", "verifier", "nonce", True)
    data["id_headers"]["kid"] = "other-profile"
    with pytest.raises(IdentityError, match="unknown_key"):
        provider.exchange("code", "verifier", "nonce", True)


@pytest.mark.parametrize(
    "field,value",
    [
        ("kid", "key-a"),  # collision across encryption and signing profiles
        ("d", "private"),
        ("p", "private"),
        ("q", "private"),
        ("dp", "private"),
        ("dq", "private"),
        ("qi", "private"),
        ("oth", []),
        ("k", "symmetric"),
        ("jku", "https://evil.test/keys"),
        ("x5u", "https://evil.test/cert"),
        ("kid", ""),
        ("alg", None),
        ("use", ["enc", "sig"]),
        ("key_ops", ["verify"]),
        ("key_ops", ["encrypt", "encrypt"]),
        ("key_ops", "encrypt"),
    ],
)
def test_skipped_encryption_key_still_obeys_whole_set_policy(field, value):
    provider, data = jwt_fixture()
    signing = data["keys"][0]
    encryption = {
        **signing,
        "kid": "encryption-key",
        "use": "enc",
        "alg": "RSA-OAEP",
        "key_ops": ["encrypt", "wrapKey"],
    }
    encryption[field] = value
    data["keys"] = [encryption, signing]
    with pytest.raises(IdentityError, match="keys_unavailable"):
        provider.exchange("code", "verifier", "nonce", True)


@pytest.mark.parametrize("field", ["alg", "use", "kty"])
def test_ambiguous_missing_key_profile_is_not_assumed_signing(field):
    provider, data = jwt_fixture()
    del data["keys"][0][field]
    with pytest.raises(IdentityError, match="keys_unavailable"):
        provider.exchange("code", "verifier", "nonce", True)


def test_duplicate_jwks_json_members_are_rejected():
    provider, _data = jwt_fixture()

    def duplicated(request):
        return httpx.Response(200, content=b'{"keys":[],"keys":[]}')

    provider.client = httpx.Client(transport=httpx.MockTransport(duplicated))
    with pytest.raises(IdentityError, match="keys_unavailable"):
        provider._key("key-a")


@pytest.mark.parametrize("kind", ["id", "access"])
def test_missing_claim_diagnostic_contains_only_fixed_kind_class_and_claim(kind, caplog):
    provider, data = jwt_fixture()
    del data[kind + "_claims"]["exp"]
    data[kind + "_claims"]["private_payload"] = "never-log-this-profile-value"
    with pytest.raises(IdentityError, match="invalid_token"):
        provider.exchange("private-code-never-log", "private-verifier-never-log", "nonce", True)
    record = next(record for record in caplog.records if record.name.endswith(".provider"))
    assert record.getMessage() == (
        f"OIDC token rejected: kind={kind}_token "
        "exception=MissingRequiredClaimError missing_claim=exp"
    )
    assert record.exc_info is None and record.stack_info is None
    assert "never-log" not in caplog.text and "private_payload" not in caplog.text


def test_wrong_audience_diagnostic_excludes_exception_text_and_claim_value(caplog):
    provider, data = jwt_fixture()
    data["access_claims"]["aud"] = "private-audience-value-never-log"
    with pytest.raises(IdentityError, match="invalid_token"):
        provider.exchange("code", "verifier", "nonce", True)
    assert "kind=access_token exception=InvalidAudienceError missing_claim=None" in caplog.text
    assert "private-audience" not in caplog.text


def test_policy_header_diagnostic_excludes_caller_controlled_values(caplog):
    provider, data = jwt_fixture()
    data["id_headers"]["jku"] = "https://private-never-log.test/key"
    with pytest.raises(IdentityError, match="invalid_token"):
        provider.exchange("code", "verifier", "nonce", True)
    assert "kind=id_token exception=ValueError missing_claim=None" in caplog.text
    assert "private-never-log" not in caplog.text


@pytest.mark.parametrize(
    "field,value,stage",
    [
        ("nonce", "private-wrong-nonce", "nonce_binding"),
        ("auth_time", None, "authentication_time_presence"),
        ("auth_time", 1, "authentication_time_freshness"),
    ],
)
def test_exchange_rejection_diagnostic_is_fixed_stage_and_class_only(field, value, stage, caplog):
    provider, data = jwt_fixture()
    data["id_claims"][field] = value
    with pytest.raises(IdentityError, match="exchange_rejected"):
        provider.exchange("private-code", "private-verifier", "nonce", True)
    assert f"OIDC exchange rejected: stage={stage} exception=ValueError" in caplog.text
    assert "private" not in caplog.text


@pytest.mark.parametrize("amr", [None, [], ["unrecognized"], "pwd", ["pwd", 1]])
def test_recent_auth_time_without_recognized_signed_method_is_rejected(amr):
    provider, data = jwt_fixture()
    data["id_claims"]["amr"] = amr
    with pytest.raises(IdentityError, match="exchange_rejected"):
        provider.exchange("code", "verifier", "nonce", True)


def test_recent_password_only_method_is_valid_without_claiming_mfa():
    provider, data = jwt_fixture()
    data["id_claims"]["amr"] = ["pwd"]
    data["id_claims"]["acr"] = "password-profile"
    principal = provider.exchange("code", "verifier", "nonce", True)
    assert principal.factors == ("pwd",)
    assert principal.mfa is False
