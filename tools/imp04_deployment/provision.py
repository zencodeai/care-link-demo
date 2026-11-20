"""Initial-only migration/bootstrap; never loads an admin credential into serving roles."""

import hashlib
import json
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
from tools.imp03_runtime.compose import identity_service

from .config import (
    DATABASES,
    LOGINS,
    POLICY_DIGEST,
    REPO,
    Record,
    load,
    record,
    text,
    validate_binding,
    verify_sources,
    write,
)

MIGRATIONS = {
    "identity": [
        ("001_identity.sql", "fa77d31cb725261281fac94f0a60f5b34c3e0e1bf93bc531b0917d72f303ff79"),
        (
            "002_option_b_and_workload.sql",
            "fa40c00c6b8c32e5f2a56791214d82bdfff1468c9690e5eee6362bd4ae084dbd",
        ),
    ],
    "data": [
        ("001_manual.sql", "4e949968ed96009403870ccdf3cb49a47a885b4f7bfb10f54dc390dbc9ae22cd"),
        (
            "002_review_recovery.sql",
            "f20888c4daa455f5a8606ab2ccecc3b03e4d41ba6e8ee83bf8266c8d2cf0babb",
        ),
        (
            "003_plans_consent_directory.sql",
            "295790c4df2c8ce600bd3362a82e43699118a8ac8889ba9074a4afdb77f3da42",
        ),
    ],
}


def migration_bytes(role: str, name: str, expected: str) -> bytes:
    content = (REPO / "services" / role / "migrations" / name).read_bytes()
    if hashlib.sha256(content).hexdigest() != expected:
        raise ValueError("Exact accepted migration digest required")
    return content


