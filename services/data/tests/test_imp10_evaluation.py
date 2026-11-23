"""Synthetic replay authorization with signed transport, OPA and PostgreSQL."""

import base64
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import httpx
import psycopg
import pytest
from care_link_core.evaluation_http import HttpEvaluationGateway
from care_link_core.manual_envelopes import SignedEnvelopeFactory
from care_link_core.manual_identity import HttpManualIdentity
from care_link_data import PostgresStore
from care_link_data.app import SignedGatewaySecurity, create_app
from care_link_data.evaluation import ReplayResult
from care_link_domain import ManualError
from care_link_identity import Custody, IdentityService, ReceiptSigner
from care_link_identity.manual_runtime import create_manual_identity_app
from care_link_policy_input import DelegationVerifier, OpaPolicy
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from services.identity.tests.conftest import Clock, FakeProvider, MemoryStore, signed_in

ROOT = Path(__file__).resolve().parents[3]


class OfflineFixture:
    def __init__(self, owner):
        self.scope = {(owner.account_id, owner.role)}
        self.request = {
            "scenario_id": str(uuid4()),
            "input_manifest_digest": "a" * 64,
            "recorded_outputs_digest": "b" * 64,
            "bundle_digest": "c" * 64,
        }
        self.calls = []
        self.result = ReplayResult("completed", "d" * 64)
        self.after_computation = lambda: None

    def authorize(self, actor, request):
        if (actor.account_id, actor.role) not in self.scope or self.request != request:
            raise ManualError("evaluation.fixture_out_of_scope", 404)

    def evaluate(self, request):
        assert request == self.request
        self.calls.append(request)
        self.after_computation()
        return self.result


@pytest.fixture(scope="module")
def evaluation_schema(database):
    with psycopg.connect(database.admin) as connection:
        installed = connection.execute("SELECT to_regclass('quality.evaluation')").fetchone()
        if installed is None or installed[0] is None:
            migration = ROOT / "services/data/migrations/013_imp10_evaluation.sql"
            connection.execute(migration.read_text())


def provision(harness, role):
    actor = replace(
        harness.operator,
        role=role,
        account_id=str(uuid4()),
        identity_evidence_id=str(uuid4()),
    )
    PostgresStore(harness.database.admin).provision_principal(actor)
    return actor


@pytest.fixture
def replay_case(evaluation_schema, harness):
    trainer = provision(harness, "trainer")
    offline = OfflineFixture(trainer)
    harness.service.replay_evaluator = offline
    return harness, trainer, offline


def test_replay_is_audited_idempotent_and_rereads_current_scope(replay_case):
    h, trainer, offline = replay_case
    operation = str(uuid4())
    evaluation = h.service.replay_create(trainer, operation, offline.request)
    assert evaluation == {
        "id": evaluation["id"],
        "state": "completed",
        "evidence_digest": "d" * 64,
        "clinical_claim": False,
    }
    assert h.service.replay_create(trainer, operation, offline.request) == evaluation
    assert h.service.evaluation_read(trainer, evaluation["id"]) == evaluation
    assert offline.calls == [offline.request]
    assert h.read("SELECT count(*) FROM quality.evaluation") == [(1,)]
    assert h.read("SELECT count(*) FROM quality.metric_release") == [(0,)]
    assert h.read("SELECT count(*) FROM core.session") == [(0,)]
    assert h.read(
        "SELECT action FROM audit.event WHERE action LIKE %s ORDER BY sequence", ("replay_create%",)
    ) == [("replay_create",), ("replay_create.replay",)]

    foreign, governance = provision(h, "trainer"), provision(h, "governance")
    for actor in (h.participant, foreign, governance):
        with pytest.raises(ManualError):
            h.service.evaluation_read(actor, evaluation["id"])
    offline.scope.add((governance.account_id, governance.role))
    assert h.service.evaluation_read(governance, evaluation["id"]) == evaluation
    with pytest.raises(ManualError, match="idempotency_conflict"):
        h.service.replay_create(governance, operation, offline.request)
    offline.scope.remove((trainer.account_id, trainer.role))
    with pytest.raises(ManualError):
        h.service.replay_create(trainer, operation, offline.request)


def test_overlapping_exact_retry_creates_one_audited_reference(replay_case):
    h, trainer, offline = replay_case
    operation = str(uuid4())
    barrier = Barrier(2, timeout=0.6)
    offline.after_computation = barrier.wait
    with ThreadPoolExecutor(max_workers=2) as workers:
        first, second = [
            workers.submit(h.service.replay_create, trainer, operation, offline.request)
            for _ in range(2)
        ]
        assert first.result() == second.result()
    assert h.read("SELECT count(*) FROM quality.evaluation") == [(1,)]
    assert h.read(
        "SELECT count(*) FROM audit.event WHERE action='replay_create' AND decision='PERMIT'"
    ) == [(1,)]


def test_missing_recorded_observation_is_failed_and_expired_metadata_is_denied(replay_case):
    h, trainer, offline = replay_case
    offline.result = ReplayResult("failed", None)
    value = h.service.replay_create(trainer, str(uuid4()), offline.request)
    assert value["state"] == "failed"
    assert value["evidence_digest"] is None
    assert value["clinical_claim"] is False
    with psycopg.connect(h.database.admin) as connection:
        connection.execute(
            "UPDATE quality.evaluation SET created_at=now()-interval '2 days', "
            "expires_at=now()-interval '1 day' WHERE id=%s",
            (value["id"],),
        )
    with pytest.raises(ManualError):
        h.service.evaluation_read(trainer, value["id"])


