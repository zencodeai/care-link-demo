"""Fresh IMP-03 realm in the shared provider; credentials remain operator-private.

Only the coordinator calls bootstrap under the Option B resource lease. Existing
realms are never reconciled or repaired: an exact persisted binding is verified,
otherwise the operation refuses before writing to the provider.
"""

import base64
import json
import os
import secrets
import stat
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import httpx

from .profiles import ACTIVE

REALM = ACTIVE.realm
BASE = "https://id.localhost:20443"
ISSUER = BASE + "/realms/" + REALM
CLIENT = REALM + "-browser"
AUDIENCE = REALM + "-resource"
MAIN = ACTIVE.main_origin
ROLES = {"participant": "pid", "worker": "worker", "supervisor": "supervisor"}
if ACTIVE.name == "continuation-001":
    ROLES.update(worker2="worker", security="security")
Record = dict[str, object]


def _record(value: object) -> Record:
    if not isinstance(value, dict):
        raise ValueError("Expected private provider object")
    return cast(Record, value)


def _text(value: Record, key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ValueError("Missing private provider field: " + key)
    return result


def _origin(value: str) -> str:
    url = httpx.URL(value)
    if (
        url.scheme != "https"
        or url.path != "/"
        or url.query
        or url.fragment
        or url.userinfo
        or str(url).rstrip("/") != value
    ):
        raise ValueError("Exact HTTPS browser origin required")
    return value


def _validate(
    state: Record, main_origin: str, *, realm: str = REALM, roles: dict[str, str] | None = None
) -> None:
    expected_roles = roles if roles is not None else ROLES
    client_id = realm + "-browser"
    if set(state) != {"session", "realm", "binding", "main_origin", "users", "client"}:
        raise ValueError("Exact private IMP-03 provider state required")
    if (
        state["session"] != "imp03-003"
        or state["realm"] != realm
        or state["main_origin"] != main_origin
    ):
        raise ValueError("Existing provider state has different immutable targets")
    for key in ("binding",):
        if str(UUID(_text(state, key))) != state[key]:
            raise ValueError("Canonical provider binding required")
    users, client = _record(state["users"]), _record(state["client"])
    if set(users) != set(expected_roles) or set(client) != {"id", "client_id", "secret"}:
        raise ValueError("Exact separately issued users and client required")
    if client["client_id"] != client_id or len(_text(client, "secret")) < 32:
        raise ValueError("Exact confidential IMP-03 client required")
    identifiers = [_text(client, "id")]
    passwords: set[str] = set()
    seeds: set[str] = set()
    for name, role in expected_roles.items():
        actor = _record(users[name])
        if set(actor) != {"id", "account_id", "username", "password", "totp_secret", "roles"}:
            raise ValueError("Exact synthetic account binding required")
        if actor["username"] != "imp03-" + name or actor["roles"] != [role]:
            raise ValueError("Separate exact actor role required")
        identifiers.extend((_text(actor, "id"), _text(actor, "account_id")))
        password, seed = _text(actor, "password"), _text(actor, "totp_secret")
        if len(password) < 32 or len(base64.b32decode(seed)) != 20:
            raise ValueError("Private generated password and TOTP seed required")
        passwords.add(password)
        seeds.add(seed)
    if (
        len(passwords) != len(expected_roles)
        or len(seeds) != len(expected_roles)
        or len(set(identifiers)) != len(identifiers)
    ):
        raise ValueError("Provider subjects/accounts/credentials must be distinct")
    if any(str(UUID(value)) != value for value in identifiers):
        raise ValueError("Canonical distinct account/client UUIDs required")


def private_state(path: Path, main_origin: str = MAIN) -> Record:
    """Create/read a 0600 state in an existing owner-only 0700 directory."""
    main_origin = _origin(main_origin)
    parent = path.parent.lstat()
    if (
        not path.is_absolute()
        or path.parent.is_symlink()
        or not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.geteuid()
        or stat.S_IMODE(parent.st_mode) != 0o700
    ):
        raise ValueError("Absolute owner-only0700 provider state directory required")
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise ValueError("Private regular0600 state file required")
        state = _record(json.loads(path.read_text()))
        _validate(state, main_origin)
        return state
    state: Record = {
        "session": "imp03-003",
        "realm": REALM,
        "binding": str(uuid4()),
        "main_origin": main_origin,
        "users": {
            name: {
                "id": str(uuid4()),
                "account_id": str(uuid4()),
                "username": "imp03-" + name,
                "password": secrets.token_urlsafe(32),
                "totp_secret": base64.b32encode(secrets.token_bytes(20)).decode(),
                "roles": [role],
            }
            for name, role in ROLES.items()
        },
        "client": {"id": str(uuid4()), "client_id": CLIENT, "secret": secrets.token_urlsafe(48)},
    }
    _validate(state, main_origin)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as output:
        output.write(json.dumps(state, indent=2) + "\n")
        output.flush()
        os.fsync(output.fileno())
    return state


def _mapper(name: str, provider: str, **configuration: str) -> Record:
    return {
        "name": name,
        "protocol": "openid-connect",
        "protocolMapper": provider,
        "config": configuration,
    }


def _mappers(*, realm: str = REALM) -> list[Record]:
    audience, client_id = realm + "-resource", realm + "-browser"
    # Keycloak canonicalizes these built-in mappers with an explicit UserInfo
    # flag. Bind its actual profile rather than rejecting harmless defaults.
    claims = {
        "id.token.claim": "true",
        "access.token.claim": "true",
        "userinfo.token.claim": "true",
    }
    return [
        _mapper(
            "actual-provider-subject",
            "oidc-sub-mapper",
            **{
                "access.token.claim": "true",
                "introspection.token.claim": "true",
                "lightweight.claim": "false",
            },
        ),
        _mapper(
            "actual-authentication-time",
            "oidc-usersessionmodel-note-mapper",
            **{
                **claims,
                "user.session.note": "AUTH_TIME",
                "introspection.token.claim": "true",
                "claim.name": "auth_time",
                "jsonType.label": "long",
            },
        ),
        _mapper("actual-authentication-methods", "oidc-amr-mapper", **claims),
        _mapper("actual-authentication-level", "oidc-acr-mapper", **claims),
        _mapper(
            "distinct-resource-audience",
            "oidc-audience-mapper",
            **{
                "included.custom.audience": audience,
                "userinfo.token.claim": "false",
                "id.token.claim": "false",
                "access.token.claim": "true",
                "introspection.token.claim": "true",
            },
        ),
        _mapper(
            "actual-introspection-audience",
            "oidc-audience-mapper",
            **{
                "included.client.audience": client_id,
                "userinfo.token.claim": "false",
                "id.token.claim": "false",
                "access.token.claim": "true",
                "introspection.token.claim": "true",
            },
        ),
    ]


def realm_document(
    state: Record, *, realm: str = REALM, roles: dict[str, str] | None = None
) -> Record:
    """Provider import, with actual authenticators and no application role mapper."""
    _validate(state, _text(state, "main_origin"), realm=realm, roles=roles)
    expected_roles = roles if roles is not None else ROLES
    client_id = realm + "-browser"
    client, users = _record(state["client"]), _record(state["users"])
    origin = _text(state, "main_origin")
    actor_documents: list[Record] = []
    for name in expected_roles:
        actor = _record(users[name])
        actor_documents.append(
            {
                "id": actor["id"],
                "username": actor["username"],
                "enabled": True,
                "email": "imp03-" + name + "@care-link.invalid",
                "emailVerified": False,
                "firstName": "Synthetic",
                "lastName": "Owner-operated profile",
                "requiredActions": [],
                "credentials": [
                    {"type": "password", "value": actor["password"], "temporary": False},
                    {
                        "type": "otp",
                        "userLabel": "imp03-owned-lab-totp",
                        "secretData": json.dumps({"value": actor["totp_secret"]}),
                        "credentialData": json.dumps(
                            {
                                "subType": "totp",
                                "digits": 6,
                                "period": 30,
                                "counter": 0,
                                "algorithm": "HmacSHA1",
                                "secretEncoding": "BASE32",
                            }
                        ),
                    },
                ],
            }
        )
    return {
        "realm": realm,
        "enabled": True,
        "sslRequired": "all",
        "registrationAllowed": False,
        "resetPasswordAllowed": False,
        "rememberMe": False,
        "loginWithEmailAllowed": False,
        "duplicateEmailsAllowed": False,
        "bruteForceProtected": True,
        "accessTokenLifespan": 3600,
        "ssoSessionIdleTimeout": 900,
        "ssoSessionMaxLifespan": 3600,
        "defaultSignatureAlgorithm": "RS256",
        "attributes": {"care-link.imp03-binding": state["binding"], "acr.loa.map": '{"2":2}'},
        "otpPolicyType": "totp",
        "otpPolicyAlgorithm": "HmacSHA1",
        "otpPolicyDigits": 6,
        "otpPolicyPeriod": 30,
        "otpPolicyLookAheadWindow": 1,
        "otpPolicyCodeReusable": False,
        "browserFlow": "care-link-imp03-browser",
        "clients": [
            {
                "id": client["id"],
                "clientId": client_id,
                "name": client_id,
                "enabled": True,
                "protocol": "openid-connect",
                "publicClient": False,
                "secret": client["secret"],
                "standardFlowEnabled": True,
                "implicitFlowEnabled": False,
                "directAccessGrantsEnabled": False,
                "serviceAccountsEnabled": False,
                "redirectUris": [origin + "/v1/auth/callback"],
                "webOrigins": [origin],
                "defaultClientScopes": [],
                "optionalClientScopes": [],
                "fullScopeAllowed": False,
                "attributes": {
                    "pkce.code.challenge.method": "S256",
                    "default.acr.values": "2",
                    "acr.loa.map": '{"2":2}',
                },
                "protocolMappers": _mappers(realm=realm),
            }
        ],
        "users": actor_documents,
        "authenticatorConfig": [
            {"alias": "imp03-loa2", "config": {"loa-condition-level": "2", "loa-max-age": "0"}},
            {
                "alias": "imp03-password-method",
                "config": {"default.reference.value": "pwd", "default.reference.maxAge": "300"},
            },
            {
                "alias": "imp03-otp-method",
                "config": {"default.reference.value": "otp", "default.reference.maxAge": "300"},
            },
        ],
        "authenticationFlows": [
            {
                "alias": "care-link-imp03-browser",
                "description": "Actual password and OTP for separate synthetic IMP-03 actors",
                "providerId": "basic-flow",
                "topLevel": True,
                "builtIn": False,
                "authenticationExecutions": [
                    {
                        "flowAlias": "imp03-two-factors",
                        "authenticatorFlow": True,
                        "requirement": "CONDITIONAL",
                        "priority": 10,
                        "userSetupAllowed": False,
                    }
                ],
            },
            {
                "alias": "imp03-two-factors",
                "providerId": "basic-flow",
                "topLevel": False,
                "builtIn": False,
                "authenticationExecutions": [
                    {
                        "authenticator": "conditional-level-of-authentication",
                        "authenticatorConfig": "imp03-loa2",
                        "authenticatorFlow": False,
                        "requirement": "REQUIRED",
                        "priority": 0,
                    },
                    {
                        "authenticator": "auth-username-password-form",
                        "authenticatorConfig": "imp03-password-method",
                        "authenticatorFlow": False,
                        "requirement": "REQUIRED",
                        "priority": 10,
                    },
                    {
                        "authenticator": "auth-otp-form",
                        "authenticatorConfig": "imp03-otp-method",
                        "authenticatorFlow": False,
                        "requirement": "REQUIRED",
                        "priority": 20,
                    },
                ],
            },
        ],
    }


def _object(response: httpx.Response) -> Record:
    if response.status_code not in range(200, 300) or len(response.content) > 1024 * 1024:
        raise ValueError("Shared provider request failed; private response suppressed")
    return _record(response.json())


def _verify(client: httpx.Client, headers: dict[str, str], state: Record, realm: Record) -> None:
    desired = realm_document(state)
    for field in ("realm", "enabled", "sslRequired", "browserFlow", "defaultSignatureAlgorithm"):
        if realm.get(field) != desired[field]:
            raise ValueError("Existing IMP-03 realm configuration differs")
    if _record(realm.get("attributes")).get("care-link.imp03-binding") != state["binding"]:
        raise ValueError("Existing realm is outside persisted IMP-03 binding")
    base = BASE + "/admin/realms/" + REALM
    configured = _record(state["client"])
    current = _object(
        client.get(base + "/clients/" + _text(configured, "id"), headers=headers, timeout=10)
    )
    desired_client = _record(cast(list[object], desired["clients"])[0])
    for field in (
        "id",
        "clientId",
        "enabled",
        "protocol",
        "publicClient",
        "standardFlowEnabled",
        "implicitFlowEnabled",
        "directAccessGrantsEnabled",
        "serviceAccountsEnabled",
        "redirectUris",
        "webOrigins",
        "fullScopeAllowed",
    ):
        if current.get(field) != desired_client[field]:
            raise ValueError("Existing IMP-03 client configuration differs")
    for field, value in _record(desired_client["attributes"]).items():
        if _record(current.get("attributes")).get(field) != value:
            raise ValueError("Existing IMP-03 client assurance profile differs")
    actual_mappers = current.get("protocolMappers")
    if not isinstance(actual_mappers, list) or len(cast(list[object], actual_mappers)) != len(
        _mappers()
    ):
        raise ValueError("Existing IMP-03 protocol mapper profile differs")
    for mapper in _mappers():
        matches = [
            _record(x)
            for x in cast(list[object], actual_mappers)
            if _record(x).get("name") == mapper["name"]
        ]
        if len(matches) != 1 or any(matches[0].get(k) != v for k, v in mapper.items()):
            raise ValueError("Existing IMP-03 required protocol mapper differs")
    secret = _object(
        client.get(
            base + "/clients/" + _text(configured, "id") + "/client-secret",
            headers=headers,
            timeout=10,
        )
    )
    if not secrets.compare_digest(_text(secret, "value"), _text(configured, "secret")):
        raise ValueError("Existing IMP-03 client credential differs")
    for raw in _record(state["users"]).values():
        actor = _record(raw)
        current = _object(
            client.get(base + "/users/" + _text(actor, "id"), headers=headers, timeout=10)
        )
        if (
            any(current.get(k) != actor[k] for k in ("id", "username"))
            or current.get("enabled") is not True
        ):
            raise ValueError("Existing IMP-03 provider subject/username binding differs")
        if current.get("requiredActions"):
            raise ValueError("Existing IMP-03 actor requires unfinished provider actions")
        credentials = client.get(
            base + "/users/" + _text(actor, "id") + "/credentials", headers=headers, timeout=10
        )
        if credentials.status_code != 200 or len(credentials.content) > 1024 * 1024:
            raise ValueError("Provider credential verification failed; private response suppressed")
        rows: object = credentials.json()
        if not isinstance(rows, list) or {
            _record(item).get("type") for item in cast(list[object], rows)
        } != {"password", "otp"}:
            raise ValueError("Separately issued password and OTP credentials required")


def bootstrap(
    client: httpx.Client,
    admin_password: str,
    state_path: Path,
    *,
    main_origin: str = MAIN,
) -> Record:
    """Create fresh realm once, or verify exact persisted targets without writes."""
    if client.follow_redirects:
        raise ValueError("Provider administration must not follow redirects")
    state = private_state(state_path, main_origin)
    token = _object(
        client.post(
            BASE + "/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": "imp02-owner-admin",
                "password": admin_password,
            },
            timeout=10,
        )
    )
    headers = {"Authorization": "Bearer " + _text(token, "access_token")}
    url = BASE + "/admin/realms/" + REALM
    before = client.get(url, headers=headers, timeout=10)
    if before.status_code == 404:
        created = client.post(
            BASE + "/admin/realms", json=realm_document(state), headers=headers, timeout=30
        )
        if created.status_code != 201:
            raise ValueError("Fresh IMP-03 realm creation refused; partial resources retained")
        realm = _object(client.get(url, headers=headers, timeout=10))
    else:
        realm = _object(before)
    _verify(client, headers, state, realm)
    return state


