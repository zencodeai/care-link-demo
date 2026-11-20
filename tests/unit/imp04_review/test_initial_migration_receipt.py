"""Fresh initialization binds verified migration bytes in the same transaction."""

from contextlib import contextmanager
from uuid import uuid4

from psycopg.conninfo import make_conninfo

from tools.imp04_deployment import provision


class Connection:
    def __init__(self):
        self.transactions = []
        self.current = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params=None):
        if self.current is not None:
            self.current.append((query, params))
        return self

    def fetchone(self):
        return None

    @contextmanager
    def transaction(self):
        self.current = []
        try:
            yield
            self.transactions.append(self.current)
        finally:
            self.current = None


def test_initial_migration_digest_is_recorded_with_its_verified_ddl(monkeypatch):
    connection = Connection()
    monkeypatch.setattr(provision.psycopg, "connect", lambda *_args, **_kwargs: connection)
    settings = {
        "host": "postgres.imp04.internal",
        "hostaddr": "127.0.0.1",
        "port": 5432,
        "sslmode": "verify-full",
        "sslrootcert": "/private/fixture/ca.crt",
        "password": str(uuid4()),
    }
    admin = make_conninfo(**settings, dbname="postgres", user="postgres")
    runtime = make_conninfo(**settings, dbname="imp04_runtime_002", user="imp04_data_runtime_002")
    provision.initialize_database(admin, runtime, "data")
    expected = dict(provision.MIGRATIONS["data"])["002_review_recovery.sql"]
    ddl = provision.migration_bytes("data", "002_review_recovery.sql", expected)
    assert any(
        operations
        == [
            (ddl, None),
            (
                "INSERT INTO core.review_schema_version VALUES(%s,%s)",
                ("review-recovery-1", expected),
            ),
        ]
        for operations in connection.transactions
    )
