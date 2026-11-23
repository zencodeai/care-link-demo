"""Configuration and adverse checks for the protected Training process boundary."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

import pytest
from care_link_data.training_replay import capture, sha256, training_bundle
from care_link_domain import Actor, ManualError
from care_link_domain import canonical_training as canonical
from care_link_domain import exercise_training_fixture as exercise
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi.testclient import TestClient

from tools.imp10_runtime import protected_training as protected

ARTIFACT = Path(__file__).resolve().parents[3] / "config/demo/imp10/training-artifact.json"


def actor(role="trainer"):
    now = datetime.now(UTC)
    return Actor(
        account_id=str(uuid4()),
        role=role,
        identity_revision=1,
        role_revision=1,
        auth_time=now,
        mfa=True,
        browser_session_digest="a" * 64,
        transport_generation=1,
        credential_ref="synthetic-test-credential",
        expires_at=now + timedelta(seconds=60),
        identity_evidence_id=str(uuid4()),
    )


def pin(path: Path, raw: bytes | None = None):
    if raw is not None:
        path.write_bytes(raw)
    return {"path": str(path), "sha256": sha256(path.read_bytes())}


def verification_key(path: Path):
    public = Ed25519PrivateKey.generate().public_key()
    path.write_bytes(public.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
    return str(path)


def training_config(tmp_path, owner):
    key = tmp_path / "training-content.key"
    key.write_bytes(b"a" * 32)
    key.chmod(0o600)
    policy = {
        "version": 1,
        "grants": [
            {"trainer_id": owner.account_id, "actions": ["scenario_create", "scenario_read"]}
        ],
    }
    cfg = {
        "role": "training",
        "training_enabled": True,
        "training_artifact": pin(ARTIFACT),
        "training_policy": pin(tmp_path / "training-policy.json", canonical(policy)),
        "content_key": str(key),
        "core_public_key": verification_key(tmp_path / "core.pem"),
        "identity_public_key": verification_key(tmp_path / "identity.pem"),
        "store_dsn": "host=training.invalid dbname=training user=trainer sslmode=verify-full "
        "sslrootcert=/tmp/synthetic-test-training-ca.pem",
    }
    return cfg, policy


class UnavailableIdentity:
    def resolve(self, _evidence):
        raise AssertionError("No actor evidence belongs in this transport denial test")


def test_explicit_training_grants_stay_bound_to_current_pins(tmp_path, monkeypatch):
    owner = actor()
    config, _policy = training_config(tmp_path, owner)
    original_factory = protected.training_application
    observed = {}

    def application(dsn, identity, verify, permit, cipher, **pins):
        observed.update(permit=permit, **pins)
        return original_factory(dsn, identity, verify, permit, cipher, **pins)

    monkeypatch.setattr(protected, "training_application", application)
    app = protected.configured_training(config, UnavailableIdentity(), lambda *_: False)
    with TestClient(app) as client:
        refused = client.post("/internal/v1/training/scenario_create", json={})
    assert refused.status_code == 403
    assert refused.json()["message_key"] == "training.workload_denied"
    assert observed["admitted_trainers"] == {owner.account_id}

    permit, target, digest = observed["permit"], str(uuid4()), "b" * 64
    assert permit(owner, "scenario_create", None, digest)
    assert permit(owner, "scenario_read", target, digest)
    assert not permit(owner, "scenario_stop", target, digest)
    assert not permit(owner, "scenario_create", target, digest)
    assert not permit(owner, "scenario_read", None, digest)
    assert not permit(owner, "scenario_read", "not-a-uuid", digest)
    assert not permit(owner, "scenario_read", target, "not-a-hash")
    assert not permit(replace(owner, role="worker"), "scenario_read", target, digest)
    assert not permit(actor(), "scenario_read", target, digest)

    policy_path = Path(config["training_policy"]["path"])
    policy_path.write_bytes(policy_path.read_bytes() + b" ")
    assert not permit(owner, "scenario_read", target, digest)


def test_training_startup_rejects_unsafe_or_unpinned_config(tmp_path):
    owner = actor()
    config, policy = training_config(tmp_path, owner)

    def start(value):
        return protected.configured_training(value, UnavailableIdentity(), lambda *_: False)

    with pytest.raises(ValueError, match="opt-in"):
        start({**config, "training_enabled": False})
    with pytest.raises(ValueError, match="verified TLS"):
        start({**config, "store_dsn": "host=training.invalid sslmode=require"})
    with pytest.raises(ValueError, match="keys must be distinct"):
        start({**config, "identity_public_key": config["core_public_key"]})
    with pytest.raises(ValueError, match="pin mismatch"):
        start({**config, "training_policy": {**config["training_policy"], "sha256": "f" * 64}})
    extra = {**policy, "grants": [{"trainer_id": owner.account_id, "actions": ["*"]}]}
    with pytest.raises(ValueError, match="explicit trainer"):
        start({**config, "training_policy": pin(tmp_path / "wildcard.json", canonical(extra))})
    Path(config["content_key"]).chmod(0o644)
    with pytest.raises(ValueError, match="custody mismatch"):
        start(config)


def replay_config(tmp_path, owner, reviewer, *, with_observation=True):
    contents = ARTIFACT.read_bytes()
    bundle = training_bundle(
        {
            "runner": files("care_link_domain").joinpath("training.py").read_bytes(),
            "artifact": contents,
            "contracts": files("care_link_contracts").joinpath("schema.json").read_bytes(),
        }
    )
    scenario = str(uuid4())
    fixture = {
        "artifact_digest": sha256(contents),
        "locale": "fr-CA",
        "fixture_mode": "partial",
        "business_clock_at": "2001-01-01T00:00:00Z",
    }
    entry = capture(
        scenario,
        fixture,
        exercise(scenario, fixture) if with_observation else None,
        datetime.now(UTC),
        bundle=bundle,
        owner_id=owner.account_id,
        reviewers=frozenset({reviewer.account_id}),
    )
    manifest = pin(tmp_path / "input.json", entry.manifest)
    observations = pin(tmp_path / "observations.json", entry.observations)
    catalog = {
        "version": 1,
        "artifact_digest": fixture["artifact_digest"],
        "bundle_digest": bundle,
        "captures": [
            {
                "owner_id": entry.owner_id,
                "reviewers": sorted(entry.reviewers),
                "manifest": manifest,
                "observations": observations,
            }
        ],
    }
    config = {
        "role": "data",
        "training_enabled": True,
        "training_artifact": pin(ARTIFACT),
        "replay_catalog": pin(tmp_path / "catalog.json", canonical(catalog)),
    }
    request = {
        "scenario_id": scenario,
        "input_manifest_digest": manifest["sha256"],
        "recorded_outputs_digest": observations["sha256"],
        "bundle_digest": bundle,
    }
    return config, catalog, request


def test_configured_replay_binds_current_actor_and_exact_capture(tmp_path):
    owner, reviewer = actor(), actor("governance")
    cfg, _catalog, request = replay_config(tmp_path, owner, reviewer)
    evaluator = protected.configured_replay(cfg)
    evaluator.authorize(owner, request)
    evaluator.authorize(reviewer, request)
    assert evaluator.evaluate(request).state == "completed"
    for denied in (actor(), actor("governance"), replace(owner, mfa=False)):
        with pytest.raises(ManualError, match="capture_unavailable"):
            evaluator.authorize(denied, request)
    with pytest.raises(ManualError, match="capture_unavailable"):
        evaluator.authorize(owner, {**request, "recorded_outputs_digest": "f" * 64})

    (tmp_path / "observations.json").unlink()
    with pytest.raises(ManualError, match="release_unavailable"):
        evaluator.authorize(owner, request)
    with pytest.raises(ManualError, match="release_unavailable"):
        evaluator.evaluate(request)


def test_replay_startup_rejects_catalog_drift_and_preserves_missingness(tmp_path):
    owner, reviewer = actor(), actor("governance")
    cfg, catalog, request = replay_config(tmp_path, owner, reviewer, with_observation=False)
    replay = protected.configured_replay(cfg)
    replay.authorize(owner, request)
    assert replay.evaluate(request).state == "failed"

    drifted = pin(tmp_path / "bundle-drift.json", canonical({**catalog, "bundle_digest": "f" * 64}))
    with pytest.raises(ValueError, match="installed training bundle"):
        protected.configured_replay({**cfg, "replay_catalog": drifted})
    noncanonical = pin(tmp_path / "noncanonical.json", canonical(catalog) + b"\n")
    with pytest.raises(ValueError, match="Canonical replay catalog"):
        protected.configured_replay({**cfg, "replay_catalog": noncanonical})
    empty = pin(tmp_path / "empty-catalog.json", canonical({**catalog, "captures": []}))
    restricted = protected.configured_replay({**cfg, "replay_catalog": empty})
    with pytest.raises(ManualError, match="capture_unavailable"):
        restricted.authorize(owner, request)
