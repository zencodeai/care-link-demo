"""Fresh-only private issuance and role configuration for the accepted target."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from cryptography import x509
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from psycopg.conninfo import make_conninfo

from .config import (
    ACTORS,
    AUTH_UID,
    CONFIG,
    DATABASES,
    DESTINATIONS,
    ENVOY_IMAGE,
    ISSUER,
    LOGINS,
    MAIN,
    OPA_DIGEST,
    PG_HOST,
    PRIVATE,
    PROVIDER,
    REALM,
    REPO,
    ROLE_UID,
    ROLES,
    ROOT,
    SPIRE_IMAGE,
    Record,
    record,
    text,
    validate_binding,
    verify_sources,
    write,
)


def integer(value: Record, key: str) -> int:
    item = value.get(key)
    if type(item) is not int or item < 0:
        raise ValueError("Explicit nonnegative integer required")
    return item


def absolute(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or not str(path).startswith(ROOT + "/"):
        raise ValueError("Exact container-internal runtime path required")
    return path


def prepare(binding: Record, root: Path, *, assign_ownership: bool = False) -> None:
    if assign_ownership and os.geteuid() != 0:
        raise ValueError("Assignment requires authorized Linux custody supervisor")
    validate_binding(binding)
    verify_sources()
    absolute(str(root))
    root.mkdir(mode=0o700, parents=False, exist_ok=False)
    keys = {name: Ed25519PrivateKey.generate() for name in ("identity", "core", "journal")}
    journal_id = str(uuid4())
    for role in ROLES:
        directory = root / role
        directory.mkdir(mode=0o700)
        cfg: Record = {
            **record(record(binding["roles"])[role]),
            "role": role,
            "session": "imp03-002",
            "imp04_target": "care-link-imp04-002",
        }
        for name in ("identity", "core", "journal"):
            public_path = directory / (name + ".pub")
            write(
                public_path,
                keys[name]
                .public_key()
                .public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo),
            )
            cfg[name + "_public_key"] = str(public_path)
        if role in {"identity", "core", "journal"}:
            path = directory / "signing.key"
            write(path, keys[role].private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
            cfg["core_signing_key" if role == "core" else "signing_key"] = str(path)
            cfg["signing_key_id"] = "imp03-002-" + role
        if role == "core":
            cfg["web_directory"] = binding["web_directory"]
        if role == "identity":
            cfg.update(record(binding["identity"]))
            cfg["main_origin"] = binding["main_origin"]
            path = directory / "custody.key"
            write(path, Fernet.generate_key())
            cfg["custody_key"] = str(path)
        if role == "data":
            cfg.update(record(binding["data"]))
            for key in ("content_key", "cursor_key"):
                path = directory / (key + ".key")
                write(path, secrets.token_bytes(32))
                cfg[key] = str(path)
            fixture = json.loads((REPO / "config/demo/imp04/directory-fixtures.json").read_text())
            pin = json.loads((REPO / "config/demo/imp04/directory-source-key-pin.json").read_text())
            from care_link_data.directory_admission import VerifiedDirectoryAdmission
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

            source_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(pin["public_key_hex"]))
            VerifiedDirectoryAdmission(fixture["signed_admissions"], {pin["key_id"]: source_key})
            source_key_path = directory / "directory-source.pub"
            write(
                source_key_path,
                source_key.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo),
            )
            cfg["directory_signed_admissions"] = fixture["signed_admissions"]
            cfg["directory_trusted_keys"] = {pin["key_id"]: str(source_key_path)}
            cfg["disclosures"] = json.loads(
                (REPO / "config/demo/imp03/disclosures.json").read_text()
            )
        if role == "pdp":
            cfg.update(record(binding["pdp"]))
            manifest = json.loads((REPO / "config/demo/imp04/policy/bootstrap.json").read_text())
            path = directory / "manual.rego"
            write(path, (REPO / "config/demo/imp04/policy/manual.rego").read_bytes())
            public_path = directory / "policy.pub"
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

            key = Ed25519PublicKey.from_public_bytes(base64.b64decode(manifest["public_key"]))
            write(public_path, key.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
            cfg["policy"] = {
                "source": str(path),
                "signature": manifest["signature"],
                "public_key": str(public_path),
            }
        if role == "journal":
            cfg.update(journal_directory=str(directory / "state"), journal_id=journal_id)
        write(directory / "config.json", (json.dumps(cfg, indent=2) + "\n").encode())
        if assign_ownership:
            if os.geteuid() != 0:
                raise ValueError("Assignment requires the authorized Linux custody supervisor")
            uid = integer(cfg, "uid")
            for path in directory.iterdir():
                os.chown(path, uid, uid)
            os.chown(directory, uid, uid)
    # This public receipt carries no bearer or database credentials.
    receipt: Record = {
        "session": "imp03-002",
        "actors": binding["actors"],
        "journal_id": journal_id,
        "policy_digest": hashlib.sha256(
            (REPO / "config/demo/imp04/policy/manual.rego").read_bytes()
        ).hexdigest(),
        "configuration_digests": {
            role: hashlib.sha256((root / role / "config.json").read_bytes()).hexdigest()
            for role in ROLES
        },
    }
    write(root / "receipt.json", (json.dumps(receipt, indent=2) + "\n").encode())
    write(root / "bindings.json", (json.dumps(binding, indent=2) + "\n").encode())
    if assign_ownership:
        root.chmod(0o711)


_record = record
_text = text


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
    validate_provider(state)
    expected_roles = roles if roles is not None else ACTORS
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
                "email": "imp04-" + name + "@care-link.invalid",
                "emailVerified": False,
                "firstName": "Synthetic",
                "lastName": "Owner-operated profile",
                "requiredActions": [],
                "credentials": [
                    {"type": "password", "value": actor["password"], "temporary": False},
                    {
                        "type": "otp",
                        "userLabel": "imp04-owned-lab-totp",
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
        "attributes": {"care-link.imp04-binding": state["binding"], "acr.loa.map": '{"2":2}'},
        "otpPolicyType": "totp",
        "otpPolicyAlgorithm": "HmacSHA1",
        "otpPolicyDigits": 6,
        "otpPolicyPeriod": 30,
        "otpPolicyLookAheadWindow": 1,
        "otpPolicyCodeReusable": False,
        "browserFlow": "care-link-imp04-browser",
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
            {"alias": "imp04-loa2", "config": {"loa-condition-level": "2", "loa-max-age": "0"}},
            {
                "alias": "imp04-password-method",
                "config": {"default.reference.value": "pwd", "default.reference.maxAge": "300"},
            },
            {
                "alias": "imp04-otp-method",
                "config": {"default.reference.value": "otp", "default.reference.maxAge": "300"},
            },
        ],
        "authenticationFlows": [
            {
                "alias": "care-link-imp04-browser",
                "description": "Actual password and OTP for separate synthetic IMP-03 actors",
                "providerId": "basic-flow",
                "topLevel": True,
                "builtIn": False,
                "authenticationExecutions": [
                    {
                        "flowAlias": "imp04-two-factors",
                        "authenticatorFlow": True,
                        "requirement": "CONDITIONAL",
                        "priority": 10,
                        "userSetupAllowed": False,
                    }
                ],
            },
            {
                "alias": "imp04-two-factors",
                "providerId": "basic-flow",
                "topLevel": False,
                "builtIn": False,
                "authenticationExecutions": [
                    {
                        "authenticator": "conditional-level-of-authentication",
                        "authenticatorConfig": "imp04-loa2",
                        "authenticatorFlow": False,
                        "requirement": "REQUIRED",
                        "priority": 0,
                    },
                    {
                        "authenticator": "auth-username-password-form",
                        "authenticatorConfig": "imp04-password-method",
                        "authenticatorFlow": False,
                        "requirement": "REQUIRED",
                        "priority": 10,
                    },
                    {
                        "authenticator": "auth-otp-form",
                        "authenticatorConfig": "imp04-otp-method",
                        "authenticatorFlow": False,
                        "requirement": "REQUIRED",
                        "priority": 20,
                    },
                ],
            },
        ],
    }


def validate_provider(state: Record) -> None:
    if (
        set(state) != {"session", "realm", "binding", "main_origin", "users", "client"}
        or state["realm"] != REALM
        or state["main_origin"] != MAIN
        or state["session"] != "imp04-002"
    ):
        raise ValueError("Exact independently issued provider state required")
    users = record(state["users"])
    if set(users) != set(ACTORS):
        raise ValueError("Nine exact actor slots required")
    identities: list[str] = []
    credentials: list[str] = []
    for slot, role in ACTORS.items():
        actor = record(users[slot])
        if (
            set(actor) != {"id", "account_id", "username", "password", "totp_secret", "roles"}
            or actor["username"] != "imp04-" + slot
            or actor["roles"] != [role]
        ):
            raise ValueError("Exact independent actor role/username required")
        identities.extend([text(actor, "id"), text(actor, "account_id")])
        credentials.extend([text(actor, "password"), text(actor, "totp_secret")])
    if len(set(identities)) != len(identities) or len(set(credentials)) != len(credentials):
        raise ValueError("Actors must have distinct identities and credentials")


def provider_state() -> Record:
    state: Record = {
        "session": "imp04-002",
        "realm": REALM,
        "binding": str(uuid4()),
        "main_origin": MAIN,
        "users": {
            slot: {
                "id": str(uuid4()),
                "account_id": str(uuid4()),
                "username": "imp04-" + slot,
                "password": secrets.token_urlsafe(36),
                "totp_secret": base64.b32encode(secrets.token_bytes(20)).decode(),
                "roles": [role],
            }
            for slot, role in ACTORS.items()
        },
        "client": {
            "id": str(uuid4()),
            "client_id": REALM + "-browser",
            "secret": secrets.token_urlsafe(48),
        },
    }
    validate_provider(state)
    return state


def make_binding(state: Record, passwords: dict[str, str]) -> Record:
    validate_provider(state)
    issuer_base = ISSUER + "/protocol/openid-connect/"
    oidc = {
        "issuer": ISSUER,
        "client_id": REALM + "-browser",
        "client_secret": text(record(state["client"]), "secret"),
        "redirect_uri": MAIN + "/v1/auth/callback",
        "authorization_endpoint": issuer_base + "auth",
        "token_endpoint": issuer_base + "token",
        "jwks_uri": issuer_base + "certs",
        "introspection_endpoint": issuer_base + "token/introspect",
        "revocation_endpoint": issuer_base + "revoke",
        "resource_audience": REALM + "-resource",
        "mfa_acr": "2",
        "access_token_type": "JWT",
    }
    binding: Record = {
        "session": "imp03-002",
        "main_origin": MAIN,
        "web_directory": "/app/apps/web/dist",
        "actors": [
            {
                "account_id": record(raw)["account_id"],
                "subject": record(raw)["id"],
                "roles": record(raw)["roles"],
            }
            for raw in record(state["users"]).values()
        ],
        "roles": {
            role: {
                "uid": ROLE_UID[role],
                "proxy_uid": 22002,
                "fence_uid": 22000,
                "fence_socket": ROOT + "/fence/fence.sock",
                "backend_socket": ROOT + "/" + role + "/backend/app.sock",
                "outbound": {
                    destination: {
                        "socket": ROOT + "/" + role + "/outbound/" + destination + ".sock",
                        "origin": "https://" + destination + ".imp04.mesh:8443",
                    }
                    for destination in DESTINATIONS[role]
                },
            }
            for role in ROLES
        },
        "identity": {
            "store_dsn": make_conninfo(
                host=PG_HOST,
                hostaddr="127.0.0.1",
                port=5432,
                dbname=DATABASES["identity"],
                user=LOGINS["identity"],
                password=passwords["identity"],
                sslmode="verify-full",
                sslrootcert=CONFIG + "/identity/shared-ca.crt",
            ),
            "provider_address": "127.0.0.1",
            "provider_ca": CONFIG + "/identity/shared-ca.crt",
            "oidc": oidc,
        },
        "data": {
            "store_dsn": make_conninfo(
                host=PG_HOST,
                hostaddr="127.0.0.1",
                port=5432,
                dbname=DATABASES["data"],
                user=LOGINS["data"],
                password=passwords["data"],
                sslmode="verify-full",
                sslrootcert=CONFIG + "/data/shared-ca.crt",
            )
        },
        "pdp": {"executable": "/opt/opa", "executable_digest": OPA_DIGEST},
        "mesh": {
            role: {
                "address": "172.29.44." + str(11 + index),
                "port": 8443,
                "authorization_socket": ROOT + "/" + role + "/authorization/authz.sock",
                "spire_socket": ROOT + "/" + role + "/spire/agent.sock",
                "proxy_config": ROOT + "/" + role + "/proxy/envoy.json",
                "trust_bundle": ROOT + "/" + role + "/authorization/bundle.pem",
                "authorization_uid": AUTH_UID[role],
            }
            for index, role in enumerate(ROLES)
        },
        "browser_tls": {
            "address": "172.29.44.12",
            "port": 30443,
            "certificate": ROOT + "/core/proxy/manual.crt",
            "private_key": ROOT + "/core/proxy/manual.key",
        },
        "pins": {
            "envoy_image": ENVOY_IMAGE,
            "envoy_version": "1.40.2",
            "spire_image": SPIRE_IMAGE,
            "spire_version": "1.16.0",
            "svid_ttl_seconds": 300,
        },
    }
    validate_binding(binding)
    return binding


def issue_tls(directory: Path) -> None:
    directory.mkdir(mode=0o700)
    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "IMP04 plans002 private transport CA")]
    )
    ca = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=7))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False
        )
        .add_extension(
            x509.KeyUsage(False, False, False, False, False, True, True, False, False),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    write(directory / "ca.crt", ca.public_bytes(Encoding.PEM))
    write(
        directory / "ca.key",
        ca_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()),
    )
    for filename, hostname in [
        ("manual", "plans.localhost"),
        ("keycloak", "id.plans.localhost"),
        ("postgres", PG_HOST),
    ]:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)]))
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=2))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
            )
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                critical=False,
            )
            .add_extension(
                x509.KeyUsage(True, False, True, False, False, False, False, False, False),
                critical=True,
            )
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256())
        )
        write(directory / (filename + ".crt"), cert.public_bytes(Encoding.PEM))
        write(
            directory / (filename + ".key"),
            key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()),
        )


def issue(private: Path = PRIVATE) -> Record:
    """Issue only fresh private inputs for this exact target, without runtime I/O."""
    if private != PRIVATE or not private.is_absolute() or private.is_symlink():
        raise ValueError("Exact accepted IMP-04 private root required")
    verify_sources()
    private.mkdir(mode=0o700, parents=False, exist_ok=False)
    os.chmod(private, 0o700)
    issue_tls(private / "tls")
    state = provider_state()
    passwords = {role: secrets.token_urlsafe(36) for role in ["identity", "data"]}
    binding = make_binding(state, passwords)
    postgres_password = secrets.token_urlsafe(36)
    provider_database_password = secrets.token_urlsafe(36)
    provider_admin_password = secrets.token_urlsafe(36)
    admin = {
        role + "_admin_dsn": make_conninfo(
            host=PG_HOST,
            hostaddr="127.0.0.1",
            port=5432,
            dbname="postgres",
            user="postgres",
            password=postgres_password,
            sslmode="verify-full",
            sslrootcert=CONFIG + "/" + role + "/shared-ca.crt",
        )
        for role in ["identity", "data"]
    }
    values: Record = {
        "binding": binding,
        "admin": admin,
        "provider": state,
        "postgres_password": postgres_password,
        "provider_database_password": provider_database_password,
        "provider_admin_password": provider_admin_password,
    }
    write(private / "inputs.json", json.dumps(values, indent=2) + "\n")
    write(private / "provider-state.json", json.dumps(state, indent=2) + "\n")
    write(private / "realm.json", json.dumps(realm_document(state), indent=2) + "\n")
    # Password uses URL-safe generated bytes; explicit quoting remains deterministic.
    from psycopg import sql

    provider_sql = (
        sql.SQL(
            "CREATE ROLE imp04_provider_runtime_002 LOGIN NOSUPERUSER NOCREATEDB "
            "NOCREATEROLE NOBYPASSRLS PASSWORD {};\n"
            "CREATE DATABASE imp04_provider_002 OWNER imp04_provider_runtime_002;\n"
            "REVOKE ALL ON DATABASE imp04_provider_002 FROM PUBLIC;\n"
            "GRANT CONNECT ON DATABASE imp04_provider_002 TO imp04_provider_runtime_002;\n"
            "REVOKE TEMPORARY ON DATABASE imp04_provider_002 FROM PUBLIC;\n"
        )
        .format(sql.Literal(provider_database_password))
        .as_string()
    )
    write(private / "provider-init.sql", provider_sql)
    write(
        private / "browser.json",
        json.dumps(
            {
                "mainOrigin": MAIN,
                "oidcOrigin": PROVIDER,
                "helpOrigin": "https://help.localhost:19443",
                "staticOrigin": "https://static.localhost:21443",
                "caFile": str(private / "tls/ca.crt"),
                "actors": {
                    slot: {
                        "accountId": record(actor)["account_id"],
                        "role": ACTORS[slot],
                        "username": record(actor)["username"],
                        "password": record(actor)["password"],
                        "totpSecret": record(actor)["totp_secret"],
                    }
                    for slot, actor in record(state["users"]).items()
                },
            },
            indent=2,
        )
        + "\n",
    )
    public: Record = {
        "target": "care-link-imp04-002",
        "actors": binding["actors"],
        "policy_digest": hashlib.sha256(
            (REPO / "config/demo/imp04/policy/manual.rego").read_bytes()
        ).hexdigest(),
        "transport_ca_sha256": hashlib.sha256((private / "tls/ca.crt").read_bytes()).hexdigest(),
        "credentials_issued": True,
        "deployed": False,
    }
    write(private / "issuance-summary.json", json.dumps(public, indent=2) + "\n")
    return public


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["issue"])
    parser.add_argument("--private", type=Path, default=PRIVATE)
    args = parser.parse_args()
    print(json.dumps(issue(args.private), indent=2))


if __name__ == "__main__":
    main()
