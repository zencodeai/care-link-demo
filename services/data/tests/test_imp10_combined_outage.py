"""Opt-in synthetic workstation qualification over independently bound TLS roles."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from uuid import uuid4

import httpx
import psycopg
import pytest
from care_link_core.evaluation_http import HttpEvaluationGateway
from care_link_core.manual_app import create_manual_app
from care_link_core.manual_channels import ManualChannels
from care_link_core.manual_envelopes import SignedEnvelopeFactory
from care_link_core.manual_http import HttpManualGateway
from care_link_core.referral_http import HttpReferralGateway
from care_link_data import PostgresStore
from care_link_domain import Actor, ManualError
from care_link_policy_input import DelegationVerifier
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse

from services.data.tests.imp10_outage_help import start_help
from services.data.tests.imp10_outage_listeners import RoleTopology
from services.data.tests.imp10_outage_model import (
    Peers,
    RoleTransport,
    measured_turn,
    start_assistance,
)
from services.data.tests.imp10_outage_roles import (
    assert_receiver_scope,
    assert_replay_scope,
    assert_training_capture,
    start_roles,
)
from services.data.tests.test_assistance import case
from services.data.tests.test_assistance_jobs import jobs_store  # noqa: F401
from services.data.tests.test_imp10_evaluation import evaluation_schema, signed_opa  # noqa: F401
from services.data.tests.test_imp10_training_boundary import training_dsn  # noqa: F401
from services.data.tests.test_referrals import (
    build_case,
    dispatch,
    referral_harness,  # noqa: F401
    send,
)
from tests.evaluation.qwen_combined_journey import IdentityFixture

ROOT = Path(__file__).resolve().parents[3]
DATA = "https://data:8443"
ACTOR_HEADER = "X-Synthetic-Browser"


class Browser:
    def __init__(self, authority, help_service) -> None:
        self.authority, self.help = authority, help_service
        self.by_ticket: dict[str, Actor] = {}
        self.by_principal: dict[str, Actor] = {}
        self.tickets: dict[str, str] = {}

    def add(self, actor: Actor) -> dict[str, str]:
        token = self.tickets.setdefault(actor.account_id, uuid4().hex)
        self.by_ticket[token] = self.by_principal[actor.account_id] = actor
        return {ACTOR_HEADER: token}

    def current(self, actor: Actor) -> Actor:
        try:
            self.help.assert_identity_available()
        except httpx.HTTPError as error:
            raise ManualError("manual.identity_unavailable", 503) from error
        return self.authority.current(actor)

    def authenticate(self, request: Request) -> Actor:
        actor = self.by_ticket.get(request.headers.get(ACTOR_HEADER, ""))
        if actor is None:
            raise ManualError("manual.identity_required", 403)
        return self.current(actor)

    def csrf(self, request: Request, actor: Actor) -> None:
        if self.tickets[actor.account_id] != request.headers.get(ACTOR_HEADER):
            raise ManualError("manual.identity_required", 403)

    def resolve(self, evidence):
        actor = self.by_principal.get(evidence["principal_id"])
        if actor is None:
            raise ManualError("manual.identity_required", 403)
        return self.current(actor)


class IdentityEvidence:
    def __init__(self, browser: Browser) -> None:
        self.browser = browser
        self.key = Ed25519PrivateKey.generate()

    def evidence(self, actor, action, request_digest, nonce, resource):
        self.browser.current(actor)
        signer = IdentityFixture(actor)
        signer.key = self.key
        return signer.evidence(actor, action, request_digest, nonce, resource)


def start_policy(topology, h, keys, local):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/decisions")
    def evaluate(body: dict[str, object], request: Request):
        if not any(keys.verify(request, role) for role in ("core", "data")):
            return JSONResponse({}, status_code=403)
        try:
            return local.evaluate(body)
        except ManualError as error:
            return JSONResponse({"code": error.code}, status_code=error.status)

    topology.start("policy", app)
    url = topology.origin("policy") + "/decisions"

    class RemotePolicy:
        def __init__(self, role):
            self.client = topology.client(headers=keys.headers(role))

        def evaluate(self, request):
            try:
                response = self.client.post(url, json=request, timeout=0.8)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as error:
                raise ManualError("manual.policy_unavailable", 503) from error

    h.service.policy = RemotePolicy("data")
    return RemotePolicy("core")


@contextmanager
def audit_unavailable(h):
    with psycopg.connect(h.database.admin) as connection:
        connection.execute("ALTER TABLE audit.event RENAME TO event_unavailable")
        connection.commit()
        try:
            yield
        finally:
            connection.execute("ALTER TABLE audit.event_unavailable RENAME TO event")


def accepted(response):
    assert response.status_code == 200, (response.request.url.path, response.text)
    return response.json()


def denied(response, status, key=None):
    assert response.status_code == status, (response.request.url.path, response.text)
    value = response.json()
    if key is not None:
        assert value["message_key"] == key
    return {"status": response.status_code, "key": value["message_key"]}


def replayed_roles(browser, core, h, roles, worker):
    trainer, other = roles[0], roles[1]
    use = {"owner": trainer, "other": other, "worker": worker}
    scenario = assert_training_capture(browser, core, roles[2], **use)
    replay = roles[2].admit_replay(scenario)
    value = assert_replay_scope(browser, core, h, roles[2], replay, **use)
    return scenario, value["state"]


@pytest.mark.skipif(
    not os.environ.get("CARE_LINK_IMP10_COMBINED_EVIDENCE"),
    reason="Requires explicit live pinned provider and disposable topology qualification",
)
def test_combined_role_outages(
    referral_harness,  # noqa: F811
    receiver_database,
    training_dsn,  # noqa: F811
    evaluation_schema,  # noqa: F811
    jobs_store,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
    profile = json.loads((ROOT / "doc/REQ/demo-parameters.json").read_text())["capacity"]
    model = {
        key: Path(os.environ["CARE_LINK_JOURNEY_" + suffix])
        for key, suffix in {
            "artifact_directory": "MODEL_DIR",
            "model_index": "MODEL_INDEX",
            "lmstudio_token_file": "TOKEN_FILE",
        }.items()
    }
    assert os.environ.get("CARE_LINK_OPA_BINARY")
    started = datetime.now(UTC)
    h, _ = referral_harness
    referral = build_case(referral_harness, receiver_database)
    referral_session = referral[3]
    assert referral_session["service_phase"] == "human_controlled"
    admin = PostgresStore(h.database.admin)
    pairs = [h]
    for _ in range(profile["active_sessions"] - 1):
        participant = replace(
            h.participant,
            account_id=str(uuid4()),
            browser_session_digest=uuid4().hex + uuid4().hex,
            credential_ref=uuid4().hex + uuid4().hex,
            identity_evidence_id=str(uuid4()),
        )
        admin.provision_principal(participant)
        pairs.append(replace(h, participant=participant))
    workloads = [case(pair) for pair in pairs[1:]]
    command = workloads[0][1]
    sid = referral_session["id"]
    first = {
        **command,
        "binding": {"kind": "session", "session_id": sid},
        "scope": {**command["scope"], "session_id": sid},
        "expected_revision": h.service.session_read(h.worker, sid)["revision"],
    }
    commands = [first, *(body for _, body, _ in workloads)]
    sessions = [body["binding"]["session_id"] for body in commands]
    with psycopg.connect(h.database.admin) as connection:
        connection.execute("UPDATE core.session SET jurisdiction='CA-XX'")
    peer = workloads[0][2]
    local_policy = signed_opa(h)

    with RoleTopology(tmp_path) as topology, ExitStack() as stack:
        help_path = tmp_path / "help"
        help_path.mkdir(mode=0o700)
        release_path = tmp_path / "release"
        release_path.mkdir(mode=0o700)
        help_service = start_help(topology, h, help_path, stack)
        security = Browser(h.authority, help_service)
        worker = security.add(h.worker)
        participants = [security.add(pair.participant) for pair in pairs]
        browser = topology.client(timeout=2)
        core_url = topology.origin("core")
        keys = Peers()
        core_key = Ed25519PrivateKey.generate()
        identity = IdentityEvidence(security)
        delegations = DelegationVerifier(
            core_key.public_key(), identity.key.public_key(), security.resolve
        )
        core_policy = start_policy(topology, h, keys, local_policy)
        role_core_client = topology.client(headers=keys.headers("core"))
        role_data_client = topology.client(headers=keys.headers("data"))
        roles = start_roles(
            topology,
            role_core_client,
            role_data_client,
            referral,
            training_dsn,
            core_key=core_key,
            identity_key=identity.key.public_key(),
            evidence=identity,
            resolve=security.resolve,
            workload=keys.verify,
        )
        receiver = security.add(roles.receiver_actor)
        other_receiver = security.add(roles.other_receiver)
        trainer = security.add(roles.trainer)
        other_trainer = security.add(roles.other_trainer)
        core_client = stack.enter_context(
            httpx.Client(transport=RoleTransport(topology, "data", keys, "core"), trust_env=False)
        )
        envelopes = SignedEnvelopeFactory(core_client, DATA, identity, core_policy, core_key)
        assistance = start_assistance(
            topology,
            stack,
            h,
            release_path,
            keys=keys,
            core_key=core_key,
            identity=identity,
            delegations=delegations,
            envelopes=envelopes,
            core_client=core_client,
            peer=peer,
            model=model,
        )
        topology.start(
            "core",
            create_manual_app(
                HttpManualGateway(core_client, DATA, envelopes),
                security,
                ManualChannels(),
                referrals=HttpReferralGateway(core_client, DATA, envelopes),
                receiver=roles.receiver_gateway,
                training=roles.training_gateway,
                evaluation=HttpEvaluationGateway(core_client, DATA, envelopes),
                assistance=assistance.tasks,
                assistance_availability=assistance.availability,
                assistance_broker=assistance.broker,
                runtime_verify=assistance.verify_runtime,
            ),
        )

        def read(session, headers):
            return accepted(browser.get(core_url + f"/v1/sessions/{session}", headers=headers))

        def post(path, body, headers, key=None):
            return browser.post(
                core_url + path,
                json=body,
                headers={
                    **headers,
                    "Idempotency-Key": key or str(uuid4()),
                },
            )

        def effect_counts():
            return {
                name: h.read(statement)[0][0]
                for name, statement in {
                    "messages": "SELECT count(*) FROM core.message",
                    "drafts": "SELECT count(*) FROM assistance.draft",
                    "dispatches": "SELECT count(*) FROM referral.dispatch",
                    "evaluations": "SELECT count(*) FROM quality.evaluation",
                }.items()
            }

        def message_body(session):
            current = read(session, worker)
            return {
                "expected_revision": current["revision"],
                "expected_control_epoch": current["control_epoch"],
                "text": "Synthetic support from the assigned worker.",
                "accepted_draft_id": None,
            }

        def timed_read(session, headers):
            began = monotonic()
            state = read(session, headers)["service_phase"]
            assert state == "human_controlled"
            return round((monotonic() - began) * 1000, 3)

        def message_permits():
            return h.read(
                "SELECT count(*) FROM audit.event WHERE action='message_send' AND decision='PERMIT'"
            )[0][0]

        pending = dispatch(referral)
        received = send(referral, pending)
        assert received["state"] == "received"
        assert_receiver_scope(
            browser,
            core_url,
            received["dispatch_id"],
            owner=receiver,
            other=other_receiver,
            worker=worker,
        )
        scenario, replay_state = replayed_roles(
            browser, core_url, h, (trainer, other_trainer, roles), worker
        )
        help_baseline = help_service.probe("en-CA")
        expected_sessions = profile["active_sessions"]
        assert len(set(sessions)) == expected_sessions

        commands[0]["expected_revision"] = read(sessions[0], worker)["revision"]
        with ThreadPoolExecutor(max_workers=12) as pool:
            running = []
            tasks = []
            try:
                for index, body in enumerate(commands):
                    tasks.append(accepted(post("/v1/tasks", body, worker)))
                    if index < profile["concurrent_inference_jobs"]:
                        running.append(pool.submit(measured_turn, assistance))
                try:
                    assistance.barrier.wait(profile["concurrent_inference_jobs"])
                except AssertionError:
                    for call in running:
                        if call.done():
                            assert call.result()["state"] == "awaiting_human"
                    raise
                peak = {
                    "connected_sessions": h.read(
                        "SELECT count(*) FROM core.session WHERE service_phase='human_controlled'"
                    )[0][0],
                    "occupied_inference_slots": h.read(
                        "SELECT count(*) FROM assistance.compute_slot WHERE state='occupied'"
                    )[0][0],
                    "unique_pending_tasks": len(assistance.queue._pending),
                }
                assert list(peak.values()) == [
                    expected_sessions,
                    profile["concurrent_inference_jobs"],
                    profile["inference_queue_limit"],
                ]
                with pytest.raises(ManualError, match="capacity_unavailable"):
                    assistance.queue.enqueue(tasks[0])
                parallel_help = pool.submit(help_service.probe, "fr-CA")
                peak_read_ms = list(pool.map(timed_read, sessions, participants))
                help_at_peak = parallel_help.result(timeout=4)
                assert all(not call.done() for call in running)
            finally:
                assistance.barrier.release.set()
            warm = [call.result(timeout=45) for call in running]
        assert all(outcome["state"] == "awaiting_human" for outcome in warm), warm

        message_session = sessions[-1]
        message_path = f"/v1/sessions/{message_session}/messages"
        observations = {}
        for fault, locale in (
            ("model", "fr-CA"),
            ("policy", "en-CA"),
            ("audit", "fr-CA"),
            ("identity", "en-CA"),
            ("main_roles_and_dependencies", "fr-CA"),
        ):
            before = effect_counts()
            permits = message_permits()
            mutation = message_body(message_session)
            operation = str(uuid4())
            fault_start = monotonic()
            with ExitStack() as outage:
                if fault == "model":
                    assistance.barrier.release.clear()
                    with ThreadPoolExecutor(max_workers=1) as model_pool:
                        interrupted = model_pool.submit(measured_turn, assistance)
                        try:
                            assistance.barrier.wait(profile["concurrent_inference_jobs"] + 1)
                            outage.enter_context(topology.pause("host-inference-bridge"))
                        finally:
                            assistance.barrier.release.set()
                        failure = interrupted.result(timeout=10)
                    assert failure["state"] == "compute_unknown"
                    assert failure["safe_reason"] == "provider_stop_unverified"
                    assert h.read(
                        "SELECT count(*) FROM assistance.compute_slot WHERE state='compute_unknown'"
                    ) == [(1,)]
                    assert effect_counts() == before
                    value = accepted(post(message_path, mutation, worker, operation))
                    assert value["kind"] == "human_authored"
                    visible = accepted(
                        browser.get(core_url + message_path, headers=participants[-1])
                    )
                    assert [message["id"] for message in visible["items"]] == [value["id"]]
                    before["messages"] += 1
                    permits += 1
                    outcome = {"manual": "visible_human_authored", "assistance": failure}
                elif fault == "policy":
                    outage.enter_context(topology.pause("policy"))
                    outcome = denied(
                        post(message_path, mutation, worker, operation),
                        503,
                        "manual.policy_unavailable",
                    )
                elif fault == "audit":
                    outage.enter_context(audit_unavailable(h))
                    outcome = denied(post(message_path, mutation, worker, operation), 503)
                    assert h.read("SELECT to_regclass('audit.event')") == [(None,)]
                elif fault == "identity":
                    outage.enter_context(topology.pause("identity"))
                    outcome = denied(
                        post(message_path, mutation, worker, operation),
                        503,
                        "manual.identity_unavailable",
                    )
                else:
                    outage.enter_context(audit_unavailable(h))
                    unavailable = (
                        "host-inference-bridge",
                        "receiver",
                        "training",
                        "policy",
                        "inference",
                        "data",
                        "core",
                    )
                    for role in unavailable:
                        outage.enter_context(topology.pause(role))
                    for role in unavailable:
                        with pytest.raises(httpx.TransportError):
                            browser.get(topology.origin(role))
                    with pytest.raises(httpx.TransportError):
                        post(message_path, mutation, worker, operation)
                    assert h.read("SELECT to_regclass('audit.event')") == [(None,)]
                    outcome = {
                        "transport": "connection_failed",
                        "stopped_listeners": unavailable,
                        "canonical_audit_available": False,
                    }
                continuity = (
                    help_service.assert_identity_down()
                    if fault == "identity"
                    else {**help_service.probe(locale), **help_service.verify_static()}
                )
                assert effect_counts() == before
            assert effect_counts() == before
            assert message_permits() == permits
            committed = h.read(
                "SELECT d.state, a.decision FROM durable.operation d "
                "JOIN audit.event a ON d.canonical_audit_id=a.event_id WHERE d.key=%s",
                (operation,),
            )
            assert committed == ([("committed", "PERMIT")] if fault == "model" else [])
            assert h.read(
                "SELECT count(*) FROM durable.operation WHERE key=%s",
                (operation,),
            ) == [(int(fault == "model"),)]
            recovery = read(message_session, participants[-1])
            assert recovery["service_phase"] == "human_controlled"
            if fault == "model":
                outcome["verified_live_recovery"] = measured_turn(assistance)
                assert outcome["verified_live_recovery"]["state"] == "awaiting_human"
            observations[fault] = {
                "observed": outcome,
                "help": continuity,
                "durable_protected_operation_count": len(committed),
                "check_and_recovery_ms": round((monotonic() - fault_start) * 1000, 3),
            }
        help_service.probe("fr-CA")
        assert (
            accepted(browser.get(core_url + f"/v1/training/scenarios/{scenario}", headers=trainer))[
                "state"
            ]
            == "completed"
        )
        assert_receiver_scope(
            browser,
            core_url,
            received["dispatch_id"],
            owner=receiver,
            other=other_receiver,
            worker=worker,
        )

        job_states = h.read(
            "SELECT state,count(*),count(result_digest) FROM assistance.inference_job "
            "GROUP BY state ORDER BY state"
        )
        assert job_states == [("completed", 3, 3), ("compute_unknown", 1, 0)]
        assert h.read("SELECT state FROM assistance.compute_slot ORDER BY state") == [
            ("compute_unknown",),
            ("free",),
        ]
        provider_observations = assistance.barrier.completed_calls
        assert len(provider_observations) == 3

        evidence = {
            "started_at_utc": started.isoformat(),
            "ended_at_utc": datetime.now(UTC).isoformat(),
            "model_digest": assistance.artifact_digest,
            "peak": peak,
            "warm_runtime": warm,
            "warm_bridge_responses": provider_observations,
            "peak_protected_read_ms": peak_read_ms,
            "faults": observations,
            "help_baseline": help_baseline,
            "help_at_peak": help_at_peak,
            "help_durable": help_service.summary(),
            "offline_evaluation_state": replay_state,
            "receiver_state": received["state"],
            "durable_counts": effect_counts(),
            "durable_inference_jobs": [
                {"state": state, "jobs": count, "result_digests": digests}
                for state, count, digests in job_states
            ],
            "scope": (
                "Synthetic actors and fixture channels with owned TLS listener faults "
                "and read-only live Qwen"
            ),
        }
    with Path(os.environ["CARE_LINK_IMP10_COMBINED_EVIDENCE"]).open("x") as file:
        json.dump(evidence, file, indent=2, sort_keys=True)
        file.write("\n")
