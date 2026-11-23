"""The actual Core and simulator bindings with a separate TLS database."""

import base64
import json
import secrets
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import psycopg
import pytest
from care_link_core.manual_app import create_manual_app
from care_link_core.manual_channels import ManualChannels
from care_link_core.training_http import HttpTrainingGateway
from care_link_data.app import create_app as data_app
from care_link_data.training_replay import OfflineTrainingReplay, capture, sha256, training_bundle
from care_link_domain import ManualError
from care_link_domain.training import CHANNELS, DIRECTORY_STATES, MODES, canonical, exercise
from care_link_simulators.training import TrainingService
from care_link_simulators.training_app import TrainingIdentity, create_training_app
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = (ROOT / "config/demo/imp10/training-artifact.json").read_bytes()
PIN = sha256(ARTIFACT)


def fixture(mode="drop_after_store"):
    return {
        "artifact_digest": PIN,
        "locale": "fr-CA",
        "fixture_mode": mode,
        "business_clock_at": "2001-01-01T00:00:00Z",
    }


@pytest.fixture(scope="module")
def training_dsn(database):
    name = "imp10_training_" + uuid4().hex[:12]
    runtime = name + "_runtime"
    password = secrets.token_urlsafe()
    with psycopg.connect(database.admin, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        with psycopg.connect(make_conninfo(database.admin, dbname=name)) as admin:
            admin.execute((ROOT / "services/simulators/migrations/002_training.sql").read_text())
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(runtime), sql.Literal(password)
                )
            )
            admin.execute(
                sql.SQL("GRANT care_link_training_runtime TO {}").format(sql.Identifier(runtime))
            )
        yield make_conninfo(database.admin, dbname=name, user=runtime, password=password)
    finally:
        with psycopg.connect(database.admin, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(runtime)))
            admin.execute("DROP ROLE IF EXISTS care_link_training_runtime")


def actors(harness):
    owner = replace(harness.worker, role="trainer")
    other = replace(owner, account_id=str(uuid4()))
    return owner, other


def build(harness, training_dsn):
    owner, other = actors(harness)
    flags = {"policy": True, "workload": True}
    service = TrainingService(
        training_dsn,
        harness.authority,
        lambda *_: flags["policy"],
        harness.service.cipher,
        artifact=ARTIFACT,
        artifact_digest=PIN,
        admitted_trainers=frozenset({owner.account_id, other.account_id}),
    )
    return owner, other, flags, service


def signed(key, fields):
    return {
        **fields,
        "signature": base64.urlsafe_b64encode(key.sign(canonical(fields))).rstrip(b"=").decode(),
    }


def timestamp(value):
    return value.isoformat().replace("+00:00", "Z")


def test_browser_core_and_training_current_authority(harness, training_dsn):
    owner, other, flags, service = build(harness, training_dsn)
    sender, identity_signer = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    roster = {actor.account_id: actor for actor in (owner, other)}

    class Evidence:
        def evidence(self, actor, action, digest, nonce, resource):
            now = datetime.now(UTC)
            return signed(
                identity_signer,
                {
                    "id": str(uuid4()),
                    "principal_id": actor.account_id,
                    "role": actor.role,
                    "identity_revision": str(actor.identity_revision),
                    "role_revision": str(actor.role_revision),
                    "action": action,
                    "request_digest": digest,
                    "nonce": nonce,
                    "resource_id": resource,
                    "verified_at": timestamp(now),
                    "expires_at": timestamp(now + timedelta(seconds=0.95)),
                    "kind": "human_identity",
                },
            )

    def resolve(receipt):
        return replace(roster[receipt["principal_id"]], identity_evidence_id=receipt["id"])

    simulator = TestClient(
        create_training_app(
            service,
            TrainingIdentity(sender.public_key(), identity_signer.public_key(), resolve),
            lambda _request, peer: flags["workload"] and peer == "core",
        )
    )
    messages = []

    def relay(request):
        messages.append((request.url.path, json.loads(request.content), dict(request.headers)))
        reply = simulator.request(
            request.method, request.url.path, headers=request.headers, content=request.content
        )
        return httpx.Response(reply.status_code, content=reply.content, headers=reply.headers)

    class Browser:
        def authenticate(self, request):
            return {"trainer": owner, "foreign": other, "participant": harness.participant}[
                request.headers["x-profile"]
            ]

        def csrf(self, request, _actor):
            if request.headers.get("x-csrf") != "fixture":
                raise ManualError("manual.csrf_denied")

    def command(client, profile, path, data, key=None):
        return client.post(
            path,
            json=data,
            headers={
                "x-profile": profile,
                "x-csrf": "fixture",
                "idempotency-key": key or str(uuid4()),
            },
        )

    with httpx.Client(transport=httpx.MockTransport(relay)) as http:
        gateway = HttpTrainingGateway(http, "https://training.test", Evidence(), sender)
        bff = TestClient(
            create_manual_app(harness.service, Browser(), ManualChannels(), training=gateway)
        )
        uri = "/v1/training/scenarios"
        assert command(bff, "participant", uri, fixture()).status_code == 403
        assert bff.post(uri, json=fixture(), headers={"x-profile": "trainer"}).status_code == 403
        assert messages == []
        key = str(uuid4())
        created = command(bff, "trainer", uri, fixture(), key)
        assert created.status_code == 200, created.text
        assert command(bff, "trainer", uri, fixture(), key).json() == created.json()
        assert command(bff, "trainer", uri, fixture("delay"), key).status_code == 409
        target = uri + "/" + created.json()["resource_id"]
        assert bff.get(target, headers={"x-profile": "foreign"}).status_code == 404
        read = bff.get(target, headers={"x-profile": "trainer"})
        assert read.json()["state"] == "running"
        flags["policy"] = False
        stopped = command(bff, "trainer", target + "/stop", {"expected_revision": "1"})
        assert stopped.status_code == 403
        flags["policy"] = True
        flags["workload"] = False
        assert bff.get(target, headers={"x-profile": "trainer"}).status_code == 403
        flags["workload"] = True
        path, envelope, headers = messages[-1]
        envelope["audience"] = "care-link-receiver"
        assert simulator.post(path, json=envelope, headers=headers).status_code == 422
        assert (
            command(bff, "trainer", target + "/stop", {"expected_revision": "1"}).status_code == 200
        )
        assert bff.get(target, headers={"x-profile": "trainer"}).json()["state"] == "stopped"
        assert command(bff, "participant", "/v1/identity-links", {}).status_code == 403

    class Unexpected:
        def verify(self, *_args):
            pytest.fail("Disabled Data identity link consulted authority")

    data = TestClient(data_app(harness.service, Unexpected()))
    denial = data.post("/internal/v1/data/identity_link_request", json={"kind": "export"})
    assert denial.status_code == 403
    assert denial.json()["message_key"] == "manual.capability_disabled"


