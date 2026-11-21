"""Real PostgreSQL qualification; only the explicit disposable test DSN is used."""

import json
import os
import secrets
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from care_link_data import AESGCMContentCipher, ManualService, PostgresStore
from care_link_data.values import digest, stamp
from care_link_domain import Actor, JournalState, ManualError
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[3]


class Authority:
    def __init__(self) -> None:
        self.denied: set[str] = set()
        self.proofs: dict[str, tuple[str, str, str]] = {}

    def current(self, actor: Actor) -> Actor:
        if actor.account_id in self.denied:
            raise ManualError("test.identity_unavailable", 503)
        return actor

    def recovery_proof(
        self, actor: Actor, ceremony_id: str, session_id: str, family_id: str
    ) -> None:
        if self.proofs.pop(ceremony_id, None) != (actor.account_id, session_id, family_id):
            raise ManualError("test.recovery_proof_required")


class Channels:
    def __init__(self) -> None:
        self.closed: set[str] = set()

    def current(
        self, account_id: str, browser_session_digest: str, transport_generation: int
    ) -> bool:
        del browser_session_digest, transport_generation
        return account_id not in self.closed


class Policy:
    """Boundary test double. This does not qualify OPA or artifact activation."""

    def __init__(self) -> None:
        self.fail = False
        self.obligations: list[dict[str, str]] = [{"kind": "audit_before_effect"}]
        self.before_return: object = None

    def evaluate(self, request: dict[str, object]) -> dict[str, object]:
        if self.fail:
            raise ManualError("test.pdp_unavailable", 503)
        facts = request["authority_facts"]
        permitted = isinstance(facts, dict) and facts["resource_owned_or_assigned"]
        return {
            "decision_id": str(uuid4()),
            "decision": "PERMIT" if permitted else "DENY",
            "binding_digest": digest(request),
            "reasons": ["CURRENT_SCOPE"] if permitted else ["NOT_AUTHORIZED"],
            "obligations": self.obligations,
            "versions": request["versions"],
            "bundle_digest": request["bundle_digest"],
            "expires_at": stamp(datetime.now(UTC) + timedelta(seconds=0.75)),
        }


class Journal:
    """Current-head test double; real signed filesystem journal is tested separately."""

    def __init__(self) -> None:
        self.state = JournalState(str(uuid4()), 1, 0, "0" * 64, 0, 1, datetime.now(UTC))
        self.fail = False
        self.records: list[dict[str, object]] = []

    def head(self) -> JournalState:
        if self.fail:
            raise ManualError("test.journal_unavailable", 503)
        return replace(self.state, observed_at=datetime.now(UTC))

    def append(self, request: dict[str, object]) -> JournalState:
        if self.fail:
            raise ManualError("test.journal_unavailable", 503)
        self.records.append(request)
        tip = self.state.tip + 1
        self.state = replace(
            self.state,
            tip=tip,
            restriction_barrier=tip
            if request.get("kind") == "restrict_intent"
            else self.state.restriction_barrier,
            tip_digest=digest(request),
        )
        return self.head()


@dataclass(repr=False)
class Database:
    admin: str
    runtime: str


@pytest.fixture(scope="session")
def database() -> Iterator[Database]:
    admin = os.environ.get("CARE_LINK_MANUAL_TEST_DSN")
    if not admin:
        pytest.skip("explicit disposable PostgreSQL TLS fixture DSN not supplied")
    settings = conninfo_to_dict(admin)
    name = "imp03_manual"
    password = secrets.token_urlsafe(32)
    created = False
    migrated = False
    with psycopg.connect(admin, autocommit=True) as connection:
        if connection.execute("SELECT 1 FROM pg_database WHERE datname=%s", (name,)).fetchone():
            raise RuntimeError("Test refuses to adopt existing imp03_manual database")
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        created = True
    target = make_conninfo(**{**settings, "dbname": name})
    try:
        with psycopg.connect(target) as connection:
            connection.execute((ROOT / "services/data/migrations/001_manual.sql").read_text())
            connection.execute(
                (ROOT / "services/data/migrations/003_plans_consent_directory.sql").read_text()
            )
            connection.execute((ROOT / "services/data/migrations/005_referrals.sql").read_text())
            connection.execute(
                (ROOT / "services/data/migrations/006_imp06_assistance.sql").read_text()
            )
            connection.execute(
                (ROOT / "services/data/migrations/007_imp06_inference.sql").read_text()
            )
            connection.execute(
                (ROOT / "services/data/migrations/008_imp07_lifecycle.sql").read_text()
            )
            connection.execute(
                (ROOT / "services/data/migrations/009_imp08_governance.sql").read_text()
            )
            connection.execute(
                (ROOT / "services/data/migrations/010_imp08_evidence.sql").read_text()
            )
            connection.execute(
                (ROOT / "services/data/migrations/011_imp08_custody_ordering.sql").read_text()
            )
            connection.execute(
                (ROOT / "services/data/migrations/012_imp09_recovery.sql").read_text()
            )
        migrated = True
        with psycopg.connect(admin) as connection:
            connection.execute(
                sql.SQL("CREATE ROLE imp03_runtime_test LOGIN INHERIT PASSWORD {}").format(
                    sql.Literal(password)
                )
            )
            connection.execute("GRANT care_link_data_runtime TO imp03_runtime_test")
        runtime = make_conninfo(
            **{**settings, "dbname": name, "user": "imp03_runtime_test", "password": password}
        )
        yield Database(target, runtime)
    finally:
        if created:
            with psycopg.connect(admin, autocommit=True) as connection:
                connection.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
                )
                if migrated:
                    for role in [
                        "imp03_runtime_test",
                        "care_link_data_runtime",
                        "care_link_audit_reader",
                        "care_link_backup",
                    ]:
                        connection.execute(
                            sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role))
                        )


