"""Exercise the live bridge and gateway with an isolated signed qualification release."""

import argparse
import hashlib
import json
import os
import ssl
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from uuid import uuid4

import httpx
from care_link_inference import THREATS, BrokerRequest, HttpBridge, HttpTokenCounter
from care_link_inference.admission import InferenceDenied
from care_link_inference.gateway import InferenceGateway
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from tests.evaluation.qwen_local import source
from tools.imp06_runtime.bridge import bridge_application
from tools.imp06_runtime.release_custody import ReleaseCustody, ReleaseTrust
from tools.imp06_runtime.release_custody_records import (
    EVALUATORS,
    EvaluationEvidence,
    EvaluatorAck,
    EvaluatorBoot,
    ModelIdentity,
    ReleaseArtifact,
    ReleaseObservation,
    digest,
)


class ObservedCompletions:
    """Receipt-only ledger double. PostgreSQL durability is qualified separately."""

    def __init__(self) -> None:
        self.completions: list[bool] = []

    def reserve(self, _record: dict[str, object]) -> str:
        return "fixture-slot"

    def mark_unknown(self, _job_id: str) -> None:
        raise RuntimeError("provider completion unverified")

    def complete(self, _job_id: str, _digest: str, *, deliverable: bool) -> bool:
        self.completions.append(deliverable)
        return deliverable


def load_evidence(path: Path) -> dict[str, object]:
    value = cast(dict[str, object], json.loads(path.read_text()))
    if value.get("state") != "passed":
        raise ValueError("passing exact evidence required")
    return value


