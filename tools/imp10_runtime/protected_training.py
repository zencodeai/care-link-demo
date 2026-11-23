"""Load the role-owned Training policy and offline replay admission."""

import json
import os
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import cast

from care_link_contracts import validate_contract
from care_link_data import AESGCMContentCipher
from care_link_data.evaluation import ReplayCreate, ReplayEvaluator, ReplayResult
from care_link_data.training_replay import (
    OfflineTrainingReplay,
    TrainingCapture,
    sha256,
    training_bundle,
)
from care_link_domain import Actor, ManualError, admit_training_artifact
from care_link_domain import canonical_training as canonical
from fastapi import FastAPI, Request

from tools.imp02_application.config import public_key, text

from .training import TrainerIdentity, training_application

Record = dict[str, object]
ACTIONS = frozenset({"scenario_create", "scenario_read", "scenario_stop"})
REPLAY_LIMIT = 128
JSON_LIMIT = 65536
ARTIFACT_LIMIT = 4096


def _record(value: object, fields: set[str]) -> Record:
    if not isinstance(value, dict):
        raise ValueError("Exact protected training configuration fields required")
    record = cast(Record, value)
    if set(record) != fields:
        raise ValueError("Exact protected training configuration fields required")
    return record


def _array(value: object, limit: int) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("Bounded protected training configuration array required")
    array = cast(list[object], value)
    if len(array) > limit:
        raise ValueError("Bounded protected training configuration array required")
    return array


def _unique(pairs: list[tuple[str, object]]) -> Record:
    result: Record = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate protected training configuration field")
        result[name] = value
    return result


