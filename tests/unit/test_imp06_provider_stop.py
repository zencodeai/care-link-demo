"""Exercise receipt custody, signature and exact durable inference restriction."""

import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from care_link_workload_trust import FenceReceipt, FenceState, TrustDenied
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tools.imp06_runtime.provider_stop import ProviderStopAuthority

INFERENCE = "spiffe://care-link.demo/demo/inference"
RUNTIME = "spiffe://care-link.demo/demo/runtime"
GENERATION = "bridge-stopped"


class Fence:
    def __init__(self, command: str) -> None:
        self.confirmed = FenceReceipt(command, INFERENCE, 1, True)
        self.state = FenceState(
            1,
            frozenset({INFERENCE, RUNTIME}),
            frozenset({INFERENCE}),
            ((command, INFERENCE),),
            "a" * 64,
        )
        self.unavailable = False

    def current(self) -> FenceState:
        if self.unavailable:
            raise TrustDenied("fixture offline")
        return self.state

    def receipt(self, command_id: str) -> FenceReceipt | None:
        return self.confirmed if command_id == self.confirmed.command_id else None


class ReceiptFixture:
    def __init__(self, directory: Path) -> None:
        self.file = directory / (GENERATION + ".json")
        self.signer = Ed25519PrivateKey.generate()
        self.stop = datetime.now(UTC) - timedelta(seconds=1)
        command = str(uuid4())
        self.fence = Fence(command)
        self.authority = ProviderStopAuthority(
            directory,
            self.signer.public_key(),
            self.fence,
            issuer="host-stop",
            target="synthetic",
            owner_uid=os.geteuid(),
            current_generation="bridge-replacement",
        )
        self.record: dict[str, object] = {
            "attestation": "care-link.provider-process-exited.v1",
            "issuer": "host-stop",
            "target": "synthetic",
            "bridge_generation": GENERATION,
            "fence_command": command,
            "restriction_generation": 1,
            "provider_instance_digest": "b" * 64,
            "stop_evidence_digest": "c" * 64,
            "stopped_at": self.stop.isoformat().replace("+00:00", "Z"),
        }

    def write(self, signer: Ed25519PrivateKey | None = None, **override: object) -> None:
        body = self.record | override
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("ascii")
        signature = (signer or self.signer).sign(canonical).hex()
        value = json.dumps(body | {"signature": signature}, sort_keys=True, separators=(",", ":"))
        self.file.write_text(value)
        self.file.chmod(0o640)


def test_signed_retired_generation_recovers_only_under_exact_current_fence(tmp_path):
    fixture = ReceiptFixture(tmp_path)
    fixture.write()
    assert fixture.authority.verified_stop_time(GENERATION) == fixture.stop
    assert fixture.authority.verified_stop_time("bridge-replacement") is None
    assert fixture.authority.verified_stop_time("../bridge-stopped") is None

    # An unrelated later restriction preserves the exact earlier fence command.
    prior = fixture.fence.state
    fixture.fence.state = replace(
        prior,
        generation=2,
        denied=frozenset({INFERENCE, RUNTIME}),
        commands=(*prior.commands, (str(uuid4()), RUNTIME)),
    )
    fixture.fence.confirmed = replace(fixture.fence.confirmed, generation=2)
    assert fixture.authority.verified_stop_time(GENERATION) == fixture.stop
    fixture.fence.state = replace(prior, commands=((str(uuid4()), INFERENCE),))
    assert fixture.authority.verified_stop_time(GENERATION) is None
    fixture.fence.state = prior
    fixture.fence.unavailable = True
    assert fixture.authority.verified_stop_time(GENERATION) is None


@pytest.mark.parametrize(
    "override",
    [
        {"attestation": "http_request_timed_out"},
        {"target": "other-synthetic-target"},
        {"issuer": "untrusted-signer"},
        {"bridge_generation": "different-generation"},
        {"stop_evidence_digest": "unverified"},
        {"restriction_generation": True},
        {"stopped_at": "9999-01-01T00:00:00Z"},
    ],
)
def test_even_authentic_mismatched_evidence_denies_stop(tmp_path, override):
    fixture = ReceiptFixture(tmp_path)
    fixture.write(**override)
    assert fixture.authority.verified_stop_time(GENERATION) is None


def test_missing_forged_and_unsafe_receipt_denies_stop(tmp_path):
    fixture = ReceiptFixture(tmp_path)
    assert fixture.authority.verified_stop_time(GENERATION) is None
    fixture.write(Ed25519PrivateKey.generate())
    assert fixture.authority.verified_stop_time(GENERATION) is None
    fixture.write()
    fixture.file.chmod(0o666)
    assert fixture.authority.verified_stop_time(GENERATION) is None
    contents = fixture.file.read_bytes()
    fixture.file.unlink()
    target = tmp_path / "other"
    target.write_bytes(contents)
    fixture.file.symlink_to(target)
    assert fixture.authority.verified_stop_time(GENERATION) is None


def test_unconfirmed_or_wrong_peer_fence_denies_stop(tmp_path):
    fixture = ReceiptFixture(tmp_path)
    fixture.write()
    confirmed = fixture.fence.confirmed
    fixture.fence.confirmed = replace(confirmed, durable=False)
    assert fixture.authority.verified_stop_time(GENERATION) is None
    fixture.fence.confirmed = replace(confirmed, peer=RUNTIME)
    assert fixture.authority.verified_stop_time(GENERATION) is None
