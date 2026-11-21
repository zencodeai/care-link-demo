"""Offline preparation and signed serving activation for the synthetic IMP-06 demo."""

import argparse
import hashlib
import json
import os
import stat
from datetime import datetime
from pathlib import Path
from typing import Annotated, cast

from care_link_contracts import ContractError
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field

from .release_custody import (
    MAX_ACK_LIFETIME,
    MAX_RECORD_BYTES,
    ReleaseCustody,
    ReleaseDenied,
    ReleaseTrust,
    ReviewAuthority,
)
from .release_custody_records import (
    EVALUATORS,
    ChangeClass,
    EvaluatorAck,
    EvaluatorBoot,
    HumanApproval,
    ReleaseArtifact,
    ReleaseObservation,
    ReleaseRecord,
)
from .serving_release_candidate import CandidateManifest, prepare_candidate

type PublicKeyHex = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class _Reviewer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    public_key: PublicKeyHex
    maximum_class: ChangeClass


class _TrustDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    target: str
    artifact_keys: dict[str, PublicKeyHex]
    evaluator_keys: dict[str, PublicKeyHex]
    reviewers: dict[str, _Reviewer]


def _bounded_file(path: Path, limit: int = MAX_RECORD_BYTES) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError("regular input record required")
        data = source.read(limit + 1)
    if not 0 < len(data) <= limit:
        raise ValueError("invalid or oversized input record")
    return data


def load_serving_trust(path: Path, *, owner_uid: int) -> ReleaseTrust:
    """Load public trust roots from the independently provisioned custody file."""
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        directory = os.fstat(parent)
        if directory.st_uid != owner_uid or directory.st_mode & 0o022:
            raise ReleaseDenied("unsafe serving trust directory")
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    with os.fdopen(descriptor, "rb") as source:
        info = os.fstat(source.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != owner_uid
            or info.st_nlink != 1
            or info.st_mode & 0o022
            or not 0 < info.st_size <= MAX_RECORD_BYTES
        ):
            raise ReleaseDenied("unsafe serving trust file")
        data = source.read(MAX_RECORD_BYTES + 1)
    if not 0 < len(data) <= MAX_RECORD_BYTES:
        raise ReleaseDenied("invalid serving trust file size")
    trust = _TrustDocument.model_validate(json.loads(data, object_pairs_hook=_unique))
    return ReleaseTrust(
        trust.target,
        "serving",
        {name: _public_key(key) for name, key in trust.artifact_keys.items()},
        {name: _public_key(key) for name, key in trust.evaluator_keys.items()},
        {
            name: ReviewAuthority(_public_key(reviewer.public_key), reviewer.maximum_class)
            for name, reviewer in trust.reviewers.items()
        },
    )


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate serving trust binding")
        result[key] = value
    return result


def _public_key(public_key: PublicKeyHex) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key))


def read_release_record[T: ReleaseRecord](record_type: type[T], path: Path) -> T:
    """Read exactly the canonical bytes that the detached signature covers."""
    data = _bounded_file(path)
    record = record_type.model_validate_json(data)
    if record.signing_bytes() != data:
        raise ValueError("canonical release record bytes required")
    return record


def _signature(path: Path) -> bytes:
    data = _bounded_file(path, 64)
    if len(data) != 64:
        raise ValueError("detached Ed25519 signature must be 64 raw bytes")
    return data


def _write_unsigned(path: Path, record: ReleaseRecord) -> None:
    with path.open("xb") as sink:
        sink.write(record.signing_bytes())


def _serving_artifact(path: Path) -> ReleaseArtifact:
    artifact = read_release_record(ReleaseArtifact, path)
    if artifact.purpose != "serving" or artifact.target.startswith("qual-"):
        raise ReleaseDenied("serving artifact required")
    artifact.validated_function()
    return artifact


