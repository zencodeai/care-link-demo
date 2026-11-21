"""Opt-in Core, Runtime, Data, Inference and bridge journey on disposable TLS PostgreSQL."""

import base64
import hashlib
import hmac
import json
import os
import ssl
from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import cast
from uuid import uuid4

import httpx
from care_link_core.assistance import HttpAssistanceGateway, attach_assistance_routes
from care_link_core.assistance_broker import (
    HttpCoordinator,
    InferenceBroker,
    TaskDelegationSigner,
    attach_broker_routes,
)
from care_link_core.assistance_broker.actors import ActorTasks, BoundTaskGateway
from care_link_core.assistance_broker.work import WorkQueue
from care_link_core.manual_envelopes import SignedEnvelopeFactory
from care_link_data.app import SignedGatewaySecurity
from care_link_data.values import stamp
from care_link_domain import Actor, ManualError, WorkloadPeer
from care_link_inference import (
    THREATS,
    DataTransport,
    HttpBridge,
    HttpContextAuthority,
    HttpInferencePort,
    HttpJobLedger,
    HttpTokenCounter,
    InferenceGateway,
)
from care_link_inference import create_app as inference_routes
from care_link_inference_bridge import TokenReceipt
from care_link_inference_bridge import create_app as bridge_routes
from care_link_inference_bridge.tokenization import content_digest
from care_link_policy_input import DelegationVerifier
from care_link_runtime import HttpBrokerTransport, RuntimeClient
from care_link_runtime.worker import RuntimeWorker
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from services.data.tests import test_assistance, test_assistance_knowledge
from services.data.tests.conftest import Harness
from tests.evaluation.qwen_local import source
from tests.evaluation.qwen_signed_bridge import load_evidence, stage
from tools.imp06_runtime.bridge import bridge_application
from tools.imp06_runtime.data import data_application
from tools.imp06_runtime.release_custody_records import (
    EvaluationEvidence,
    ModelIdentity,
    ReleaseArtifact,
    ReleaseObservation,
    digest,
)
from tools.imp06_runtime.releases import ReleaseBindings
from tools.imp06_runtime.resources import load_knowledge_resources

Record = dict[str, object]
ROOT = Path(__file__).resolve().parents[2]
SLICE = ROOT / "doc/IMP/slices/IMP-06-bounded-ai-assistance/sessions"
BASELINE = SLICE / "005-deployment-release-qualification/evidence"
ROLE_HEADER = "X-Qualification-Role"
MATCHED_NEED = "Fictional needs"
MANUAL_REPLY = "I recorded the fictional needs for the next worker to review."
pytest_plugins = ("services.data.tests.conftest",)

review_body = cast(
    Callable[[Record, str], Record],
    test_assistance.review_body,  # pyright: ignore[reportUnknownMemberType]
)
knowledge_case = cast(
    Callable[[Harness], tuple[object, Record, WorkloadPeer]],
    test_assistance_knowledge.knowledge_case,  # pyright: ignore[reportUnknownMemberType]
)