def stage(directory: Path, artifact: ReleaseArtifact) -> tuple[ReleaseCustody, int, dict[str, str]]:
    signer = Ed25519PrivateKey.generate()
    evaluators = {role: Ed25519PrivateKey.generate() for role in EVALUATORS}
    trust = ReleaseTrust(
        target=artifact.target,
        purpose="qualification",
        artifact_keys={artifact.signer: signer.public_key()},
        evaluator_keys={role: key.public_key() for role, key in evaluators.items()},
    )
    custody = ReleaseCustody(directory / "release.sqlite", trust=trust, owner_uid=os.geteuid())
    custody.initialize()
    activation = str(uuid4())
    epoch = custody.stage(
        artifact, signer.sign(artifact.signing_bytes()), activation_id=activation, expected_epoch=0
    )
    now = datetime.now(UTC)
    boots: dict[str, str] = {}
    for role, key in evaluators.items():
        boot = EvaluatorBoot(
            purpose="qualification",
            target=artifact.target,
            instance=role,
            boot_id=str(uuid4()),
            previous_boot_id=None,
        )
        custody.register_boot(boot, key.sign(boot.signing_bytes()))
        assert custody.prepare(artifact.observation).bundle_digest == artifact.bundle_digest
        boots[role] = boot.boot_id
        ack = EvaluatorAck(
            purpose="qualification",
            target=artifact.target,
            instance=role,
            boot_id=boot.boot_id,
            activation_id=activation,
            bundle_digest=artifact.bundle_digest,
            epoch=epoch,
            status="ready",
            issued_at=now.isoformat().replace("+00:00", "Z"),
            expires_at=(now + timedelta(minutes=4)).isoformat().replace("+00:00", "Z"),
        )
        custody.acknowledge(ack, key.sign(ack.signing_bytes()))
    custody.activate(expected_epoch=epoch)
    return custody, epoch, boots


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--model-index", required=True, type=Path)
    parser.add_argument("--token-file", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--image-id", required=True)
    args = parser.parse_args()
    directory: Path = args.evidence
    evaluated = load_evidence(directory / "authenticated-qwen.json")
    workload_path = directory / "qwen-final-workload.json"
    workload = load_evidence(workload_path)
    provenance = load_evidence(directory / "model-provenance.json")
    proof = cast(
        dict[str, object], cast(list[dict[str, object]], evaluated["cases"])[0]["token_proof"]
    )
    assert (
        evaluated["artifact_digest"] == workload["artifact_digest"] == provenance["artifact_digest"]
    )
    for field in ("tokenizer_digest", "template_digest"):
        assert proof[field] == workload[field]
    sources = cast(dict[str, str], evaluated["source_sha256"])
    for path, expected in sources.items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected, path
    instruction = Path("config/demo/assistance/prompts/worker-summary-v2.txt").read_text()
    instruction_source = {
        **source("selection-instruction", instruction, "template"),
        "verification": "verified",
    }
    instruction_item = {
        "source": instruction_source,
        "label": "approved_instruction",
        "text": instruction,
        "critical": True,
    }
    cases = cast(list[dict[str, object]], evaluated["cases"])
    evaluation = EvaluationEvidence(
        canonical_schema_digest=str(evaluated["canonical_schema_sha256"]),
        wire_schema_digest=str(evaluated["wire_schema_sha256"]),
        prompt_digest=digest([instruction_item]),
        english_digest=digest([case for case in cases if case["language"] == "en-CA"]),
        french_digest=digest([case for case in cases if case["language"] == "fr-CA"]),
        grounding_digest=digest(cases),
        adversarial_digest=digest([case for case in cases if case["injection"]]),
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
        image_digest=args.image_id.removeprefix("sha256:"),
        catalog_digest=str(evaluated["knowledge_catalog_sha256"]),
        evaluation_digest=digest(evaluation.model_dump(mode="json")),
    )
    artifact = ReleaseArtifact(
        purpose="qualification",
        target="qual-imp06-signed-bridge",
        change_class="C2",
        proposer="synthetic-test-runner",
        signer="disposable-release-signer",
        evidence=evaluation,
        observation=observation,
        instruction_source=instruction_source,
        instruction=instruction,
    )
    with TemporaryDirectory(prefix="care-link-imp06-signed-bridge.") as temporary:
        custody, epoch, boots = stage(Path(temporary), artifact)
        bridge_bindings = custody.qualification_bindings(
            observation, instance="host-inference-bridge", boot_id=boots["host-inference-bridge"]
        )
        inference_bindings = custody.qualification_bindings(
            observation, instance="inference", boot_id=boots["inference"]
        )
        manifest = inference_bindings.manifest
        assert manifest is not None
        in_process_identity = str(uuid4())
        app = bridge_application(
            bridge_bindings,
            lambda request, role: role == "inference"
            and request.headers.get("X-Fixture-Identity") == in_process_identity,
            artifact_directory=args.artifact_dir,
            model_index=args.model_index,
            lmstudio_token_file=args.token_file,
        )
        ledger = ObservedCompletions()
        revoke = False
        restricted_epoch: int | None = None
        with TestClient(app) as client:

            def relay(request: httpx.Request) -> httpx.Response:
                nonlocal restricted_epoch
                response = client.post(
                    request.url.path,
                    content=request.content,
                    headers={"X-Fixture-Identity": in_process_identity},
                )
                if revoke and request.url.path.endswith("/execute") and response.status_code == 200:
                    restricted_epoch = custody.disable(expected_epoch=epoch)
                return httpx.Response(response.status_code, content=response.content)

            tls = ssl.create_default_context()
            bridge = HttpBridge(tls, transport=httpx.MockTransport(relay))
            counter = HttpTokenCounter(tls, manifest, transport=httpx.MockTransport(relay))
            gateway = InferenceGateway(
                manifest,
                release_verified=inference_bindings.current,
                counter=counter,
                bridge=bridge,
                ledger=ledger,
                broker_current=lambda _request: True,
            )
            report = "A fictional adult wants to discuss treatment preferences and recovery goals."
            report_item = {
                "source": source("signed-fixture-report", report, "assertion"),
                "label": "untrusted_report",
                "text": report,
                "critical": True,
            }

            def request() -> BrokerRequest:
                return BrokerRequest(
                    str(uuid4()),
                    str(uuid4()),
                    "1",
                    "1",
                    "worker_summary",
                    (instruction_item, report_item),
                    frozenset(),
                    datetime.now(UTC) + timedelta(seconds=25),
                    str(uuid4()),
                )

            try:
                missing_peer = client.post("/internal/v1/inference/tokenize", json={}).status_code
                completed = gateway.execute("broker", request())
                assert completed.state == "completed" and completed.proposal is not None
                assert completed.proposal["candidate_text"] == report
                revoke = True
                fenced = gateway.execute("broker", request())
                assert fenced.state == "cancelled" and fenced.proposal is None
                try:
                    gateway.execute("broker", request())
                except InferenceDenied as error:
                    assert error.reason == "model_evidence_unverified"
                else:
                    raise RuntimeError("restricted release admitted new work")
            finally:
                counter.close()
                bridge.close()
        assert missing_peer == 403 and restricted_epoch == epoch + 1
        assert ledger.completions == [True, False]
    receipt = {
        "state": "passed",
        "recorded_at": datetime.now(UTC).isoformat(),
        "bundle_digest": artifact.bundle_digest,
        "candidate_image_id": args.image_id,
        "activated_epoch": epoch,
        "restricted_epoch": restricted_epoch,
        "signed_fixture_acknowledgments": sorted(boots),
        "untrusted_asgi_request": missing_peer,
        "gateway_completed_exact_synthetic_excerpt": True,
        "gateway_discarded_in_flight_proposal_after_epoch_change": True,
        "new_work_after_disable": "denied",
        "authorization_scope": (
            "Ephemeral qualification ledger and evaluator keys, ASGI relay, "
            "and real authenticated LM Studio. Serving authorization is separate."
        ),
    }
    (directory / "signed-bridge.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