def _validity(args: argparse.Namespace) -> tuple[datetime, datetime]:
    issued, expires = cast(str, args.issued_at), cast(str, args.expires_at)
    if not issued.endswith("Z") or not expires.endswith("Z"):
        raise ValueError("UTC timestamps ending in Z required")
    start, end = datetime.fromisoformat(issued), datetime.fromisoformat(expires)
    if start >= end:
        raise ValueError("invalid record validity period")
    return start, end


def _control(args: argparse.Namespace) -> dict[str, object]:
    owner_uid = args.owner_uid
    trust = load_serving_trust(args.trust, owner_uid=owner_uid)
    custody = ReleaseCustody(args.ledger, trust=trust, owner_uid=owner_uid)
    match args.command:
        case "initialize":
            custody.initialize()
            return {"state": "disabled", "epoch": 0}
        case "stage":
            artifact = _serving_artifact(args.artifact)
            approval = read_release_record(HumanApproval, args.approval)
            epoch = custody.stage(
                artifact,
                _signature(args.artifact_signature),
                activation_id=approval.activation_id,
                expected_epoch=approval.epoch - 1,
                approval=approval,
                approval_signature=_signature(args.approval_signature),
            )
            return {"state": "staged", "epoch": epoch, "bundle_digest": artifact.bundle_digest}
        case "record-boot":
            boot = read_release_record(EvaluatorBoot, args.record)
            custody.register_boot(boot, _signature(args.signature))
            return {"state": "recorded", "instance": boot.instance, "boot_id": boot.boot_id}
        case "acknowledge":
            ack = read_release_record(EvaluatorAck, args.record)
            custody.acknowledge(ack, _signature(args.signature))
            return {"state": "acknowledged", "instance": ack.instance, "epoch": ack.epoch}
        case "activate":
            custody.activate(expected_epoch=args.epoch)
            return {"state": "active", "epoch": args.epoch}
        case "disable":
            return {"state": "disabled", "epoch": custody.disable(expected_epoch=args.epoch)}
        case "prepare-ack":
            start, end = _validity(args)
            if end - start > MAX_ACK_LIFETIME:
                raise ValueError("evaluator acknowledgment lifetime exceeds registry maximum")
            observed = read_release_record(ReleaseObservation, args.observation)
            artifact = custody.prepare(observed)
            if custody.current_boot(args.instance) != args.boot_id:
                raise ReleaseDenied("current evaluator boot is required")
            ack = EvaluatorAck(
                purpose="serving",
                target=trust.target,
                instance=args.instance,
                boot_id=args.boot_id,
                activation_id=args.activation_id,
                bundle_digest=artifact.bundle_digest,
                epoch=args.epoch,
                status=args.status,
                issued_at=args.issued_at,
                expires_at=args.expires_at,
            )
            _write_unsigned(args.output, ack)
            return {"state": "unsigned", "instance": ack.instance}
        case _:
            raise ValueError("unknown release control operation")