def release_artifact() -> ReleaseArtifact:
    evaluated = load_evidence(BASELINE / "authenticated-qwen.json")
    workload_path = BASELINE / "qwen-final-workload.json"
    workload = load_evidence(workload_path)
    provenance = load_evidence(BASELINE / "model-provenance.json")
    image_path = os.environ.get("CARE_LINK_JOURNEY_IMAGE_RECEIPT")
    image = load_evidence(Path(image_path) if image_path else BASELINE / "image-smoke.json")
    cases = cast(list[Record], evaluated["cases"])
    proof = cast(Record, cases[0]["token_proof"])
    assert (
        evaluated["artifact_digest"] == workload["artifact_digest"] == provenance["artifact_digest"]
    )
    for field in ("tokenizer_digest", "template_digest"):
        assert proof[field] == workload[field]
    sources = cast(dict[str, str], evaluated["source_sha256"])
    if image_path:
        sources = {**sources, **cast(dict[str, str], image["source_sha256"])}
    for path, expected in sources.items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected, path
    instruction = (ROOT / "config/demo/assistance/prompts/worker-summary-v2.txt").read_text()
    reference = {
        **source("selection-instruction", instruction, "template"),
        "verification": "verified",
    }
    prompt = [
        {
            "source": reference,
            "label": "approved_instruction",
            "text": instruction,
            "critical": True,
        }
    ]
    evidence = EvaluationEvidence(
        canonical_schema_digest=str(evaluated["canonical_schema_sha256"]),
        wire_schema_digest=str(evaluated["wire_schema_sha256"]),
        prompt_digest=digest(prompt),
        english_digest=digest([c for c in cases if c["language"] == "en-CA"]),
        french_digest=digest([c for c in cases if c["language"] == "fr-CA"]),
        grounding_digest=digest(cases),
        adversarial_digest=digest([c for c in cases if c["injection"]]),
        latency_digest=hashlib.sha256(workload_path.read_bytes()).hexdigest(),
        threats=tuple(sorted(THREATS)),
        input_token_limit=cast(int, workload["input_token_limit"]),
    )
    observation = ReleaseObservation(
        model=ModelIdentity(
            artifact_digest=str(evaluated["artifact_digest"]),
            origin=str(provenance["origin"]),
            quantization=str(provenance["quantization"]),
            license=str(provenance["license"]),
            server_version=str(provenance["server_version"]),
            engine_version=str(provenance["engine_version"]),
            sdk_render_mode=str(evaluated["render_mode"]),
            tokenizer_digest=str(proof["tokenizer_digest"]),
            template_digest=str(proof["template_digest"]),
        ),
        code_digest=digest(sources),
        image_digest=str(image["image_id"]).removeprefix("sha256:"),
        catalog_digest=str(evaluated["knowledge_catalog_sha256"]),
        evaluation_digest=digest(evidence.model_dump(mode="json")),
    )
    return ReleaseArtifact(
        purpose="qualification",
        target="qual-imp06-combined-journey",
        change_class="C2",
        proposer="synthetic-test-runner",
        signer="disposable-release-signer",
        evidence=evidence,
        observation=observation,
        instruction_source=reference,
        instruction=instruction,
    )


class IdentityFixture:
    """Generate genuine request-bound evidence for a single synthetic worker."""

    def __init__(self, actor: Actor) -> None:
        self.actor, self.key = actor, Ed25519PrivateKey.generate()

    def evidence(
        self, actor: Actor, action: str, request_digest: str, nonce: str, resource: object
    ) -> Record:
        assert actor.account_id == self.actor.account_id
        now = datetime.now(UTC)
        value = {
            "id": actor.identity_evidence_id,
            "principal_id": actor.account_id,
            "role": actor.role,
            "identity_revision": str(actor.identity_revision),
            "role_revision": str(actor.role_revision),
            "action": action,
            "resource_id": resource,
            "request_digest": request_digest,
            "nonce": nonce,
            "verified_at": stamp(now),
            "expires_at": stamp(now + timedelta(seconds=0.95)),
            "kind": "human_identity",
        }
        from care_link_policy_input.opa import canonical

        signature = base64.urlsafe_b64encode(self.key.sign(canonical(value))).rstrip(b"=").decode()
        return {**value, "signature": signature}


class ProviderFixture:
    """Deterministic application-path regression, never counted as model evidence."""

    def __init__(self, releases: ReleaseBindings) -> None:
        self.model = releases.manifest
        assert self.model is not None

    def count(self, messages: Sequence[Mapping[str, str]]) -> TokenReceipt:
        model = self.model
        assert model is not None
        return TokenReceipt(
            model.model_identifier,
            model.loaded_model_id,
            model.artifact_digest,
            model.tokenizer_digest,
            model.template_digest,
            model.model_window,
            128,
            0,
            content_digest(messages),
        )

    def complete(self, payload: Record, deadline: datetime) -> bytes:
        assert deadline > datetime.now(UTC)
        return json.dumps(
            {
                "model": payload["model"],
                "choices": [
                    {"finish_reason": "stop", "message": {"content": '{"selected_indices":[0]}'}}
                ],
                "usage": {"prompt_tokens": 128, "completion_tokens": 8},
            }
        ).encode()


