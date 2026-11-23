"""Private inputs and initial-only dependency provisioning for the G-10 Kind qualification."""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
from care_link_data import PostgresStore
from care_link_domain import Actor, canonical_training
from care_link_identity import IdentityService
from care_link_recovery_control import FileJournal
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from psycopg import sql
from psycopg.conninfo import make_conninfo

from tools.imp02_application.provider_bootstrap import realm_document
from tools.imp03_runtime.compose import identity_service

ROOT = Path(__file__).resolve().parents[2]
STATE = Path("/private/tmp/care-link-imp10-008-inputs")
CLUSTER = "care-link-imp10-008"
SCOPE = "imp10-008"
ID_ORIGIN = "https://id.imp10-008.localhost:39443"
MAIN_ORIGIN = "https://main.imp10-008.localhost:38441"
HELP_ORIGIN = "https://help.imp10-008.localhost:39444"
REALM = f"{SCOPE}-qualified"
ISSUER = f"{ID_ORIGIN}/realms/{REALM}"
IDENTITY_KEY = f"{SCOPE}-identity"
POSTGRES_PORT = 5432
ROLES = ("pid", "worker", "supervisor", "trainer", "receiver", "governance")
DB_ROLES = ("identity", "data", "receiver", "training")
Record = dict[str, Any]


def write(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        path.chmod(0o600)
        stream.write(data)


def encode(value: object) -> bytes:
    return json.dumps(value, sort_keys=True).encode()


def artifact(path: str) -> bytes:
    return (ROOT / path).read_bytes()


def tls_inputs(directory: Path = STATE) -> None:
    ca_key = generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name(
        [x509.NameAttribute(x509.NameOID.COMMON_NAME, "CARE-Link G-10 ephemeral CA")]
    )
    now = datetime.now(UTC)
    builder = (
        x509.CertificateBuilder()
        .issuer_name(ca_name)
        .not_valid_before(now - timedelta(minutes=3))
        .not_valid_after(now + timedelta(days=2))
    )
    ca = (
        builder.subject_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .sign(ca_key, SHA256())
    )
    write(directory / "browser-ca.pem", ca.public_bytes(Encoding.PEM))
    for role, names in {
        "postgres": (
            x509.DNSName("postgres"),
            x509.DNSName(f"postgres.{CLUSTER}.svc.cluster.local"),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
        ),
        "keycloak": (x509.DNSName("id.imp10-008.localhost"),),
        "core": (x509.DNSName("main.imp10-008.localhost"),),
    }.items():
        key = generate_private_key(public_exponent=65537, key_size=2048)
        cert = (
            builder.subject_name(
                x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, names[0].value)])
            )
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .add_extension(x509.SubjectAlternativeName(names), critical=False)
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                critical=False,
            )
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
            )
            .sign(ca_key, SHA256())
        )
        write(directory / f"{role}.crt", cert.public_bytes(Encoding.PEM))
        write(
            directory / f"{role}.key",
            key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()),
        )


def signing_inputs() -> None:
    for name in ("identity", "core-signing", "journal", "policy", "receiver-mapping"):
        key = Ed25519PrivateKey.generate()
        write(
            STATE / f"{name}.sign",
            key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()),
        )
        write(
            STATE / f"{name}.pub",
            key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo),
        )


def oidc(settings: Record, surface: str) -> Record:
    origin = {"main": MAIN_ORIGIN, "help": HELP_ORIGIN}[surface]
    prefix = ISSUER + "/protocol/openid-connect/"
    return {
        "issuer": ISSUER,
        "client_id": f"care-link-{SCOPE}-{surface}",
        "client_secret": settings[f"{surface}_client_secret"],
        "redirect_uri": origin + "/v1/auth/callback",
        "authorization_endpoint": prefix + "auth",
        "token_endpoint": prefix + "token",
        "jwks_uri": prefix + "certs",
        "introspection_endpoint": prefix + "token/introspect",
        "revocation_endpoint": prefix + "revoke",
        "resource_audience": f"care-link-{SCOPE}-resource",
        "mfa_acr": "2",
        "access_token_type": "JWT",
    }


