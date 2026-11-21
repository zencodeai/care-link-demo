"""Derive unsigned, target-bound serving bytes from pinned qualification evidence."""

import hashlib
import json
import re
from pathlib import Path
from typing import cast
from uuid import NAMESPACE_URL, uuid5

from care_link_inference import MODEL, THREATS
from pydantic import BaseModel, ConfigDict

from .release_custody_records import (
    ChangeClass,
    Digest,
    EvaluationEvidence,
    ModelIdentity,
    ReleaseArtifact,
    ReleaseObservation,
    digest,
)

_PROMPT = "config/demo/assistance/prompts/worker-summary-v2.txt"
_CATALOG = "config/demo/knowledge/catalog.json"
_REQUIRED_RECEIPTS = (
    "authenticated-qwen.json",
    "qwen-final-workload.json",
    "model-provenance.json",
    "image-smoke.json",
)


class FilePin(BaseModel):
    model_config = ConfigDict(strict=True)

    path: str
    sha256: Digest


class CandidateManifest(BaseModel):
    model_config = ConfigDict(strict=True)

    gate: str
    gate_state: str
    role_runtime_image: str
    source: list[FilePin]
    observations: list[FilePin]


class CaseObservation(BaseModel):
    model_config = ConfigDict(strict=True)

    state: str
    language: str
    injection: bool
    prompt_count_matches: bool
    exact_grounding: bool


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _verified_file(root: Path, pin: FilePin) -> bytes:
    located = root / pin.path
    path = located.resolve(strict=True)
    if Path(pin.path).is_absolute() or not path.is_relative_to(root) or not path.is_file():
        raise ValueError("candidate file outside the source tree")
    source = path.read_bytes()
    if _sha256(source) != pin.sha256:
        raise ValueError("candidate file differs from pinned evidence")
    return source


def _source_hashes(root: Path, pins: list[FilePin]) -> dict[str, str]:
    if not pins or len({pin.path for pin in pins}) != len(pins):
        raise ValueError("candidate source list must be nonempty and unique")
    for pin in pins:
        _verified_file(root, pin)
    return {pin.path: pin.sha256 for pin in pins}


def _passing_cases(records: list[dict[str, object]]) -> list[CaseObservation]:
    cases = [CaseObservation.model_validate(record) for record in records]
    if not cases or any(
        case.state != "passed" or not case.prompt_count_matches or not case.exact_grounding
        for case in cases
    ):
        raise ValueError("passing case-level token and grounding evidence required")
    return cases


def _object(payload: bytes) -> dict[str, object]:
    data: object = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("qualification observation must be an object")
    return cast(dict[str, object], data)


