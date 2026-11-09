"""Pinned-origin OIDC code exchange, JWT verification and uncached introspection."""

import base64
import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from urllib.parse import urlencode, urlsplit

import httpx
import jwt

from .domain import ExchangeUncertain, IdentityError, Principal

logger = logging.getLogger(__name__)
DIAGNOSTIC_CLAIMS = frozenset({"iss", "sub", "aud", "exp", "iat", "nbf", "auth_time", "nonce"})
VERIFIED_METHODS = frozenset({"pwd", "otp", "hwk", "swk", "webauthn"})


def _unique_members(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate JSON member")
        result[name] = value
    return result


@dataclass(frozen=True)
class OIDCConfig:
    issuer: str
    client_id: str
    client_secret: str
    redirect_uri: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    introspection_endpoint: str
    revocation_endpoint: str
    resource_audience: str
    mfa_acr: str
    access_token_type: str = "at+jwt"  # noqa: S105 - exact public JOSE type, not a secret

    def __post_init__(self) -> None:
        if self.access_token_type not in {"at+jwt", "JWT"}:
            raise ValueError("exact admitted asymmetric access token profile required")
        if self.resource_audience == self.client_id:
            raise ValueError("access and browser ID-token audiences must be distinct")
        authority = urlsplit(self.issuer)
        if authority.scheme != "https" or not authority.netloc or authority.username:
            raise ValueError("OIDC issuer must be pinned HTTPS")
        for endpoint in (
            self.authorization_endpoint,
            self.token_endpoint,
            self.jwks_uri,
            self.introspection_endpoint,
            self.revocation_endpoint,
        ):
            parsed = urlsplit(endpoint)
            if (parsed.scheme, parsed.netloc) != (authority.scheme, authority.netloc):
                raise ValueError("OIDC endpoints must have the pinned issuer origin")
            if parsed.fragment or parsed.username:
                raise ValueError("Invalid pinned endpoint")
        redirect = urlsplit(self.redirect_uri)
        if redirect.scheme != "https" or redirect.fragment or redirect.username:
            raise ValueError("Callback must use fixed private HTTPS")
        if not all((self.client_id, self.client_secret, self.resource_audience, self.mfa_acr)):
            raise ValueError("Missing OIDC integration values")


class OIDCProvider:
    """The HTTP client is owned by composition root, with TLS verification enabled."""

    def __init__(self, config: OIDCConfig, client: httpx.Client) -> None:
        self.config = config
        self.client = client
        self._keys: dict[str, jwt.PyJWK] = {}
        self._keys_at = 0.0
        self._refresh_lock = threading.Lock()

    def authorization_url(self, state: str, nonce: str, verifier: str, fresh: bool) -> str:
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        params = {
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "response_type": "code",
            "response_mode": "query",
            "scope": "openid",
            "claims": json.dumps({"id_token": {"auth_time": {"essential": True}}}),
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge.rstrip(b"=").decode(),
            "code_challenge_method": "S256",
        }
        if fresh:
            params.update({"max_age": "0", "prompt": "login", "acr_values": self.config.mfa_acr})
        return self.config.authorization_endpoint + "?" + urlencode(params)

    def _key(self, kid: str) -> jwt.PyJWK:
        started = time.monotonic()
        with self._refresh_lock:
            age = time.monotonic() - self._keys_at
            if age < 300 and kid in self._keys:
                return self._keys[kid]
            # A completed concurrent refresh is sufficient for unknown keys too.
            if self._keys_at > started and kid not in self._keys:
                raise IdentityError("identity.unknown_key")
            try:
                response = self.client.get(self.config.jwks_uri, timeout=3, follow_redirects=False)
                response.raise_for_status()
                if len(response.content) > 64 * 1024:
                    raise ValueError("oversized keys")
                raw_document: object = json.loads(
                    response.content, object_pairs_hook=_unique_members
                )
                if not isinstance(raw_document, dict):
                    raise ValueError("invalid key document")
                data = cast(dict[str, object], raw_document)
                raw_keys = data.get("keys")
                if not isinstance(raw_keys, list) or len(cast(list[object], raw_keys)) > 16:
                    raise ValueError("invalid keys")
                keys: dict[str, jwt.PyJWK] = {}
                seen: set[str] = set()
                for raw in cast(list[object], raw_keys):
                    if not isinstance(raw, dict):
                        raise ValueError("invalid key")
                    item = cast(dict[str, object], raw)
                    key_id = item.get("kid")
                    key_type, algorithm, purpose = item.get("kty"), item.get("alg"), item.get("use")
                    if (
                        not isinstance(key_id, str)
                        or not key_id
                        or len(key_id) > 256
                        or key_id in seen
                        or not isinstance(key_type, str)
                        or not key_type
                        or not isinstance(algorithm, str)
                        or not algorithm
                        or not isinstance(purpose, str)
                        or purpose not in {"sig", "enc"}
                        or {"d", "p", "q", "dp", "dq", "qi", "oth", "k", "jku", "x5u"} & item.keys()
                    ):
                        raise ValueError("invalid key policy")
                    seen.add(key_id)
                    operations = item.get("key_ops")
                    if operations is not None:
                        if not isinstance(operations, list):
                            raise ValueError("invalid key operations")
                        values = cast(list[object], operations)
                        if (
                            not values
                            or not all(isinstance(value, str) for value in values)
                            or len(set(cast(list[str], values))) != len(values)
                            or (purpose == "sig" and values != ["verify"])
                            or (
                                purpose == "enc"
                                and {"verify", "sign"} & set(cast(list[str], values))
                            )
                        ):
                            raise ValueError("ambiguous key operations")
                    if algorithm == "RS256" and (key_type != "RSA" or purpose != "sig"):
                        raise ValueError("ambiguous signing key profile")
                    # Providers may publish encryption or other signing keys in
                    # the same JWKS. None can satisfy this fixed RS256 profile.
                    if key_type != "RSA" or algorithm != "RS256" or purpose != "sig":
                        continue
                    keys[key_id] = jwt.PyJWK.from_dict(item, algorithm="RS256")
                self._keys = keys
                self._keys_at = time.monotonic()
            except (httpx.HTTPError, ValueError, jwt.PyJWTError) as error:
                raise IdentityError("identity.keys_unavailable", 503) from error
            if kid not in self._keys:
                raise IdentityError("identity.unknown_key")
            return self._keys[kid]

    def _claims(self, raw: str, audience: str, id_token: bool) -> dict[str, object]:
        try:
            if len(raw) > 32 * 1024:
                raise ValueError("oversized token")

            parts = raw.split(".")
            if len(parts) != 3:
                raise ValueError("invalid compact JWT")
            for segment in parts[:2]:
                decoded = base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
                json.loads(decoded, object_pairs_hook=_unique_members)
            header = cast(dict[str, object], jwt.get_unverified_header(raw))
            kid = header.get("kid")
            if (
                header.get("alg") != "RS256"
                or not isinstance(kid, str)
                or "jku" in header
                or "x5u" in header
                or header.get("crit")
                or (not id_token and header.get("typ") != self.config.access_token_type)
            ):
                raise ValueError("invalid token header")
            claims = cast(
                dict[str, object],
                jwt.decode(
                    raw,
                    self._key(kid),
                    algorithms=["RS256"],
                    issuer=self.config.issuer,
                    audience=audience,
                    leeway=0,
                    options={"require": ["iss", "sub", "aud", "exp", "iat"]},
                ),
            )
            for field in ("exp", "iat"):
                if type(claims.get(field)) is not int:
                    raise ValueError("invalid numeric date")
            if "nbf" in claims and type(claims["nbf"]) is not int:
                raise ValueError("invalid numeric date")
            if not isinstance(claims.get("sub"), str) or not claims["sub"]:
                raise ValueError("invalid subject")
            audiences = claims.get("aud")
            if isinstance(audiences, list) and len(cast(list[object], audiences)) > 1:
                if claims.get("azp") != self.config.client_id:
                    raise ValueError("wrong authorized party")
            elif "azp" in claims and claims["azp"] != self.config.client_id:
                raise ValueError("wrong authorized party")
            return claims
        except (ValueError, jwt.PyJWTError) as error:
            missing = (
                error.claim
                if isinstance(error, jwt.MissingRequiredClaimError)
                and error.claim in DIAGNOSTIC_CLAIMS
                else None
            )
            # Keep diagnostics internal and categorical. Exception text, token
            # strings, decoded values and traceback locals must never be logged.
            logger.warning(
                "OIDC token rejected: kind=%s exception=%s missing_claim=%s",
                "id_token" if id_token else "access_token",
                type(error).__name__,
                missing,
            )
            raise IdentityError("identity.invalid_token") from error

    def exchange(self, code: str, verifier: str, nonce: str, fresh: bool) -> Principal:
        try:
            response = self.client.post(
                self.config.token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.config.redirect_uri,
                    "code_verifier": verifier,
                },
                auth=(self.config.client_id, self.config.client_secret),
                timeout=10,
                follow_redirects=False,
            )
        except httpx.TimeoutException as error:
            raise ExchangeUncertain() from error
        except httpx.HTTPError as error:
            raise ExchangeUncertain() from error
        stage = "token_response"
        try:
            response.raise_for_status()
            if len(response.content) > 64 * 1024:
                raise ValueError("oversized token response")
            data = cast(dict[str, object], response.json())
            id_raw, access_raw = data.get("id_token"), data.get("access_token")
            if not isinstance(id_raw, str) or not isinstance(access_raw, str):
                raise ValueError("missing tokens")
            if data.get("token_type") != "Bearer":
                raise ValueError("invalid token type")
            stage = "id_token_validation"
            claims = self._claims(id_raw, self.config.client_id, True)
            stage = "access_token_validation"
            access = self._claims(access_raw, self.config.resource_audience, False)
            stage = "nonce_binding"
            if claims.get("nonce") != nonce:
                raise ValueError("wrong flow")
            stage = "subject_binding"
            if access["sub"] != claims["sub"]:
                raise ValueError("wrong flow")
            stage = "authentication_time_presence"
            auth_time = claims.get("auth_time")
            if type(auth_time) is not int:
                raise ValueError("missing authentication time")
            stage = "authentication_time_conversion"
            verified_at = datetime.fromtimestamp(auth_time, UTC)
            now = datetime.now(UTC)
            age = (now - verified_at).total_seconds()
            stage = "authentication_time_freshness"
            if age < -5 or (fresh and age > 300):
                raise ValueError("stale authentication")
            stage = "assurance_mapping"
            amr = claims.get("amr")
            if not isinstance(amr, list) or not all(
                isinstance(method, str) for method in cast(list[object], amr)
            ):
                raise ValueError("missing signed authentication method evidence")
            methods = tuple(method for method in cast(list[str], amr) if method in VERIFIED_METHODS)
            if not methods:
                raise ValueError("no admitted signed authentication method")
            mfa = claims.get("acr") == self.config.mfa_acr and bool(
                {"otp", "hwk", "swk", "webauthn"} & set(methods)
            )
            stage = "principal_expiry"
            return Principal(
                subject=cast(str, claims["sub"]),
                auth_time=verified_at,
                mfa=mfa,
                factors=methods,
                access_token=access_raw,
                expires_at=datetime.fromtimestamp(
                    min(cast(int, claims["exp"]), cast(int, access["exp"])), UTC
                ),
            )
        except (httpx.HTTPError, ValueError, KeyError) as error:
            logger.warning(
                "OIDC exchange rejected: stage=%s exception=%s", stage, type(error).__name__
            )
            raise IdentityError("identity.exchange_rejected") from error

    def active(self, access_token: str, subject: str) -> bool:
        try:
            response = self.client.post(
                self.config.introspection_endpoint,
                data={"token": access_token},
                auth=(self.config.client_id, self.config.client_secret),
                timeout=0.5,
                follow_redirects=False,
            )
            response.raise_for_status()
            if len(response.content) > 32 * 1024:
                return False
            data = cast(dict[str, object], response.json())
            return data.get("active") is True and data.get("sub") == subject
        except (httpx.HTTPError, ValueError):
            return False

    def revoke(self, access_token: str) -> None:
        try:
            response = self.client.post(
                self.config.revocation_endpoint,
                data={"token": access_token},
                auth=(self.config.client_id, self.config.client_secret),
                timeout=3,
                follow_redirects=False,
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise IdentityError("identity.provider_logout_pending", 503) from error
