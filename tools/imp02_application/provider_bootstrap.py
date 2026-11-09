"""Explicit named-lab Keycloak bootstrap; coordinator invokes against pinned TLS.

Only care-link-imp02 realm is created. Existing realm mutation requires the same
private persisted binding. Generated passwords/seeds/client secrets remain in the
external0600 state file, never returned by public_summary or printed by this tool.
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
from care_link_identity import IdentityService

REALM = "care-link-imp02"
BASE = "https://id.localhost:20443"
ISSUER = BASE + "/realms/" + REALM
ALL_ROLES = [
    "pid",
    "carer",
    "professional_participant",
    "worker",
    "supervisor",
    "receiver",
    "operator",
    "governance",
    "auditor",
    "security",
    "trainer",
]
PROFILE_NAMES = ("main", "participant", "other", "worker")


def _synthetic_profile(username: str) -> dict[str, object]:
    if username not in PROFILE_NAMES:
        raise ValueError("Exact synthetic owner-operated profile required")
    return {
        "email": username + "@care-link.invalid",
        "emailVerified": False,
        "firstName": "Synthetic",
        "lastName": "Owner-operated profile",
    }


def _subject_mapper() -> dict[str, object]:
    return {
        "name": "actual-provider-subject",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-sub-mapper",
        "config": {
            "access.token.claim": "true",
            "introspection.token.claim": "true",
            "lightweight.claim": "false",
        },
    }


def _authentication_time_mapper() -> dict[str, object]:
    # Exact built-in basic-scope profile observed in the admitted Keycloak lab.
    # Reads the actual completed authentication session, never a fixed timestamp.
    return {
        "name": "actual-authentication-time",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-usersessionmodel-note-mapper",
        "config": {
            "user.session.note": "AUTH_TIME",
            "id.token.claim": "true",
            "introspection.token.claim": "true",
            "access.token.claim": "true",
            "claim.name": "auth_time",
            "jsonType.label": "long",
        },
    }


def _introspection_audience_mapper(client_id: str) -> dict[str, object]:
    if client_id not in {"care-link-main", "care-link-help"}:
        raise ValueError("Exact admitted introspecting BFF client required")
    return {
        "name": "actual-introspection-audience",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-audience-mapper",
        "config": {
            "included.client.audience": client_id,
            "id.token.claim": "false",
            "access.token.claim": "true",
            "introspection.token.claim": "true",
        },
    }


def _lifecycle_role_mapper() -> dict[str, object]:
    return {
        "name": "actual-scoped-realm-management-roles",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-usermodel-client-role-mapper",
        "config": {
            "usermodel.clientRoleMapping.clientId": "realm-management",
            "claim.name": "resource_access.realm-management.roles",
            "jsonType.label": "String",
            "multivalued": "true",
            "id.token.claim": "false",
            "access.token.claim": "true",
            "introspection.token.claim": "true",
        },
    }


def _json(response: httpx.Response) -> dict[str, object]:
    response.raise_for_status()
    if len(response.content) > 1024 * 1024:
        raise ValueError("Oversized administrative response")
    value: object = response.json()
    if not isinstance(value, dict):
        raise ValueError("Administrative object response required")
    return cast(dict[str, object], value)


def _objects(response: httpx.Response) -> list[dict[str, object]]:
    response.raise_for_status()
    if len(response.content) > 1024 * 1024:
        raise ValueError("Oversized administrative response")
    document: object = response.json()
    if not isinstance(document, list) or not all(
        isinstance(item, dict) for item in cast(list[object], document)
    ):
        raise ValueError("Administrative object array required")
    return cast(list[dict[str, object]], document)


def private_state(path: Path, main_origin: str, help_origin: str) -> dict[str, object]:
    parent = path.parent.stat()
    if (
        path.parent.is_symlink()
        or parent.st_uid != os.geteuid()
        or stat.S_IMODE(parent.st_mode) != 0o700
    ):
        raise ValueError("Externally owned0700 state directory required")
    if path.exists():
        info = path.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise ValueError("Private regular0600 state file required")
        data = cast(dict[str, object], json.loads(path.read_text()))
        if (
            data.get("realm") != REALM
            or data.get("main_origin") != main_origin
            or data.get("help_origin") != help_origin
        ):
            raise ValueError("Existing lab state has different immutable targets")
        return data
    users = {
        name: {
            "id": str(uuid4()),
            "account_id": str(uuid4()),
            "username": name,
            "password": secrets.token_urlsafe(32),
            "totp_secret": base64.b32encode(secrets.token_bytes(20)).decode(),
            "roles": ALL_ROLES if name == "main" else ["worker"] if name == "worker" else ["pid"],
            "attribution": "project owner main role-playing a scoped synthetic test account",
        }
        for name in PROFILE_NAMES
    }
    data: dict[str, object] = {
        "realm": REALM,
        "binding": str(uuid4()),
        "main_origin": main_origin,
        "help_origin": help_origin,
        "users": users,
        "clients": {
            role: {
                "id": str(uuid4()),
                "client_id": "care-link-" + role,
                "secret": secrets.token_urlsafe(48),
            }
            for role in ("main", "help", "lifecycle")
        },
    }
    encoded = json.dumps(data, indent=2).encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        offset = 0
        while offset < len(encoded):
            offset += os.write(fd, encoded[offset:])
        os.fsync(fd)
    finally:
        os.close(fd)
    return data


def realm_document(state: dict[str, object]) -> dict[str, object]:
    users = cast(dict[str, dict[str, object]], state["users"])
    clients = cast(dict[str, dict[str, str]], state["clients"])
    protocol_mappers = [
        _subject_mapper(),
        _authentication_time_mapper(),
        {
            "name": "actual-authentication-methods",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-amr-mapper",
            "config": {"id.token.claim": "true", "access.token.claim": "true"},
        },
        {
            "name": "actual-authentication-level",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-acr-mapper",
            "config": {"id.token.claim": "true", "access.token.claim": "true"},
        },
        {
            "name": "distinct-resource-audience",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-audience-mapper",
            "config": {
                "included.custom.audience": "care-link-resource",
                "id.token.claim": "false",
                "access.token.claim": "true",
            },
        },
    ]
    client_documents: list[dict[str, object]] = []
    for role in ("main", "help"):
        item = clients[role]
        origin = str(state[role + "_origin"])
        client_documents.append(
            {
                "id": item["id"],
                "clientId": item["client_id"],
                "name": item["client_id"],
                "enabled": True,
                "protocol": "openid-connect",
                "publicClient": False,
                "secret": item["secret"],
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
                "protocolMappers": protocol_mappers
                + [_introspection_audience_mapper(item["client_id"])],
            }
        )
    lifecycle = clients["lifecycle"]
    client_documents.append(
        {
            "id": lifecycle["id"],
            "clientId": lifecycle["client_id"],
            "enabled": True,
            "protocol": "openid-connect",
            "publicClient": False,
            "secret": lifecycle["secret"],
            "serviceAccountsEnabled": True,
            "standardFlowEnabled": False,
            "directAccessGrantsEnabled": False,
            "fullScopeAllowed": False,
            "defaultClientScopes": ["kc-admin-api"],
            "optionalClientScopes": [],
            "protocolMappers": [_subject_mapper(), _lifecycle_role_mapper()],
        }
    )
    user_documents: list[dict[str, object]] = []
    for item in users.values():
        user_documents.append(
            {
                "id": item["id"],
                "username": item["username"],
                "enabled": True,
                **_synthetic_profile(str(item["username"])),
                "requiredActions": [],
                "credentials": [
                    {"type": "password", "value": item["password"], "temporary": False},
                    {
                        "type": "otp",
                        "userLabel": "owned-lab-totp",
                        "secretData": json.dumps({"value": item["totp_secret"]}),
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
        "realm": REALM,
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
        "attributes": {"care-link.lab-binding": str(state["binding"]), "acr.loa.map": '{"2":2}'},
        "otpPolicyType": "totp",
        "otpPolicyAlgorithm": "HmacSHA1",
        "otpPolicyDigits": 6,
        "otpPolicyPeriod": 30,
        "otpPolicyLookAheadWindow": 1,
        "otpPolicyCodeReusable": False,
        "browserFlow": "care-link-browser",
        "clients": client_documents,
        "users": user_documents,
        "authenticatorConfig": [
            {"alias": "care-link-loa2", "config": {"loa-condition-level": "2", "loa-max-age": "0"}},
            {
                "alias": "care-link-password-method",
                "config": {"default.reference.value": "pwd", "default.reference.maxAge": "300"},
            },
            {
                "alias": "care-link-otp-method",
                "config": {"default.reference.value": "otp", "default.reference.maxAge": "300"},
            },
        ],
        "authenticationFlows": [
            {
                "alias": "care-link-browser",
                "description": "Actual password and OTP in the named synthetic lab",
                "providerId": "basic-flow",
                "topLevel": True,
                "builtIn": False,
                "authenticationExecutions": [
                    {
                        "flowAlias": "care-link-two-factors",
                        "authenticatorFlow": True,
                        "requirement": "CONDITIONAL",
                        "priority": 10,
                        "userSetupAllowed": False,
                    }
                ],
            },
            {
                "alias": "care-link-two-factors",
                "providerId": "basic-flow",
                "topLevel": False,
                "builtIn": False,
                "authenticationExecutions": [
                    {
                        "authenticator": "conditional-level-of-authentication",
                        "authenticatorConfig": "care-link-loa2",
                        "authenticatorFlow": False,
                        "requirement": "REQUIRED",
                        "priority": 0,
                    },
                    {
                        "authenticator": "auth-username-password-form",
                        "authenticatorConfig": "care-link-password-method",
                        "authenticatorFlow": False,
                        "requirement": "REQUIRED",
                        "priority": 10,
                    },
                    {
                        "authenticator": "auth-otp-form",
                        "authenticatorConfig": "care-link-otp-method",
                        "authenticatorFlow": False,
                        "requirement": "REQUIRED",
                        "priority": 20,
                    },
                ],
            },
        ],
    }


def _reconcile_synthetic_profiles(
    client: httpx.Client, headers: dict[str, str], state: dict[str, object]
) -> None:
    """Called only after exact persisted realm binding verification.

    No email delivery, email verification, credentials, roles or MFA settings are
    changed. The reserved invalid-domain email is only provider profile metadata.
    Preflight all four exact UUID/username bindings before any update.
    """
    users = cast(dict[str, dict[str, object]], state["users"])
    if set(users) != set(PROFILE_NAMES):
        raise ValueError("Exact four synthetic configured profiles required")
    updates: list[tuple[str, dict[str, object]]] = []
    for username in PROFILE_NAMES:
        configured = users[username]
        subject = str(configured["id"])
        if str(UUID(subject)) != subject or configured.get("username") != username:
            raise ValueError("Exact configured provider subject binding required")
        endpoint = BASE + f"/admin/realms/{REALM}/users/{subject}"
        current = _json(client.get(endpoint, headers=headers, timeout=10, follow_redirects=False))
        if current.get("id") != subject or current.get("username") != username:
            raise ValueError("Existing provider subject/username binding differs")
        actions = current.get("requiredActions", [])
        if not isinstance(actions, list) or not all(
            isinstance(action, str) for action in cast(list[object], actions)
        ):
            raise ValueError("Malformed required actions; preserve existing provider state")
        desired = _synthetic_profile(username)
        if "UPDATE_PROFILE" in actions:
            # Profile fields and this one satisfied action change atomically in
            # Keycloak's validated user update; all other actions are preserved.
            desired["requiredActions"] = [
                action for action in cast(list[str], actions) if action != "UPDATE_PROFILE"
            ]
        if any(current.get(key) != value for key, value in desired.items()):
            updates.append((endpoint, desired))
    for endpoint, payload in updates:
        response = client.put(
            endpoint, json=payload, headers=headers, timeout=10, follow_redirects=False
        )
        response.raise_for_status()


def _reconcile_subject_mappers(
    client: httpx.Client, headers: dict[str, str], state: dict[str, object]
) -> None:
    """Exact bound BFF/lifecycle clients only; preserve scopes and other mappers.

    Keycloak's built-in Subject mapper emits the actual authenticated user ID.
    This never fabricates a subject or changes the strict resource-token parser.
    """
    clients = cast(dict[str, dict[str, str]], state["clients"])
    for surface in ("main", "help", "lifecycle"):
        configured = clients[surface]
        client_id = configured["id"]
        if str(UUID(client_id)) != client_id:
            raise ValueError("Canonical configured client UUID required")
        endpoint = BASE + f"/admin/realms/{REALM}/clients/{client_id}"
        current = _json(client.get(endpoint, headers=headers, timeout=10, follow_redirects=False))
        if (
            current.get("id") != client_id
            or current.get("clientId") != configured["client_id"]
            or current.get("protocol") != "openid-connect"
        ):
            raise ValueError("Existing provider client binding differs")
        if surface == "lifecycle" and (
            configured["client_id"] != "care-link-lifecycle"
            or current.get("serviceAccountsEnabled") is not True
            or current.get("fullScopeAllowed") is not False
        ):
            raise ValueError("Lifecycle client must retain exact scoped service-account boundary")
        response = client.get(
            endpoint + "/protocol-mappers/models",
            headers=headers,
            timeout=10,
            follow_redirects=False,
        )
        response.raise_for_status()
        if len(response.content) > 1024 * 1024:
            raise ValueError("Oversized protocol mapper response")
        document: object = response.json()
        if not isinstance(document, list) or not all(
            isinstance(item, dict) for item in cast(list[object], document)
        ):
            raise ValueError("Protocol mapper array required")
        desired_mappers = (
            (_subject_mapper(), _lifecycle_role_mapper())
            if surface == "lifecycle"
            else (
                _subject_mapper(),
                _authentication_time_mapper(),
                _introspection_audience_mapper(configured["client_id"]),
            )
        )
        for desired in desired_mappers:
            matches = [
                item
                for item in cast(list[dict[str, object]], document)
                if item.get("name") == desired["name"]
            ]
            if len(matches) > 1:
                raise ValueError("Ambiguous configured required mapper")
            if not matches:
                result = client.post(
                    endpoint + "/protocol-mappers/models",
                    json=desired,
                    headers=headers,
                    timeout=10,
                    follow_redirects=False,
                )
            else:
                mapper = matches[0]
                if all(mapper.get(key) == value for key, value in desired.items()):
                    continue
                mapper_id = mapper.get("id")
                if not isinstance(mapper_id, str) or str(UUID(mapper_id)) != mapper_id:
                    raise ValueError("Canonical existing required mapper UUID required")
                result = client.put(
                    endpoint + "/protocol-mappers/models/" + mapper_id,
                    json={**desired, "id": mapper_id},
                    headers=headers,
                    timeout=10,
                    follow_redirects=False,
                )
            result.raise_for_status()


def _reconcile_lifecycle_admin_scope(
    client: httpx.Client, headers: dict[str, str], state: dict[str, object]
) -> None:
    """Associate the verified provider built-in scope to lifecycle only.

    Keycloak26.8.2 requires both its Admin API audience and kc-admin-api scope.
    Do not manufacture a replacement scope/audience or disable the provider check.
    Existing service-account roles and fullScopeAllowed remain unchanged.
    """
    lifecycle = cast(dict[str, dict[str, str]], state["clients"])["lifecycle"]
    client_id = lifecycle["id"]
    if lifecycle["client_id"] != "care-link-lifecycle" or str(UUID(client_id)) != client_id:
        raise ValueError("Exact configured lifecycle client required")
    base = BASE + f"/admin/realms/{REALM}"
    endpoint = base + "/clients/" + client_id
    current = _json(client.get(endpoint, headers=headers, timeout=10, follow_redirects=False))
    if (
        current.get("id") != client_id
        or current.get("clientId") != lifecycle["client_id"]
        or current.get("protocol") != "openid-connect"
        or current.get("serviceAccountsEnabled") is not True
        or current.get("fullScopeAllowed") is not False
    ):
        raise ValueError("Lifecycle scoped service-account boundary differs")
    scopes = _objects(
        client.get(base + "/client-scopes", headers=headers, timeout=10, follow_redirects=False)
    )
    matches = [scope for scope in scopes if scope.get("name") == "kc-admin-api"]
    if len(matches) != 1:
        raise ValueError("Exact built-in kc-admin-api scope required")
    scope = matches[0]
    scope_id = scope.get("id")
    if (
        scope.get("protocol") != "openid-connect"
        or not isinstance(scope_id, str)
        or str(UUID(scope_id)) != scope_id
    ):
        raise ValueError("Invalid built-in kc-admin-api scope binding")
    mappers = _objects(
        client.get(
            base + "/client-scopes/" + scope_id + "/protocol-mappers/models",
            headers=headers,
            timeout=10,
            follow_redirects=False,
        )
    )
    if (
        len(mappers) != 1
        or mappers[0].get("protocol") != "openid-connect"
        or mappers[0].get("protocolMapper") != "oidc-admin-api-audience-mapper"
    ):
        raise ValueError("Unrecognized built-in Admin API audience mapper")
    existing = _objects(
        client.get(
            endpoint + "/default-client-scopes",
            headers=headers,
            timeout=10,
            follow_redirects=False,
        )
    )
    if any(scope.get("id") == scope_id for scope in existing):
        return
    result = client.put(
        endpoint + "/default-client-scopes/" + scope_id,
        headers=headers,
        timeout=10,
        follow_redirects=False,
    )
    result.raise_for_status()


def bootstrap(
    client: httpx.Client,
    admin_password: str,
    state_path: Path,
    *,
    main_origin: str = "https://main.localhost:18443",
    help_origin: str = "https://help.localhost:19443",
) -> dict[str, object]:
    """Run only under the coordinator's exact isolated-lab authorization."""
    state = private_state(state_path, main_origin, help_origin)
    response = client.post(
        BASE + "/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": "imp02-owner-admin",
            "password": admin_password,
        },
        timeout=10,
        follow_redirects=False,
    )
    token = _json(response).get("access_token")
    if not isinstance(token, str):
        raise ValueError("Verified TLS bootstrap login failed")
    headers = {"Authorization": "Bearer " + token}
    result = client.post(
        BASE + "/admin/realms",
        json=realm_document(state),
        headers=headers,
        timeout=30,
        follow_redirects=False,
    )
    if result.status_code not in {201, 409}:
        result.raise_for_status()
    realm = _json(
        client.get(
            BASE + "/admin/realms/" + REALM, headers=headers, timeout=10, follow_redirects=False
        )
    )
    attributes = cast(dict[str, object], realm.get("attributes", {}))
    if attributes.get("care-link.lab-binding") != state["binding"]:
        raise ValueError("Existing realm is outside this exact lab binding")
    _reconcile_synthetic_profiles(client, headers, state)
    _reconcile_subject_mappers(client, headers, state)
    _reconcile_lifecycle_admin_scope(client, headers, state)
    # Bound service-account lifecycle permission is limited to user management in
    # this disposable realm. It grants no main-realm or business authority.
    clients = cast(dict[str, dict[str, str]], state["clients"])
    lifecycle = clients["lifecycle"]
    service_account = _json(
        client.get(
            BASE + f"/admin/realms/{REALM}/clients/{lifecycle['id']}/service-account-user",
            headers=headers,
            timeout=10,
            follow_redirects=False,
        )
    )
    role_clients = client.get(
        BASE + f"/admin/realms/{REALM}/clients",
        params={"clientId": "realm-management"},
        headers=headers,
        timeout=10,
        follow_redirects=False,
    )
    role_clients.raise_for_status()
    representations = cast(list[dict[str, object]], role_clients.json())
    if len(representations) != 1:
        raise ValueError("Exact realm-management client not found")
    realm_management = str(representations[0]["id"])
    roles = [
        _json(
            client.get(
                BASE + f"/admin/realms/{REALM}/clients/{realm_management}/roles/" + name,
                headers=headers,
                timeout=10,
                follow_redirects=False,
            )
        )
        for name in ("manage-users", "view-users", "query-users")
    ]
    mapped = client.post(
        BASE
        + f"/admin/realms/{REALM}/users/{service_account['id']}/role-mappings/clients/"
        + realm_management,
        json=roles,
        headers=headers,
        timeout=10,
        follow_redirects=False,
    )
    mapped.raise_for_status()
    scoped = client.post(
        BASE
        + f"/admin/realms/{REALM}/clients/{lifecycle['id']}/scope-mappings/clients/"
        + realm_management,
        json=roles,
        headers=headers,
        timeout=10,
        follow_redirects=False,
    )
    scoped.raise_for_status()
    return state