def relay(target: TestClient, host: str, key: str, trace: list[Record]) -> httpx.MockTransport:
    def send(request: httpx.Request) -> httpx.Response:
        assert request.url.scheme == "https" and request.url.host == host
        headers = dict(request.headers)
        headers[ROLE_HEADER] = key
        result = target.request(
            request.method, request.url.path, headers=headers, content=request.content
        )
        step: Record = {"target": host, "path": request.url.path, "status": result.status_code}
        if result.status_code >= 400 and result.headers.get("content-type") == "application/json":
            step["error"] = result.json().get("message_key", result.json().get("key"))
        if host == "inference" and result.status_code == 200:
            receipt = cast(Record, result.json())
            step.update(
                state=receipt["state"],
                input_tokens=receipt["input_tokens"],
                output_tokens=receipt["output_tokens"],
            )
        trace.append(step)
        return httpx.Response(result.status_code, headers=result.headers, content=result.content)

    return httpx.MockTransport(send)


def record_matched_need(harness: Harness, task_command: Record) -> str:
    session_id = str(cast(Record, task_command["binding"])["session_id"])
    state = harness.service.session_read(harness.participant, session_id)
    harness.service.message_send(
        harness.participant,
        str(uuid4()),
        {
            "expected_revision": state["revision"],
            "expected_control_epoch": state["control_epoch"],
            "text": MATCHED_NEED,
            "accepted_draft_id": None,
        },
        session_id,
    )
    task_command["expected_revision"] = harness.service.session_read(harness.worker, session_id)[
        "revision"
    ]
    return session_id


def complete_manual_followthrough(harness: Harness, session_id: str) -> Record:
    began = monotonic()
    before = harness.service.messages_read(harness.worker, session_id)
    inputs = cast(list[Record], before["items"])
    assert [(item["kind"], item["text"]) for item in inputs] == [("participant", MATCHED_NEED)]
    state = harness.service.session_read(harness.worker, session_id)
    assert state["service_phase"] == "human_controlled"
    reply = harness.service.message_send(
        harness.worker,
        str(uuid4()),
        {
            "expected_revision": state["revision"],
            "expected_control_epoch": state["control_epoch"],
            "text": MANUAL_REPLY,
            "accepted_draft_id": None,
        },
        session_id,
    )
    delivered = harness.service.messages_read(harness.participant, session_id)
    items = cast(list[Record], delivered["items"])
    assert len(items) == 2 and items[1]["id"] == reply["id"]
    assert items[1]["kind"] == "human_authored" and items[1]["text"] == MANUAL_REPLY
    return {
        "source_read": "exact_participant_report",
        "manual_receipt": "visible_to_participant",
        "elapsed_seconds": round(monotonic() - began, 3),
    }


