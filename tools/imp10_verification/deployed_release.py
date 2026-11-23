"""Prepare and operate the disposable IMP-10 qualification release custody."""

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from care_link_policy_input.opa import canonical
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import BaseModel, ConfigDict

from tools.imp06_runtime.release_custody import (
    MAX_ACK_LIFETIME,
    MAX_RECORD_BYTES,
    ReleaseCustody,
    ReleaseDenied,
    ReleaseTrust,
)
from tools.imp06_runtime.release_custody_records import (
    EVALUATORS,
    Digest,
    EvaluatorAck,
    EvaluatorBoot,
    Identifier,
    ReleaseArtifact,
    ReleaseObservation,
)
from tools.imp06_runtime.releases import ReleaseBindings
from tools.imp06_runtime.serving_release import read_release_record
from tools.imp06_runtime.serving_release_candidate import FilePin

TARGET = "qual-imp10-008"
SIGNER = "imp10-008-disposable-artifact"
LEDGER = "release.sqlite"
TRUST = "trust.json"
OBSERVATION = "observation.json"
BASELINE = Path(
    "doc/IMP/slices/IMP-06-bounded-ai-assistance/sessions/005-deployment-release-qualification/"
)
BASELINE_MANIFEST = "b88f2b794b69f27a47903d1c44ca84a572bf8596f3465dc0508a42088d43c4ea"
EVALUATION_INPUTS = frozenset(
    {"authenticated-qwen.json", "qwen-final-workload.json", "model-provenance.json"}
)


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PublicTrust(Closed):
    purpose: Literal["qualification"] = "qualification"
    target: Literal["qual-imp10-008"] = TARGET
    artifact_keys: dict[str, Digest]
    evaluator_keys: dict[str, Digest]

    def trust(self) -> ReleaseTrust:
        if set(self.artifact_keys) != {SIGNER}:
            raise ReleaseDenied("unexpected qualification artifact signer")
        return ReleaseTrust(
            self.target,
            self.purpose,
            {
                name: Ed25519PublicKey.from_public_bytes(bytes.fromhex(key))
                for name, key in self.artifact_keys.items()
            },
            {
                name: Ed25519PublicKey.from_public_bytes(bytes.fromhex(key))
                for name, key in self.evaluator_keys.items()
            },
        )


class Activation(Closed):
    id: Identifier
    bundle_digest: Digest
    epoch: Literal[1] = 1


class ImageReceipt(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    state: Literal["passed"]
    image_id: str
    knowledge_digest: Digest
    source_sha256: dict[str, Digest]


class EvidenceManifest(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    gate: Literal["G-06"]
    observations: list[FilePin]


def _now() -> datetime:
    return datetime.now(UTC)


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _directory(path: Path, owner_uid: int, *, private: bool = False) -> None:
    info = path.stat(follow_symlinks=False)
    forbidden = 0o077 if private else 0o022
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != owner_uid or info.st_mode & forbidden:
        raise ReleaseDenied("unsafe qualification custody directory")


def _owned_read(path: Path, owner_uid: int, *, private: bool = False) -> bytes:
    _directory(path.parent, owner_uid, private=private)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as source:
        info = os.fstat(source.fileno())
        forbidden = 0o077 if private else 0o022
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != owner_uid
            or info.st_nlink != 1
            or info.st_mode & forbidden
            or not 0 < info.st_size <= MAX_RECORD_BYTES
        ):
            raise ReleaseDenied("unsafe qualification custody file")
        return source.read(MAX_RECORD_BYTES + 1)


def _closed[T: BaseModel](record: type[T], value: bytes) -> T:
    parsed = record.model_validate_json(value)
    if canonical(parsed.model_dump(mode="json")) != value:
        raise ReleaseDenied("noncanonical qualification evidence")
    return parsed


def _write(path: Path, value: bytes, *, mode: int, gid: int | None = None) -> None:
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, mode)
    with os.fdopen(descriptor, "wb") as stream:
        if gid is not None:
            os.fchown(stream.fileno(), -1, gid)
        os.fchmod(stream.fileno(), mode)
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def _write_record(path: Path, record: BaseModel, *, mode: int, gid: int | None = None) -> None:
    _write(path, canonical(record.model_dump(mode="json")), mode=mode, gid=gid)


