"""Pinned OPA/Rego adapter; signatures establish integrity, never human approval."""

import base64
import hashlib
import json
import subprocess
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from care_link_contracts import validate_contract
from care_link_domain import ManualError
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


class OpaPolicy:
    """Evaluate exact signed source with a digest-pinned executable and bounded budget.

    No permission cache, policy-selected executable, shell or network policy fetch.
    Trusted signing keys and artifact digests are explicit composition inputs.
    """

    def __init__(
        self,
        executable: Path,
        executable_digest: str,
        source: bytes,
        signature: str,
        public_key: Ed25519PublicKey,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.executable = executable
        self.executable_digest = executable_digest
        self.source = source
        self.signature = signature
        self.public_key = public_key
        self.clock = clock
        self.bundle_digest = hashlib.sha256(source).hexdigest()
        self._verify()

    def _verify(self) -> None:
        try:
            self.public_key.verify(base64.b64decode(self.signature, validate=True), self.source)
            # Integrity is checked for every evaluation. Stream the pinned
            # executable instead of allocating one complete binary per request:
            # overlapping 60MB reads otherwise compete with the OPA children.
            with self.executable.open("rb") as binary:
                actual_digest = hashlib.file_digest(binary, "sha256").hexdigest()
            if actual_digest != self.executable_digest:
                raise ValueError("binary digest mismatch")
        except (OSError, ValueError, InvalidSignature) as error:
            raise ManualError("manual.policy_integrity", 503) from error

    def evaluate(self, request: dict[str, object]) -> dict[str, object]:
        encoded_request = canonical(request)
        frozen: dict[str, object] = json.loads(encoded_request)
        validate_contract("PolicyInput", frozen)
        self._verify()
        if frozen["bundle_digest"] != self.bundle_digest:
            raise ManualError("manual.policy_bundle_stale", 503)
        started = self.clock()
        try:
            with tempfile.TemporaryDirectory(prefix="care-link-policy-") as directory:
                source = Path(directory) / "manual.rego"
                source.write_bytes(self.source)
                result = subprocess.run(  # noqa: S603
                    [
                        str(self.executable),
                        "eval",
                        "--format=json",
                        "--stdin-input",
                        "--data",
                        str(source),
                        "data.care_link.manual.allow",
                    ],
                    input=encoded_request,
                    capture_output=True,
                    timeout=0.5,
                    check=False,
                )
            if result.returncode or len(result.stdout) > 65536:
                raise ValueError("OPA evaluation unavailable")
            parsed = json.loads(result.stdout)
            allowed = parsed["result"][0]["expressions"][0]["value"]
            if type(allowed) is not bool:
                raise ValueError("OPA returned no boolean decision")
        except (OSError, ValueError, KeyError, IndexError, subprocess.TimeoutExpired) as error:
            raise ManualError("manual.policy_unavailable", 503) from error
        if self.clock() >= started + timedelta(seconds=0.75):
            raise ManualError("manual.policy_deadline", 503)
        decision: dict[str, object] = {
            "decision_id": str(uuid4()),
            "decision": "PERMIT" if allowed else "DENY",
            "binding_digest": hashlib.sha256(encoded_request).hexdigest(),
            "reasons": ["CURRENT_SCOPE" if allowed else "NOT_AUTHORIZED"],
            "obligations": [{"kind": "audit_before_effect"}],
            "versions": frozen["versions"],
            "bundle_digest": self.bundle_digest,
            "expires_at": (started + timedelta(seconds=0.75)).isoformat().replace("+00:00", "Z"),
        }
        validate_contract("PolicyDecision", decision)
        return decision