def _prepare(args: argparse.Namespace) -> dict[str, object]:
    if args.command == "prepare":
        candidate = _bounded_file(args.manifest)
        evidence = CandidateManifest.model_validate_json(candidate)
        artifact = prepare_candidate(
            args.root,
            candidate,
            target=args.target,
            proposer=args.proposer,
            signer=args.signer,
            change_class=args.change_class,
        )
        _write_unsigned(args.output, artifact)
        return {
            "state": "unsigned",
            "target": artifact.target,
            "bundle_digest": artifact.bundle_digest,
            "candidate_evidence_digest": hashlib.sha256(candidate).hexdigest(),
            "qualification_gate": evidence.gate_state,
        }
    if args.command == "prepare-boot":
        record = EvaluatorBoot(
            purpose="serving",
            target=args.target,
            instance=args.instance,
            boot_id=args.boot_id,
            previous_boot_id=args.previous_boot_id,
        )
        _write_unsigned(args.output, record)
        return {"state": "unsigned", "instance": record.instance}
    artifact = _serving_artifact(args.artifact)
    if args.reviewer in {artifact.proposer, artifact.signer}:
        raise ReleaseDenied("independent reviewer identity required")
    _validity(args)
    approval = HumanApproval(
        target=artifact.target,
        reviewer=args.reviewer,
        authority=artifact.change_class,
        activation_id=args.activation_id,
        bundle_digest=artifact.bundle_digest,
        epoch=args.epoch,
        issued_at=args.issued_at,
        expires_at=args.expires_at,
        evidence_digest=args.evidence_digest,
    )
    _write_unsigned(args.output, approval)
    return {"state": "unsigned", "bundle_digest": approval.bundle_digest, "epoch": approval.epoch}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    command = parser.add_subparsers(dest="command", required=True)
    candidate = command.add_parser("prepare", help="write exact unsigned target-bound artifact")
    approval = command.add_parser(
        "prepare-approval", help="write unsigned independent review bytes"
    )
    boot = command.add_parser("prepare-boot", help="write unsigned process boot bytes")
    acknowledged = command.add_parser("prepare-ack", help="write unsigned evaluator acknowledgment")
    stage = command.add_parser("stage", help="verify and stage signed artifact and review records")
    register_boot = command.add_parser("record-boot", help="register signed process boot")
    acknowledge = command.add_parser("acknowledge", help="accept a signed process acknowledgment")
    initialize = command.add_parser("initialize", help="initialize a new disabled ledger")
    activate = command.add_parser("activate", help="activate only with five current signed ACKs")
    disable = command.add_parser("disable", help="move to the next restrictive epoch")

    for control in (acknowledged, stage, register_boot, acknowledge, initialize, activate, disable):
        control.add_argument(
            "--trust", type=Path, required=True, help="provisioned public trust JSON"
        )
        control.add_argument("--ledger", type=Path, required=True)
        control.add_argument("--owner-uid", type=int, default=os.geteuid())
    for unsigned in (candidate, approval, boot, acknowledged):
        unsigned.add_argument("--output", type=Path, required=True)
    for program in (candidate, boot):
        program.add_argument("--target", required=True)
    for program in (approval, acknowledged, activate, disable):
        program.add_argument("--epoch", type=int, required=True)
    for program in (approval, acknowledged):
        program.add_argument("--activation-id", required=True)
        program.add_argument("--issued-at", required=True)
        program.add_argument("--expires-at", required=True)
    for program in (boot, acknowledged):
        program.add_argument("--instance", choices=sorted(EVALUATORS), required=True)
        program.add_argument("--boot-id", required=True)
    for program in (stage, approval):
        program.add_argument("--artifact", type=Path, required=True)
    for program in (register_boot, acknowledge):
        program.add_argument("--record", type=Path, required=True)
        program.add_argument("--signature", type=Path, required=True, help="64 raw signature bytes")
    candidate.add_argument("--root", type=Path, default=Path.cwd())
    candidate.add_argument("--manifest", type=Path, required=True)
    candidate.add_argument("--proposer", required=True)
    candidate.add_argument("--signer", required=True)
    candidate.add_argument("--change-class", choices=("C2", "C3"), required=True)
    approval.add_argument("--reviewer", required=True)
    approval.add_argument("--evidence-digest", required=True)
    boot.add_argument("--previous-boot-id")
    acknowledged.add_argument("--observation", type=Path, required=True)
    acknowledged.add_argument("--status", choices=("ready", "rejected"), required=True)
    stage.add_argument(
        "--artifact-signature", type=Path, required=True, help="64 raw signature bytes"
    )
    stage.add_argument("--approval", type=Path, required=True)
    stage.add_argument(
        "--approval-signature", type=Path, required=True, help="64 raw signature bytes"
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command in {"prepare", "prepare-approval", "prepare-boot"}:
            result = _prepare(args)
        else:
            result = _control(args)
    except ReleaseDenied as error:
        parser.exit(1, f"{error}\n")
    except (OSError, ValueError, TypeError, KeyError, ContractError):
        parser.exit(1, "Release control input invalid or unavailable\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