def test_stop_fences_projection_and_recording_is_durable(harness, training_dsn):
    owner, _, _, service = build(harness, training_dsn)

    def invoke(operation, target):
        try:
            return operation(owner, str(uuid4()), target, {"expected_revision": "1"})["state"]
        except ManualError as error:
            assert error.status == 409
            return "conflict"

    for _ in range(3):
        created = service.scenario_create(owner, str(uuid4()), fixture())
        target = created["resource_id"]
        with ThreadPoolExecutor(max_workers=2) as threads:
            stop = threads.submit(invoke, service.scenario_stop, target)
            complete = threads.submit(invoke, service.complete_fixture, target)
            assert sorted([stop.result(), complete.result()]) == ["committed", "conflict"]
        state = service.scenario_read(owner, target)
        assert state["revision"] == "2"
        if stop.result() == "committed":
            assert state["state"] == "stopped" and state["evidence_digest"] is None
            with pytest.raises(ManualError, match="training.recording_unavailable"):
                service.recording(owner, target)
        else:
            assert state["state"] == "completed"
            assert service.recording(owner, target)[1]["effects"]["model_request"] == "suppressed"


def test_replay_reexecutes_exact_recorded_fixture_and_expires_on_real_clock(harness, training_dsn):
    owner, other, _, service = build(harness, training_dsn)
    target = service.scenario_create(owner, str(uuid4()), fixture("partial"))["resource_id"]
    service.complete_fixture(owner, str(uuid4()), target, {"expected_revision": "1"})
    original_inputs, original, captured_at = service.recording(owner, target)
    assert original["receiver"]["accepted_fields"] == ["support_preference"]
    reviewer = replace(other, role="governance")
    bundle = training_bundle(
        {
            "runner": (ROOT / "packages/domain/src/care_link_domain/training.py").read_bytes(),
            "artifact": ARTIFACT,
            "contracts": (
                ROOT / "packages/contracts/python/src/care_link_contracts/schema.json"
            ).read_bytes(),
        }
    )
    now = [captured_at + timedelta(seconds=1)]
    for record, status in [
        (original, "completed"),
        (None, "failed"),
        ({**original, "locale": "en-CA"}, "failed"),
    ]:
        admitted = capture(
            target,
            original_inputs,
            record,
            captured_at,
            bundle=bundle,
            owner_id=owner.account_id,
            reviewers=frozenset({reviewer.account_id}),
        )
        evaluator = OfflineTrainingReplay(
            [admitted], bundle=bundle, artifact_digest=PIN, clock=lambda: now[0]
        )
        request = {
            "scenario_id": target,
            "input_manifest_digest": sha256(admitted.manifest),
            "recorded_outputs_digest": sha256(admitted.observations),
            "bundle_digest": bundle,
        }
        evaluator.authorize(owner, request)
        evaluator.authorize(reviewer, request)
        with pytest.raises(ManualError):
            evaluator.authorize(other, request)
        with pytest.raises(ManualError):
            evaluator.evaluate({**request, "recorded_outputs_digest": "5" * 64})
        result = evaluator.evaluate(request)
        assert result.state == status and result.evidence_digest
        assert evaluator.evaluate(request) == result
    now[0] = captured_at + timedelta(days=7)
    with pytest.raises(ManualError):
        evaluator.authorize(owner, request)