def test_worker_summary_combined_qualification(harness: Harness, tmp_path: Path) -> None:
    provider = os.environ.get("CARE_LINK_JOURNEY_PROVIDER", "fixture")
    assert provider in {"fixture", "live"}
    artifact = release_artifact()
    resources = load_knowledge_resources()
    assert artifact.observation.catalog_digest == resources.catalog.digest
    _manual_coordinator, baseline_command, _manual_peer = knowledge_case(harness)
    baseline_sid = record_matched_need(harness, baseline_command)
    actor_only = complete_manual_followthrough(harness, baseline_sid)
    assert harness.read("SELECT count(*) FROM assistance.inference_job")[0][0] == 0
    assert harness.read("SELECT count(*) FROM assistance.draft")[0][0] == 0
    actor_only.update(inference_jobs=0, drafts=0)
    custody, epoch, boots = stage(tmp_path, artifact)

    def binding(role: str) -> ReleaseBindings:
        return custody.qualification_bindings(
            artifact.observation, instance=role, boot_id=boots[role]
        )

    _coordinator, task_command, peer = knowledge_case(harness)
    assisted_sid = record_matched_need(harness, task_command)
    assert assisted_sid != baseline_sid
    ids = {role: str(uuid4()) for role in ("core", "runtime", "inference", "browser")}

    def verify(request: Request, role: str) -> bool:
        return hmac.compare_digest(request.headers.get(ROLE_HEADER, ""), ids[role])

    def current_peer(candidate: WorkloadPeer) -> bool:
        return candidate == peer and binding("runtime").current()

    def runtime_auth(request: Request) -> WorkloadPeer:
        if not verify(request, "runtime") or not current_peer(peer):
            raise ManualError("assistance.runtime_denied", 403)
        return peer

    async def actor_auth(
        request: Request, *, mutation: bool = False, require_view: bool = True
    ) -> Actor:
        if not verify(request, "browser"):
            raise ManualError("manual.identity_required", 403)
        return harness.authority.current(harness.worker)

    core_key = Ed25519PrivateKey.generate()
    identity = IdentityFixture(harness.worker)
    delegations = DelegationVerifier(
        core_key.public_key(),
        identity.key.public_key(),
        lambda _evidence: harness.authority.current(harness.worker),
    )
    data_app = data_application(
        harness.service,
        SignedGatewaySecurity(delegations, verify),
        releases=binding("data"),
        delegations=delegations,
        verify=verify,
        runtime_current=current_peer,
        bridge_generation=digest({"boot": boots["host-inference-bridge"]}),
        knowledge=resources.catalog,
        knowledge_regions=resources.regions,
    )
    bridge_binding = binding("host-inference-bridge")
    if provider == "live":
        bridge_app = bridge_application(
            bridge_binding,
            verify,
            artifact_directory=Path(os.environ["CARE_LINK_JOURNEY_MODEL_DIR"]),
            model_index=Path(os.environ["CARE_LINK_JOURNEY_MODEL_INDEX"]),
            lmstudio_token_file=Path(os.environ["CARE_LINK_JOURNEY_TOKEN_FILE"]),
        )
    else:
        delegate = ProviderFixture(bridge_binding)
        bridge_app = bridge_routes(delegate, verify, counter=delegate)

    timeline: list[Record] = []
    statuses: dict[str, object] = {}
    tls = ssl.create_default_context()
    began = monotonic()
    with ExitStack() as stack:
        data = stack.enter_context(TestClient(data_app))
        host = stack.enter_context(TestClient(bridge_app))
        data_io = DataTransport(tls, transport=relay(data, "data", ids["inference"], timeline))
        stack.callback(data_io.close)
        contexts = HttpContextAuthority(data_io)
        inference = binding("inference")
        manifest = inference.manifest
        assert manifest is not None
        bridge = HttpBridge(
            tls, transport=relay(host, "host-inference-bridge", ids["inference"], timeline)
        )
        counter = HttpTokenCounter(
            tls,
            manifest,
            transport=relay(host, "host-inference-bridge", ids["inference"], timeline),
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
        core_data = stack.enter_context(
            httpx.Client(transport=relay(data, "data", ids["core"], timeline), trust_env=False)
        )
        envelopes = SignedEnvelopeFactory(
            core_data, "https://data:8443", identity, harness.policy, core_key
        )
        tasks = HttpAssistanceGateway(core_data, "https://data:8443", envelopes)
        actors = ActorTasks()
        work = WorkQueue(actors, tasks)
        commands = BoundTaskGateway(
            tasks, actors, enqueue=work.enqueue, remove=work.remove, knowledge=resources.catalog
        )
        core_release = binding("core")
        broker = InferenceBroker(
            HttpCoordinator(core_data, TaskDelegationSigner(identity, core_key), tasks),
            inference_port,
            actor_for_task=actors.resolve,
            release=core_release.release,
            work=work.claim,
        )
        core = FastAPI()

        async def handle_error(_request: Request, error: Exception) -> JSONResponse:
            assert isinstance(error, ManualError)
            return JSONResponse({"key": error.code}, status_code=error.status)

        core.add_exception_handler(ManualError, handle_error)

        def availability(actor: Actor) -> Record:
            enabled = actor.role == "worker" and core_release.current()
            return {
                "available": enabled,
                "functions": ["worker_summary"] if enabled else [],
                "reason": None if enabled else "assistance.function_disabled",
            }

        attach_assistance_routes(core, commands, actor_auth, availability)
        attach_broker_routes(core, broker, runtime_auth)
        service = stack.enter_context(TestClient(core))
        workforce = {ROLE_HEADER: ids["browser"]}

        def get(path: str) -> Record:
            response = service.get(path, headers=workforce)
            assert response.status_code == 200, (response.json(), timeline)
            return cast(Record, response.json())

        def post(path: str, body: Record) -> Record:
            response = service.post(
                path, json=body, headers={**workforce, "Idempotency-Key": str(uuid4())}
            )
            assert response.status_code == 200, (response.json(), timeline)
            return cast(Record, response.json())

        assert get("/v1/assistance")["available"] is True
        assert service.post("/internal/v1/broker/work", json={}).status_code == 403
        assert inference_client.post("/internal/v1/inference/jobs", json={}).status_code == 403
        assert (
            data.post("/internal/v1/data/assistance/inference/current", json={}).status_code == 403
        )
        assert host.post("/internal/v1/inference/tokenize", json={}).status_code == 403
        task = post("/v1/tasks", task_command)
        assert task["state"] == "scoped"
        transport = relay(service, "core", ids["runtime"], timeline)
        observations: list[Record] = []

        def runtime_request(request: httpx.Request) -> httpx.Response:
            response = transport.handle_request(request)
            if response.status_code == 200 and request.url.path.endswith("/lease"):
                lease = cast(Record, response.json())
                observation = runtime_transport.invoke(
                    "tool_invoke",
                    {
                        "task_id": lease["task_id"],
                        "step_id": lease["step_id"],
                        "fence": lease["fence"],
                        "expected_task_revision": lease["task_revision"],
                        "invocation_id": str(uuid4()),
                        "arguments": {
                            "tool": "protocol_read",
                            "artifact_digest": resources.catalog.digest,
                            "section_id": "shared-goals",
                            "locale": "en-CA",
                        },
                    },
                )
                outcome = cast(Record, observation["result"])
                sources = cast(list[Record], observation["sources"])
                assert outcome["kind"] == "success" and observation["taint"] == "untrusted"
                assert [item["kind"] for item in sources] == ["protocol"]
                observations.append({"tool": "protocol_read", "taint": "untrusted", "sources": 1})
            return response

        runtime_transport = HttpBrokerTransport(tls, transport=httpx.MockTransport(runtime_request))
        stack.callback(runtime_transport.close)
        worker = RuntimeWorker(RuntimeClient(runtime_transport), runtime_transport.poll_work)
        try:
            result = worker.run_once()
        except httpx.HTTPStatusError as error:
            raise AssertionError(
                (error.response.status_code, error.response.json(), timeline)
            ) from error
        assert result is not None and result.get("state") == "awaiting_human", (result, timeline)
        assert worker.run_once() is None
        assert len(observations) == 1 and result["tools_used"] == 1
        context = get(f"/v1/tasks/{task['id']}/context")
        draft = get(f"/v1/drafts/{context['draft_id']}")
        assert json.dumps({"kind": "text", "text": "Fictional needs"}, sort_keys=True) in (
            str(draft["text"]).splitlines()
        )
        refs = cast(list[Record], draft["sources"])
        assert sum(ref["kind"] == "assertion" for ref in refs) == 1
        assert all(ref["kind"] in {"assertion", "protocol"} for ref in refs)
        review_path = f"/v1/drafts/{draft['id']}/review"
        edit_body = review_body(draft, "reject")
        edit_body.update(decision="edit", edited_text="Worker edit of the fictional needs.")
        post(review_path, edit_body)
        revised_draft = get(f"/v1/drafts/{draft['id']}")
        assert revised_draft["payload_digest"] != draft["payload_digest"]
        before_stale = len(timeline)
        stale = service.post(
            review_path,
            json=review_body(draft, "accept"),
            headers={**workforce, "Idempotency-Key": str(uuid4())},
        )
        assert stale.status_code == 409, (stale.json(), timeline[before_stale:])
        assert any(
            step.get("error") == "assistance.stale_review" for step in timeline[before_stale:]
        ), timeline[before_stale:]
        assert get(f"/v1/drafts/{draft['id']}")["payload_digest"] == revised_draft["payload_digest"]
        review = post(review_path, review_body(revised_draft, "reject"))
        assert review["decision"] == "reject"
        assert get(f"/v1/drafts/{draft['id']}")["state"] == "rejected"
        assert get(f"/v1/tasks/{task['id']}")["state"] == "completed"

        durable = harness.read(
            "SELECT state,model_digest,result_digest FROM assistance.inference_job "
            "WHERE task_id=%s",
            (task["id"],),
        )
        assert len(durable) == 1 and durable[0][:2] == ("completed", manifest.artifact_digest)
        assert isinstance(durable[0][2], str) and len(durable[0][2]) == 64
        assert harness.read("SELECT state FROM assistance.compute_slot ORDER BY id") == [
            ("free",),
            ("free",),
        ]
        assert harness.read("SELECT count(*) FROM assistance.draft")[0][0] == 1
        assert harness.read("SELECT count(*) FROM referral.dispatch")[0][0] == 0
        stored_draft = cast(Record, harness.read("SELECT body FROM assistance.draft")[0][0])
        assert stored_draft.keys() == {"ciphertext"}
        inference_outcomes = [
            {name: item[name] for name in ("state", "input_tokens", "output_tokens")}
            for item in timeline
            if item["target"] == "inference" and item["status"] == 200
        ]
        assert len(inference_outcomes) == 1
        assert inference_outcomes[0]["state"] == "completed"
        statuses.update(
            task="completed", durable_inference_job="completed", draft="rejected", free_slots=2
        )
        restricted = custody.disable(expected_epoch=epoch)
        assert get("/v1/assistance")["available"] is False
        session_id = str(cast(Record, task["scope"])["session_id"])
        assert harness.service.session_read(harness.worker, session_id)["id"] == session_id
        assert not core_release.current()
        assisted = complete_manual_followthrough(harness, assisted_sid)
        assert assisted["manual_receipt"] == actor_only["manual_receipt"]
        assisted.update(inference_jobs=1, drafts=1, exact_stale_review_denied=True)
        statuses.update(
            manual_session="human_authored_followthrough_committed_after_disable",
            referral_dispatch_rows=0,
        )

    destination = os.environ.get("CARE_LINK_JOURNEY_EVIDENCE")
    if destination:
        report = {
            "state": "passed",
            "recorded_at": stamp(datetime.now(UTC)),
            "provider": provider,
            "fixture_release_only": True,
            "bundle_digest": artifact.bundle_digest,
            "activated_epoch": epoch,
            "restricted_epoch": restricted,
            "matched_comparison": {"actor_only": actor_only, "assisted": assisted},
            "bounded_observations": observations,
            "elapsed_seconds": round(monotonic() - began, 3),
            "asserted_states": statuses,
            "inference_outcomes": inference_outcomes,
            "successful_role_hops": sorted(
                {
                    str(step["target"])
                    + " "
                    + "/".join(
                        "{id}" if len(segment) == 36 else segment
                        for segment in str(step["path"]).split("/")
                    )
                    for step in timeline
                    if step["status"] == 200
                }
            ),
            "boundaries": [
                "Signed fixture identity and qualification release keys.",
                "Fixture ASGI role authentication and fixed-origin relay.",
                "Fixture identity, channel, PDP and journal. Real TLS PostgreSQL and app state.",
            ],
        }
        Path(destination).write_text(json.dumps(report, indent=2) + "\n")