def actor_registry(state: Record) -> list[Record]:
    _validate(state, _text(state, "main_origin"))
    return [
        {"account_id": actor["account_id"], "subject": actor["id"], "roles": actor["roles"]}
        for actor in (_record(_record(state["users"])[name]) for name in ROLES)
    ]


def oidc_settings(state: Record) -> dict[str, str]:
    _validate(state, _text(state, "main_origin"))
    return {
        "issuer": ISSUER,
        "client_id": CLIENT,
        "client_secret": _text(_record(state["client"]), "secret"),
        "redirect_uri": _text(state, "main_origin") + "/v1/auth/callback",
        "authorization_endpoint": ISSUER + "/protocol/openid-connect/auth",
        "token_endpoint": ISSUER + "/protocol/openid-connect/token",
        "jwks_uri": ISSUER + "/protocol/openid-connect/certs",
        "introspection_endpoint": ISSUER + "/protocol/openid-connect/token/introspect",
        "revocation_endpoint": ISSUER + "/protocol/openid-connect/revoke",
        "resource_audience": AUDIENCE,
        "mfa_acr": "2",
        "access_token_type": "JWT",
    }


def browser_config(
    state: Record,
    *,
    help_origin: str,
    static_origin: str,
    ignore_https_errors: bool = False,
) -> Record:
    _validate(state, _text(state, "main_origin"))
    result: Record = {
        "session": "imp03-002",
        "mainOrigin": _text(state, "main_origin"),
        "oidcOrigin": BASE,
        "helpOrigin": _origin(help_origin),
        "staticOrigin": _origin(static_origin),
        "ignoreHTTPSErrors": ignore_https_errors,
        "accounts": {},
    }
    accounts: dict[str, str] = {}
    for name, role in ROLES.items():
        actor = _record(_record(state["users"])[name])
        accounts[name if name == "worker2" else role] = _text(actor, "account_id")
        result[name] = {
            "username": actor["username"],
            "password": actor["password"],
            "totpSecret": actor["totp_secret"],
        }
    result["accounts"] = accounts
    if (
        len(
            {
                httpx.URL(_text(result, key)).host
                for key in ("mainOrigin", "oidcOrigin", "helpOrigin", "staticOrigin")
            }
        )
        != 4
    ):
        raise ValueError("Four distinct cookie hostnames required")
    return result


def public_summary(state: Record) -> Record:
    _validate(state, _text(state, "main_origin"))
    return {
        "realm": REALM,
        "issuer": ISSUER,
        "client_id": CLIENT,
        "account_count": len(ROLES),
        "synthetic_owner_role_playing": True,
        "assurance_source": "actual completed password/OTP authenticators, not fixed claims",
    }
