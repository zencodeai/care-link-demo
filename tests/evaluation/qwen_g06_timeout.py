"""Observe one owned late inference through the fixed bridge and durable Data ledger."""

import hashlib
import hmac
import json
import os
import ssl
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from time import monotonic
from typing import cast
from uuid import uuid4

import httpx
import pytest
from care_link_core.assistance_broker import InferenceBroker
from care_link_data import (
    AssistanceCoordinator,
    StoredInferenceAuthority,
    attach_inference_ledger_gateway,
)
from care_link_data.assistance_jobs import PostgresJobLedger
from care_link_inference import (
    DataTransport,
    HttpBridge,
    HttpContextAuthority,
    HttpInferencePort,
    HttpJobLedger,
    HttpTokenCounter,
    InferenceGateway,
)
from care_link_inference import create_app as inference_routes
from care_link_inference.context import canonical
from care_link_inference.gateway import provider_envelope
from care_link_inference_bridge import LocalModelBridge
from care_link_inference_bridge import create_app as bridge_routes
from care_link_inference_bridge.bridge import ENDPOINT, ORIGIN
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from services.data.tests.conftest import Harness
from tests.evaluation.qwen_combined_journey import (
    ROLE_HEADER,
    ProviderFixture,
    Record,
    knowledge_case,
    relay,
    release_artifact,
    stage,
)
from tools.imp06_runtime import bridge as bridge_module
from tools.imp06_runtime.releases import ReleaseBindings

pytest_plugins = ("services.data.tests.conftest",)
READ_WINDOW_SECONDS = 0.025


class ProviderObservation:
    def __init__(self) -> None:
        self.sent = Event()
        self.sent_at: float | None = None
        self.received_at: float | None = None
        self.request_digest: str | None = None

    def dispatch(self, digest: str) -> None:
        assert self.request_digest is None
        self.request_digest = digest
        self.sent_at = monotonic()
        self.sent.set()


