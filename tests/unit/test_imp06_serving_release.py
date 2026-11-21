"""The serving controller imports signed artifacts and never generates trust."""

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from care_link_inference import MODEL, proposal_schema, provider_proposal_schema
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tools.imp06_runtime.release_custody import ReleaseCustody, ReleaseDenied
from tools.imp06_runtime.release_custody_records import (
    EVALUATORS,
    EvaluatorAck,
    EvaluatorBoot,
    HumanApproval,
    ReleaseArtifact,
    digest,
)
from tools.imp06_runtime.serving_release import (
    load_serving_trust,
    main,
    read_release_record,
)

TARGET = "serving-cli-test"
PROPOSER = "test-proposer"
SIGNER = "test-signer"
REVIEWER = "independent-test-reviewer"


def _file(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
    return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _timestamp(value):
    return value.isoformat().replace("+00:00", "Z")


def _run(*parts):
    main([str(part) for part in parts])


@pytest.fixture
def candidate(tmp_path):
    corpus = _file(tmp_path, "config/demo/knowledge/catalog.json", b"synthetic catalog")
    prompt = _file(
        tmp_path, "config/demo/assistance/prompts/worker-summary-v2.txt", b"Draft from the sources."
    )
    sources = {pin["path"]: pin["sha256"] for pin in (corpus, prompt)}
    pinned_artifact = {
        "artifact_digest": digest("fixture-artifact"),
        "tokenizer_digest": digest("fixture-tokenizer"),
        "template_digest": digest("fixture-template"),
    }
    proof = {
        **pinned_artifact,
        "model_identifier": MODEL,
        "loaded_model_id": MODEL,
        "model_window": 8192,
    }
    cases = [
        {
            "language": locale,
            "injection": injection,
            "state": "passed",
            "prompt_count_matches": True,
            "exact_grounding": True,
            "token_proof": proof,
            "prompt_tokens": 1024,
        }
        for locale in ("en-CA", "fr-CA")
        for injection in (False, True)
    ]
    image_id = "sha256:" + digest("fixture-image")
    entries = {
        "authenticated-qwen.json": {
            "function": "worker_summary",
            "model_identifier": MODEL,
            "state": "passed",
            "render_mode": "fixture-render-mode",
            "server_authentication_preflight": "passed",
            "cases": cases,
            "source_sha256": sources,
            "artifact_digest": pinned_artifact["artifact_digest"],
            "knowledge_catalog_sha256": corpus["sha256"],
            "canonical_schema_sha256": digest(proposal_schema()),
            "wire_schema_sha256": digest(provider_proposal_schema()),
        },
        "qwen-final-workload.json": {
            **pinned_artifact,
            "state": "passed",
            "render_mode": "fixture-render-mode",
            "diagnostic_stress": False,
            "input_token_limit": 2048,
            "cases": cases,
        },
        "model-provenance.json": {
            "state": "passed",
            "artifact_digest": pinned_artifact["artifact_digest"],
            "origin": "local fixture",
            "quantization": "fixture",
            "license": "fixture",
            "server_version": "fixture",
            "engine_version": "fixture",
        },
        "image-smoke.json": {
            "state": "passed",
            "image_id": image_id,
            "source_sha256": sources,
            "knowledge_digest": corpus["sha256"],
        },
    }
    manifest = {
        "gate": "G-06",
        "gate_state": "blocked",
        "role_runtime_image": image_id,
        "source": [corpus, prompt],
        "observations": [_file(tmp_path, f"evidence/{name}", row) for name, row in entries.items()],
    }
    return _file(tmp_path, "manifest.json", manifest)


def _prepare_candidate(tmp_path, candidate):
    output = tmp_path / "unsigned.json"
    _run(
        "prepare",
        "--target",
        TARGET,
        "--proposer",
        PROPOSER,
        "--signer",
        SIGNER,
        "--root",
        tmp_path,
        "--manifest",
        tmp_path / candidate["path"],
        "--change-class",
        "C2",
        "--output",
        output,
    )
    return output


def _trust(tmp_path):
    keys = {actor: Ed25519PrivateKey.generate() for actor in (SIGNER, REVIEWER, *EVALUATORS)}
    public_keys = {name: key.public_key().public_bytes_raw().hex() for name, key in keys.items()}
    body = {
        "target": TARGET,
        "artifact_keys": {SIGNER: public_keys[SIGNER]},
        "evaluator_keys": {role: public_keys[role] for role in EVALUATORS},
        "reviewers": {REVIEWER: {"public_key": public_keys[REVIEWER], "maximum_class": "C2"}},
    }
    path = tmp_path / _file(tmp_path, "trust.json", body)["path"]
    return keys, path


def _sign(path, private_key):
    signature = path.with_suffix(".sig")
    signature.write_bytes(private_key.sign(path.read_bytes()))
    return signature


def test_serving_cli_requires_independent_signature_and_all_current_boots(
    tmp_path, capsys, candidate
):
    raw = _prepare_candidate(tmp_path, candidate)
    artifact = read_release_record(ReleaseArtifact, raw)
    assert artifact.purpose == "serving"
    assert artifact.observation.image_digest == digest("fixture-image")
    assert json.loads(capsys.readouterr().out)["qualification_gate"] == "blocked"
    keys, trust = _trust(tmp_path)
    ledger = tmp_path / "release.sqlite"
    control = ("--trust", trust, "--ledger", ledger)
    _run("initialize", *control)
    activation = str(uuid4())
    now = datetime.now(UTC) - timedelta(seconds=1)
    validity = (
        "--issued-at",
        _timestamp(now),
        "--expires-at",
        _timestamp(now + timedelta(minutes=1)),
    )
    approval = tmp_path / "approval.json"
    _run(
        "prepare-approval",
        "--artifact",
        raw,
        "--reviewer",
        REVIEWER,
        "--epoch",
        1,
        "--activation-id",
        activation,
        "--evidence-digest",
        candidate["sha256"],
        "--output",
        approval,
        *validity,
    )
    assert read_release_record(HumanApproval, approval).bundle_digest == artifact.bundle_digest
    stage = (
        "stage",
        *control,
        "--artifact",
        raw,
        "--artifact-signature",
        _sign(raw, keys[SIGNER]),
        "--approval",
        approval,
    )
    with pytest.raises(SystemExit, match="1"):
        _run(*stage, "--approval-signature", _sign(approval, keys[SIGNER]))
    _run(*stage, "--approval-signature", _sign(approval, keys[REVIEWER]))
    with pytest.raises(SystemExit, match="1"):
        _run("activate", *control, "--epoch", 1)
    observation = tmp_path / "observation.json"
    observation.write_bytes(artifact.observation.signing_bytes())
    boot_ids = {}
    for role in sorted(EVALUATORS):
        boot = tmp_path / f"{role}-boot.json"
        boot_id = str(uuid4())
        boot_ids[role] = boot_id
        _run(
            "prepare-boot",
            "--target",
            TARGET,
            "--instance",
            role,
            "--boot-id",
            boot_id,
            "--output",
            boot,
        )
        assert read_release_record(EvaluatorBoot, boot).boot_id == boot_id
        _run("record-boot", *control, "--record", boot, "--signature", _sign(boot, keys[role]))
        ack = tmp_path / f"{role}-ack.json"
        _run(
            "prepare-ack",
            *control,
            "--observation",
            observation,
            "--instance",
            role,
            "--boot-id",
            boot_id,
            "--epoch",
            1,
            "--activation-id",
            activation,
            "--status",
            "ready",
            "--output",
            ack,
            *validity,
        )
        assert read_release_record(EvaluatorAck, ack).bundle_digest == artifact.bundle_digest
        _run("acknowledge", *control, "--record", ack, "--signature", _sign(ack, keys[role]))
    _run("activate", *control, "--epoch", 1)
    custody = ReleaseCustody(
        ledger, trust=load_serving_trust(trust, owner_uid=os.geteuid()), owner_uid=os.geteuid()
    )
    bindings = custody.serving_bindings(
        artifact.observation, instance="core", boot_id=boot_ids["core"]
    )
    assert bindings.current()
    _run("disable", *control, "--epoch", 1)
    assert not bindings.current()


def test_stale_qualification_source_and_tampered_evidence_are_denied(tmp_path, candidate):
    _file(tmp_path, "config/demo/assistance/prompts/worker-summary-v2.txt", b"Changed source.")
    with pytest.raises(SystemExit, match="1"):
        _prepare_candidate(tmp_path, candidate)
    _file(
        tmp_path, "config/demo/assistance/prompts/worker-summary-v2.txt", b"Draft from the sources."
    )
    _file(tmp_path, "evidence/qwen-final-workload.json", {"state": "passed"})
    with pytest.raises(SystemExit, match="1"):
        _prepare_candidate(tmp_path, candidate)
    assert not (tmp_path / "unsigned.json").exists()


def test_serving_trust_rejects_mutable_and_duplicate_bindings(tmp_path):
    _, trust = _trust(tmp_path)
    trust.chmod(0o622)
    with pytest.raises(ReleaseDenied, match="unsafe serving trust file"):
        load_serving_trust(trust, owner_uid=os.geteuid())
    trust.chmod(0o600)
    raw = trust.read_bytes()
    trust.write_bytes(b'{"target": "duplicate-target", ' + raw[1:])
    with pytest.raises(ValueError, match="duplicate serving trust binding"):
        load_serving_trust(trust, owner_uid=os.geteuid())