def initialize_database(admin: str, runtime: str, role: str) -> str:
    settings, admin_settings = conninfo_to_dict(runtime), conninfo_to_dict(admin)
    if settings.get("dbname") != DATABASES[role] or settings.get("user") != LOGINS[role]:
        raise ValueError("Exact separately named IMP-04 database/runtime login required")
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
            for migration_name, expected in MIGRATIONS["identity"]:
                connection.execute(migration_bytes("identity", migration_name, expected))
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
            for migration_name, expected in MIGRATIONS["data"]:
                with connection.transaction():
                    connection.execute(migration_bytes("data", migration_name, expected))
                    if migration_name == "002_review_recovery.sql":
                        connection.execute(
                            "INSERT INTO core.review_schema_version VALUES(%s,%s)",
                            ("review-recovery-1", expected),
                        )
            connection.execute(
                sql.SQL("GRANT care_link_data_runtime TO {}").format(sql.Identifier(login))
            )
        connection.execute(
            sql.SQL("REVOKE TEMPORARY ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name))
        )
    return target


def provision(root: Path, admin_config: Record) -> Record:
    verify_sources()
    if set(admin_config) != {"identity_admin_dsn", "data_admin_dsn"}:
        raise ValueError("Exact private initial-admin settings required")
    validate_binding(load(root / "bindings.json"))
    for migration_role, migrations in MIGRATIONS.items():
        for migration_name, expected in migrations:
            migration_bytes(migration_role, migration_name, expected)
    receipt = load(root / "receipt.json")
    if receipt.get("policy_digest") != POLICY_DIGEST:
        raise ValueError("Exact accepted IMP04 policy digest required")
    identity_cfg = load(root / "identity/config.json", owned=False)
    data_cfg = load(root / "data/config.json", owned=False)
    journal_cfg = load(root / "journal/config.json", owned=False)
    for role in ("identity", "core", "data", "pdp", "journal"):
        expected_config = record(receipt["configuration_digests"])[role]
        if (
            hashlib.sha256((root / role / "config.json").read_bytes()).hexdigest()
            != expected_config
        ):
            raise ValueError("Prepared target role configuration digest differs")
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

    result: Record = {
        "target": "care-link-imp04-002",
        "journal_id": receipt["journal_id"],
        "policy_digest": receipt["policy_digest"],
        "accounts_provisioned": len(cast(list[object], receipt["actors"])),
        "business_migrations": [
            "001_manual.sql",
            "002_review_recovery.sql",
            "003_plans_consent_directory.sql",
        ],
        "identity_migrations": ["001_identity.sql", "002_option_b_and_workload.sql"],
    }
    write(root / "provision-receipt.json", json.dumps(result, indent=2) + "\n")
    return result


def admit_delegation(
    root: Path,
    subject_id: str,
    carer_account_id: str,
    delegation_id: str,
) -> Record:
    """Offline fixture admission: one subject/carer, strategies, plan, ten minutes.

    This is absent from serving transports and requires private migration-owner
    custody. It creates no consent grant and cannot revoke or restore rights.
    """
    from uuid import UUID

    from .config import CONFIG, PG_HOST, PREFIX

    if str(root) != CONFIG or root.is_symlink():
        raise ValueError("Exact private new-target configuration root required")
    for value in (subject_id, carer_account_id, delegation_id):
        if str(UUID(value)) != value:
            raise ValueError("Canonical separately issued delegation identifiers required")
    config = load(root / "data/config.json", owned=False)
    if config.get("imp04_target") != PREFIX:
        raise ValueError("Exact IMP04 data target required")
    validate_binding(load(root / "bindings.json"))
    admin = load(root / "admin.json")
    settings = conninfo_to_dict(text(admin, "data_admin_dsn"))
    expected = {
        "host": PG_HOST,
        "hostaddr": "127.0.0.1",
        "port": "5432",
        "dbname": "postgres",
        "user": "postgres",
        "sslmode": "verify-full",
        "sslrootcert": CONFIG + "/data/shared-ca.crt",
    }
    if set(settings) != set(expected) | {"password"} or any(
        settings.get(k) != v for k, v in expected.items()
    ):
        raise ValueError("Exact private IMP04 migration-owner endpoint required")
    dsn = make_conninfo("", **{**settings, "dbname": DATABASES["data"]})
    with psycopg.connect(dsn) as connection:
        # Same global -> principal -> subject order as product data operations.
        guard = connection.execute(
            "SELECT mode FROM control.guard WHERE key='demo' FOR UPDATE"
        ).fetchone()
        principal = connection.execute(
            "SELECT role,revoked FROM control.principal_guard WHERE principal_id=%s FOR UPDATE",
            (carer_account_id,),
        ).fetchone()
        subject = connection.execute(
            "SELECT delete_state FROM core.subject_guard WHERE subject_id=%s FOR UPDATE",
            (subject_id,),
        ).fetchone()
        persona = connection.execute(
            "SELECT kind FROM core.persona WHERE id=%s", (subject_id,)
        ).fetchone()
        if (
            not guard
            or not principal
            or principal != ("carer", False)
            or subject != ("active",)
            or persona != ("pid",)
        ):
            raise ValueError(
                "Existing active PID subject and independently issued current carer required"
            )
        if connection.execute(
            "SELECT 1 FROM consent.delegation WHERE id=%s", (delegation_id,)
        ).fetchone():
            raise ValueError("Existing delegation refused; inspect previous operation")
        now_row = connection.execute("SELECT clock_timestamp()").fetchone()
        if now_row is None:
            raise ValueError("Database wall clock unavailable")
        created_at = now_row[0]
        expires_at = created_at + timedelta(minutes=10)
        connection.execute(
            "INSERT INTO consent.delegation "
            "(id,subject_id,grantor_id,purposes,fields,expires_at,revoked_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,NULL)",
            (
                delegation_id,
                subject_id,
                carer_account_id,
                ["plan"],
                ["plan.strategies"],
                expires_at,
            ),
        )
    return {
        "target": PREFIX,
        "delegation_id": delegation_id,
        "subject_id": subject_id,
        "grantor_id": carer_account_id,
        "purposes": ["plan"],
        "fields": ["plan.strategies"],
        "created_at": created_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "revoked_at": None,
        "runtime_write_authority": False,
        "consent_granted": False,
    }
