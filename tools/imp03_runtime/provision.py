"""Initial-only migration/bootstrap; never loads an admin credential into serving roles."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

import httpx
import psycopg
from care_link_data import PostgresStore
from care_link_domain import Actor
from care_link_recovery_control import FileJournal
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from tools.imp02_application.config import private_key

from .compose import identity_service
from .config import Record, load, record, text

ROOT = Path(__file__).resolve().parents[2]
DATABASES = {"identity": "imp03_identity_002", "data": "imp03_runtime_002"}
LOGINS = {"identity": "imp03_identity_runtime_002", "data": "imp03_data_runtime_002"}


def initialize_database(admin: str, runtime: str, role: str) -> str:
    settings, admin_settings = conninfo_to_dict(runtime), conninfo_to_dict(admin)
    if settings.get("dbname") != DATABASES[role] or settings.get("user") != LOGINS[role]:
        raise ValueError("Exact separately named IMP-03 database/runtime login required")
    if admin_settings.get("sslmode") != "verify-full" or not admin_settings.get("sslrootcert"):
        raise ValueError("Admin PostgreSQL requires pinned verify-full TLS")
    for key in ("host", "hostaddr", "port", "sslrootcert"):
        if settings.get(key) != admin_settings.get(key):
            raise ValueError("Admin/runtime database endpoint mismatch")
    name, login = DATABASES[role], LOGINS[role]
    with psycopg.connect(admin, autocommit=True) as connection:
        if connection.execute("SELECT 1 FROM pg_database WHERE datname=%s", (name,)).fetchone():
            raise ValueError("Initial-only provisioning refuses existing database")
        if connection.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (login,)).fetchone():
            raise ValueError("Initial-only provisioning refuses existing runtime login")
        connection.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOBYPASSRLS INHERIT PASSWORD {}"
            ).format(sql.Identifier(login), sql.Literal(settings["password"]))
        )
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        connection.execute(
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name))
        )
        connection.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(name), sql.Identifier(login)
            )
        )
    target = make_conninfo("", **{**admin_settings, "dbname": name})
    with psycopg.connect(target, autocommit=True) as connection:
        if role == "identity":
            for migration in sorted((ROOT / "services/identity/migrations").glob("*.sql")):
                connection.execute(migration.read_bytes())
            connection.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            connection.execute(
                sql.SQL("GRANT USAGE ON SCHEMA identity TO {}").format(sql.Identifier(login))
            )
            connection.execute(
                sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON identity.record TO {}").format(
                    sql.Identifier(login)
                )
            )
        else:
            connection.execute((ROOT / "services/data/migrations/001_manual.sql").read_bytes())
            connection.execute(
                sql.SQL("GRANT care_link_data_runtime TO {}").format(sql.Identifier(login))
            )
        connection.execute(
            sql.SQL("REVOKE TEMPORARY ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name))
        )
    return target


def provision(root: Path, admin_config: Record) -> None:
    if set(admin_config) != {"identity_admin_dsn", "data_admin_dsn"}:
        raise ValueError("Exact private initial-admin settings required")
    receipt = load(root / "receipt.json")
    identity_cfg = load(root / "identity/config.json", owned=False)
    data_cfg = load(root / "data/config.json", owned=False)
    journal_cfg = load(root / "journal/config.json", owned=False)
    # Preflight both exact endpoint/credential bindings and both names before CREATE.
    for role, cfg in (("identity", identity_cfg), ("data", data_cfg)):
        settings = conninfo_to_dict(text(cfg, "store_dsn"))
        admin = conninfo_to_dict(text(admin_config, role + "_admin_dsn"))
        if settings.get("dbname") != DATABASES[role] or settings.get("user") != LOGINS[role]:
            raise ValueError("Exact runtime database/login required")
        if admin.get("sslmode") != "verify-full" or not admin.get("sslrootcert"):
            raise ValueError("Pinned admin TLS required")
        if any(
            settings.get(key) != admin.get(key)
            for key in ("host", "hostaddr", "port", "sslrootcert")
        ):
            raise ValueError("Admin/runtime endpoint mismatch")
    # No existing database or login is ever adopted.

    for role in ("identity", "data"):
        admin = text(admin_config, role + "_admin_dsn")
        with psycopg.connect(admin) as connection:
            if connection.execute(
                "SELECT 1 FROM pg_database WHERE datname=%s", (DATABASES[role],)
            ).fetchone():
                raise ValueError("Initial provisioning refuses to adopt existing database")
            if connection.execute(
                "SELECT 1 FROM pg_roles WHERE rolname=%s", (LOGINS[role],)
            ).fetchone():
                raise ValueError("Initial provisioning refuses to adopt existing runtime login")
    # The business migration creates these cluster-global NOLOGIN roles. A
    # collision is an existing target, never something this helper may adopt.
    with psycopg.connect(text(admin_config, "data_admin_dsn")) as connection:
        for role in ("care_link_data_runtime", "care_link_audit_reader", "care_link_backup"):
            if connection.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
                raise ValueError("Initial provisioning refuses existing business group roles")
    journal_path = Path(text(journal_cfg, "journal_directory"))
    if journal_path.exists() or journal_path.is_symlink():
        raise ValueError("Initial provisioning refuses existing journal state")
    identity_admin = initialize_database(
        text(admin_config, "identity_admin_dsn"), text(identity_cfg, "store_dsn"), "identity"
    )
    data_admin = initialize_database(
        text(admin_config, "data_admin_dsn"), text(data_cfg, "store_dsn"), "data"
    )
    journal = FileJournal.provision(
        Path(text(journal_cfg, "journal_directory")),
        private_key(text(journal_cfg, "signing_key")),
        text(journal_cfg, "signing_key_id"),
        journal_id=text(journal_cfg, "journal_id"),
    )
    # Reassign provisioned host state to its exact runtime custodian.
    import os

    if os.geteuid() == 0:
        uid = int(str(journal_cfg["uid"]))
        for path in Path(text(journal_cfg, "journal_directory")).iterdir():
            os.chown(path, uid, uid)
        os.chown(text(journal_cfg, "journal_directory"), uid, uid)
    admin_store = PostgresStore(data_admin)
    admin_store.bootstrap(journal.head(), text(receipt, "policy_digest"))
    clients: list[httpx.Client] = []
    service = identity_service({**identity_cfg, "store_dsn": identity_admin}, clients)
    try:
        for raw in cast(list[object], receipt["actors"]):
            actor = record(raw)
            roles = cast(list[str], actor["roles"])
            service.provision(text(actor, "subject"), text(actor, "account_id"), roles)
            now = datetime.now(UTC)
            principal = Actor(
                text(actor, "account_id"),
                roles[0],
                1,
                1,
                now,
                roles[0] != "pid",
                "0" * 64,
                0,
                "",
                now + timedelta(minutes=1),
                str(uuid4()),
            )
            admin_store.provision_principal(principal)
    finally:
        for client in clients:
            client.close()
