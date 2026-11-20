"""Exact credential-exclusive configuration for the accepted IMP-04 target."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import cast
from uuid import UUID

from psycopg.conninfo import conninfo_to_dict

Record = dict[str, object]
REPO = Path(__file__).resolve().parents[2]
PREFIX = "care-link-imp04-002"
PRIVATE = Path("/private/tmp/care-link-imp04-002")
ROOT = "/run/care-link-imp03-002"
CONFIG = ROOT + "/configuration"
ROLES = ("identity", "core", "data", "pdp", "journal")
ROLE_UID = {role: 22011 + i for i, role in enumerate(ROLES)}
AUTH_UID = {role: 22031 + i for i, role in enumerate(ROLES)}
MAIN = "https://plans.localhost:30443"
PROVIDER = "https://id.plans.localhost:31443"
REALM = "care-link-imp04-002"
ISSUER = PROVIDER + "/realms/" + REALM
PG_HOST = "postgres.imp04.internal"
DATABASES = {"identity": "imp04_identity_002", "data": "imp04_runtime_002"}
LOGINS = {"identity": "imp04_identity_runtime_002", "data": "imp04_data_runtime_002"}
ACTORS = {
    "pid": "pid",
    "pid-other": "pid",
    "carer": "carer",
    "professional": "professional_participant",
    "worker1": "worker",
    "worker2": "worker",
    "supervisor": "supervisor",
    "operator": "operator",
    "security": "security",
}
DESTINATIONS = {
    "identity": (),
    "core": ("identity", "data", "pdp"),
    "data": ("identity", "core", "pdp", "journal"),
    "pdp": (),
    "journal": (),
}
POLICY_DIGEST = "cc62534fcfaf302154ccb8e0aed6f386e7857e848354d8bb41d8d10177665604"
DIRECTORY_DIGEST = "26862660a86ce46088c9c98977eb78b6f49fe37ea585aac7c97ffc835443f6e6"
DIRECTORY_PIN_DIGEST = "7b74979946be2edbaa32a8d109d609c881600d353f1e7735d3536fbc2f626fdb"
ENVOY_IMAGE = (
    "envoyproxy/envoy@sha256:8de97e654644827d62afdbf7e1d3dc9fee01a8690d410dd1c63a30dc6b6cecbb"
)
SPIRE_IMAGE = (
    "ghcr.io/spiffe/spire-agent@sha256:"
    "ab3a8ce70435374cc5d84c81eabf0278dc046ddbc0a736d59694ba9e5975b1b6"
)
PROPOSAL_DIGEST = "645107a51875afc2f1ee2f6520639c8e013385ec6f92c2f12caf087e190d681a"
OPA_DIGEST = "8fc1c524f93b4369eb207961aba213d990604205fc49fe3ba923dfc125c8a422"


def record(value: object) -> Record:
    if not isinstance(value, dict):
        raise ValueError("Explicit configuration object required")
    return cast(Record, value)


def text(value: Record, key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError("Required nonempty configuration field: " + key)
    return item


def write(path: Path, content: str | bytes, *, mode: int = 0o600) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "wb") as stream:
        stream.write(content.encode() if isinstance(content, str) else content)
        stream.flush()
        os.fsync(stream.fileno())


def load(path: Path, *, owned: bool = True) -> Record:
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_mode & 0o077
        or (owned and info.st_uid != os.geteuid())
    ):
        raise ValueError("Owner-only regular configuration required")
    return record(json.loads(path.read_text(), object_pairs_hook=unique))


def unique(pairs: list[tuple[str, object]]) -> Record:
    result: Record = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate configuration field")
        result[key] = value
    return result


def proposal() -> Record:
    path = (
        REPO
        / "doc/IMP/slices/IMP-04-plans-consent-directory/sessions"
        / "002-deployment-qualification-preparation/target-proposal.json"
    )
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != PROPOSAL_DIGEST:
        raise ValueError("Exact accepted deployment proposal digest required")
    value = record(json.loads(content))
    if record(value["target"]).get("prefix") != PREFIX or record(value["target"]).get(
        "private_root"
    ) != str(PRIVATE):
        raise ValueError("Exact accepted IMP-04 target required")
    return value


def verify_sources() -> None:
    for path, expected in [
        (
            "config/demo/imp04/policy/bootstrap.json",
            "14dcdd98ff2b5bde8f38b2d3d8082bd18dd7616a0a9ef248f1a2a3967e4832e0",
        ),
        ("config/demo/imp04/policy/manual.rego", POLICY_DIGEST),
        ("config/demo/imp04/directory-fixtures.json", DIRECTORY_DIGEST),
        ("config/demo/imp04/directory-source-key-pin.json", DIRECTORY_PIN_DIGEST),
    ]:
        if hashlib.sha256((REPO / path).read_bytes()).hexdigest() != expected:
            raise ValueError("Accepted source pin differs: " + path)


def validate_binding(binding: Record) -> None:
    if set(binding) != {
        "session",
        "main_origin",
        "web_directory",
        "actors",
        "roles",
        "identity",
        "data",
        "pdp",
        "mesh",
        "browser_tls",
        "pins",
    }:
        raise ValueError("Exact IMP-04 binding fields required")
    if (
        binding["session"] != "imp03-002"
        or binding["main_origin"] != MAIN
        or binding["web_directory"] != "/app/apps/web/dist"
    ):
        raise ValueError("Exact protocol and new IMP-04 origin required")
    roles, mesh = record(binding["roles"]), record(binding["mesh"])
    if set(roles) != set(ROLES) or set(mesh) != set(ROLES):
        raise ValueError("All five exclusive custodians required")
    for index, role in enumerate(ROLES):
        cfg, target = record(roles[role]), record(mesh[role])
        expected = {
            "uid": ROLE_UID[role],
            "proxy_uid": 22002,
            "fence_uid": 22000,
            "fence_socket": ROOT + "/fence/fence.sock",
            "backend_socket": ROOT + "/" + role + "/backend/app.sock",
        }
        if set(cfg) != set(expected) | {"outbound"} or any(
            cfg.get(k) != v for k, v in expected.items()
        ):
            raise ValueError("Exact role UID/socket custody required")
        outbound = record(cfg["outbound"])
        if set(outbound) != set(DESTINATIONS[role]):
            raise ValueError("Exact role-specific egress required")
        for destination, raw in outbound.items():
            if record(raw) != {
                "socket": ROOT + "/" + role + "/outbound/" + destination + ".sock",
                "origin": "https://" + destination + ".imp04.mesh:8443",
            }:
                raise ValueError("Exact new-target mesh origin/socket required")
        expected_mesh = {
            "address": "172.29.44." + str(11 + index),
            "port": 8443,
            "authorization_socket": ROOT + "/" + role + "/authorization/authz.sock",
            "spire_socket": ROOT + "/" + role + "/spire/agent.sock",
            "proxy_config": ROOT + "/" + role + "/proxy/envoy.json",
            "trust_bundle": ROOT + "/" + role + "/authorization/bundle.pem",
            "authorization_uid": AUTH_UID[role],
        }
        if target != expected_mesh:
            raise ValueError("Exact independent mesh custody required")
    identity, data = record(binding["identity"]), record(binding["data"])
    if set(identity) != {"store_dsn", "oidc", "provider_address", "provider_ca"} or set(data) != {
        "store_dsn"
    }:
        raise ValueError("Exact role-exclusive credential fields required")
    passwords: set[str] = set()
    for role, cfg in [("identity", identity), ("data", data)]:
        dsn = conninfo_to_dict(text(cfg, "store_dsn"))
        expected_dsn = {
            "host": PG_HOST,
            "hostaddr": "127.0.0.1",
            "port": "5432",
            "dbname": DATABASES[role],
            "user": LOGINS[role],
            "sslmode": "verify-full",
            "sslrootcert": CONFIG + "/" + role + "/shared-ca.crt",
        }
        password = dsn.get("password", "")
        if (
            not isinstance(password, str)
            or set(dsn) != set(expected_dsn) | {"password"}
            or any(dsn.get(k) != v for k, v in expected_dsn.items())
            or len(password) < 32
        ):
            raise ValueError(
                "Exact independently credentialled verify-full IMP-04 database required"
            )
        passwords.add(password)
    if (
        len(passwords) != 2
        or identity.get("provider_address") != "127.0.0.1"
        or identity.get("provider_ca") != CONFIG + "/identity/shared-ca.crt"
    ):
        raise ValueError("Independent role credentials and provider transport required")
    oidc = record(identity["oidc"])
    endpoint = ISSUER + "/protocol/openid-connect/"
    expected_oidc = {
        "issuer": ISSUER,
        "client_id": REALM + "-browser",
        "resource_audience": REALM + "-resource",
        "redirect_uri": MAIN + "/v1/auth/callback",
        "authorization_endpoint": endpoint + "auth",
        "token_endpoint": endpoint + "token",
        "jwks_uri": endpoint + "certs",
        "introspection_endpoint": endpoint + "token/introspect",
        "revocation_endpoint": endpoint + "revoke",
        "mfa_acr": "2",
        "access_token_type": "JWT",
    }
    if (
        set(oidc) != set(expected_oidc) | {"client_secret"}
        or any(oidc.get(k) != v for k, v in expected_oidc.items())
        or len(text(oidc, "client_secret")) < 32
    ):
        raise ValueError("Exact independent provider/client/audience required")
    if record(binding["pdp"]) != {"executable": "/opt/opa", "executable_digest": OPA_DIGEST}:
        raise ValueError("Exact platform OPA pin required")
    actors = binding["actors"]
    if not isinstance(actors, list) or len(cast(list[object], actors)) != len(ACTORS):
        raise ValueError("Nine independently issued actors required")
    accounts: set[str] = set()
    subjects: set[str] = set()
    actor_roles: list[str] = []
    for raw in cast(list[object], actors):
        actor = record(raw)
        if (
            set(actor) != {"account_id", "subject", "roles"}
            or not isinstance(actor["roles"], list)
            or len(cast(list[object], actor["roles"])) != 1
        ):
            raise ValueError("Exact single-role issued actor required")
        account, subject = text(actor, "account_id"), text(actor, "subject")
        if (
            str(UUID(account)) != account
            or str(UUID(subject)) != subject
            or account in accounts
            or subject in subjects
        ):
            raise ValueError("Distinct canonical account/provider subjects required")
        accounts.add(account)
        subjects.add(subject)
        role_value = cast(list[object], actor["roles"])[0]
        if not isinstance(role_value, str):
            raise ValueError("Exact string actor role required")
        actor_roles.append(role_value)
    if sorted(actor_roles) != sorted(ACTORS.values()) or accounts & subjects:
        raise ValueError("Exact distinct nine-actor registry required")
    if record(binding["browser_tls"]) != {
        "address": "172.29.44.12",
        "port": 30443,
        "certificate": ROOT + "/core/proxy/manual.crt",
        "private_key": ROOT + "/core/proxy/manual.key",
    }:
        raise ValueError("Exact new browser TLS custody required")
    if record(binding["pins"]) != {
        "envoy_image": ENVOY_IMAGE,
        "envoy_version": "1.40.2",
        "spire_image": SPIRE_IMAGE,
        "spire_version": "1.16.0",
        "svid_ttl_seconds": 300,
    }:
        raise ValueError("Exact admitted mesh products required")