class ObservedProviderWire(httpx.BaseTransport):
    """Keep production HTTP settings and observe only the bounded request timeline."""

    def __init__(self, observation: ProviderObservation) -> None:
        self.observation = observation
        self.transport = httpx.HTTPTransport(
            trust_env=False, retries=0, limits=httpx.Limits(max_connections=2)
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and str(request.url) == ORIGIN + "/api/v1/models":
            return self.transport.handle_request(request)
        assert request.method == "POST" and str(request.url) == ENDPOINT
        digest = hashlib.sha256(canonical(json.loads(request.content)).encode()).hexdigest()

        def trace(event: str, _info: dict[str, object]) -> None:
            if event == "http11.send_request_body.complete":
                self.observation.dispatch(digest)
            elif event == "http11.receive_response_body.complete":
                self.observation.received_at = monotonic()

        request.extensions["trace"] = trace
        return self.transport.handle_request(request)

    def close(self) -> None:
        self.transport.close()


class HeldFixtureProvider(ProviderFixture):
    def __init__(
        self,
        releases: ReleaseBindings,
        observation: ProviderObservation,
        allow_completion: Event,
    ) -> None:
        super().__init__(releases)
        self.observation = observation
        self.allow_completion = allow_completion

    def complete(self, payload: Record, deadline: datetime) -> bytes:
        self.observation.dispatch(hashlib.sha256(canonical(payload).encode()).hexdigest())
        assert self.allow_completion.wait(20)
        raw = super().complete(payload, deadline)
        self.observation.received_at = monotonic()
        return raw


class DownstreamReadTimeout(httpx.BaseTransport):
    """Drop the gateway-facing wait while the one upstream generation remains connected."""

    def __init__(
        self,
        transport: httpx.BaseTransport,
        executor: ThreadPoolExecutor,
        observation: ProviderObservation,
    ) -> None:
        self.transport = transport
        self.executor = executor
        self.observation = observation
        self.completion: Future[httpx.Response] | None = None
        self.timed_out_at: float | None = None

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/internal/v1/inference/execute"
        assert self.completion is None
        self.completion = self.executor.submit(self.transport.handle_request, request)
        assert self.observation.sent.wait(10), "provider request body was not observed"
        with pytest.raises(TimeoutError):
            self.completion.result(timeout=READ_WINDOW_SECONDS)
        self.timed_out_at = monotonic()
        assert self.observation.received_at is None
        raise httpx.ReadTimeout("qualification downstream read window expired", request=request)


def ledger_state(harness: Harness, job_id: str) -> list[tuple[object, ...]]:
    return harness.read(
        "SELECT job.state,slot.state,job.result_digest,job.request_digest "
        "FROM assistance.inference_job job JOIN assistance.compute_slot slot "
        "ON slot.id=job.slot_id AND slot.job_id=job.id "
        "WHERE job.id=%s AND slot.bridge_generation=job.bridge_generation",
        (job_id,),
    )


def assert_manual_message(harness: Harness, session_id: str) -> None:
    session = harness.service.session_read(harness.worker, session_id)
    message = harness.service.message_send(
        harness.worker,
        str(uuid4()),
        {
            "expected_revision": session["revision"],
            "expected_control_epoch": session["control_epoch"],
            "text": "Fictional manual support remains available.",
            "accepted_draft_id": None,
        },
        session_id,
    )
    items = cast(list[Record], harness.service.messages_read(harness.worker, session_id)["items"])
    assert message["kind"] == "human_authored"
    assert any(item["id"] == message["id"] for item in items)


def test_timeout_holds_real_slot_and_fences_late_provider_response(
    harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mode = os.environ.get("CARE_LINK_G06_TIMEOUT_PROVIDER", "fixture")
    assert mode in {"fixture", "live"}
    artifact = release_artifact()
    custody, epoch, boots = stage(tmp_path, artifact)

    def binding(role: str) -> ReleaseBindings:
        return custody.qualification_bindings(
            artifact.observation, instance=role, boot_id=boots[role]
        )

    raw_coordinator, command, peer = knowledge_case(harness)
    coordinator = cast(AssistanceCoordinator, raw_coordinator)
    task = coordinator.task_create(harness.worker, str(uuid4()), command)
    session_id = str(cast(Record, command["binding"])["session_id"])
    actor_for_task = coordinator.actor_for_task

    generation = hashlib.sha256(boots["host-inference-bridge"].encode()).hexdigest()
    ids = {role: str(uuid4()) for role in ("inference", "core")}

    def verify(request: Request, role: str) -> bool:
        return hmac.compare_digest(request.headers.get(ROLE_HEADER, ""), ids[role])

    data = FastAPI()
    data_binding = binding("data")
    durable = PostgresJobLedger(
        harness.service.store,
        current=lambda tx, job: data_binding.current()
        and coordinator.inference_current(tx, job, actor_for_task),
        bridge_generation=generation,
    )
    attach_inference_ledger_gateway(
        data,
        durable,
        verify,
        StoredInferenceAuthority(coordinator, actor_for_task, data_binding.records, generation),
    )
    observation = ProviderObservation()
    allow_completion = Event()
    bridge_binding = binding("host-inference-bridge")
    if mode == "live":

        def observed_bridge(*, api_token: str | None = None) -> LocalModelBridge:
            return LocalModelBridge(
                api_token=api_token, transport=ObservedProviderWire(observation)
            )

        monkeypatch.setattr(bridge_module, "LocalModelBridge", observed_bridge)
        host = bridge_module.bridge_application(
            bridge_binding,
            verify,
            artifact_directory=Path(os.environ["CARE_LINK_JOURNEY_MODEL_DIR"]),
            model_index=Path(os.environ["CARE_LINK_JOURNEY_MODEL_INDEX"]),
            lmstudio_token_file=Path(os.environ["CARE_LINK_JOURNEY_TOKEN_FILE"]),
        )
    else:
        provider = HeldFixtureProvider(bridge_binding, observation, allow_completion)
        host = bridge_routes(provider, verify, counter=provider)

    timeline: list[Record] = []
    tls = ssl.create_default_context()
    with ExitStack() as stack:
        data_client = stack.enter_context(TestClient(data))
        host_client = stack.enter_context(TestClient(host))
        executor = stack.enter_context(ThreadPoolExecutor(max_workers=1))
        stack.callback(allow_completion.set)
        data_io = DataTransport(
            tls, transport=relay(data_client, "data", ids["inference"], timeline)
        )
        stack.callback(data_io.close)
        contexts = HttpContextAuthority(data_io)
        inference = binding("inference")
        manifest = inference.manifest
        assert manifest is not None
        host_io = relay(host_client, "host-inference-bridge", ids["inference"], timeline)
        dropped = DownstreamReadTimeout(host_io, executor, observation)
        bridge = HttpBridge(tls, transport=dropped)
        counter = HttpTokenCounter(
            tls,
            manifest,
            transport=relay(host_client, "host-inference-bridge", ids["inference"], timeline),
        )
        stack.callback(bridge.close)
        stack.callback(counter.close)
        gateway = InferenceGateway(
            manifest,
            release_verified=inference.current,
            counter=counter,
            bridge=bridge,
            ledger=HttpJobLedger(data_io),
            broker_current=contexts.current,
        )
        inference_client = stack.enter_context(
            TestClient(inference_routes(gateway, verify, contexts.resolve))
        )
        inference_port = HttpInferencePort(
            tls, transport=relay(inference_client, "inference", ids["core"], timeline)
        )
        stack.callback(inference_port.close)
        broker = InferenceBroker(
            coordinator,
            inference_port,
            actor_for_task=actor_for_task,
            release=binding("core").release,
        )
        lease = broker.lease(
            str(task["id"]),
            {"expected_revision": task["revision"], "step_id": str(uuid4()), "fence": "0"},
            peer,
        )
        outcome = broker.infer(
            {
                "task_id": task["id"],
                "step_id": lease["step_id"],
                "fence": lease["fence"],
                "expected_task_revision": task["revision"],
            },
            peer,
        )
        assert (outcome["state"], outcome["safe_reason"], outcome["proposal"]) == (
            "compute_unknown",
            "provider_stop_unverified",
            None,
        )
        job = str(outcome["job_id"])
        assert dropped.timed_out_at is not None
        assert observation.sent_at is not None
        assert observation.request_digest is not None
        retained = [("compute_unknown", "compute_unknown", None, observation.request_digest)]
        assert ledger_state(harness, job) == retained
        held_at = monotonic()
        cancelled = coordinator.task_cancel(
            harness.worker, str(uuid4()), {"expected_revision": task["revision"]}, str(task["id"])
        )
        assert cancelled["state"] == "cancelled"
        assert_manual_message(harness, session_id)
        manual_at = monotonic()
        assert observation.received_at is None
        allow_completion.set()
        assert dropped.completion is not None
        late = dropped.completion.result(timeout=30)
        assert late.status_code == 200
        envelope = provider_envelope(late.content)
        assert envelope["model"] == manifest.loaded_model_id
        choices = cast(list[Record], envelope["choices"])
        assert len(choices) == 1 and choices[0]["finish_reason"] == "stop"
        usage = cast(Record, envelope["usage"])
        assert isinstance(usage["completion_tokens"], int) and usage["completion_tokens"] > 0
        assert observation.received_at is not None
        assert (
            observation.sent_at
            < dropped.timed_out_at
            < held_at
            < manual_at
            < observation.received_at
        )
        assert ledger_state(harness, job) == retained
        assert not broker.pending
        assert harness.read("SELECT count(*) FROM assistance.draft") == [(0,)]
        assert harness.read("SELECT count(*) FROM referral.dispatch") == [(0,)]
        assert not any(
            item["path"] == "/internal/v1/data/assistance/inference/complete" for item in timeline
        )
        restricted = custody.disable(expected_epoch=epoch)
        assert not inference.current()

    target = os.environ.get("CARE_LINK_G06_TIMEOUT_EVIDENCE")
    if target:
        receipt: Record = {
            "state": "passed",
            "recorded_at": datetime.now(UTC).isoformat(),
            "provider": mode,
            "qualification_bundle": artifact.bundle_digest,
            "candidate_image": "sha256:" + artifact.observation.image_digest,
            "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "provider_model": manifest.loaded_model_id,
            "request_digest_matches_held_job": True,
            "downstream_read_window_seconds": READ_WINDOW_SECONDS,
            "seconds_after_provider_request_body_sent": {
                "downstream_timeout": round(dropped.timed_out_at - observation.sent_at, 4),
                "durable_unknown": round(held_at - observation.sent_at, 4),
                "manual_message_confirmed": round(manual_at - observation.sent_at, 4),
                "original_provider_response_completed": round(
                    observation.received_at - observation.sent_at, 4
                ),
            },
            "provider_completion": {
                "http_status": late.status_code,
                "finish_reason": choices[0]["finish_reason"],
                "prompt_tokens": usage["prompt_tokens"],
                "completion_tokens": usage["completion_tokens"],
                "same_retained_request": True,
                "response_content_recorded": False,
            },
            "job": "compute_unknown",
            "compute_slot": "compute_unknown",
            "manual_message": "durable_human_authored",
            "proposal_returned": False,
            "draft_rows": 0,
            "referral_dispatch_rows": 0,
            "release_disabled_at_epoch": restricted,
            "boundaries": [
                "Test-only relay deadline. The original upstream connection remained open.",
                "No physical compute instrumentation or provider hard-stop attestation.",
                "In-process role relays, fixture authorities and real TLS PostgreSQL.",
                "The late reply reached only the observer. The application kept the slot held.",
            ],
        }
        with Path(target).open("x", encoding="utf-8") as output:
            json.dump(receipt, output, indent=2)
            output.write("\n")
