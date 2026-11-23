"""Connect the current bounded Runtime and inference roles over fixture HTTPS."""

import json
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Condition, Event
from time import monotonic
from uuid import uuid4

import httpx
from care_link_core.assistance import HttpAssistanceGateway
from care_link_core.assistance_broker import HttpCoordinator, InferenceBroker, TaskDelegationSigner
from care_link_core.assistance_broker.actors import ActorTasks, BoundTaskGateway
from care_link_core.assistance_broker.work import WorkQueue
from care_link_core.manual_envelopes import IdentityEvidencePort, SignedEnvelopeFactory
from care_link_data.app import SignedGatewaySecurity
from care_link_domain import Actor, ManualError, WorkloadPeer
from care_link_inference import (
    DataTransport,
    HttpBridge,
    HttpContextAuthority,
    HttpInferencePort,
    HttpJobLedger,
    HttpTokenCounter,
    InferenceGateway,
)
from care_link_inference import create_app as inference_app
from care_link_policy_input import DelegationVerifier
from care_link_runtime import HttpBrokerTransport, RuntimeClient
from care_link_runtime.worker import RuntimeWorker
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import Request

from services.data.tests.conftest import Harness
from services.data.tests.imp10_outage_listeners import RoleTopology
from tests.evaluation.qwen_combined_journey import release_artifact
from tests.evaluation.qwen_signed_bridge import stage
from tools.imp06_runtime.bridge import bridge_application
from tools.imp06_runtime.data import data_application
from tools.imp06_runtime.release_custody_records import digest
from tools.imp06_runtime.resources import load_knowledge_resources

Record = dict[str, object]
ROLE_HEADER = "X-Qualification-Role"


class Peers:
    """Private synthetic peer bindings used with the topology's server TLS."""

    def __init__(self) -> None:
        self._keys = {role: uuid4().hex for role in ("core", "data", "inference", "runtime")}

    def headers(self, role: str) -> dict[str, str]:
        return {ROLE_HEADER: self._keys[role]}

    def verify(self, request: Request, role: str) -> bool:
        from hmac import compare_digest

        key = self._keys.get(role)
        return key is not None and compare_digest(request.headers.get(ROLE_HEADER, ""), key)


class RoleTransport(httpx.BaseTransport):
    """Resolve one logical product DNS identity to its owned bound listener."""

    def __init__(self, topology: RoleTopology, target: str, peers: Peers, source: str) -> None:
        self.client = topology.client(headers=peers.headers(source))
        self.origin = httpx.URL(topology.origin(target))
        self.logical_host = target

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.scheme != "https" or url.host != self.logical_host or url.port != 8443:
            raise ValueError("Only the fixed role origin is admitted")
        target = self.origin.copy_with(raw_path=url.raw_path)
        headers = {key: value for key, value in request.headers.items() if key != "host"}
        forwarded = self.client.build_request(
            request.method,
            target,
            content=request.read(),
            headers=headers,
            extensions=request.extensions.copy(),
        )
        return self.client.send(forwarded, stream=True)

    def close(self) -> None:
        self.client.close()


class ComputeBarrier:
    """Hold actual requests immediately after their durable slot is reserved."""

    def __init__(self, bridge: HttpBridge) -> None:
        self.bridge = bridge
        self.condition = Condition()
        self.release = Event()
        self.entered = 0
        self.completed_calls: list[Record] = []

    def complete(self, payload: Record, deadline: datetime) -> bytes:
        with self.condition:
            self.entered += 1
            self.condition.notify_all()
        if not self.release.wait(20):
            raise TimeoutError("Fixture compute barrier expired")
        started = monotonic()
        raw = self.bridge.complete(payload, deadline)
        elapsed = round((monotonic() - started) * 1000, 3)
        usage = json.loads(raw)["usage"]
        with self.condition:
            self.completed_calls.append(
                {
                    "bridge_elapsed_ms": elapsed,
                    "prompt_tokens": usage["prompt_tokens"],
                    "completion_tokens": usage["completion_tokens"],
                }
            )
        return raw

    def wait(self, count: int) -> None:
        with self.condition:
            assert self.condition.wait_for(lambda: self.entered >= count, timeout=12)


@dataclass(frozen=True)
class Assistance:
    tasks: BoundTaskGateway
    queue: WorkQueue
    broker: InferenceBroker
    verify_runtime: Callable[[Request], WorkloadPeer]
    availability: Callable[[Actor], Record]
    worker: RuntimeWorker
    barrier: ComputeBarrier
    artifact_digest: str