@dataclass
class Harness:
    database: Database
    service: ManualService
    authority: Authority
    policy: Policy
    journal: Journal
    channels: Channels
    participant: Actor
    worker: Actor
    supervisor: Actor
    operator: Actor

    def create(self) -> dict[str, object]:
        return self.service.session_create(
            self.participant,
            str(uuid4()),
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

    def read(self, sql_text: str, parameters: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
        with psycopg.connect(self.database.admin) as connection:
            return connection.execute(sql_text, parameters).fetchall()


@pytest.fixture
def harness(database: Database) -> Harness:
    with psycopg.connect(database.admin) as connection:
        connection.execute(
            "TRUNCATE governance.instance,governance.signer,governance.exception_rule,"
            "lifecycle.scan_cursor,durable.duty_nonce,durable.duty_operation,"
            "durable.due_job,"
            "control.signal_receipt,control.signal_head,control.signal_source,"
            "recovery.help_import,recovery.target_validation,recovery.restriction,"
            "recovery.new_principal,recovery.command,control.guard,"
            "control.principal_guard,audit.head CASCADE"
        )
        connection.execute("INSERT INTO audit.head VALUES('demo',1,repeat('0',64))")
    now = datetime.now(UTC)

    def actor(role: str) -> Actor:
        return Actor(
            str(uuid4()),
            role,
            1,
            1,
            now,
            role != "pid",
            secrets.token_hex(32),
            1,
            secrets.token_hex(32),
            now + timedelta(hours=1),
            str(uuid4()),
        )

    participant, worker, supervisor, operator = [
        actor(role) for role in ["pid", "worker", "supervisor", "operator"]
    ]
    authority, policy, journal, channels = Authority(), Policy(), Journal(), Channels()
    admin = PostgresStore(database.admin)
    admin.bootstrap(journal.head(), "a" * 64)
    for item in [participant, worker, supervisor, operator]:
        admin.provision_principal(item)
    templates = json.loads((ROOT / "config/demo/imp03/disclosures.json").read_text())
    service = ManualService(
        PostgresStore(database.runtime),
        authority,
        policy,
        journal,
        AESGCMContentCipher(secrets.token_bytes(32)),
        channel=channels,
        disclosure_templates=templates,
        cursor_key=secrets.token_bytes(32),
    )
    return Harness(
        database,
        service,
        authority,
        policy,
        journal,
        channels,
        participant,
        worker,
        supervisor,
        operator,
    )


@pytest.fixture(scope="session")
def receiver_database(database):
    settings = conninfo_to_dict(database.admin)
    name = "imp05_receiver"
    password = secrets.token_urlsafe(32)
    with psycopg.connect(database.admin, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    admin = make_conninfo(**{**settings, "dbname": name})
    try:
        with psycopg.connect(admin) as connection:
            connection.execute(
                (ROOT / "services/simulators/migrations/001_receiver.sql").read_text()
            )
        with psycopg.connect(database.admin) as connection:
            connection.execute(
                sql.SQL("CREATE ROLE imp05_receiver_test LOGIN INHERIT PASSWORD {}").format(
                    sql.Literal(password)
                )
            )
            connection.execute("GRANT care_link_receiver_runtime TO imp05_receiver_test")
        runtime = make_conninfo(
            **{**settings, "dbname": name, "user": "imp05_receiver_test", "password": password}
        )
        yield admin, runtime
    finally:
        with psycopg.connect(database.admin, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )
            connection.execute("DROP ROLE IF EXISTS imp05_receiver_test,care_link_receiver_runtime")