def _digest(value: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("Explicit SHA-256 pin required")
    return value


def _actor_id(value: object) -> str:
    validate_contract("Id", value)
    return cast(str, value)


def _read(path: Path, limit: int, *, private: bool = False) -> bytes:
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Absolute role-owned artifact path required")
    flags = os.O_RDONLY | os.O_NONBLOCK
    if private:
        flags |= os.O_NOFOLLOW
    with os.fdopen(os.open(path, flags), "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or (
            private and (info.st_mode & 0o077 or info.st_uid != os.geteuid())
        ):
            raise ValueError("Protected training file custody mismatch")
        content = handle.read(limit + 1)
    if len(content) > limit:
        raise ValueError("Protected training file exceeds its byte bound")
    return content


@dataclass(frozen=True)
class _Pin:
    path: Path
    digest: str
    limit: int

    @classmethod
    def from_value(cls, value: object, limit: int) -> _Pin:
        pin = _record(value, {"path", "sha256"})
        return cls(Path(text(pin, "path")), _digest(text(pin, "sha256")), limit)

    def read(self) -> bytes:
        content = _read(self.path, self.limit)
        if sha256(content) != self.digest:
            raise ValueError("Protected training file pin mismatch")
        return content


def _document(pin: _Pin, fields: set[str], *, require_canonical: bool = False) -> Record:
    raw = pin.read()
    decoded = _record(json.loads(raw, object_pairs_hook=_unique), fields | {"version"})
    if type(decoded["version"]) is not int or decoded["version"] != 1:
        raise ValueError("Unsupported protected training configuration version")
    if require_canonical and canonical(decoded) != raw:
        raise ValueError("Canonical replay catalog bytes required")
    return decoded


def _enabled(cfg: Record, role: str) -> None:
    if cfg.get("role") != role or cfg.get("training_enabled") is not True:
        raise ValueError("Exact opt-in protected training role required")


def configured_training(
    cfg: Record, identity: TrainerIdentity, verify: Callable[[Request, str], bool]
) -> FastAPI:
    """Construct the Training workload from its own store, key and pinned grants."""
    _enabled(cfg, "training")
    artifact = _Pin.from_value(cfg.get("training_artifact"), ARTIFACT_LIMIT)
    policy = _Pin.from_value(cfg.get("training_policy"), JSON_LIMIT)
    document = _document(policy, {"grants"})
    grants: dict[str, frozenset[str]] = {}
    for value in _array(document["grants"], REPLAY_LIMIT):
        item = _record(value, {"trainer_id", "actions"})
        trainer = _actor_id(item["trainer_id"])
        actions = _array(item["actions"], len(ACTIONS))
        if (
            trainer in grants
            or not actions
            or not all(isinstance(action, str) and action in ACTIONS for action in actions)
            or len(set(cast(list[str], actions))) != len(actions)
        ):
            raise ValueError("Unique explicit trainer action grants required")
        grants[trainer] = frozenset(cast(list[str], actions))
    if not grants:
        raise ValueError("Protected training requires an explicit trainer roster")

    def permit(actor: Actor, action: str, target: str | None, request_digest: str) -> bool:
        if (
            actor.role != "trainer"
            or action not in grants.get(actor.account_id, ())
            or (target is None) != (action == "scenario_create")
        ):
            return False
        try:
            _digest(request_digest)
            if target is not None:
                _actor_id(target)
            policy.read()
            artifact.read()
        except (OSError, ValueError):
            return False
        return True

    cipher = AESGCMContentCipher(_read(Path(text(cfg, "content_key")), 32, private=True))
    core_key = public_key(text(cfg, "core_public_key"))
    identity_key = public_key(text(cfg, "identity_public_key"))
    if core_key.public_bytes_raw() == identity_key.public_bytes_raw():
        raise ValueError("Core and Identity verification keys must be distinct")
    app, _service = training_application(
        text(cfg, "store_dsn"),
        identity,
        verify,
        permit,
        cipher,
        core_key=core_key,
        identity_key=identity_key,
        artifact=artifact.read(),
        artifact_digest=artifact.digest,
        admitted_trainers=frozenset(grants),
    )
    return app


@dataclass(frozen=True)
class _PinnedReplay:
    evaluator: OfflineTrainingReplay
    catalog: _Pin
    artifact: _Pin
    inputs: dict[str, tuple[_Pin, _Pin]]

    def _current(self, request: ReplayCreate) -> None:
        pins = self.inputs.get(request["input_manifest_digest"])
        if pins is None:
            raise ManualError("evaluation.capture_unavailable", 404)
        try:
            self.catalog.read()
            self.artifact.read()
            for pin in pins:
                pin.read()
        except (OSError, ValueError) as error:
            raise ManualError("evaluation.release_unavailable", 503) from error

    def authorize(self, actor: Actor, request: ReplayCreate) -> None:
        self.evaluator.authorize(actor, request)
        self._current(request)

    def evaluate(self, request: ReplayCreate) -> ReplayResult:
        self._current(request)
        return self.evaluator.evaluate(request)


def configured_replay(cfg: Record) -> ReplayEvaluator:
    """Load Data's bounded offline corpus and its current explicit access grants."""
    _enabled(cfg, "data")
    artifact = _Pin.from_value(cfg.get("training_artifact"), ARTIFACT_LIMIT)
    artifact_bytes = artifact.read()
    admit_training_artifact(artifact_bytes, artifact.digest)
    catalog = _Pin.from_value(cfg.get("replay_catalog"), JSON_LIMIT)
    document = _document(
        catalog, {"artifact_digest", "bundle_digest", "captures"}, require_canonical=True
    )
    bundle = training_bundle(
        {
            "runner": files("care_link_domain").joinpath("training.py").read_bytes(),
            "artifact": artifact_bytes,
            "contracts": files("care_link_contracts").joinpath("schema.json").read_bytes(),
        }
    )
    if document["artifact_digest"] != artifact.digest or document["bundle_digest"] != bundle:
        raise ValueError("Replay catalog differs from the installed training bundle")

    captures: list[TrainingCapture] = []
    inputs: dict[str, tuple[_Pin, _Pin]] = {}
    for value in _array(document["captures"], REPLAY_LIMIT):
        item = _record(value, {"owner_id", "reviewers", "manifest", "observations"})
        owner = _actor_id(item["owner_id"])
        reviewers = [_actor_id(reviewer) for reviewer in _array(item["reviewers"], REPLAY_LIMIT)]
        if len(set(reviewers)) != len(reviewers):
            raise ValueError("Unique explicit replay reviewer grants required")
        manifest = _Pin.from_value(item["manifest"], JSON_LIMIT)
        observations = _Pin.from_value(item["observations"], JSON_LIMIT)
        if manifest.digest in inputs:
            raise ValueError("Duplicate admitted replay input")
        captures.append(
            TrainingCapture(manifest.read(), observations.read(), owner, frozenset(reviewers))
        )
        inputs[manifest.digest] = (manifest, observations)
    evaluator = OfflineTrainingReplay(captures, bundle=bundle, artifact_digest=artifact.digest)
    return _PinnedReplay(evaluator, catalog, artifact, inputs)
