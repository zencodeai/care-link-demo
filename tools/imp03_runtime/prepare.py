"""Create role-exclusive configuration from an explicitly supplied private binding."""

import base64
import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import httpx
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from psycopg.conninfo import conninfo_to_dict

from .config import FENCE_READER_GID, FENCE_RESTRICT_UID, ROLES, Record, integer, load, record, text

ROOT = Path(__file__).resolve().parents[2]
DESTINATIONS = {
    "core": ("identity", "data", "pdp"),
    "data": ("identity", "core", "pdp", "journal"),
    "identity": (),
    "pdp": (),
    "journal": (),
}


def write(path: Path, content: bytes) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())


def absolute(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or "imp02" in value or "imp-02" in value:
        raise ValueError("Independent absolute IMP-03 path required")
    return path


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
        raise ValueError("Exact IMP-03 binding fields required")
    if binding["session"] != "imp03-002":
        raise ValueError("Wrong isolated runtime session")
    origin = httpx.URL(text(binding, "main_origin"))
    if (
        origin.scheme != "https"
        or origin.path != "/"
        or origin.query
        or origin.fragment
        or origin.userinfo
    ):
        raise ValueError("Private exact HTTPS browser origin required")
    if not (absolute(text(binding, "web_directory")) / "index.html").is_file():
        raise ValueError("Built browser bundle required")
    roles = record(binding["roles"])
    if set(roles) != set(ROLES):
        raise ValueError("All five independently credentialled process roles required")
    uids: list[int] = []
    trust_uids: set[int] = set()
    sockets: list[str] = []
    for role in ROLES:
        cfg = record(roles[role])
        if set(cfg) != {
            "uid",
            "proxy_uid",
            "fence_uid",
            "fence_socket",
            "backend_socket",
            "outbound",
        }:
            raise ValueError("Exact process custody fields required")
        uid, proxy, fence = (integer(cfg, name) for name in ("uid", "proxy_uid", "fence_uid"))
        if (
            uid == 0
            or uid in {proxy, fence}
            or proxy == fence
            or {FENCE_READER_GID, FENCE_RESTRICT_UID} & {uid, proxy, fence}
        ):
            raise ValueError("Separate non-root application/proxy/fence custodians required")
        uids.append(uid)
        trust_uids.update((proxy, fence))
        sockets.append(str(absolute(text(cfg, "backend_socket"))))
        absolute(text(cfg, "fence_socket"))
        outbound = record(cfg["outbound"])
        if set(outbound) != set(DESTINATIONS[role]):
            raise ValueError("Exact role-specific outbound destinations required")
        for destination, raw in outbound.items():
            target = record(raw)
            if set(target) != {"socket", "origin"}:
                raise ValueError("Exact outbound origin/socket required")
            sockets.append(str(absolute(text(target, "socket"))))
            url = httpx.URL(text(target, "origin"))
            if (
                url.scheme != "https"
                or url.path != "/"
                or url.query
                or url.fragment
                or url.userinfo
            ):
                raise ValueError("Exact mesh HTTPS origin required")
            if destination not in ROLES:
                raise ValueError("Unowned mesh destination")
    if set(uids) & trust_uids:
        raise ValueError("Application UIDs must be disjoint from all proxy/fence custodians")
    if len(set(uids)) != len(uids) or len(set(sockets)) != len(sockets):
        raise ValueError("Process credentials and sockets must be exclusive")
    for role in ("identity", "data"):
        dsn = conninfo_to_dict(text(record(binding[role]), "store_dsn"))
        if dsn.get("sslmode") != "verify-full" or not dsn.get("sslrootcert"):
            raise ValueError("Pinned verify-full PostgreSQL required")
        if (
            dsn.get("dbname")
            != {"identity": "imp03_identity_002", "data": "imp03_runtime_002"}[role]
            or dsn.get("user") != "imp03_" + role + "_runtime_002"
        ):
            raise ValueError("Named independent IMP-03 databases/runtime logins required")
        if not dsn.get("password"):
            raise ValueError("Separately issued runtime PostgreSQL credential required")
    identity_password = conninfo_to_dict(text(record(binding["identity"]), "store_dsn"))["password"]
    data_password = conninfo_to_dict(text(record(binding["data"]), "store_dsn"))["password"]
    if identity_password == data_password:
        raise ValueError("Identity/business runtime passwords must differ")
    actors = binding["actors"]
    if not isinstance(actors, list) or len(cast(list[object], actors)) < 3:
        raise ValueError(
            "Separately issued synthetic participant/worker/supervisor registry required"
        )
    account_ids: set[str] = set()
    subjects: set[str] = set()
    actor_roles: set[str] = set()
    for raw in cast(list[object], actors):
        actor = record(raw)
        if set(actor) != {"account_id", "subject", "roles"}:
            raise ValueError("Exact issued-account registry required")
        account_id = text(actor, "account_id")
        if str(UUID(account_id)) != account_id or account_id in account_ids:
            raise ValueError("Unique canonical account IDs required")
        account_ids.add(account_id)
        subject = text(actor, "subject")
        if subject in subjects:
            raise ValueError("Separate provider subjects required")
        subjects.add(subject)
        values = actor["roles"]
        if (
            not isinstance(values, list)
            or len(cast(list[object], values)) != 1
            or values[0] not in {"pid", "worker", "supervisor", "operator"}
        ):
            raise ValueError("One exact demo role per separately issued actor required")
        actor_roles.add(cast(str, values[0]))
    if not {"pid", "worker", "supervisor"} <= actor_roles:
        raise ValueError("Required actor roles absent")
    mesh = record(binding["mesh"])
    if set(mesh) != set(ROLES):
        raise ValueError("All workload listener bindings required")
    authorization_uids: set[int] = set()
    for raw in mesh.values():
        target = record(raw)
        if set(target) != {
            "address",
            "port",
            "authorization_socket",
            "spire_socket",
            "proxy_config",
            "trust_bundle",
            "authorization_uid",
        }:
            raise ValueError("Exact attested mesh listener fields required")
        for key in ("authorization_socket", "spire_socket", "proxy_config", "trust_bundle"):
            absolute(text(target, key))
        integer(target, "port")
        authorization_uid = integer(target, "authorization_uid")
        if authorization_uid in set(uids) | trust_uids | authorization_uids | {
            FENCE_READER_GID,
            FENCE_RESTRICT_UID,
        }:
            raise ValueError(
                "Authorization custodians must be distinct from all runtime custodians"
            )
        authorization_uids.add(authorization_uid)
    if set(record(binding["identity"])) != {"store_dsn", "oidc", "provider_address", "provider_ca"}:
        raise ValueError("Exact identity credential configuration required")
    if set(record(binding["data"])) != {"store_dsn"}:
        raise ValueError("Exact business credential configuration required")
    if set(record(binding["pdp"])) != {"executable", "executable_digest"}:
        raise ValueError("Exact pinned policy executable configuration required")
    fence_bindings = {
        (text(record(roles[role]), "fence_socket"), integer(record(roles[role]), "fence_uid"))
        for role in ROLES
    }
    if len(fence_bindings) != 1:
        raise ValueError("One exact independently owned fence required")
    # Validate pins with the existing immutable product builder during rendering.


def prepare(binding: Record, root: Path, *, assign_ownership: bool = False) -> None:
    if assign_ownership and os.geteuid() != 0:
        raise ValueError("Assignment requires authorized Linux custody supervisor")
    validate_binding(binding)
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
            cfg["disclosures"] = json.loads(
                (ROOT / "config/demo/imp03/disclosures.json").read_text()
            )
        if role == "pdp":
            cfg.update(record(binding["pdp"]))
            manifest = json.loads((ROOT / "config/demo/imp03/policy/bootstrap.json").read_text())
            path = directory / "manual.rego"
            write(path, (ROOT / "config/demo/imp03/policy/manual.rego").read_bytes())
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
            (ROOT / "config/demo/imp03/policy/manual.rego").read_bytes()
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


def check_config(root: Path, role: str) -> Record:
    if role not in ROLES:
        raise ValueError("Unknown role")
    if not root.is_absolute() or root.is_symlink() or (root / role).is_symlink():
        raise ValueError("Exact absolute nonsymlink runtime root required")
    cfg = load(root / role / "config.json")
    if cfg.get("session") != "imp03-002" or cfg.get("role") != role:
        raise ValueError("Wrong role/session binding")
    if integer(cfg, "uid") != os.geteuid():
        raise ValueError("Current UID is not the assigned role custodian")
    forbidden = {
        "core": {"store_dsn", "custody_key", "content_key", "signing_key"},
        "data": {"custody_key", "signing_key", "core_signing_key", "oidc"},
        "identity": {"content_key", "cursor_key", "core_signing_key"},
        "pdp": {"store_dsn", "content_key", "custody_key", "core_signing_key"},
        "journal": {"store_dsn", "content_key", "custody_key", "core_signing_key"},
    }
    if forbidden[role] & set(cfg):
        raise ValueError("Cross-role credential in runtime configuration")
    for name in ("signing_key", "core_signing_key", "custody_key", "content_key", "cursor_key"):
        if name not in cfg:
            continue
        path = Path(text(cfg, name))
        info = path.lstat()
        if (
            path.is_symlink()
            or not path.is_file()
            or info.st_mode & 0o077
            or info.st_uid != os.geteuid()
            or not path.resolve().is_relative_to((root / role).resolve())
        ):
            raise ValueError("Role-exclusive owner-only credential required")
    return cfg
