"""Coordinator-run real PostgreSQL/provider/backup qualification for the named lab.

No module-import setup, destructive reset, provider impersonation or fake login.
Temporal retention boundaries are explicitly seeded fixtures; elapsed30/7days is
not claimed. Operator proof must be an actual recent MFA main operator session.
"""

import hashlib
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

import httpx
import psycopg
from care_link_identity import (
    EncryptedIdentityBackups,
    IdentityService,
    KeycloakCleanup,
    KeycloakServiceCredentials,
    RetentionService,
    SessionRetentionAuthority,
)
from care_link_identity.domain import stamp
from psycopg.conninfo import conninfo_to_dict

from .provider_bootstrap import BASE, ISSUER, REALM


def apply_migrations(
    migration_dsn: str, expected_database: str, repository: Path, *, confirm_named_lab: bool
) -> list[dict[str, str]]:
    if (
        not confirm_named_lab
        or not expected_database
        or expected_database in {"postgres", "template0", "template1"}
    ):
        raise ValueError("Exact isolated identity database and named-lab confirmation required")
    settings = conninfo_to_dict(migration_dsn)
    if settings.get("dbname") != expected_database or settings.get("sslmode") != "verify-full":
        raise ValueError("Exact database and verified PostgreSQL TLS required")
    results = []
    with psycopg.connect(migration_dsn, autocommit=True, connect_timeout=3) as connection:
        database = connection.execute("SELECT current_database()").fetchone()
        if database is None or database[0] != expected_database:
            raise ValueError("Database target mismatch")
        registered = connection.execute(
            "SELECT to_regclass('identity.schema_migration')::text"
        ).fetchone()
        records = connection.execute("SELECT to_regclass('identity.record')::text").fetchone()
        if records and records[0] is not None and (registered is None or registered[0] is None):
            raise ValueError("Existing unmanaged identity schema requires explicit reconciliation")
        for name in ("001_identity.sql", "002_option_b_and_workload.sql"):
            path = repository / "services/identity/migrations" / name
            source = path.read_text()
            digest = hashlib.sha256(source.encode()).hexdigest()
            prior = None
            if registered and registered[0] is not None:
                prior = connection.execute(
                    "SELECT sha256 FROM identity.schema_migration WHERE name=%s", (name,)
                ).fetchone()
            if prior:
                if prior[0] != digest:
                    raise ValueError("Applied migration digest differs from current source")
                results.append({"name": name, "sha256": digest, "state": "already_applied"})
                continue
            body = re.fullmatch(r"(?s).*?\nBEGIN;\n(.*)\nCOMMIT;\s*", source)
            if body is None:
                raise ValueError("Expected explicitly transactional source migration")
            with connection.transaction():
                connection.execute(body.group(1), prepare=False)
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS identity.schema_migration"
                    "(name text PRIMARY KEY,sha256 text NOT NULL)"
                )
                connection.execute("REVOKE ALL ON identity.schema_migration FROM PUBLIC")
                connection.execute(
                    "INSERT INTO identity.schema_migration(name,sha256) VALUES (%s,%s)",
                    (name, digest),
                )
            registered = ("identity.schema_migration",)
            results.append({"name": name, "sha256": digest, "state": "applied"})
    return results


