"""Real encrypted pg_dump/pg_restore plus host promotion and guarded manual use.

Only the dedicated IMP09 container is used. Current identity, MFA and policy are
explicit synthetic adapters here; their separate boundary checks remain required.
"""

import secrets
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic
from uuid import UUID, uuid4

import psycopg
import pytest
from care_link_data import ManualService, PostgresStore
from care_link_domain import ManualError
from care_link_recovery_control import (
    BoundGenerationJournal,
    EncryptedCaptures,
    FileJournal,
    RecoveryCoordinator,
    RecoveryHuman,
    RecoveryLedger,
)
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from tools.imp09_runtime.postgres import (
    PostgresCaptureSource,
    PostgresRecoveryTargets,
    schema_digest,
)


class Authority:
    """Synthetic independently provisioned human identities, no human acceptance."""

    def current(self, actor, operation):
        return RecoveryHuman(
            actor.account_id,
            actor.account_id,
            actor.role,
            actor.identity_revision,
            actor.role_revision,
            actor.expires_at,
        )

    def approval(self, actor, ceremony_id, proposal_id, binding_digest, expires_at):
        return self.current(actor, "promotion_approve")

    def still_current(self, human):
        return human.expires_at > datetime.now(UTC)


def key():
    return str(uuid4())


def test_real_capture_restore_current_restriction_promotion_and_manual(
    harness, tmp_path, record_property
):
    h = harness
    if conninfo_to_dict(h.database.admin).get("port") != "35439":
        pytest.skip("only owned IMP09 fixture is allowed for integration")
    start = monotonic()
    signer = Ed25519PrivateKey.generate()
    journal = FileJournal.provision(tmp_path / "journal", signer, "synthetic-host")
    h.service.journal = journal
    with psycopg.connect(h.database.admin) as connection:
        connection.execute(
            "UPDATE control.guard SET journal_id=%s,journal_generation=1,"
            "restriction_barrier=0,journal_tip_seen=0",
            (journal.journal_id,),
        )
    old = h.create()
    # The restored participant is intentionally never re-admitted. A fresh actor
    # absent from the snapshot gets current independent identity checks only.
    fresh = replace(h.participant, account_id=key(), credential_ref=secrets.token_hex(32))
    EncryptedCaptures.provision(tmp_path / "captures")
    captures = EncryptedCaptures(
        tmp_path / "captures", secrets.token_bytes(32), signer, "capture-key"
    )
    ledger = RecoveryLedger.provision(tmp_path / "ledger", signer)
    registry = tmp_path / "registry"
    registry.mkdir(mode=0o700)
    staging = tmp_path / "staging"
    staging.mkdir(mode=0o700)
    schema = schema_digest(Path(__file__).resolve().parents[3])
    artifact = "a" * 64
    smoke_observations = []

    def smoke(dsn, generation):
        # Read-only pre-admission smoke checks exact generation, audit head,
        # current independent identity and negative rights without audit mutation.
        assert h.authority.current(fresh).account_id == fresh.account_id
        with psycopg.connect(dsn) as connection:
            guard = connection.execute(
                "SELECT mode,serving_generation FROM control.guard"
            ).fetchone()
            old_principal = connection.execute(
                "SELECT revoked FROM control.principal_guard WHERE principal_id=%s",
                (h.participant.account_id,),
            ).fetchone()
            new_principal = connection.execute(
                "SELECT revoked FROM control.principal_guard WHERE principal_id=%s",
                (fresh.account_id,),
            ).fetchone()
            audit = connection.execute("SELECT digest FROM audit.head").fetchone()
            smoke_observations.append((guard, old_principal, new_principal, audit))
            return (
                guard == ("ai_disabled", generation)
                and old_principal == (True,)
                and new_principal == (False,)
                and audit is not None
            )

    targets = PostgresRecoveryTargets(
        h.database.admin,
        registry,
        h.operator.account_id,
        smoke,
        schema,
        artifact,
        current_principals=lambda: (h.authority.current(fresh),),
        content_cipher=h.service.cipher,
    )
    coordinator = RecoveryCoordinator(
        captures,
        journal,
        ledger,
        targets,
        Authority(),
        PostgresCaptureSource(h.database.admin, schema, artifact),
        staging,
        host_custody=lambda: True,
    )

    def call(action, body=None, resource=None, actor=None):
        return coordinator.execute(
            action, actor or h.operator, body, resource_id=resource, command_id=key()
        )

    backup = call("backup_capture", {})
    # New current restriction after capture cannot disappear into old snapshot.
    journal.append(
        {
            "command_id": key(),
            "expected_tip": str(journal.head().tip),
            "kind": "restrict_intent",
            "scope": {
                "session_id": None,
                "subject_id": None,
                "purpose": "recovery",
                "fields": [],
                "recipient_id": None,
            },
            "restriction": {
                "kind": "identity_revoke",
                "principal_id": h.participant.account_id,
                "identity_revision": "4",
                "disabled": True,
            },
            "binding_digest": "a" * 64,
            "db_operation_id": None,
            "relaxation_evidence_digest": None,
        }
    )
    target = call(
        "restore_create",
        {
            "backup_id": backup["id"],
            "manifest_digest": backup["manifest_digest"],
            "expected_revision": "0",
        },
    )
    name = "imp09_quarantine_" + UUID(target["id"]).hex
    try:
        gate = BoundGenerationJournal(coordinator, target["id"])
        for database_name in ["imp03_manual", name]:
            before = make_conninfo(
                **{**conninfo_to_dict(targets.runtime_dsn(target["id"])), "dbname": database_name}
            )
            with pytest.raises(psycopg.OperationalError):
                psycopg.connect(before)
        assert not gate.admits(1) and not gate.admits(2)
        target = call("restore_validate", {"expected_revision": target["revision"]}, target["id"])
        binding = call("evidence_target", resource=target["id"])
        proposed = call(
            "promotion_propose",
            {
                "target_id": target["id"],
                "expected_revision": target["revision"],
                **{
                    k: binding[k]
                    for k in [
                        "backup_digest",
                        "head_digest",
                        "restriction_barrier",
                        "validation_digest",
                        "serving_generation",
                    ]
                },
                "binding": binding,
            },
        )
        proposal = call("promotion_read", resource=proposed["resource_id"])
        approver = replace(h.operator, account_id=key(), role="security")
        approval = call(
            "promotion_approve",
            {
                "proposal_id": proposal["id"],
                "exact_binding_digest": proposal["binding_digest"],
                "ceremony_id": key(),
                "expires_at": (datetime.now(UTC) + timedelta(seconds=120))
                .isoformat()
                .replace("+00:00", "Z"),
            },
            actor=approver,
        )
        approved = call("promotion_read", resource=approval["resource_id"])
        call(
            "promotion_execute",
            {
                "proposal_id": approved["id"],
                "approval_id": approved["approval_id"],
                "exact_binding_digest": approved["binding_digest"],
                "expected_serving_generation": "1",
            },
        )
        assert gate.admits(2) and not gate.admits(1)
        with pytest.raises(ManualError):
            h.service.session_read(h.participant, old["id"])
        source_denied = make_conninfo(
            **{**conninfo_to_dict(targets.runtime_dsn(target["id"])), "dbname": "imp03_manual"}
        )
        with pytest.raises(psycopg.OperationalError):
            psycopg.connect(source_denied)
        assert smoke_observations
        # Successful protected manual write through actual generation-aware data
        # engine; restored participant still denied. These writes occur only after
        # sealed promotion, and therefore may advance normal audit/journal heads.
        service = ManualService(
            PostgresStore(targets.runtime_dsn(target["id"])),
            h.authority,
            h.policy,
            gate,
            h.service.cipher,
            channel=h.channels,
            disclosure_templates=h.service.disclosure_templates,
            cursor_key=secrets.token_bytes(32),
        )
        with pytest.raises(ManualError):
            service.session_read(h.participant, old["id"])
        created = service.session_create(
            fresh,
            key(),
            {
                "tags": {"environment": "demo", "population": "synthetic"},
                "participant_kind": "pid",
                "jurisdiction": None,
                "locale": "en-CA",
                "channel": "web",
                "persona_id": None,
                "fixture_id": None,
            },
        )
        assert created["id"] != old["id"]
        assert gate.admits(2)
        assert captures.inspect(backup["id"])["expires_at"] == backup["expires_at"]
        # Ordinary runtime credentials cannot connect to the quarantine/target DB.
        denied = make_conninfo(**{**conninfo_to_dict(h.database.runtime), "dbname": name})
        with pytest.raises(psycopg.OperationalError):
            psycopg.connect(denied)
        # Maintenance journal fence immediately invalidates both edge/DB paths.
        with ledger.exclusive():
            state = ledger.load()
            state["serving"] = None
            ledger.save(state)
        assert not gate.admits(2)
        with pytest.raises(ManualError):
            service.session_create(
                fresh,
                key(),
                {
                    "tags": {"environment": "demo", "population": "synthetic"},
                    "participant_kind": "pid",
                    "jurisdiction": None,
                    "locale": "en-CA",
                    "channel": "web",
                    "persona_id": None,
                    "fixture_id": None,
                },
            )
        # Every quarantine/staging copy retains the original capture expiry.
        copied = targets.inventory()
        assert copied[0]["expires_at"] == backup["expires_at"]
        assert not (Path(copied[0]["staging_path"]) / "database.dump").exists()
        targets.clock = lambda: datetime.now(UTC) + timedelta(days=8)
        with pytest.raises(ManualError):
            targets.expire_target(target["id"], lambda _: True)
        with pytest.raises(ManualError):
            targets.expire_target(target["id"], lambda _: False)
        targets.fence_all()
        expired = targets.expire_target(target["id"], lambda _: False)
        assert expired["known_copy_unlinked"] and not expired["physical_erasure_proven"]
        assert targets.inventory()[0]["expires_at"] == backup["expires_at"]
        targets.fence_all()  # expired known copies never prevent future fencing
        elapsed = monotonic() - start
        assert elapsed < 300
        record_property("full_synthetic_recovery_elapsed_seconds", elapsed)
        record_property("approval_kind", "automated synthetic action; no real human approval")
        record_property(
            "capture_age_at_restore_seconds",
            (datetime.now(UTC) - datetime.fromisoformat(backup["capture_at"])).total_seconds(),
        )
    finally:
        with psycopg.connect(h.database.admin, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )
            connection.execute(
                sql.SQL("DROP ROLE IF EXISTS {}").format(
                    sql.Identifier("imp09_target_" + UUID(target["id"]).hex)
                )
            )
            # Restore fixture-only source CONNECT; this is not a live recovery.
            connection.execute("GRANT CONNECT ON DATABASE imp03_manual TO PUBLIC")