def prepare_candidate(
    root: Path,
    manifest_bytes: bytes,
    *,
    target: str,
    proposer: str,
    signer: str,
    change_class: ChangeClass,
) -> ReleaseArtifact:
    """Build bytes for human review and external signatures, without changing serving state."""
    if target.startswith("qual-") or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,68}", target):
        raise ValueError("serving candidate requires a serving target")
    root = root.resolve(strict=True)
    manifest = CandidateManifest.model_validate_json(manifest_bytes)
    if manifest.gate != "G-06":
        raise ValueError("IMP-06 candidate evidence required")
    sources = _source_hashes(root, manifest.source)
    _source_hashes(root, manifest.observations)
    observations = {
        name: [
            (pin, _verified_file(root, pin))
            for pin in manifest.observations
            if Path(pin.path).name == name
        ]
        for name in _REQUIRED_RECEIPTS
    }
    if any(len(files) != 1 for files in observations.values()):
        raise ValueError("one pinned receipt is required for each model qualification observation")
    receipts = {name: _object(files[0][1]) for name, files in observations.items()}
    if any(receipt.get("state") != "passed" for receipt in receipts.values()):
        raise ValueError("qualifying model, workload, provenance and image receipts must pass")
    evaluated = receipts["authenticated-qwen.json"]
    workload = receipts["qwen-final-workload.json"]
    provenance = receipts["model-provenance.json"]
    image = receipts["image-smoke.json"]
    case_records = cast(list[dict[str, object]], evaluated["cases"])
    cases = _passing_cases(case_records)
    workload_cases = cast(list[dict[str, object]], workload["cases"])
    _passing_cases(workload_cases)
    token_limit = workload["input_token_limit"]
    cases_expected = {
        (language, injection) for language in ("en-CA", "fr-CA") for injection in (False, True)
    }
    proof_fields = ("tokenizer_digest", "template_digest")
    if (
        evaluated.get("function") != "worker_summary"
        or evaluated.get("model_identifier") != MODEL
        or evaluated.get("server_authentication_preflight") != "passed"
        or type(token_limit) is not int
        or {(case.language, case.injection) for case in cases} != cases_expected
        or {case.get("language") for case in workload_cases} != {"en-CA", "fr-CA"}
        or workload.get("diagnostic_stress") is not False
        or workload.get("render_mode") != evaluated.get("render_mode")
        or any(
            type(case.get("prompt_tokens")) is not int
            or not 1 <= cast(int, case["prompt_tokens"]) <= token_limit
            for case in workload_cases
        )
        or evaluated["artifact_digest"] != provenance["artifact_digest"]
        or evaluated["artifact_digest"] != workload["artifact_digest"]
        or manifest.role_runtime_image != image.get("image_id")
    ):
        raise ValueError("model, workload or image evidence differs from the exact candidate")
    for record in case_records:
        proof = cast(dict[str, object], record["token_proof"])
        if (
            proof.get("model_identifier") != MODEL
            or proof.get("loaded_model_id") != MODEL
            or proof.get("artifact_digest") != evaluated["artifact_digest"]
            or proof.get("model_window") != 8192
            or any(proof[field] != workload[field] for field in proof_fields)
        ):
            raise ValueError("evaluation token proof differs from qualified identity")
    for receipt in (evaluated, image):
        hashes = cast(dict[str, str], receipt["source_sha256"])
        if not hashes:
            raise ValueError("source pins are required")
        for path, checksum in hashes.items():
            _verified_file(root, FilePin(path=path, sha256=checksum))
            if sources.get(path, checksum) != checksum:
                raise ValueError("qualification source pins disagree")
            sources[path] = checksum
    catalog_digest = str(evaluated["knowledge_catalog_sha256"])
    if sources.get(_CATALOG) != catalog_digest or image.get("knowledge_digest") != catalog_digest:
        raise ValueError("catalog differs from qualified inputs")
    instruction = _verified_file(root, FilePin(path=_PROMPT, sha256=sources[_PROMPT])).decode()
    instruction_source: dict[str, object] = {
        "kind": "template",
        "id": str(uuid5(NAMESPACE_URL, "care-link-synthetic:selection-instruction")),
        "revision": "1",
        "digest": sources[_PROMPT],
        "observed_at": "2026-11-20T00:00:00Z",
        "verification": "verified",
    }
    evaluation = EvaluationEvidence(
        canonical_schema_digest=str(evaluated["canonical_schema_sha256"]),
        wire_schema_digest=str(evaluated["wire_schema_sha256"]),
        prompt_digest=digest(
            [
                {
                    "source": instruction_source,
                    "label": "approved_instruction",
                    "text": instruction,
                    "critical": True,
                }
            ]
        ),
        english_digest=digest([record for record in case_records if record["language"] == "en-CA"]),
        french_digest=digest([record for record in case_records if record["language"] == "fr-CA"]),
        grounding_digest=digest(case_records),
        adversarial_digest=digest([record for record in case_records if record["injection"]]),
        latency_digest=observations["qwen-final-workload.json"][0][0].sha256,
        threats=tuple(sorted(THREATS)),
        input_token_limit=token_limit,
    )
    artifact = ReleaseArtifact(
        purpose="serving",
        target=target,
        proposer=proposer,
        signer=signer,
        change_class=change_class,
        observation=ReleaseObservation(
            model=ModelIdentity(
                artifact_digest=str(evaluated["artifact_digest"]),
                origin=str(provenance["origin"]),
                quantization=str(provenance["quantization"]),
                license=str(provenance["license"]),
                server_version=str(provenance["server_version"]),
                engine_version=str(provenance["engine_version"]),
                sdk_render_mode=str(evaluated["render_mode"]),
                tokenizer_digest=str(workload["tokenizer_digest"]),
                template_digest=str(workload["template_digest"]),
            ),
            code_digest=digest(sources),
            image_digest=manifest.role_runtime_image.removeprefix("sha256:"),
            catalog_digest=catalog_digest,
            evaluation_digest=digest(evaluation.model_dump(mode="json")),
        ),
        evidence=evaluation,
        instruction_source=instruction_source,
        instruction=instruction,
    )
    artifact.validated_function()
    return artifact
