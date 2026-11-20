"""One-shot fresh IMP-04 preparation, before any application has ever served.

This module is invoked only by an explicitly authorized Linux operator. It does
not launch applications, browsers or an operator server. Serving role configs
receive only their own public registry and directory admission material.
"""

import argparse
import hashlib
import json
import os
import stat
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID, uuid5

import httpx
import psycopg
from care_link_data import AESGCMContentCipher, ManualService, PostgresStore
from care_link_data.directory_admission import VerifiedDirectoryAdmission
from care_link_data.review_admin import ReviewRunAdmin, apply_plans_review_migration
from care_link_domain import Actor, ManualError
from care_link_identity.manual import ManualIdentityAuthority
from care_link_identity.provider import OIDCProvider
from care_link_identity.service import IdentityService
from care_link_policy_input import OpaPolicy
from care_link_recovery_control import FileJournal
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from tools.imp02_application.config import private_key, public_key
from tools.imp03_runtime.compose import identity_service
from tools.imp04_deployment.config import (
    CONFIG,
    DATABASES,
    LOGINS,
    PREFIX,
    ROLE_UID,
    ROLES,
    load,
    record,
    text,
)

from .adapters import IdentityCustody, InProcessReviewActors, ServiceReviewAdapter
from .bootstrap import BootstrapAuthority, BootstrapIdentityFactory
from .directory import DirectoryReviewPreflight
from .fixture_sources import create_fixture_sources
from .fixtures import ServiceFixtureBuilder
from .lifecycle import PlansReviewLifecycle
from .storage import private_directory, read_json, write_json
from .types import JsonRecord


class NeverServedCore:
    def __init__(self, root: Path, configs: dict[str, JsonRecord], run_id: str) -> None:
        self.root, self.configs, self.run_id = root, configs, run_id

    def verify(self) -> None:
        for role in ROLES:
            receipt = self.root / role / "process.json"
            if receipt.exists() or receipt.is_symlink():
                raise ValueError("One-shot preparation refuses any application serving receipt")
        backend = Path(self.configs["core"]["backend_socket"])
        expected = self.root.parent / "core" / "backend"
        if backend.parent != expected or expected.is_symlink() or not os.path.ismount(expected):
            raise ValueError("Actual read-only Core backend mount required for offline proof")
        if backend.exists() or backend.is_symlink():
            raise ValueError("Core backend must never have been activated")

    def retire_views(self, run_id: str) -> JsonRecord:
        if run_id != self.run_id:
            raise ValueError("Exact fresh run required")
        self.verify()
        return {"run_id": run_id, "verified_never_served": True}


class PreparationAuthority:
    """Ordinary OIDC authority for two exact privileged sessions; review otherwise."""

    def __init__(
        self, identity: IdentityService, bootstrap: BootstrapAuthority, privileged: dict[str, Actor]
    ) -> None:
        self.identity = ManualIdentityAuthority(identity)
        self.bootstrap, self.privileged = bootstrap, privileged

    def authority(self, actor: Actor) -> ManualIdentityAuthority | BootstrapAuthority:
        if actor.review_run_id is not None:
            return self.bootstrap
        expected = self.privileged.get(actor.role)
        if (
            expected is None
            or actor.account_id != expected.account_id
            or actor.credential_ref != expected.credential_ref
            or actor.browser_session_digest != expected.browser_session_digest
        ):
            raise ManualError("manual.preparation_actor_denied", 403)
        return self.identity

    def current(self, actor: Actor) -> Actor:
        return self.authority(actor).current(actor)

    def recovery_proof(
        self, actor: Actor, ceremony_id: str, session_id: str, family_id: str
    ) -> None:
        self.authority(actor).recovery_proof(actor, ceremony_id, session_id, family_id)

    def consent_proof(
        self,
        actor: Actor,
        proof_id: str,
        subject_id: str,
        session_id: str,
        purpose: str,
        basis: str,
    ) -> None:
        self.authority(actor).consent_proof(actor, proof_id, subject_id, session_id, purpose, basis)


def target_admin_dsn(admin_dsn: str, runtime_dsn: str, role: str) -> str:
    admin, runtime = conninfo_to_dict(admin_dsn), conninfo_to_dict(runtime_dsn)
    if (
        role not in {"identity", "data"}
        or runtime.get("dbname") != DATABASES[role]
        or runtime.get("user") != LOGINS[role]
        or admin.get("sslmode") != "verify-full"
        or not admin.get("sslrootcert")
        or runtime.get("sslmode") != "verify-full"
        or any(admin.get(k) != runtime.get(k) for k in ("host", "hostaddr", "port", "sslrootcert"))
    ):
        raise ValueError("Exact independent IMP-04 pinned database endpoint required")
    return make_conninfo("", **{**admin, "dbname": DATABASES[role]})


