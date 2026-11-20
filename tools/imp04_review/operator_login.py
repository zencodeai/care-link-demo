"""Private real-provider operator bootstrap; no CLI or network work on import."""

from __future__ import annotations

import base64
import hashlib
import hmac
import math
import re
import secrets
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import parse_qsl, urljoin, urlsplit
from uuid import UUID, uuid4

import httpx
from care_link_identity.crypto import digest, token
from care_link_identity.domain import instant
from care_link_identity.provider import OIDCProvider
from care_link_identity.service import IdentityService

LIMIT = 256 * 1024


@dataclass(frozen=True, repr=False)
class PrivilegedCredentials:
    role: Literal["operator", "security"]
    account_id: str
    subject: str
    username: str
    password: str
    totp_secret: str


class PrivilegedLoginError(RuntimeError):
    """Only fixed categories escape; provider forms, URLs and credentials do not."""


@dataclass(repr=False)
class _Form:
    action: str
    method: str
    fields: list[tuple[str, str]] = field(default_factory=lambda: list[tuple[str, str]]())
    username: list[str] = field(default_factory=lambda: list[str]())
    password: list[str] = field(default_factory=lambda: list[str]())
    otp: list[str] = field(default_factory=lambda: list[str]())


class _Forms(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.forms: list[_Form] = []
        self.current: _Form | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if len(attrs) > 64 or len({key for key, _ in attrs}) != len(attrs):
            raise PrivilegedLoginError("invalid_form")
        values = dict(attrs)
        if tag == "form":
            if self.current is not None or len(self.forms) >= 8:
                raise PrivilegedLoginError("invalid_form")
            self.current = _Form(
                values.get("action") or "", (values.get("method") or "get").lower()
            )
            self.forms.append(self.current)
        if tag != "input" or self.current is None or "disabled" in values:
            return
        name = values.get("name")
        kind = (values.get("type") or "text").lower()
        if kind in {"checkbox", "radio"} and "checked" not in values:
            return
        if not name or kind in {"button", "submit", "reset", "image", "file"}:
            return
        if len(self.current.fields) >= 128 or any(key == name for key, _ in self.current.fields):
            raise PrivilegedLoginError("invalid_form")
        self.current.fields.append((name, values.get("value") or ""))
        if kind == "password":
            self.current.password.append(name)
        elif name.lower() in {"otp", "totp"} or values.get("autocomplete") == "one-time-code":
            self.current.otp.append(name)
        elif name.lower() in {"username", "email"} or values.get("autocomplete") == "username":
            self.current.username.append(name)

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self.current = None


def _fresh_totp(secret: str, clock: Callable[[], datetime], sleep: Callable[[float], None]) -> str:
    if not re.fullmatch(r"[A-Z2-7]{16,128}={0,6}", secret):
        raise PrivilegedLoginError("invalid_credentials")
    try:
        key = base64.b32decode(secret + "=" * ((-len(secret)) % 8))
    except ValueError:
        raise PrivilegedLoginError("invalid_credentials") from None
    before = clock().timestamp()
    if not math.isfinite(before):
        raise PrivilegedLoginError("invalid_clock")
    sleep(30 - before % 30 + 0.1)
    after = clock().timestamp()
    if not math.isfinite(after) or int(after // 30) <= int(before // 30):
        raise PrivilegedLoginError("invalid_clock")
    hashed = hmac.new(key, int(after // 30).to_bytes(8), hashlib.sha1).digest()
    offset = hashed[-1] & 15
    number = int.from_bytes(hashed[offset : offset + 4]) & 0x7FFFFFFF
    return f"{number % 1_000_000:06d}"


def _configuration(service: IdentityService, credentials: PrivilegedCredentials) -> OIDCProvider:
    provider = service.provider
    if (
        not isinstance(provider, OIDCProvider)
        or service.review_context is not None
        or service.interactive_policy is not None
        or credentials.role not in {"operator", "security"}
    ):
        raise PrivilegedLoginError("ordinary_provider_required")
    config = provider.config
    issuer = urlsplit(config.issuer)
    main = urlsplit(service.origin)
    if (
        issuer.scheme != "https"
        or issuer.username
        or issuer.password
        or issuer.query
        or issuer.fragment
        or not re.fullmatch(r"/realms/[A-Za-z0-9_.-]{1,128}", issuer.path)
        or service.issuer != config.issuer
        or config.redirect_uri != service.origin + "/v1/auth/callback"
        or main.scheme != "https"
        or main.username
        or main.password
        or main.path
        or main.query
        or main.fragment
    ):
        raise PrivilegedLoginError("invalid_provider_configuration")
    suffixes = {
        "authorization_endpoint": "auth",
        "token_endpoint": "token",
        "jwks_uri": "certs",
        "introspection_endpoint": "token/introspect",
        "revocation_endpoint": "revoke",
    }
    if any(
        getattr(config, name) != config.issuer + "/protocol/openid-connect/" + suffix
        for name, suffix in suffixes.items()
    ):
        raise PrivilegedLoginError("invalid_provider_configuration")
    if (
        str(UUID(credentials.account_id)) != credentials.account_id
        or str(UUID(credentials.subject)) != credentials.subject
        or not credentials.username
        or not credentials.password
        or len(credentials.username) > 1024
        or len(credentials.password) > 4096
    ):
        raise PrivilegedLoginError("invalid_credentials")
    return provider


def _provider_url(url: str, provider: OIDCProvider) -> None:
    target, issuer = urlsplit(url), urlsplit(provider.config.issuer)
    paths = {
        issuer.path + "/protocol/openid-connect/auth",
        issuer.path + "/login-actions/authenticate",
        issuer.path + "/login-actions/restart",
    }
    if (
        (target.scheme, target.netloc) != (issuer.scheme, issuer.netloc)
        or target.username
        or target.password
        or target.fragment
        or target.path not in paths
        or len(url) > 16384
    ):
        raise PrivilegedLoginError("foreign_provider_navigation")


def _callback(url: str, provider: OIDCProvider, state: str) -> tuple[str, str]:
    target, expected = urlsplit(url), urlsplit(provider.config.redirect_uri)
    if (
        (target.scheme, target.netloc, target.path)
        != (expected.scheme, expected.netloc, expected.path)
        or target.username
        or target.password
        or target.fragment
        or len(url) > 16384
    ):
        raise PrivilegedLoginError("foreign_callback")
    pairs = parse_qsl(target.query, keep_blank_values=True, encoding="utf-8", errors="strict")
    values = dict(pairs)
    if (
        len(values) != len(pairs)
        or not {"state", "code", "iss"} <= values.keys()
        or not values.keys() <= {"state", "code", "iss", "session_state"}
        or not secrets.compare_digest(values["state"], state)
        or values["iss"] != provider.config.issuer
        or not 1 <= len(values["code"]) <= 2048
        or any(
            any(ord(char) < 32 or ord(char) == 127 for char in value) for value in values.values()
        )
    ):
        raise PrivilegedLoginError("invalid_callback")
    return values["code"], values["iss"]


def _authenticate(
    provider: OIDCProvider,
    url: str,
    state: str,
    credentials: PrivilegedCredentials,
    clock: Callable[[], datetime],
    sleep: Callable[[float], None],
) -> tuple[str, str]:
    cookies = httpx.Cookies()
    method, data = "GET", None
    password, otp = False, False
    used = 0
    callback = urlsplit(provider.config.redirect_uri)
    for _ in range(12):
        target = urlsplit(url)
        if (target.scheme, target.netloc, target.path) == (
            callback.scheme,
            callback.netloc,
            callback.path,
        ):
            if not password or not otp:
                raise PrivilegedLoginError("missing_password_or_otp")
            return _callback(url, provider, state)
        _provider_url(url, provider)
        request = provider.client.build_request(
            method, url, data=data, headers={"Accept": "text/html"}, timeout=10
        )
        for header in ("cookie", "authorization", "proxy-authorization"):
            request.headers.pop(header, None)
        cookies.set_cookie_header(request)
        with closing(
            provider.client.send(request, auth=None, follow_redirects=False, stream=True)
        ) as response:
            cookies.extract_cookies(response)
            if response.status_code in {301, 302, 303, 307, 308}:
                if response.status_code in {307, 308} and method == "POST":
                    raise PrivilegedLoginError("credential_redirect_denied")
                location = response.headers.get("location")
                if not location:
                    raise PrivilegedLoginError("invalid_provider_response")
                url, method, data = urljoin(url, location), "GET", None
                continue
            if (
                response.status_code != 200
                or response.headers.get("content-type", "").split(";")[0] != "text/html"
            ):
                raise PrivilegedLoginError("invalid_provider_response")
            content = bytearray()
            for chunk in response.iter_bytes(8192):
                used += len(chunk)
                if used > LIMIT:
                    raise PrivilegedLoginError("provider_response_too_large")
                content.extend(chunk)
        parser = _Forms()
        parser.feed(content.decode("utf-8"))
        forms = [form for form in parser.forms if form.username or form.password or form.otp]
        if len(forms) != 1:
            raise PrivilegedLoginError("missing_or_ambiguous_form")
        form = forms[0]
        if (
            form.method != "post"
            or not form.action
            or any(len(names) > 1 for names in (form.username, form.password, form.otp))
        ):
            raise PrivilegedLoginError("invalid_form")
        url = urljoin(url, form.action)
        _provider_url(url, provider)
        fields = dict(form.fields)
        for name in form.username:
            fields[name] = credentials.username
        if form.password:
            if password or otp:
                raise PrivilegedLoginError("password_rejected")
            fields[form.password[0]] = credentials.password
            password = True
        if form.otp:
            if not password or otp:
                raise PrivilegedLoginError("otp_rejected")
            fields[form.otp[0]] = _fresh_totp(credentials.totp_secret, clock, sleep)
            otp = True
        method, data = "POST", fields
    raise PrivilegedLoginError("provider_step_limit")


def login_privileged(
    service: IdentityService,
    credentials: PrivilegedCredentials,
    *,
    clock: Callable[[], datetime],
    sleep: Callable[[float], None],
) -> str:
    """Return one private local session from real password+OTP provider authentication.

    The caller owns the pinned TLS client, credential custody, clock and sleep.
    No credentials, callback URL, state or session are printed or logged here.
    """
    raw: str | None = None
    try:
        provider = _configuration(service, credentials)
        start, binding = clock(), token()
        intent, state = service.login_start(credentials.role, binding)
        url = intent.get("authorization_url")
        if not isinstance(url, str):
            raise PrivilegedLoginError("invalid_provider_response")
        code, issuer = _authenticate(provider, url, state, credentials, clock, sleep)
        view, raw, proof = service.callback(state, code, binding, issuer)
        if raw is None:
            raise PrivilegedLoginError("session_not_issued")
        current = service.current(raw)
        now, authenticated = clock(), instant(current["auth_time"])
        factors = current.get("factors")
        if (
            proof is not None
            or current.get("account_id") != credentials.account_id
            or current.get("subject") != credentials.subject
            or current.get("role") != credentials.role
            or current.get("mfa") is not True
            or current.get("origin") != service.origin
            or current.get("binding") != digest(binding)
            or view.get("assurance") != "AL2"
            or not isinstance(factors, list)
            or "pwd" not in factors
            or "otp" not in factors
            or not start - timedelta(seconds=5) <= authenticated <= now + timedelta(seconds=5)
            or (now - authenticated).total_seconds() > 300
        ):
            raise PrivilegedLoginError("issued_actor_mismatch")
        return raw
    except Exception as error:
        if raw is not None:
            try:
                service.logout(raw, str(uuid4()))
            except Exception:
                raise PrivilegedLoginError("revocation_unconfirmed") from None
        if isinstance(error, PrivilegedLoginError):
            raise PrivilegedLoginError(str(error)) from None
        raise PrivilegedLoginError("privileged_login_failed") from None
