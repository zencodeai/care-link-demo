"""Narrow continuation-realm origin registration and verified password rotation.

Construction performs no I/O. Only the coordinator invokes mutations under the
explicit continuation lease. Errors are categorical: raw provider URLs, bodies,
credentials and tokens never enter a public result or diagnostic.
"""

import json
import re
import secrets
import time
from collections.abc import Callable
from html.parser import HTMLParser
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, unquote, urljoin, urlsplit
from uuid import UUID

import httpx
from care_link_identity import IdentityError, OIDCConfig, OIDCProvider

from tools.demo.secrets import totp
from tools.imp02_application.tls import PinnedAddressTransport

BASE = "https://id.localhost:20443"
REALM = "care-link-imp03-cont1"
ISSUER = BASE + "/realms/" + REALM
CLIENT = REALM + "-browser"
LEGACY_ORIGIN = "https://qualification.localhost:29443"
Record = dict[str, object]


class ReviewProviderError(ValueError):
    """No provider-controlled text is rendered in this exception."""


def _record(raw: object) -> Record:
    if not isinstance(raw, dict):
        raise ReviewProviderError("provider_shape_invalid")
    return cast(Record, raw)


def _text(raw: Record, key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ReviewProviderError("provider_shape_invalid")
    return value


def _uuid(value: str) -> str:
    try:
        if str(UUID(value)) == value:
            return value
    except ValueError:
        pass
    raise ReviewProviderError("provider_binding_invalid")


def _origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.port != 29443
        or not parsed.hostname
        or (
            value != LEGACY_ORIGIN
            and not re.fullmatch(
                r"r[0-9a-f]{32}-(participant|worker1|worker2|supervisor)\.qualification\.localhost",
                parsed.hostname,
            )
        )
    ):
        raise ReviewProviderError("provider_origin_outside_lease")
    return value