def authenticated_privileged(
    identity: IdentityService, credentials: JsonRecord, receipt: JsonRecord
) -> dict[str, Actor]:
    if set(credentials) != {"operator_session", "security_session"}:
        raise ValueError("Both genuine privileged OIDC sessions are required")
    if (
        identity.review_context is not None
        or identity.interactive_policy is not None
        or not isinstance(identity.provider, OIDCProvider)
    ):
        raise ValueError("Privileged preparation requires ordinary provider identity")
    authority = ManualIdentityAuthority(identity)
    actors: dict[str, Actor] = {}
    for role in ("operator", "security"):
        raw = credentials[role + "_session"]
        if not isinstance(raw, str) or not raw:
            raise ValueError("Missing genuine privileged session")
        actor = authority.authenticate(raw)
        expected = [item for item in receipt["actors"] if item.get("roles") == [role]]
        now = identity.clock()
        if (
            len(expected) != 1
            or actor.role != role
            or actor.account_id != expected[0]["account_id"]
            or actor.review_run_id is not None
            or not actor.mfa
            or not timedelta(0) <= now - actor.auth_time < timedelta(minutes=5)
        ):
            raise ValueError("Exact freshly authenticated privileged account required")
        actors[role] = actor
    return actors


def replace_role_file(path: Path, content: bytes, uid: int) -> None:
    """Atomically update only an independently owned role's regular private file."""
    parent = path.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != uid or parent.st_mode & 0o077:
        raise ValueError("Exact role-owned private parent required")
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_mode & 0o077:
            raise ValueError("Exact role-owned private file required")
    fd, temporary = tempfile.mkstemp(prefix=".fresh-review-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fchmod(stream.fileno(), 0o600)
            os.fchown(stream.fileno(), uid, uid)
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _restore_journal_owner(config: JsonRecord) -> None:
    directory = Path(config["journal_directory"])
    uid = int(config["uid"])
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Owned journal state required")
    for path in directory.iterdir():
        if path.is_symlink() or not path.is_file():
            raise ValueError("Unexpected journal state entry")
        os.chown(path, uid, uid)
    os.chown(directory, uid, uid)


def prepare_fresh_review(
    root: Path,
    admin_config: JsonRecord,
    *,
    run_id: str,
    lifetime_seconds: int,
    credentials_file: Path,
) -> JsonRecord:
    """Mutate only the fresh exact target; missing real authority fails closed."""
    if root != Path(CONFIG) or root.is_symlink() or os.geteuid() != 0:
        raise ValueError("Exact fresh IMP-04 Linux operator root required")
    if (
        str(UUID(run_id)) != run_id
        or type(lifetime_seconds) is not int
        or not 1 <= lifetime_seconds <= 14400
    ):
        raise ValueError("Canonical fresh run and bounded explicit lifetime required")
    if set(admin_config) != {"identity_admin_dsn", "data_admin_dsn"}:
        raise ValueError("Exact privately supplied database administration required")
    configs: dict[str, JsonRecord] = {
        role: load(root / role / "config.json", owned=False) for role in ROLES
    }
    if any(
        cfg.get("imp04_target") != PREFIX
        or cfg.get("role") != role
        or cfg.get("uid") != ROLE_UID[role]
        for role, cfg in configs.items()
    ):
        raise ValueError("All independently bound role configurations required")
    offline = NeverServedCore(root, configs, run_id)
    offline.verify()
    if any(
        configs[role].get("interactive_review_enabled") or configs[role].get("review_contexts_file")
        for role in ("core", "identity")
    ):
        raise ValueError("Fresh preparation cannot replace an existing review configuration")
    provisioned = load(root / "provision-receipt.json")
    receipt = load(root / "receipt.json")
    if provisioned.get("business_migrations") != [
        "001_manual.sql",
        "002_review_recovery.sql",
        "003_plans_consent_directory.sql",
    ]:
        raise ValueError("Exact completed initial provisioning required")
    credentials = read_json(credentials_file)
    identity_admin = target_admin_dsn(
        text(admin_config, "identity_admin_dsn"), text(configs["identity"], "store_dsn"), "identity"
    )
    data_admin = target_admin_dsn(
        text(admin_config, "data_admin_dsn"), text(configs["data"], "store_dsn"), "data"
    )
    state = root / "interactive-review"
    if state.exists() or state.is_symlink():
        raise ValueError(
            "One-shot preparation refuses retained state; recreate only the owned target"
        )
    clients: list[httpx.Client] = []
    journal_config = configs["journal"]
    try:
        identity = identity_service({**configs["identity"], "store_dsn": identity_admin}, clients)
        privileged = authenticated_privileged(identity, credentials, receipt)
        private_directory(state)
        write_json(state / "preparation.json", {"state": "preparing", "run_id": run_id})
        journal = FileJournal(
            Path(text(journal_config, "journal_directory")),
            private_key(text(journal_config, "signing_key")),
            text(journal_config, "signing_key_id"),
            expected_journal_id=text(journal_config, "journal_id"),
        )
        if journal.head().journal_id != receipt.get("journal_id"):
            raise ValueError("Exact fresh journal receipt binding required")
        with psycopg.Connection[dict[str, object]].connect(data_admin) as connection:
            apply_plans_review_migration(connection)
        policy_cfg = record(configs["pdp"]["policy"])
        policy = OpaPolicy(
            Path(text(configs["pdp"], "executable")),
            text(configs["pdp"], "executable_digest"),
            Path(text(policy_cfg, "source")).read_bytes(),
            text(policy_cfg, "signature"),
            public_key(text(policy_cfg, "public_key")),
        )
        sources = create_fixture_sources(run_id, datetime.now(UTC))
        data_cfg = configs["data"]
        source_path = root / "data" / "interactive-directory-source.pub"
        data_uid = int(data_cfg["uid"])
        replace_role_file(
            source_path,
            sources.public_key.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo),
            data_uid,
        )
        admissions = [*data_cfg["directory_signed_admissions"], *sources.envelopes]
        pins = {**data_cfg["directory_trusted_keys"], sources.key_id: str(source_path)}
        admission = VerifiedDirectoryAdmission(
            admissions, {key: public_key(str(path)) for key, path in pins.items()}
        )
        from care_link_core.manual_channels import ManualChannels

        channels = ManualChannels()

        def run_source(selected: str) -> JsonRecord:
            return read_json(state / "runs" / (str(UUID(selected)) + ".json"))

        bootstrap = BootstrapIdentityFactory(identity, run_source)
        authority = PreparationAuthority(identity, BootstrapAuthority(bootstrap), privileged)
        service = ManualService(
            PostgresStore(text(data_cfg, "store_dsn")),
            authority,
            policy,
            journal,
            AESGCMContentCipher(Path(text(data_cfg, "content_key")).read_bytes()),
            channel=channels,
            disclosure_templates=cast(dict[str, dict[str, object]], data_cfg["disclosures"]),
            cursor_key=Path(text(data_cfg, "cursor_key")).read_bytes(),
            directory_admission=admission,
        )
        for feed in sources.feeds:
            with channels.open(privileged["operator"]) as actor:
                service.directory_ingest(
                    actor, str(uuid5(UUID(run_id), "directory-ingest:" + feed["service_id"])), feed
                )
        with channels.open(privileged["security"]) as actor:
            service.directory_suspend(
                actor,
                str(uuid5(UUID(run_id), "directory-suspend")),
                {"expected_revision": "1", "reason": "security"},
                sources.service_ids["suspended"],
            )
        admin = ReviewRunAdmin(
            data_admin, "imp04-g04-" + UUID(run_id).hex, DATABASES["data"], journal.journal_id
        )
        actors = InProcessReviewActors(bootstrap, channels, admin)
        preflight = DirectoryReviewPreflight(
            service,
            service_ids=sources.service_ids,
            queries=tuple(
                {"jurisdiction": "CA-XX", "locale": locale, "need": "client_support"}
                for locale in ("en-CA", "fr-CA")
            ),
        )
        fixtures = ServiceFixtureBuilder(service, actors, preflight)
        adapter = ServiceReviewAdapter(
            admin, IdentityCustody(identity.store, identity.issuer), fixtures, offline.retire_views
        )
        manager = PlansReviewLifecycle(
            state,
            state / "registry.json",
            adapter,
            environment_id=admin.environment_id,
            target_id=PREFIX,
            port=30443,
        )
        ready = manager.start_fresh(lifetime_seconds=lifetime_seconds, run_id=run_id)
        offline.verify()
        config_digests: dict[str, str] = {}
        data_cfg.update(directory_signed_admissions=admissions, directory_trusted_keys=pins)
        for role in ("core", "identity", "data"):
            cfg = configs[role]
            uid = int(cfg["uid"])
            if role in {"core", "identity"}:
                registry = root / role / "interactive-review-origins.json"
                replace_role_file(registry, (state / "registry.json").read_bytes(), uid)
                cfg.update(
                    interactive_review_enabled=True,
                    review_contexts_file=str(registry),
                    review_legacy_origin="https://plans.localhost:30443",
                )
                cfg.pop("review_provider_configs_file", None)
            content = (json.dumps(cfg, sort_keys=True) + "\n").encode()
            replace_role_file(root / role / "config.json", content, uid)
            config_digests[role] = hashlib.sha256(content).hexdigest()
        offline.verify()
        result = {
            **ready,
            "directory": sources.provenance,
            "directory_service_ids": sources.service_ids,
            "configuration_digests": config_digests,
            "never_served_verified": True,
            "review_acceptance": "pending_actual_human_review",
        }
        write_json(state / "preparation.json", result)
        return result
    finally:
        for client in clients:
            client.close()
        _restore_journal_owner(journal_config)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--admin-config", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--lifetime-seconds", type=int, required=True)
    parser.add_argument("--credentials-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare_fresh_review(
            args.root,
            read_json(args.admin_config),
            run_id=args.run_id,
            lifetime_seconds=args.lifetime_seconds,
            credentials_file=args.credentials_file,
        )
    except Exception as error:
        print(json.dumps({"state": "preparation_unconfirmed", "error_class": type(error).__name__}))
        raise SystemExit(1) from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