def _verify_digest(path: Path, expected: str) -> bytes:
    value = path.read_bytes()
    if hashlib.sha256(value).hexdigest() != expected:
        raise ValueError("qualification evidence digest differs")
    return value


def prepare_release(
    root: Path, image_receipt: Path, image_receipt_sha256: str, *, image_id: str
) -> ReleaseArtifact:
    """Derive an unsigned artifact using existing exact qualification and image receipts."""
    root = root.resolve(strict=True)
    image_receipt = image_receipt.resolve(strict=True)
    manifest = EvidenceManifest.model_validate_json(
        _verify_digest(root / BASELINE / "candidate-manifest.json", BASELINE_MANIFEST)
    )
    expected_inputs = {
        pin.path: pin.sha256
        for pin in manifest.observations
        if Path(pin.path).name in EVALUATION_INPUTS
    }
    if set(expected_inputs) != {str(BASELINE / "evidence" / name) for name in EVALUATION_INPUTS}:
        raise ValueError("exact model qualification receipts required")
    for path, expected in expected_inputs.items():
        _verify_digest(root / path, expected)
    receipt = ImageReceipt.model_validate_json(_verify_digest(image_receipt, image_receipt_sha256))
    if (
        re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None
        or image_id != receipt.image_id
        or not receipt.source_sha256
    ):
        raise ValueError("exact package qualification receipt required")
    for path, expected in receipt.source_sha256.items():
        source = (root / path).resolve(strict=True)
        if Path(path).is_absolute() or not source.is_relative_to(root):
            raise ValueError("image source must be inside the pinned workspace")
        _verify_digest(source, expected)
    _verify_digest(root / "config/demo/knowledge/catalog.json", receipt.knowledge_digest)

    # Reuse the existing verification-only derivation without changing this process's
    # environment or importing test harnesses into the packaged role path.
    invocation = (
        "from tests.evaluation.qwen_combined_journey import release_artifact;"
        "import sys; sys.stdout.buffer.write(release_artifact().signing_bytes())"
    )
    output = subprocess.run(  # noqa: S603 - fixed Python snippet, explicit workspace and receipt
        (sys.executable, "-c", invocation),
        cwd=root,
        env={
            **os.environ,
            "PYTHONPATH": str(root),
            "CARE_LINK_JOURNEY_IMAGE_RECEIPT": str(image_receipt),
        },
        capture_output=True,
        timeout=30,
        check=False,
    )
    if output.returncode:
        raise ValueError("pinned model qualification evidence could not be reconstructed")
    _verify_digest(image_receipt, image_receipt_sha256)
    artifact = _closed(ReleaseArtifact, output.stdout)
    if (
        artifact.purpose != "qualification"
        or artifact.observation.image_digest != image_id.removeprefix("sha256:")
        or artifact.observation.catalog_digest != receipt.knowledge_digest
    ):
        raise ReleaseDenied("qualifying model and runtime image pins differ")
    artifact = artifact.model_copy(update={"target": TARGET, "signer": SIGNER})
    artifact.validated_function()
    return artifact


def load_qualification_bindings(
    shared: Path,
    *,
    owner_uid: int,
    role: str,
    boot_id: str,
    expected_observation: ReleaseObservation,
    clock: Callable[[], datetime] = _now,
) -> ReleaseBindings:
    """Read current disposable authority using only public trust and role-local pins."""
    trust = _closed(PublicTrust, _owned_read(shared / TRUST, owner_uid)).trust()
    observation = _closed(ReleaseObservation, _owned_read(shared / OBSERVATION, owner_uid))
    if observation != expected_observation:
        raise ReleaseDenied("independently provisioned role observation required")
    custody = ReleaseCustody(shared / LEDGER, trust=trust, owner_uid=owner_uid, clock=clock)
    return custody.qualification_bindings(observation, instance=role, boot_id=boot_id)