@pytest.mark.parametrize("change", ["custody", "journal", "audit", "identity", "channel"])
def test_changed_guard_before_commit_creates_no_evaluation(replay_case, change):
    h, trainer, offline = replay_case

    def restrict():
        if change == "custody":
            offline.scope.clear()
        elif change == "journal":
            h.journal.fail = True
        elif change == "identity":
            h.authority.denied.add(trainer.account_id)
        elif change == "channel":
            h.channels.closed.add(trainer.account_id)
        else:
            with psycopg.connect(h.database.admin) as connection:
                connection.execute("DELETE FROM audit.head WHERE stream_id='demo'")

    offline.after_computation = restrict
    with pytest.raises(ManualError):
        h.service.replay_create(trainer, str(uuid4()), offline.request)
    assert len(offline.calls) == 1
    assert h.read("SELECT count(*) FROM quality.evaluation") == [(0,)]


def test_mismatched_pins_and_optional_composition_fail_closed(replay_case):
    h, trainer, offline = replay_case
    with pytest.raises(ManualError):
        h.service.replay_create(
            trainer, str(uuid4()), {**offline.request, "recorded_outputs_digest": "e" * 64}
        )
    assert offline.calls == []
    h.service.replay_evaluator = None
    with pytest.raises(ManualError, match="evaluation.disabled"):
        h.service.replay_create(trainer, str(uuid4()), offline.request)
    assert h.read("SELECT count(*) FROM quality.evaluation") == [(0,)]


def signed_opa(harness):
    binary = os.environ.get("CARE_LINK_OPA_BINARY")
    if not binary:
        pytest.skip("Explicit pinned OPA required for named replay boundary")
    base = (ROOT / "config/demo/imp08/policy/manual.rego").read_bytes()
    module = (ROOT / "config/demo/imp10/policy/evaluation.rego").read_bytes()
    header = b"package care_link.manual\n\nimport rego.v1\n\n"
    assert module.startswith(header)
    candidate = base + b"\n\n" + module[len(header) :]
    signer = Ed25519PrivateKey.generate()
    policy = OpaPolicy(
        Path(binary),
        hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
        candidate,
        base64.b64encode(signer.sign(candidate)).decode(),
        signer.public_key(),
    )
    with psycopg.connect(harness.database.admin) as connection:
        connection.execute("UPDATE control.guard SET bundle_digest=%s", (policy.bundle_digest,))
    return policy


def test_signed_policy_and_http_paths_bind_exact_evaluation_and_current_identity(replay_case):
    h, trainer, offline = replay_case
    clock = Clock()
    provider = FakeProvider(clock)
    identity_key, core_key = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    identity = IdentityService(
        MemoryStore(),
        provider,
        Custody(Fernet.generate_key()),
        ReceiptSigner(identity_key, "synthetic-quality"),
        "https://issuer.test",
        "https://app.test",
        clock,
    )
    identity.provision(provider.subject, trainer.account_id, ["trainer"])
    raw = signed_in(identity, role="trainer")
    policy = signed_opa(h)

    with TestClient(
        create_manual_identity_app(
            identity, lambda request, peer: request.headers.get("x-peer") == peer
        )
    ) as identity_app:

        def identity_transport(request):
            action = request.url.path.rsplit("/", 1)[-1]
            reply = identity_app.post(
                request.url.path,
                content=request.content,
                headers={
                    "Content-Type": "application/json",
                    "x-peer": "core" if action in {"authenticate", "evidence"} else "data",
                },
            )
            return httpx.Response(reply.status_code, json=reply.json())

        with httpx.Client(transport=httpx.MockTransport(identity_transport)) as identity_client:
            remote = HttpManualIdentity(
                identity_client, "https://identity.test", identity_key.public_key()
            )
            actor = replace(remote.authenticate(raw), transport_generation=1)
            h.service.authority, h.service.policy = remote, policy
            verifier = DelegationVerifier(
                core_key.public_key(), identity_key.public_key(), remote.resolve
            )
            app = create_app(
                h.service,
                SignedGatewaySecurity(
                    verifier, lambda request, peer: request.headers.get("x-peer") == peer
                ),
            )
            with TestClient(
                app, base_url="https://data.test", headers={"x-peer": "core"}
            ) as data_client:
                factory = SignedEnvelopeFactory(
                    data_client, "https://data.test", remote, policy, core_key
                )
                gateway = HttpEvaluationGateway(data_client, "https://data.test", factory)
                value = gateway.replay_create(actor, str(uuid4()), offline.request)
                assert gateway.evaluation_read(actor, value["id"]) == value
                key = str(uuid4())
                envelope = factory.build(
                    actor, "evaluation_read", key, {}, {"evaluation_id": value["id"]}
                )
                path = "/internal/v1/data/evaluation_read"
                assert (
                    data_client.post(
                        path, json=envelope, headers={"Idempotency-Key": key, "x-peer": "runtime"}
                    ).status_code
                    == 403
                )
                envelope["path_arguments"]["evaluation_id"] = str(uuid4())
                assert (
                    data_client.post(
                        path, json=envelope, headers={"Idempotency-Key": key}
                    ).status_code
                    == 403
                )
                provider.is_active = False
                with pytest.raises(ManualError):
                    gateway.evaluation_read(actor, value["id"])
    assert h.read("SELECT count(*) FROM quality.evaluation") == [(1,)]
