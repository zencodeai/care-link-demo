"""Bridge for applications behind the protected Envoy-to-backend Unix socket.

The ASGI server's connection hook must mint SocketPeer from the actual accepted
socket. A normal public ASGI listener has no such capsule and always denies.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from .fence import TrustDenied
from .fence_protocol import FenceReader
from .unix_server import PeerSocket, peer_uid
from .verification import IDENTITY, PeerRule, route_matches

SOCKET_PEER_SCOPE_KEY = "care_link.kernel_socket_peer"


@dataclass(frozen=True)
class SocketPeer:
    uid: int | None


def socket_peer(connection: PeerSocket) -> SocketPeer:
    return SocketPeer(peer_uid(connection))


class _URL(Protocol):
    @property
    def path(self) -> str: ...


class RequestMetadata(Protocol):
    @property
    def scope(self) -> Mapping[str, object]: ...
    @property
    def headers(self) -> Mapping[str, str]: ...
    @property
    def method(self) -> str: ...
    @property
    def url(self) -> _URL: ...


class BackendVerifier:
    def __init__(
        self,
        proxy_uid: int,
        rules: tuple[PeerRule, ...],
        fences: FenceReader,
        *,
        backend_uid: int,
        local_spiffe_id: str | None = None,
    ) -> None:
        if (
            proxy_uid < 0
            or not rules
            or backend_uid != os.geteuid()
            or backend_uid == proxy_uid
            or (local_spiffe_id is not None and IDENTITY.fullmatch(local_spiffe_id) is None)
        ):
            raise ValueError("exact distinct backend/proxy UID custody and peer routes required")
        self.proxy_uid, self.rules, self.fences = proxy_uid, rules, fences
        self.local_spiffe_id = local_spiffe_id

    def __call__(self, request: RequestMetadata, peer_role: str) -> bool:
        capsule = request.scope.get(SOCKET_PEER_SCOPE_KEY)
        if not isinstance(capsule, SocketPeer) or capsule.uid != self.proxy_uid:
            return False
        # ASGI separates the query from url.path. Internal task/inference/data
        # commands admit no query adapter, even over the protected proxy socket.
        if request.url.path.startswith("/internal/") and request.scope.get("query_string") not in (
            None,
            b"",
        ):
            return False
        peer = request.headers.get("x-care-link-verified-spiffe", "")
        if not any(
            rule.spiffe_id == peer
            and peer.rsplit("/", 1)[-1] == peer_role
            and route_matches(rule.routes, request.method, request.url.path)
            for rule in self.rules
        ):
            return False
        try:
            revision = request.headers.get("x-care-link-fence-generation", "")
            if (
                not revision.isascii()
                or not revision.isdecimal()
                or (len(revision) > 1 and revision[0] == "0")
            ):
                return False
            expires = request.headers.get("x-care-link-certificate-expires-at", "")
            if not expires.endswith("Z"):
                return False
            deadline = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            state = self.fences.read()
            return (
                state.admits(peer)
                and (self.local_spiffe_id is None or state.admits(self.local_spiffe_id))
                and str(state.generation) == revision
                and datetime.now(UTC) < deadline
            )
        except (TrustDenied, ValueError):
            return False