def qualify(
    identity: IdentityService,
    operator_cookie: str,
    owner_account_id: str,
    provider_client: httpx.Client,
    lifecycle_client_id: str,
    lifecycle_secret: str,
    backup_directory: Path,
    *,
    confirm_named_lab: bool,
) -> dict[str, object]:
    if not confirm_named_lab or identity.issuer != ISSUER:
        raise ValueError("Only the exact care-link-imp02 provider is in scope")
    authority = SessionRetentionAuthority(identity, owner_account_id)
    # Actual operator authority is checked before creating the disposable probe.
    authority.authorize(
        operator_cookie, "qualify_identity_retention", "00000000-0000-0000-0000-000000000000"
    )
    tokens = KeycloakServiceCredentials(
        ISSUER + "/protocol/openid-connect/token",
        BASE,
        lifecycle_client_id,
        lifecycle_secret,
        provider_client,
    )
    headers = {"Authorization": "Bearer " + tokens.current()}
    probe_name = "retention-probe-" + uuid4().hex
    response = provider_client.post(
        BASE + f"/admin/realms/{REALM}/users",
        json={"username": probe_name, "enabled": True},
        headers=headers,
        timeout=10,
        follow_redirects=False,
    )
    response.raise_for_status()
    location = response.headers.get("location", "")
    subject = location.rstrip("/").rsplit("/", 1)[-1]
    if not subject:
        raise ValueError("Real provider did not identify the probe user")
    account_id = str(uuid4())
    identity.provision(subject, account_id, ["pid"])
    cleanup = KeycloakCleanup(BASE + f"/admin/realms/{REALM}/users", BASE, tokens, provider_client)
    retention = RetentionService(
        identity.store, identity.custody, authority, cleanup, clock=identity.clock
    )
    import os

    backups = EncryptedIdentityBackups(
        identity.store, identity.custody, backup_directory, os.geteuid(), authority, identity.clock
    )
    retention.backups = backups
    deprovision = retention.deprovision(account_id, str(uuid4()), operator_cookie)
    if deprovision["provider_state"] != "confirmed":
        raise ValueError("Actual provider deprovision remains pending")
    disabled = provider_client.get(
        BASE + f"/admin/realms/{REALM}/users/{subject}",
        headers={"Authorization": "Bearer " + tokens.current()},
        timeout=10,
        follow_redirects=False,
    )
    disabled.raise_for_status()
    user = cast(dict[str, object], disabled.json())
    if user.get("enabled") is not False:
        raise ValueError("Provider account was not actually disabled")
    capture_id = str(uuid4())
    captured = backups.capture(capture_id, operator_cookie)
    # Deliberately labelled time-boundary fixture; no wall-clock/user decision is
    # rewritten. Only this just-created synthetic probe's due anchor is seeded.
    with identity.store.transaction() as tx:
        key, account = next(
            (key, row) for key, row in tx.items("account") if row.get("account_id") == account_id
        )
        now = identity.clock()
        account.update(
            {
                "deprovisioned_at": stamp(now - timedelta(days=30)),
                "profile_purge_due_at": stamp(now - timedelta(seconds=1)),
            }
        )
        tx.put("account", key, account)
        marker = tx.get("account_marker", account_id)
        if marker is None:
            raise ValueError("Probe restriction marker missing")
        marker.update(
            {
                "deprovisioned_at": account["deprovisioned_at"],
                "profile_purge_due_at": account["profile_purge_due_at"],
            }
        )
        tx.put("account_marker", account_id, marker)
    purged = retention.purge_due(account_id, operator_cookie)
    if purged["provider_state"] != "confirmed" or purged["backup_state"] != "pending":
        raise ValueError("Expected provider cleanup with accurately pending captured copy")
    removed = provider_client.get(
        BASE + f"/admin/realms/{REALM}/users/{subject}",
        headers={"Authorization": "Bearer " + tokens.current()},
        timeout=10,
        follow_redirects=False,
    )
    if removed.status_code != 404:
        raise ValueError("Provider identifying-profile deletion not observed")
    restored = backups.restore_to_quarantine(capture_id, retention)
    restored_account = next(
        row
        for kind, _key, row in restored
        if kind == "account" and row.get("account_id") == account_id
    )
    if restored_account.get("enabled") is not False or "subject" in restored_account:
        raise ValueError("Restore resurrected current purged profile or account rights")
    original_clock = backups.clock
    expiry = datetime.fromisoformat(str(captured["expires_at"]).replace("Z", "+00:00"))
    backups.clock = lambda: expiry + timedelta(seconds=1)
    try:
        expired = backups.expire()
    finally:
        backups.clock = original_clock
    final = retention.reconcile("profile:" + account_id, operator_cookie)
    if final["state"] != "active_profile_removed_known_copies_accounted":
        raise ValueError("Known owned copy reconciliation failed")
    return {
        "scope": "real PostgreSQL/Keycloak cleanup, encrypted files; controlled time fixture",
        "deprovision": deprovision["state"],
        "profile": final["state"],
        "restore": "quarantined/no bearer or current purged subject",
        "backup_expiry": "immutable capture+7day boundary fixture; file fsync/unlink observed",
        "expired_capture_count": expired,
        "physical_erasure_claim": False,
        "owner": "main",
        "participant_admission": False,
    }
