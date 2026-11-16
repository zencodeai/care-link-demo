"""Fixed additive resource names and the credential-exclusive runtime binding."""

import copy
import json
from pathlib import Path
from typing import cast

from .profiles import ACTIVE
from .provider import actor_registry, oidc_settings

PREFIX = ACTIVE.prefix
ROOT = "/run/care-link-imp03-002"
CONFIG = ROOT + "/configuration"
ROLE_UID = {"identity": 22011, "core": 22012, "data": 22013, "pdp": 22014, "journal": 22015}
AUTH_UID = {name: 22031 + index for index, name in enumerate(ROLE_UID)}
MESH_IP = {name: ACTIVE.mesh_prefix + str(11 + index) for index, name in enumerate(ROLE_UID)}
MESH_NETWORK = PREFIX + "-mesh"
INGRESS_NETWORK = PREFIX + "-ingress"
RUNTIME_IMAGE = (
    "care-link-imp03:qualification-cont1"
    if ACTIVE.name == "continuation-001"
    else "care-link-imp03:qualification-003"
)
LABEL = "care-link.scope=imp03-003-option-b"
PRIVATE = ACTIVE.private
KUBE = [
    "kubectl",
    "--kubeconfig",
    "/private/tmp/care-link-imp02-002/cluster/kubeconfig",
    "--context",
    "kind-care-link-imp02-002",
    "--request-timeout=20s",
]
NODE = "care-link-imp02-002-control-plane"
PG_NODEPORT = 30445
Record = dict[str, object]


def volume_names() -> list[str]:
    names = ["operator", "fence", "opa", "identity-db", "identity-provider", "data-db"]
    if ACTIVE.name == "continuation-001":
        names += ["postgres-config", "postgres-data", "browser-home"]
    for role in ROLE_UID:
        names.extend(
            role + "-" + suffix
            for suffix in (
                "config",
                "backend",
                "outbound",
                "authorization",
                "proxy",
                "agent",
                "svid",
            )
        )
    return [PREFIX + "-" + name for name in names]


def mount(name: str, destination: str, *, readonly: bool = False) -> str:
    return (
        "type=volume,source="
        + PREFIX
        + "-"
        + name
        + ",destination="
        + destination
        + (",readonly" if readonly else "")
    )


def binding(
    provider: Record,
    database_passwords: dict[str, str],
    opa_digest: str,
) -> Record:
    from psycopg.conninfo import make_conninfo

    example = Path(__file__).resolve().parents[2] / "tools/imp03_runtime/bindings.example.json"
    result = cast(Record, copy.deepcopy(json.loads(example.read_text())))
    result["main_origin"] = ACTIVE.main_origin
    result["actors"] = actor_registry(provider)
    if ACTIVE.name == "continuation-001":
        result["actors"] = [
            actor
            for actor in actor_registry(provider)
            if actor["roles"] in (["pid"], ["worker"], ["supervisor"])
        ]
    result["identity"] = {
        "oidc": oidc_settings(provider),
        "provider_address": "127.0.0.1",
        "provider_ca": CONFIG + "/identity/shared-ca.crt",
    }
    for role in ("identity", "data"):
        target = cast(Record, result[role])
        target["store_dsn"] = make_conninfo(
            host="postgres.care-link-imp02-002.svc.cluster.local",
            hostaddr="127.0.0.1",
            port=5432,
            dbname={"identity": "imp03_identity_002", "data": "imp03_runtime_002"}[role],
            user="imp03_" + role + "_runtime_002",
            password=database_passwords[role],
            sslmode="verify-full",
            sslrootcert=CONFIG + "/" + role + "/shared-ca.crt",
        )
    result["pdp"] = {"executable": "/opt/opa", "executable_digest": opa_digest}
    mesh = cast(dict[str, Record], result["mesh"])
    for role, address in MESH_IP.items():
        mesh[role]["address"] = address
        mesh[role]["trust_bundle"] = ROOT + "/" + role + "/authorization/bundle.pem"
    browser = cast(Record, result["browser_tls"])
    browser.update(
        address=MESH_IP["core"],
        port=ACTIVE.browser_port,
        certificate=ROOT + "/core/proxy/manual.crt",
        private_key=ROOT + "/core/proxy/manual.key",
    )
    return result