def realm(settings: Record) -> Record:
    exemplar = settings["accounts"][0]
    value: Record = realm_document(
        {
            "binding": settings["journal_id"],
            "main_origin": MAIN_ORIGIN,
            "help_origin": HELP_ORIGIN,
            "users": {"main": {**exemplar, "id": exemplar["subject"], "username": "main"}},
            "clients": {
                surface: {
                    "id": str(uuid4()),
                    "client_id": f"care-link-{surface}",
                    "secret": settings.get(f"{surface}_client_secret", secrets.token_urlsafe(32)),
                }
                for surface in ("main", "help", "lifecycle")
            },
        }
    )
    value["realm"] = REALM
    value["clients"] = value["clients"][:2]
    for surface, client in zip(("main", "help"), value["clients"], strict=True):
        binding = oidc(settings, surface)
        client.update(clientId=binding["client_id"], name=binding["client_id"])
        for mapper in client["protocolMappers"]:
            config = mapper["config"]
            if config.get("included.custom.audience") == "care-link-resource":
                config["included.custom.audience"] = binding["resource_audience"]
            if config.get("included.client.audience") == f"care-link-{surface}":
                config["included.client.audience"] = binding["client_id"]
    otp_template = value["users"][0]["credentials"][1]
    users: list[Record] = []
    for account in settings["accounts"]:
        users.append(
            {
                "id": account["subject"],
                "username": account["username"],
                "enabled": True,
                "email": account["username"] + "@fixture.invalid",
                "emailVerified": True,
                "firstName": "Synthetic",
                "lastName": account["role"],
                "requiredActions": [],
                "credentials": [
                    {"type": "password", "value": account["password"], "temporary": False},
                    {**otp_template, "secretData": json.dumps({"value": account["totp_secret"]})},
                ],
            }
        )
    value["users"] = users
    return value


def prepare() -> Record:
    STATE.mkdir(mode=0o700, exist_ok=False)
    tls_inputs()
    signing_inputs()
    settings: Record = {
        name: secrets.token_urlsafe(32)
        for name in (
            "postgres_password",
            "keycloak_db_password",
            "keycloak_admin_password",
            "main_client_secret",
            "help_client_secret",
            *DB_ROLES,
        )
    }
    settings["journal_id"] = str(uuid4())
    settings["service_id"] = str(uuid4())
    settings["accounts"] = [
        {
            "role": role,
            "subject": str(uuid4()),
            "account_id": str(uuid4()),
            "username": f"{SCOPE}-{role}" + (f"-{index}" if index else ""),
            "password": secrets.token_urlsafe(24),
            "totp_secret": base64.b32encode(secrets.token_bytes(20)).decode(),
        }
        for role in ROLES
        for index in range(11 if role == "pid" else 2 if role in {"trainer", "receiver"} else 1)
    ]
    write(STATE / "settings.json", encode(settings))
    write(
        STATE / "browser-users.json",
        encode({a["username"]: a["password"] for a in settings["accounts"]}),
    )
    write(
        STATE / "browser-totp.json",
        encode({a["username"]: a["totp_secret"] for a in settings["accounts"]}),
    )
    for key in (
        "identity-custody",
        "data-content",
        "data-cursor",
        "receiver-content",
        "training-content",
    ):
        write(
            STATE / key,
            base64.urlsafe_b64encode(secrets.token_bytes(32))
            if key == "identity-custody"
            else secrets.token_bytes(32),
        )
    return settings


def secret(name: str, values: dict[str, bytes]) -> Record:
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "type": "Opaque",
        "metadata": {"name": name, "namespace": CLUSTER, "labels": {"care-link.session": SCOPE}},
        "data": {key: base64.b64encode(data).decode() for key, data in values.items()},
    }


def product_pins() -> Record:
    return json.loads(artifact("deploy/k8s/imp-02/products.json"))