@pytest.mark.parametrize("mode", MODES)
def test_internal_channel_and_directory_projection(mode):
    result = exercise(str(uuid4()), fixture(mode))
    assert {item["state"] for item in result["directory"]["states"]} == set(DIRECTORY_STATES)
    assert all(
        row["availability"] == "unconfirmed" and row["fallback"]
        for row in result["directory"]["states"]
        if row["state"] != "normal"
    )
    channels = result["channels"]
    assert {row["channel"] for row in channels} == set(CHANNELS)
    assert all(row["simulated"] and not row["credential_issued"] for row in channels)
    if mode in {"channel_drop", "regional_outage"}:
        assert all(row["connection"] == "unconnected" for row in channels)
    if mode == "poisoned_feed":
        assert result["directory"]["feed"] == "quarantined"
    if mode == "drop_after_store":
        assert result["receiver"] == {
            "send": "unknown",
            "lookup": "received",
            "decision": "pending",
            "accepted_fields": [],
        }
    assert result["effects"]["external_contact"] == "suppressed"


def test_tardy_final_permit_rolls_back_and_trainers_can_reuse_a_key(harness, training_dsn):
    first, second = actors(harness)
    baseline = datetime.now(UTC)
    now = [baseline]
    checks = [0]

    def slow_final(*_args):
        checks[0] += 1
        if checks[0] == 2:
            now[0] += timedelta(seconds=2)
        return True

    service = TrainingService(
        training_dsn,
        harness.authority,
        slow_final,
        harness.service.cipher,
        artifact=ARTIFACT,
        artifact_digest=PIN,
        admitted_trainers=frozenset({first.account_id, second.account_id}),
        clock=lambda: now[0],
    )
    key = str(uuid4())
    with pytest.raises(ManualError, match="training.current_authority_required"):
        service.scenario_create(
            replace(first, request_deadline=baseline + timedelta(seconds=1)), key, fixture()
        )
    with psycopg.connect(training_dsn) as conn:
        assert conn.execute(
            "SELECT count(*) FROM training.operation WHERE id=%s", (key,)
        ).fetchone() == (0,)
    result = service.scenario_create(first, key, fixture())
    other = service.scenario_create(second, key, fixture())
    assert result["resource_id"] != other["resource_id"]


def test_configured_immediate_capture_encryption_and_database_expiry(harness, training_dsn):
    from tools.imp10_runtime.training import admit_completed_capture, training_application

    owner, _ = actors(harness)
    key = Ed25519PrivateKey.generate()
    historical = [datetime.now(UTC)]

    class TrainerProof:
        current = harness.authority.current

        def resolve(self, receipt):
            return replace(owner, identity_evidence_id=receipt["id"])

    app, service = training_application(
        training_dsn,
        TrainerProof(),
        lambda *_: False,
        lambda *_: True,
        harness.service.cipher,
        core_key=key.public_key(),
        identity_key=key.public_key(),
        artifact=ARTIFACT,
        artifact_digest=PIN,
        admitted_trainers=frozenset({owner.account_id}),
        clock=lambda: historical[0],
    )
    assert TestClient(app).post("/internal/v1/training/scenario_create", json={}).status_code == 403
    target = service.scenario_create(owner, str(uuid4()), fixture("partial"))["resource_id"]
    state = service.scenario_read(owner, target)
    assert state["state"] == "completed" and state["evidence_digest"]
    sealed, request = admit_completed_capture(
        service, owner, target, bundle="1" * 64, reviewers=frozenset()
    )
    assert sha256(sealed.observations) == request["recorded_outputs_digest"]
    with psycopg.connect(training_dsn) as conn:
        ciphertext, key_ref = conn.execute(
            "SELECT projection_ciphertext,content_key_ref FROM training.scenario WHERE id=%s",
            (target,),
        ).fetchone()
        assert "support_preference" not in ciphertext and key_ref == harness.service.cipher.key_ref
    assert service.expire_recordings() == 0
    # The owner-only fixture can backdate this synthetic row without changing the runtime's grants.
    with psycopg.connect(
        make_conninfo(
            harness.database.admin, dbname=psycopg.conninfo.conninfo_to_dict(training_dsn)["dbname"]
        )
    ) as conn:
        conn.execute(
            "UPDATE training.scenario SET created_at=now()-interval '8 days' WHERE id=%s", (target,)
        )
    assert service.expire_recordings() == 1
    with pytest.raises(ManualError, match="training.scenario_unavailable"):
        service.recording(owner, target)
    assert service.expire_recordings() == 0
