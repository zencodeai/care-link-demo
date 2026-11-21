"""Data-side verification of a host-controlled stop of one bridge generation."""

import json
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID

from care_link_workload_trust import FenceReceipt, FenceState, TrustDenied
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

_ATTESTATION = "care-link.provider-process-exited.v1"
_INFERENCE_PEER = "spiffe://care-link.demo/demo/inference"
_TOKEN = re.compile(r"[a-z0-9][a-z0-9_-]{0,127}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_SIGNATURE = re.compile(r"[0-9a-f]{128}\Z")
_MAX_BYTES = 4096
_FIELDS = {
    "attestation",
    "issuer",
    "target",
    "bridge_generation",
    "fence_command",
    "restriction_generation",
    "provider_instance_digest",
    "stop_evidence_digest",
    "stopped_at",
}


class StopFenceReader(Protocol):
    def current(self) -> FenceState: ...
    def receipt(self, command_id: str) -> FenceReceipt | None: ...


def _canonical(value: dict[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate provider stop receipt field")
        result[key] = value
    return result


class ProviderStopAuthority:
    """Verify a dedicated host signer and the current authenticated inference fence.

    The host signer attests observed process exit after isolating the provider,
    with evidence bound to the exact provider instance and bridge generation.
    A Data or bridge process never holds this private key. Fence authority is
    read fresh through the independent Unix fence custodian.
    """

    def __init__(
        self,
        receipt_dir: Path,
        verification_key: Ed25519PublicKey,
        fence: StopFenceReader,
        *,
        issuer: str,
        target: str,
        owner_uid: int,
        current_generation: str,
    ) -> None:
        if (
            not receipt_dir.is_absolute()
            or owner_uid < 0
            or any(
                _TOKEN.fullmatch(value) is None for value in (issuer, target, current_generation)
            )
        ):
            raise ValueError("explicit provider stop custody and current generation required")
        self.receipt_dir, self.key, self.fence = receipt_dir, verification_key, fence
        self.issuer, self.target, self.owner_uid = issuer, target, owner_uid
        self.current_generation = current_generation

    def _read(self, bridge_generation: str) -> bytes:
        directory = os.open(self.receipt_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            parent = os.fstat(directory)
            if parent.st_uid != self.owner_uid or parent.st_mode & 0o022:
                raise ValueError("unsafe provider stop receipt directory")
            descriptor = os.open(
                bridge_generation + ".json",
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=directory,
            )
            with os.fdopen(descriptor, "rb") as stream:
                entry = os.fstat(stream.fileno())
                if (
                    not stat.S_ISREG(entry.st_mode)
                    or entry.st_uid != self.owner_uid
                    or entry.st_mode & 0o022
                    or not 0 < entry.st_size <= _MAX_BYTES
                ):
                    raise ValueError("unsafe provider stop receipt")
                return stream.read(_MAX_BYTES + 1)
        finally:
            os.close(directory)

    def _receipt(self, bridge_generation: str) -> tuple[dict[str, object], datetime]:
        raw = self._read(bridge_generation)
        if len(raw) > _MAX_BYTES:
            raise ValueError("oversized provider stop receipt")
        decoded: object = json.loads(raw, object_pairs_hook=_unique)
        if not isinstance(decoded, dict):
            raise ValueError("provider stop receipt must be an object")
        record = cast(dict[str, object], decoded)
        if set(record) != _FIELDS | {"signature"} or _canonical(record) != raw:
            raise ValueError("closed canonical provider stop receipt required")
        signature = record.pop("signature")
        if not isinstance(signature, str) or _SIGNATURE.fullmatch(signature) is None:
            raise ValueError("provider stop signature required")
        self.key.verify(bytes.fromhex(signature), _canonical(record))
        if (
            record["attestation"] != _ATTESTATION
            or record["issuer"] != self.issuer
            or record["target"] != self.target
            or record["bridge_generation"] != bridge_generation
            or any(
                not isinstance((value := record[field]), str) or _DIGEST.fullmatch(value) is None
                for field in ("provider_instance_digest", "stop_evidence_digest")
            )
        ):
            raise ValueError("provider stop binding mismatch")
        instant = record["stopped_at"]
        if not isinstance(instant, str) or not instant.endswith("Z"):
            raise ValueError("observed UTC stop time required")
        stopped_at = datetime.fromisoformat(instant)
        if stopped_at > datetime.now(UTC):
            raise ValueError("observed UTC stop time required")
        return record, stopped_at

    def verified_stop_time(self, bridge_generation: str) -> datetime | None:
        if (
            bridge_generation == self.current_generation
            or _TOKEN.fullmatch(bridge_generation) is None
        ):
            return None
        try:
            record, stopped_at = self._receipt(bridge_generation)
            command, generation = record["fence_command"], record["restriction_generation"]
            if (
                not isinstance(command, str)
                or (_DIGEST.fullmatch(command) is None and str(UUID(command)) != command)
                or type(generation) is not int
                or generation < 1
            ):
                return None
            receipt = self.fence.receipt(command)
            state = self.fence.current()
            if (
                receipt is not None
                and receipt.durable
                and receipt.command_id == command
                and receipt.peer == _INFERENCE_PEER
                and state.generation >= receipt.generation >= generation
                and _INFERENCE_PEER in state.denied
                and state.commands[generation - 1] == (command, _INFERENCE_PEER)
            ):
                return stopped_at
        except (
            OSError,
            ValueError,
            TypeError,
            IndexError,
            RecursionError,
            InvalidSignature,
            TrustDenied,
        ):
            pass
        return None
