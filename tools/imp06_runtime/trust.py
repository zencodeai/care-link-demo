"""Turn protected proxy attestation into runtime peer metadata.

The existing verifier checks kernel socket custody and current fence authority
before these headers can be consumed. Public headers alone always fail.
"""

import re
from collections.abc import Callable
from datetime import UTC, datetime

from care_link_domain import ManualError, WorkloadPeer
from care_link_workload_trust import BackendVerifier, UnixFenceClient
from fastapi import Request


def runtime_verifier(verify: BackendVerifier) -> Callable[[Request], WorkloadPeer]:
    def peer(request: Request) -> WorkloadPeer:
        if not verify(request, "runtime"):
            raise ManualError("assistance.runtime_required", 403)
        digest = request.headers.get("x-care-link-certificate-digest", "")
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ManualError("assistance.runtime_attestation_required", 403)
        return WorkloadPeer(
            "spiffe://care-link.demo/demo/runtime",
            int(request.headers["x-care-link-fence-generation"]),
            digest,
            datetime.fromisoformat(request.headers["x-care-link-certificate-expires-at"]),
        )

    return peer


def current_runtime(fences: UnixFenceClient) -> Callable[[WorkloadPeer], bool]:
    def current(peer: WorkloadPeer) -> bool:
        from care_link_workload_trust import TrustDenied

        try:
            state = fences.read()
            return (
                peer.workload_id == "spiffe://care-link.demo/demo/runtime"
                and state.admits(peer.workload_id)
                and state.generation == peer.fence_generation
                and peer.certificate_expires_at > datetime.now(UTC)
            )
        except (TrustDenied, OSError, ValueError):
            return False

    return current