def provision_local(service: IdentityService, state: dict[str, object]) -> None:
    """Controlled initial lab provision: provider groups never create these roles."""
    for account in cast(dict[str, dict[str, object]], state["users"]).values():
        service.provision(
            str(account["id"]), str(account["account_id"]), cast(list[str], account["roles"])
        )


def oidc_settings(state: dict[str, object], surface: str) -> dict[str, str]:
    if surface not in {"main", "help"}:
        raise ValueError("Exact BFF surface required")
    clients = cast(dict[str, dict[str, str]], state["clients"])
    return {
        "issuer": ISSUER,
        "client_id": clients[surface]["client_id"],
        "client_secret": clients[surface]["secret"],
        "redirect_uri": str(state[surface + "_origin"]) + "/v1/auth/callback",
        "authorization_endpoint": ISSUER + "/protocol/openid-connect/auth",
        "token_endpoint": ISSUER + "/protocol/openid-connect/token",
        "jwks_uri": ISSUER + "/protocol/openid-connect/certs",
        "introspection_endpoint": ISSUER + "/protocol/openid-connect/token/introspect",
        "revocation_endpoint": ISSUER + "/protocol/openid-connect/revoke",
        "resource_audience": "care-link-resource",
        "mfa_acr": "2",
        "access_token_type": "JWT",
    }


def public_summary(state: dict[str, object]) -> dict[str, object]:
    document = realm_document(state)
    # Source configuration identity excludes all generated secrets and raw users.
    return {
        "realm": REALM,
        "issuer": ISSUER,
        "account_count": len(cast(dict[str, object], state["users"])),
        "synthetic_owner_role_playing": True,
        "auth_flow": document["browserFlow"],
        "amr_source": "completed password/OTP authenticator references, never hardcoded claims",
    }