class _Forms(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.forms: list[tuple[str, dict[str, str], set[str]]] = []
        self.current: tuple[str, dict[str, str], set[str]] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "form":
            if self.current is not None or (values.get("method") or "get").lower() != "post":
                return
            self.current = (values.get("action") or "", {}, set())
        elif tag == "input" and self.current is not None:
            name = values.get("name")
            if name and len(name) <= 128:
                self.current[2].add(name)
                if (values.get("type") or "").lower() == "hidden":
                    value = values.get("value") or ""
                    if len(value) > 8192:
                        raise ReviewProviderError("provider_form_invalid")
                    self.current[1][name] = value

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self.current is not None:
            self.forms.append(self.current)
            self.current = None


class ProviderAdmin:
    def __init__(
        self,
        state: Record,
        admin_password: str,
        ca_file: Path,
        *,
        namespace_slot: str | None = None,
        client_factory: Callable[[], httpx.Client] | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        slots = {
            "participant": "participant",
            "worker1": "worker",
            "worker2": "worker2",
            "supervisor": "supervisor",
        }
        if namespace_slot is not None and namespace_slot not in slots:
            raise ReviewProviderError("provider_namespace_outside_lease")
        self.namespace_slot = namespace_slot
        self.realm = (
            REALM
            if namespace_slot is None or namespace_slot == "participant"
            else REALM + "-" + namespace_slot
        )
        self.issuer = BASE + "/realms/" + self.realm
        self.client_id = self.realm + "-browser"
        self.state = _record(json.loads(json.dumps(state)))
        if set(self.state) != {"session", "realm", "binding", "main_origin", "users", "client"} or (
            self.state["session"] != "imp03-003"
            or self.state["realm"] != self.realm
            or self.state["main_origin"] != LEGACY_ORIGIN
        ):
            raise ReviewProviderError("provider_realm_outside_lease")
        _uuid(_text(self.state, "binding"))
        configured = _record(self.state["client"])
        if (
            set(configured) != {"id", "client_id", "secret"}
            or configured["client_id"] != self.client_id
        ):
            raise ReviewProviderError("provider_client_outside_lease")
        _uuid(_text(configured, "id"))
        _text(configured, "secret")
        users = _record(self.state["users"])
        expected = {
            "participant": "pid",
            "worker": "worker",
            "worker2": "worker",
            "supervisor": "supervisor",
            "security": "security",
        }
        if namespace_slot is not None:
            label = slots[namespace_slot]
            expected = {label: expected[label]}
        if set(users) != set(expected):
            raise ReviewProviderError("provider_actor_binding_invalid")
        identities: set[str] = set()
        self.actors: dict[str, Record] = {}
        for slot, role in expected.items():
            actor = _record(users[slot])
            if set(actor) != {
                "id",
                "account_id",
                "username",
                "password",
                "totp_secret",
                "roles",
            } or (actor["roles"] != [role] or actor["username"] != "imp03-" + slot):
                raise ReviewProviderError("provider_actor_binding_invalid")
            subject, account = _uuid(_text(actor, "id")), _uuid(_text(actor, "account_id"))
            if subject in identities or account in identities or account == subject:
                raise ReviewProviderError("provider_actor_binding_invalid")
            identities.update((subject, account))
            self.actors[account] = actor
        if not admin_password:
            raise ReviewProviderError("provider_admin_required")
        self.password, self.ca_file = admin_password, ca_file
        self.clock, self.sleep = clock, sleep
        self.client_factory = client_factory or self._client

    def _client(self) -> httpx.Client:
        return httpx.Client(
            transport=PinnedAddressTransport(BASE, "127.0.0.1", str(self.ca_file)),
            follow_redirects=False,
            trust_env=False,
        )

    @staticmethod
    def read_object(response: httpx.Response) -> Record:
        if response.status_code != 200 or len(response.content) > 1024 * 1024:
            raise ReviewProviderError("provider_read_unavailable")
        try:
            return _record(response.json())
        except (ValueError, TypeError):
            raise ReviewProviderError("provider_shape_invalid") from None

    def owned(self, client: httpx.Client) -> tuple[dict[str, str], Record]:
        if client.follow_redirects:
            raise ReviewProviderError("provider_redirects_forbidden")
        token = self.read_object(
            client.post(
                BASE + "/realms/master/protocol/openid-connect/token",
                data={
                    "grant_type": "password",
                    "client_id": "admin-cli",
                    "username": "imp02-owner-admin",
                    "password": self.password,
                },
                timeout=10,
            )
        )
        headers = {"Authorization": "Bearer " + _text(token, "access_token")}
        realm_url = BASE + "/admin/realms/" + self.realm
        realm = self.read_object(client.get(realm_url, headers=headers, timeout=10))
        if (
            realm.get("realm") != self.realm
            or _record(realm.get("attributes")).get("care-link.imp03-binding")
            != self.state["binding"]
        ):
            raise ReviewProviderError("provider_realm_binding_changed")
        configured = _record(self.state["client"])
        actual = self.read_object(
            client.get(
                realm_url + "/clients/" + _text(configured, "id"), headers=headers, timeout=10
            )
        )
        for key, expected in {
            "id": configured["id"],
            "clientId": self.client_id,
            "enabled": True,
            "protocol": "openid-connect",
            "publicClient": False,
            "standardFlowEnabled": True,
            "implicitFlowEnabled": False,
            "directAccessGrantsEnabled": False,
            "serviceAccountsEnabled": False,
            "fullScopeAllowed": False,
        }.items():
            if actual.get(key) != expected:
                raise ReviewProviderError("provider_client_binding_changed")
        if _record(actual.get("attributes")).get("pkce.code.challenge.method") != "S256":
            raise ReviewProviderError("provider_pkce_binding_changed")
        secret = self.read_object(
            client.get(
                realm_url + "/clients/" + _text(configured, "id") + "/client-secret",
                headers=headers,
                timeout=10,
            )
        )
        if not secrets.compare_digest(_text(secret, "value"), _text(configured, "secret")):
            raise ReviewProviderError("provider_client_secret_changed")
        self._registered(actual)
        return headers, actual

    @staticmethod
    def _registered(client: Record) -> tuple[list[str], list[str]]:
        callbacks, origins = client.get("redirectUris"), client.get("webOrigins")
        if not isinstance(callbacks, list) or not isinstance(origins, list):
            raise ReviewProviderError("provider_origins_invalid")
        accepted_callbacks: list[str] = []
        accepted_origins: list[str] = []
        for value in cast(list[object], callbacks):
            if not isinstance(value, str) or not value.endswith("/v1/auth/callback"):
                raise ReviewProviderError("provider_origins_invalid")
            _origin(value.removesuffix("/v1/auth/callback"))
            accepted_callbacks.append(value)
        for value in cast(list[object], origins):
            if not isinstance(value, str):
                raise ReviewProviderError("provider_origins_invalid")
            accepted_origins.append(_origin(value))
        if LEGACY_ORIGIN + "/v1/auth/callback" not in accepted_callbacks:
            raise ReviewProviderError("provider_legacy_callback_missing")
        return accepted_callbacks, accepted_origins

    def install_origins(self, origins: list[str]) -> Record:
        requested = sorted({_origin(item) for item in origins})
        if not requested or len(requested) > 4:
            raise ReviewProviderError("provider_exact_actor_origins_required")
        if self.namespace_slot and any(
            item != LEGACY_ORIGIN
            and not (urlsplit(item).hostname or "").endswith(
                "-" + self.namespace_slot + ".qualification.localhost"
            )
            for item in requested
        ):
            raise ReviewProviderError("provider_actor_origin_mismatch")
        try:
            with self.client_factory() as client:
                headers, current = self.owned(client)
                callbacks, existing = self._registered(current)
                desired_callbacks = sorted(
                    set(callbacks) | {item + "/v1/auth/callback" for item in requested}
                )
                desired_origins = sorted(set(existing) | set(requested))
                if sorted(callbacks) != desired_callbacks or sorted(existing) != desired_origins:
                    url = (
                        BASE
                        + "/admin/realms/"
                        + self.realm
                        + "/clients/"
                        + _text(_record(self.state["client"]), "id")
                    )
                    result = client.put(
                        url,
                        json={
                            **current,
                            "redirectUris": desired_callbacks,
                            "webOrigins": desired_origins,
                        },
                        headers=headers,
                        timeout=10,
                    )
                    if result.status_code != 204:
                        raise ReviewProviderError("provider_origin_install_unconfirmed")
                    observed = self.read_object(client.get(url, headers=headers, timeout=10))
                    observed_callbacks, observed_origins = self._registered(observed)
                    if (
                        sorted(observed_callbacks) != desired_callbacks
                        or sorted(observed_origins) != desired_origins
                    ):
                        raise ReviewProviderError("provider_origin_install_unverified")
                return {"origins": requested, "verified": True}
        except httpx.HTTPError:
            raise ReviewProviderError("provider_admin_unavailable") from None

    def actor_current(self, client: httpx.Client, headers: dict[str, str], actor: Record) -> None:
        url = BASE + "/admin/realms/" + self.realm + "/users/" + _text(actor, "id")
        actual = self.read_object(client.get(url, headers=headers, timeout=10))
        if (
            actual.get("id") != actor["id"]
            or actual.get("username") != actor["username"]
            or actual.get("enabled") is not True
            or actual.get("requiredActions")
        ):
            raise ReviewProviderError("provider_actor_binding_changed")
        response = client.get(url + "/credentials", headers=headers, timeout=10)
        if response.status_code != 200 or len(response.content) > 65536:
            raise ReviewProviderError("provider_credentials_unavailable")
        rows: object = response.json()
        if not isinstance(rows, list) or {
            _record(x).get("type") for x in cast(list[object], rows)
        } != {"password", "otp"}:
            raise ReviewProviderError("provider_credential_profile_changed")

    def rotate(self, account_id: str, newpassword: str, totp_secret: str) -> Record:
        actor = self.actors.get(account_id)
        if actor is None or actor["roles"] == ["security"]:
            raise ReviewProviderError("provider_actor_outside_lease")
        if len(newpassword) < 32 or not secrets.compare_digest(
            _text(actor, "totp_secret"), totp_secret
        ):
            raise ReviewProviderError("provider_rotation_parameters_invalid")
        try:
            with self.client_factory() as client:
                headers, _configured = self.owned(client)
                self.actor_current(client, headers, actor)
                url = (
                    BASE
                    + "/admin/realms/"
                    + self.realm
                    + "/users/"
                    + _text(actor, "id")
                    + "/reset-password"
                )
                response = client.put(
                    url,
                    headers=headers,
                    json={"type": "password", "temporary": False, "value": newpassword},
                    timeout=10,
                )
                if response.status_code != 204:
                    raise ReviewProviderError("provider_password_update_unconfirmed")
                self.actor_current(client, headers, actor)
            self._verify_password(actor, newpassword, totp_secret)
            return {
                "account_id": account_id,
                "provider_subject": actor["id"],
                "rotated_fields": ["password"],
                "verified": True,
            }
        except httpx.HTTPError:
            raise ReviewProviderError("provider_admin_unavailable") from None

    def verify_password(self, account_id: str, password: str, totp_secret: str) -> Record:
        """Prove a pending password outcome without modifying provider state."""
        actor = self.actors.get(account_id)
        if actor is None or actor["roles"] == ["security"]:
            raise ReviewProviderError("provider_actor_outside_lease")
        if not secrets.compare_digest(_text(actor, "totp_secret"), totp_secret):
            raise ReviewProviderError("provider_rotation_parameters_invalid")
        try:
            with self.client_factory() as client:
                headers, _configured = self.owned(client)
                self.actor_current(client, headers, actor)
            self._verify_password(actor, password, totp_secret)
        except httpx.HTTPError:
            raise ReviewProviderError("provider_admin_unavailable") from None
        return {"account_id": account_id, "provider_subject": actor["id"], "verified": True}

    def _verify_password(self, actor: Record, password: str, seed: str) -> None:
        configured = _record(self.state["client"])
        config = OIDCConfig(
            issuer=self.issuer,
            client_id=self.client_id,
            client_secret=_text(configured, "secret"),
            redirect_uri=LEGACY_ORIGIN + "/v1/auth/callback",
            authorization_endpoint=self.issuer + "/protocol/openid-connect/auth",
            token_endpoint=self.issuer + "/protocol/openid-connect/token",
            jwks_uri=self.issuer + "/protocol/openid-connect/certs",
            introspection_endpoint=self.issuer + "/protocol/openid-connect/token/introspect",
            revocation_endpoint=self.issuer + "/protocol/openid-connect/revoke",
            resource_audience=self.realm + "-resource",
            mfa_acr="2",
            access_token_type="JWT",  # noqa: S106 - exact non-secret JOSE header profile
        )
        state, nonce, verifier = (
            secrets.token_urlsafe(32),
            secrets.token_urlsafe(32),
            secrets.token_urlsafe(48),
        )
        try:
            with self.client_factory() as client:
                provider = OIDCProvider(config, client)
                response = client.get(
                    provider.authorization_url(state, nonce, verifier, True), timeout=10
                )
                password_sent = False
                otp_sent = False
                for _ in range(12):
                    if len(response.content) > 256 * 1024:
                        raise ReviewProviderError("provider_form_invalid")
                    if response.status_code in {301, 302, 303}:
                        target = urljoin(
                            str(response.request.url), response.headers.get("location", "")
                        )
                        parsed = urlsplit(target)
                        if target.startswith(config.redirect_uri + "?"):
                            values = parse_qs(parsed.query, keep_blank_values=True)
                            if (
                                parsed.fragment
                                or set(values) - {"code", "state", "session_state", "iss"}
                                or any(len(v) != 1 for v in values.values())
                                or values.get("state") != [state]
                                or values.get("iss") != [self.issuer]
                                or not values.get("code")
                                or not password_sent
                                or not otp_sent
                            ):
                                raise ReviewProviderError("provider_callback_unverified")
                            principal = provider.exchange(values["code"][0], verifier, nonce, True)
                            try:
                                if principal.subject != actor["id"]:
                                    raise ReviewProviderError("provider_subject_mismatch")
                                if (
                                    not principal.mfa
                                    or not {"pwd", "otp"}.issubset(principal.factors)
                                    or not provider.active(
                                        principal.access_token, principal.subject
                                    )
                                ):
                                    raise ReviewProviderError(
                                        "provider_password_verification_failed"
                                    )
                            finally:
                                provider.revoke(principal.access_token)
                            return
                        self._provider_url(target, self.realm)
                        response = client.get(target, timeout=10)
                        continue
                    if response.status_code != 200:
                        raise ReviewProviderError("provider_password_verification_failed")
                    parser = _Forms()
                    parser.feed(response.text)
                    candidates = [
                        item for item in parser.forms if "password" in item[2] or "otp" in item[2]
                    ]
                    if len(candidates) != 1:
                        raise ReviewProviderError("provider_form_unrecognized")
                    action, hidden, names = candidates[0]
                    target = urljoin(str(response.request.url), action)
                    self._provider_url(target, self.realm)
                    if not urlsplit(target).path.startswith(
                        "/realms/" + self.realm + "/login-actions/"
                    ):
                        raise ReviewProviderError("provider_form_outside_lease")
                    submitted = dict(hidden)
                    if "password" in names:
                        if password_sent:
                            raise ReviewProviderError("provider_password_verification_failed")
                        submitted.update(username=_text(actor, "username"), password=password)
                        password_sent = True
                    if "otp" in names:
                        if otp_sent:
                            raise ReviewProviderError("provider_otp_verification_failed")
                        # Issuer rejects reuse: use a fresh window, never retry codes.
                        self.sleep(30 - self.clock() % 30 + 0.2)
                        code, _expires = totp(seed, now=self.clock())
                        submitted["otp"] = code
                        otp_sent = True
                    response = client.post(target, data=submitted, timeout=10)
                raise ReviewProviderError("provider_form_flow_limit")
        except (httpx.HTTPError, IdentityError, ValueError) as error:
            if isinstance(error, ReviewProviderError):
                raise
            raise ReviewProviderError("provider_password_verification_failed") from None

    @staticmethod
    def _provider_url(value: str, realm: str = REALM) -> None:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "id.localhost:20443"
            or parsed.username
            or parsed.password
            or parsed.fragment
            or not parsed.path.startswith("/realms/" + realm + "/")
            or any(part in {".", ".."} for part in unquote(parsed.path).split("/"))
            or "%" in unquote(parsed.path)
            or "\\" in unquote(parsed.path)
        ):
            raise ReviewProviderError("provider_form_outside_lease")
