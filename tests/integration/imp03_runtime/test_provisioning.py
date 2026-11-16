"""Initial-only runtime DB bootstrap on the explicit disposable TLS fixture.

Run separately from services/data/tests: migrations own cluster-wide group roles.
This does not issue actors, start listeners or qualify external trust.
"""

import json
import os
import secrets
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from tools.imp03_runtime.prepare import prepare
from tools.imp03_runtime.provision import DATABASES, LOGINS, provision
from tools.imp03_verification.audit_fault import FUNCTION, LOGIN, apply

ROOT = Path(__file__).resolve().parents[3]


def test_initial_provision_runtime_grants_and_reversible_audit_barrier(tmp_path):
    admin = os.environ.get("CARE_LINK_IMP03_PROVISION_TEST_DSN")
    if not admin:
        pytest.skip("explicit isolated provisioning TLS fixture required; run separately")
    settings = conninfo_to_dict(admin)
    if settings.get("port") != "25433" or settings.get("dbname") != "postgres":
        raise ValueError("Only explicit disposable IMP-03 PostgreSQL fixture is allowed")
    roles = [
        *LOGINS.values(),
        "care_link_data_runtime",
        "care_link_audit_reader",
        "care_link_backup",
    ]
    with psycopg.connect(admin) as connection:
        for name in DATABASES.values():
            if connection.execute("SELECT 1 FROM pg_database WHERE datname=%s", (name,)).fetchone():
                raise ValueError("Refusing an existing runtime database")
        for name in roles:
            if connection.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (name,)).fetchone():
                raise ValueError("Refusing an existing provisioning role")
    binding = json.loads((ROOT / "tools/imp03_runtime/bindings.example.json").read_text())
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<html lang='en'><title>Synthetic test</title></html>")
    binding["web_directory"] = str(web)
    for role in ("identity", "data"):
        binding[role]["store_dsn"] = make_conninfo(
            **{
                **settings,
                "dbname": DATABASES[role],
                "user": LOGINS[role],
                "password": secrets.token_urlsafe(32),
            }
        )
    binding["identity"]["provider_ca"] = settings["sslrootcert"]
    root = tmp_path / "runtime"
    prepare(binding, root)
    admins = {"identity_admin_dsn": admin, "data_admin_dsn": admin}
    try:
        provision(root, admins)
        with psycopg.connect(
            make_conninfo(**{**settings, "dbname": DATABASES["data"]})
        ) as connection:
            assert connection.execute(
                "SELECT mode,serving_generation FROM control.guard"
            ).fetchone() == ("ai_disabled", 1)
            assert connection.execute(
                "SELECT count(*) FROM control.principal_guard"
            ).fetchone() == (3,)
            assert connection.execute(
                "SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls "
                "FROM pg_roles WHERE rolname=%s",
                (LOGIN,),
            ).fetchone() == (False, False, False, False)
            assert connection.execute(
                "SELECT has_schema_privilege(%s,'core','CREATE')", (LOGIN,)
            ).fetchone() == (False,)
        apply(root, admins, pause=True)
        with psycopg.connect(
            make_conninfo(**{**settings, "dbname": DATABASES["data"]})
        ) as connection:
            assert connection.execute(
                "SELECT has_function_privilege(%s,%s,'EXECUTE')", (LOGIN, FUNCTION)
            ).fetchone() == (False,)
        apply(root, admins, pause=False)
        with psycopg.connect(
            make_conninfo(**{**settings, "dbname": DATABASES["data"]})
        ) as connection:
            assert connection.execute(
                "SELECT has_function_privilege(%s,%s,'EXECUTE')", (LOGIN, FUNCTION)
            ).fetchone() == (True,)
        with pytest.raises(ValueError, match="existing"):
            provision(root, admins)
    finally:
        with psycopg.connect(admin, autocommit=True) as connection:
            for name in DATABASES.values():
                connection.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
                )
            for name in roles:
                connection.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(name)))