class QualificationOperator:
    """Sole writer for the signed disposable ledger and independently scoped role keys."""

    def __init__(self, directory: Path, *, clock: Callable[[], datetime] = _now) -> None:
        self.directory = directory
        self.shared = directory / "shared"
        self._private = directory / "operator"
        self._uid = os.geteuid()
        self._clock = clock
        _directory(directory, self._uid)
        self._trust = _closed(PublicTrust, _owned_read(self.shared / TRUST, self._uid)).trust()
        self.custody = ReleaseCustody(
            self.shared / LEDGER, trust=self._trust, owner_uid=self._uid, clock=clock
        )
        self.observation = _closed(
            ReleaseObservation, _owned_read(self.shared / OBSERVATION, self._uid)
        )
        self.activation = _closed(
            Activation, _owned_read(self._private / "activation.json", self._uid, private=True)
        )
        if self.custody.prepare(self.observation).bundle_digest != self.activation.bundle_digest:
            raise ReleaseDenied("operator state differs from current qualification artifact")

    @classmethod
    def initialize(
        cls,
        directory: Path,
        artifact: ReleaseArtifact,
        *,
        readers_gid: int | None = None,
        clock: Callable[[], datetime] = _now,
    ) -> QualificationOperator:
        if (
            artifact.purpose != "qualification"
            or artifact.target != TARGET
            or artifact.signer != SIGNER
        ):
            raise ReleaseDenied("exact disposable qualification artifact required")
        artifact.validated_function()
        if not directory.is_absolute():
            raise ValueError("absolute qualification custody directory required")
        directory.mkdir(mode=0o710)
        try:
            shared = directory / "shared"
            private = directory / "operator"
            shared.mkdir(mode=0o750)
            private.mkdir(mode=0o700)
            if readers_gid is not None:
                for path in (directory, shared):
                    os.chown(path, -1, readers_gid, follow_symlinks=False)
            directory.chmod(0o710)
            shared.chmod(0o750)
            artifact_key = Ed25519PrivateKey.generate()
            evaluator_keys = {role: Ed25519PrivateKey.generate() for role in EVALUATORS}
            document = PublicTrust(
                artifact_keys={SIGNER: artifact_key.public_key().public_bytes_raw().hex()},
                evaluator_keys={
                    role: key.public_key().public_bytes_raw().hex()
                    for role, key in evaluator_keys.items()
                },
            )
            _write_record(shared / TRUST, document, mode=0o640, gid=readers_gid)
            _write_record(shared / OBSERVATION, artifact.observation, mode=0o640, gid=readers_gid)
            for role, key in evaluator_keys.items():
                _write(private / f"{role}.key", key.private_bytes_raw(), mode=0o600)
            # Signing a staged artifact and acknowledging a measured role boot are distinct steps.
            custody = ReleaseCustody(
                shared / LEDGER, trust=document.trust(), owner_uid=os.geteuid(), clock=clock
            )
            custody.initialize()
            ledger = shared / LEDGER
            if readers_gid is not None:
                os.chown(ledger, -1, readers_gid, follow_symlinks=False)
            ledger.chmod(0o640)
            activation = Activation(id=str(uuid4()), bundle_digest=artifact.bundle_digest)
            epoch = custody.stage(
                artifact,
                artifact_key.sign(artifact.signing_bytes()),
                activation_id=activation.id,
                expected_epoch=0,
            )
            if epoch != activation.epoch:
                raise ReleaseDenied("unexpected initial qualification epoch")
            _write_record(private / "activation.json", activation, mode=0o600)
            return cls(directory, clock=clock)
        except BaseException:
            # This exclusive initialization created the directory and has never activated it.
            shutil.rmtree(directory)
            raise

    def _key(self, role: str) -> Ed25519PrivateKey:
        if role not in EVALUATORS:
            raise ReleaseDenied("unknown qualification evaluator")
        key = Ed25519PrivateKey.from_private_bytes(
            _owned_read(self._private / f"{role}.key", self._uid, private=True)
        )
        if (
            key.public_key().public_bytes_raw()
            != self._trust.evaluator_keys[role].public_bytes_raw()
        ):
            raise ReleaseDenied("qualification evaluator key differs from public trust")
        return key

    def register_boot(self, role: str, boot_id: str) -> EvaluatorBoot:
        if str(UUID(boot_id)) != boot_id:
            raise ValueError("canonical qualification boot ID required")
        boot = EvaluatorBoot(
            purpose="qualification",
            target=TARGET,
            instance=role,
            boot_id=boot_id,
            previous_boot_id=self.custody.current_boot(role),
        )
        self.custody.register_boot(boot, self._key(role).sign(boot.signing_bytes()))
        return boot

    def acknowledge(
        self,
        role: str,
        boot_id: str,
        observation: ReleaseObservation,
        status: Literal["ready", "rejected"],
        *,
        lifetime: timedelta = timedelta(minutes=4),
    ) -> EvaluatorAck:
        """Bind one observed evaluator's inputs and status to its exact registered boot."""
        if not timedelta(0) < lifetime <= MAX_ACK_LIFETIME:
            raise ValueError("qualification ACK lifetime exceeds registry maximum")
        if observation != self.observation or self.custody.current_boot(role) != boot_id:
            raise ReleaseDenied("qualification evaluator state differs")
        artifact = self.custody.prepare(observation)
        now = self._clock()
        ack = EvaluatorAck(
            purpose="qualification",
            target=TARGET,
            instance=role,
            boot_id=boot_id,
            activation_id=self.activation.id,
            bundle_digest=artifact.bundle_digest,
            epoch=self.activation.epoch,
            status=status,
            issued_at=_utc(now),
            expires_at=_utc(now + lifetime),
        )
        self.custody.acknowledge(ack, self._key(role).sign(ack.signing_bytes()))
        return ack

    def activate(self) -> None:
        self.custody.activate(expected_epoch=self.activation.epoch)

    def disable(self) -> int:
        return self.custody.disable(expected_epoch=self.activation.epoch)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    initialize = commands.add_parser("initialize", help="validate, sign and stage one candidate")
    record_boot = commands.add_parser(
        "record-boot", help="record a supervisor-owned evaluator boot"
    )
    acknowledge = commands.add_parser(
        "acknowledge", help="bind one observed role to its exact boot"
    )
    activate = commands.add_parser("activate", help="check all five current role acknowledgments")
    disable = commands.add_parser("disable", help="advance to a restrictive epoch")
    for command in (initialize, record_boot, acknowledge, activate, disable):
        command.add_argument("--directory", type=Path, required=True)
    for command in (record_boot, acknowledge):
        command.add_argument("--role", choices=sorted(EVALUATORS), required=True)
        command.add_argument("--boot-id", required=True)
    initialize.add_argument("--root", type=Path, required=True)
    initialize.add_argument("--image-receipt", type=Path, required=True)
    initialize.add_argument("--image-receipt-sha256", required=True)
    initialize.add_argument("--image-id", required=True)
    initialize.add_argument("--readers-gid", type=int)
    acknowledge.add_argument("--observed", type=Path, required=True)
    acknowledge.add_argument("--status", choices=("ready", "rejected"), required=True)
    acknowledge.add_argument("--lifetime-seconds", type=int, default=240)
    return parser


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    try:
        directory: Path = args.directory
        if args.command == "initialize":
            artifact = prepare_release(
                args.root, args.image_receipt, args.image_receipt_sha256, image_id=args.image_id
            )
            operator = QualificationOperator.initialize(
                directory, artifact, readers_gid=args.readers_gid
            )
            result = {"state": "staged", **operator.activation.model_dump(mode="json")}
        else:
            operator = QualificationOperator(directory)
            if args.command == "record-boot":
                boot = operator.register_boot(args.role, args.boot_id)
                result = {"state": "recorded", "role": boot.instance, "boot_id": boot.boot_id}
            elif args.command == "acknowledge":
                observation = read_release_record(ReleaseObservation, args.observed)
                ack = operator.acknowledge(
                    args.role,
                    args.boot_id,
                    observation,
                    args.status,
                    lifetime=timedelta(seconds=args.lifetime_seconds),
                )
                result = {
                    "state": "acknowledged",
                    "status": ack.status,
                    "role": ack.instance,
                    "expires_at": ack.expires_at,
                }
            elif args.command == "activate":
                operator.activate()
                result = {"state": "active", "epoch": operator.activation.epoch}
            else:
                result = {"state": "disabled", "epoch": operator.disable()}
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        parser.exit(1, "Qualification custody input unavailable, stale or unverified\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