def start_assistance(
    topology: RoleTopology,
    stack: ExitStack,
    h: Harness,
    tmp_path: Path,
    *,
    keys: Peers,
    core_key: Ed25519PrivateKey,
    identity: IdentityEvidencePort,
    delegations: DelegationVerifier,
    envelopes: SignedEnvelopeFactory,
    core_client: httpx.Client,
    peer: WorkloadPeer,
    model: dict[str, Path],
) -> Assistance:
    artifact = release_artifact()
    custody, _epoch, boots = stage(tmp_path, artifact)
    knowledge = load_knowledge_resources()

    def binding(role: str):
        return custody.qualification_bindings(
            artifact.observation, instance=role, boot_id=boots[role]
        )

    def current(candidate: WorkloadPeer) -> bool:
        return candidate == peer and binding("runtime").current()

    def verify_runtime(request: Request) -> WorkloadPeer:
        if not keys.verify(request, "runtime") or not current(peer):
            raise ManualError("assistance.runtime_denied", 403)
        return peer

    topology.start(
        "data",
        data_application(
            h.service,
            SignedGatewaySecurity(delegations, keys.verify),
            releases=binding("data"),
            delegations=delegations,
            verify=keys.verify,
            runtime_current=current,
            bridge_generation=digest({"boot": boots["host-inference-bridge"]}),
            knowledge=knowledge.catalog,
            knowledge_regions=knowledge.regions,
        ),
    )

    def bridge_factory():
        return bridge_application(binding("host-inference-bridge"), keys.verify, **model)

    topology.start("host-inference-bridge", bridge_factory(), restart_factory=bridge_factory)

    def transport(target: str, source: str) -> RoleTransport:
        return RoleTransport(topology, target, keys, source)

    tls = topology.trust
    data_io = DataTransport(tls, transport=transport("data", "inference"))
    stack.callback(data_io.close)
    contexts = HttpContextAuthority(data_io)
    inference = binding("inference")
    manifest = inference.manifest
    assert manifest is not None
    bridge = HttpBridge(tls, transport=transport("host-inference-bridge", "inference"))
    counter = HttpTokenCounter(
        tls, manifest, transport=transport("host-inference-bridge", "inference")
    )
    stack.callback(bridge.close)
    stack.callback(counter.close)
    barrier = ComputeBarrier(bridge)
    gateway = InferenceGateway(
        manifest,
        release_verified=inference.current,
        counter=counter,
        bridge=barrier,
        ledger=HttpJobLedger(data_io),
        broker_current=contexts.current,
    )
    topology.start("inference", inference_app(gateway, keys.verify, contexts.resolve))
    inference_port = HttpInferencePort(tls, transport=transport("inference", "core"))
    stack.callback(inference_port.close)

    data_origin = "https://data:8443"
    tasks = HttpAssistanceGateway(core_client, data_origin, envelopes)
    actors = ActorTasks()
    queue = WorkQueue(actors, tasks)
    commands = BoundTaskGateway(
        tasks, actors, enqueue=queue.enqueue, remove=queue.remove, knowledge=knowledge.catalog
    )
    releases = binding("core")
    broker = InferenceBroker(
        HttpCoordinator(core_client, TaskDelegationSigner(identity, core_key), tasks),
        inference_port,
        actor_for_task=actors.resolve,
        release=releases.release,
        work=queue.claim,
    )

    def availability(actor: Actor) -> Record:
        enabled = actor.role == "worker" and releases.current()
        return {
            "available": enabled,
            "functions": ["worker_summary"] if enabled else [],
            "reason": None if enabled else "assistance.function_disabled",
        }

    runtime = HttpBrokerTransport(tls, transport=transport("core", "runtime"))
    stack.callback(runtime.close)
    return Assistance(
        commands,
        queue,
        broker,
        verify_runtime,
        availability,
        RuntimeWorker(RuntimeClient(runtime), runtime.poll_work),
        barrier,
        manifest.artifact_digest,
    )


def measured_turn(assistance: Assistance):
    started = monotonic()
    outcome = assistance.worker.run_once()
    assert outcome is not None
    return {
        "state": outcome["state"],
        "elapsed_ms": round((monotonic() - started) * 1000, 3),
        "safe_reason": outcome.get("safe_reason"),
    }