def dependency_objects(settings: Record) -> list[Record]:
    from tools.imp02_lab import dependencies
    from tools.imp02_lab.model import LabInputs

    products = product_pins()
    assets = Path("/private/tmp/care-link-imp10-008-assets")
    inputs = LabInputs(
        products["images"],
        assets / "kind",
        assets / "calico.yaml",
        assets,
        products["kind_sha256"],
        products["calico_manifest_sha256"],
    )
    records: list[Record] = dependencies.manifests(inputs)
    for item in records:
        item["metadata"]["namespace"] = CLUSTER
        item["metadata"]["labels"]["care-link.session"] = SCOPE
        if item["kind"] == "Deployment":
            template = item["spec"]["template"]
            template["metadata"]["labels"]["care-link.session"] = SCOPE
            pod = template["spec"]
            c = pod["containers"][0]
            c["imagePullPolicy"] = "Never"
            if c["name"] == "keycloak":
                c["image"] = "care-link-imp02-keycloak:002"
                c["args"] = [
                    f"--hostname={ID_ORIGIN}" if x.startswith("--hostname=") else x
                    for x in c["args"]
                ]
                c["args"].append("--import-realm")
                c["volumeMounts"].append(
                    {"name": "realm", "mountPath": "/opt/keycloak/data/import", "readOnly": True}
                )
                pod["volumes"].append(
                    {
                        "name": "realm",
                        "secret": {"secretName": "imp10-oidc-realm", "defaultMode": 0o640},
                    }
                )
        if item["kind"] == "Service" and item["metadata"]["name"] == "keycloak":
            item["spec"]["ports"][0].update(port=39443, nodePort=30444)
        if item["kind"] == "NetworkPolicy" and item["metadata"]["name"] == "postgres-routes":
            route = item["spec"]["ingress"][0]
            route["from"].extend(
                {"podSelector": {"matchLabels": {"app": role}}}
                for role in ("data", "receiver", "training")
            )
    init = (
        "CREATE USER keycloak PASSWORD '"
        + settings["keycloak_db_password"]
        + "';\nCREATE DATABASE keycloak OWNER keycloak;\n"
    )
    return [
        secret(
            "imp02-passwords",
            {
                name: settings[name].encode()
                for name in ("postgres_password", "keycloak_db_password", "keycloak_admin_password")
            },
        ),
        secret(
            "imp02-pki",
            {
                **{
                    f"{role}.{ext}": (STATE / f"{role}.{ext}").read_bytes()
                    for role in ("postgres", "keycloak")
                    for ext in ("crt", "key")
                },
                "ca.crt": (STATE / "browser-ca.pem").read_bytes(),
            },
        ),
        secret("imp02-postgres-init", {"00-keycloak.sql": init.encode()}),
        secret("imp10-oidc-realm", {f"{REALM}-realm.json": encode(realm(settings))}),
        *records,
    ]


def dsn(
    settings: Record,
    role: str,
    *,
    host: str = "postgres",
    port: int = POSTGRES_PORT,
    ca: str = "/config/ca.pem",
    admin: bool = False,
) -> str:
    return make_conninfo(
        host=host,
        port=port,
        dbname=role if role in DB_ROLES else "postgres",
        user="postgres" if admin else "imp10_" + role,
        password=settings["postgres_password" if admin else role],
        sslmode="verify-full",
        sslrootcert=ca,
        connect_timeout=4,
    )


def merge_policy() -> bytes:
    base = artifact("config/demo/imp08/policy/manual.rego")
    addition = artifact("config/demo/imp10/policy/evaluation.rego")
    return base.rstrip() + b"\n\n" + addition.split(b"import rego.v1\n", 1)[1].lstrip()


