"""Initial migration of this disposable lab's separate identity database."""

from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from .identity_qualification import apply_migrations


def configure(
    host: str, hostaddr: str, port: int, ca: str, passwords: dict[str, str], source: Path
) -> dict[str, object]:
    common = {
        "host": host,
        "hostaddr": hostaddr,
        "port": port,
        "sslmode": "verify-full",
        "sslrootcert": ca,
        "connect_timeout": 3,
    }
    with psycopg.connect(
        make_conninfo(
            **common, dbname="postgres", user="postgres", password=passwords["postgres_password"]
        ),
        autocommit=True,
    ) as admin:
        if admin.execute("SELECT 1 FROM pg_database WHERE datname='identity'").fetchone():
            raise ValueError("Initial migration refuses to adopt an existing identity database")
        for role, key in [
            ("identity_migrator", "identity_migrator_password"),
            ("identity_runtime", "identity_runtime_password"),
        ]:
            admin.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOINHERIT NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(role), sql.Literal(passwords[key]))
            )
        admin.execute("CREATE DATABASE identity OWNER identity_migrator")
        admin.execute("REVOKE ALL ON DATABASE identity FROM PUBLIC")
        admin.execute("GRANT CONNECT ON DATABASE identity TO identity_runtime")
        admin.execute("REVOKE ALL ON DATABASE keycloak FROM PUBLIC")
        admin.execute("GRANT CONNECT ON DATABASE keycloak TO keycloak")
    migrator = make_conninfo(
        **common,
        dbname="identity",
        user="identity_migrator",
        password=passwords["identity_migrator_password"],
    )
    apply_migrations(migrator, "identity", source, confirm_named_lab=True)
    with psycopg.connect(migrator, autocommit=True) as connection:
        connection.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        connection.execute("GRANT USAGE ON SCHEMA identity TO identity_runtime")
        connection.execute(
            "GRANT SELECT,INSERT,UPDATE,DELETE ON identity.record TO identity_runtime"
        )
    runtime = make_conninfo(
        **common,
        dbname="identity",
        user="identity_runtime",
        password=passwords["identity_runtime_password"],
    )
    with psycopg.connect(runtime) as connection:
        row = connection.execute(
            "SELECT ssl,version FROM pg_stat_ssl WHERE pid=pg_backend_pid()"
        ).fetchone()
        security = connection.execute(
            "SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls "
            "FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
        schema = connection.execute(
            "SELECT has_schema_privilege(current_user,'identity','CREATE'),"
            "has_schema_privilege(current_user,'public','CREATE'),"
            "has_database_privilege(current_user,'identity','TEMP')"
        ).fetchone()
        if not row or row != (True, "TLSv1.3") or any(security or ()) or any(schema or ()):
            raise ValueError("Identity runtime isolation/TLS qualification failed")
    return {
        "status": "migrated",
        "tls": "TLSv1.3",
        "verify_full": True,
        "runtime_superuser": False,
        "runtime_create_schema": False,
        "runtime_temporary_tables": False,
        "migration_count": len(list((source / "services/identity/migrations").glob("*.sql"))),
    }
