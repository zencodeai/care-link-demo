"""Separate PostgreSQL identity custody; no business database access.

A transaction-scoped advisory lock serializes the small lab authority, including
missing-row guards. Provider/network calls happen outside this lock. Scaling this
store requires a reviewed row-lock partitioning change, not removing the guard.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

from .domain import Transaction


class _PostgresTransaction:
    def __init__(self, connection: psycopg.Connection[tuple[object, ...]]) -> None:
        self.connection = connection

    def get(self, kind: str, key: str) -> dict[str, object] | None:
        row = self.connection.execute(
            "SELECT payload::text FROM identity.record WHERE kind=%s AND record_key=%s FOR UPDATE",
            (kind, key),
        ).fetchone()
        if row is None:
            return None
        return cast(dict[str, object], json.loads(str(row[0])))

    def put(self, kind: str, key: str, value: dict[str, object]) -> None:
        self.connection.execute(
            "INSERT INTO identity.record(kind,record_key,payload) VALUES (%s,%s,%s) "
            "ON CONFLICT(kind,record_key) DO UPDATE SET payload=excluded.payload",
            (kind, key, Jsonb(value)),
        )

    def delete(self, kind: str, key: str) -> None:
        self.connection.execute(
            "DELETE FROM identity.record WHERE kind=%s AND record_key=%s", (kind, key)
        )

    def items(self, kind: str) -> Iterator[tuple[str, dict[str, object]]]:
        rows = self.connection.execute(
            "SELECT record_key,payload::text FROM identity.record WHERE kind=%s FOR UPDATE", (kind,)
        ).fetchall()
        for row in rows:
            yield str(row[0]), cast(dict[str, object], json.loads(str(row[1])))


class PostgresStore:
    def __init__(self, dsn: str) -> None:
        settings = conninfo_to_dict(dsn)
        if settings.get("sslmode") != "verify-full" or not settings.get("sslrootcert"):
            raise ValueError("Identity PostgreSQL requires pinned CA and verify-full TLS")
        self._dsn = dsn

    @contextmanager
    def transaction(self) -> Iterator[Transaction]:
        # No connections at import/startup, no schema creation or migration here.
        with psycopg.connect(self._dsn, connect_timeout=3) as connection:
            connection.execute("SET LOCAL lock_timeout = '2s'")
            connection.execute("SET LOCAL statement_timeout = '3s'")
            connection.execute("SELECT pg_advisory_xact_lock(218027, 2)")
            yield _PostgresTransaction(connection)