def initialize(
    settings: Record,
    *,
    admin_port: int,
    admin_host: str = "127.0.0.1",
    existing_empty: bool = False,
    existing_migrations: bool = False,
) -> None:
    def local(role: str) -> str:
        return dsn(
            settings,
            role,
            host=admin_host,
            port=admin_port,
            ca=str(STATE / "browser-ca.pem"),
            admin=True,
        )

    if not existing_migrations:
        with psycopg.connect(local("postgres"), autocommit=True) as connection:
            for role in DB_ROLES:
                login = sql.Identifier("imp10_" + role)
                database = sql.Identifier(role)
                if not existing_empty:
                    connection.execute(
                        sql.SQL("CREATE ROLE {} LOGIN INHERIT NOBYPASSRLS PASSWORD {}").format(
                            login, sql.Literal(settings[role])
                        )
                    )
                    connection.execute(sql.SQL("CREATE DATABASE {}").format(database))
                    connection.execute(
                        sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(database)
                    )
                    connection.execute(
                        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(database, login)
                    )

        for role in DB_ROLES:
            directory = (
                ROOT
                / "services"
                / (role if role in {"identity", "data"} else "simulators")
                / "migrations"
            )
            migrations = (
                sorted(directory.glob("*.sql"))
                if role in {"identity", "data"}
                else [
                    directory
                    / {"receiver": "001_receiver.sql", "training": "002_training.sql"}[role]
                ]
            )
            login = sql.Identifier("imp10_" + role)
            with psycopg.connect(local(role), autocommit=True) as connection:
                if (
                    existing_empty
                    and connection.execute(
                        "SELECT nspname FROM pg_namespace WHERE nspname IN (%s, 'core')",
                        (role,),
                    ).fetchone()
                ):
                    raise ValueError("Recovery only applies to an empty owned database")
                for migration in migrations:
                    connection.execute(migration.read_bytes())
                if role == "identity":
                    connection.execute(
                        sql.SQL("GRANT USAGE ON SCHEMA identity TO {}").format(login)
                    )
                    connection.execute(
                        sql.SQL(
                            "GRANT SELECT,INSERT,UPDATE,DELETE ON identity.record TO {}"
                        ).format(login)
                    )
                else:
                    group = sql.Identifier(f"care_link_{role}_runtime")
                    connection.execute(sql.SQL("GRANT {} TO {}").format(group, login))

    from tools.imp02_application.config import private_key

    key = private_key(str(STATE / "journal.sign"))
    journal = FileJournal.provision(
        STATE / "journal", key, f"{SCOPE}-journal", journal_id=settings["journal_id"]
    )
    store = PostgresStore(local("data"))
    policy = STATE / "manual.rego"
    policy_digest = hashlib.sha256(
        policy.read_bytes() if policy.is_file() else merge_policy()
    ).hexdigest()
    with psycopg.connect(local("data")) as connection:
        guard = connection.execute(
            "SELECT bundle_digest, journal_id::text, epoch, mode FROM control.guard"
        ).fetchone()
        partial_principals = connection.execute(
            "SELECT count(*) FROM control.principal_guard"
        ).fetchone()
    if guard is None:
        store.bootstrap(journal.head(), policy_digest)
    elif (
        not existing_migrations
        or guard != (policy_digest, settings["journal_id"], 1, "ai_disabled")
        or partial_principals != (0,)
    ):
        raise ValueError("Existing guard does not match the untouched disposable bootstrap")
    actor_config = {
        "oidc": oidc(settings, "main"),
        "provider_address": "127.0.0.1",
        "provider_ca": str(STATE / "browser-ca.pem"),
        "store_dsn": local("identity"),
        "custody_key": str(STATE / "identity-custody"),
        "signing_key": str(STATE / "identity.sign"),
        "signing_key_id": IDENTITY_KEY,
        "main_origin": MAIN_ORIGIN,
    }
    clients: list[Any] = []
    service: IdentityService = identity_service(actor_config, clients)
    try:
        for account in settings["accounts"]:
            role, account_id = account["role"], account["account_id"]
            service.provision(account["subject"], account_id, [role])
            now = datetime.now(UTC)
            store.provision_principal(
                Actor(
                    account_id,
                    role,
                    1,
                    1,
                    now,
                    role != "pid",
                    "0" * 64,
                    0,
                    "",
                    now + timedelta(minutes=1),
                    str(uuid4()),
                )
            )
    finally:
        for client in clients:
            client.close()


def file_pin(path: str, data: bytes) -> Record:
    return {"path": path, "sha256": hashlib.sha256(data).hexdigest()}


def signed_mapping(settings: Record) -> bytes:
    from tools.imp02_application.config import private_key

    unsigned = {
        "key_id": "imp10-008-mapping",
        "revision": 1,
        "origin": "https://receiver.mesh:8443",
        "service_ids": [settings["service_id"]],
        "workload_id": "spiffe://care-link.demo/demo/receiver",
        "tags": {"environment": "demo", "population": "synthetic"},
    }
    raw = private_key(str(STATE / "receiver-mapping.sign")).sign(canonical_training(unsigned))
    return encode({**unsigned, "signature": base64.b64encode(raw).decode()})
