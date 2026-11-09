"""Explicit local workload trust interfaces; imports create no listeners or files."""

from .backend import SOCKET_PEER_SCOPE_KEY, BackendVerifier, SocketPeer, socket_peer
from .envoy import ProxyInputs, build_envoy, spire_registration
from .fence import FenceState, FenceStore, TrustDenied
from .fence_client import UnixFenceClient
from .fence_protocol import FenceReader, FenceReceipt, RestrictiveFence, WorkloadMap
from .fence_server import FenceServer
from .listeners import BrowserListener, OutboundListener, add_browser, add_outbound
from .socket_custody import SocketCustody
from .unix_server import AuthorizationServer, peer_uid
from .uvicorn_adapter import ProtectedUnixH11Protocol
from .verification import Admission, PeerRule, WorkloadEnforcer

__all__ = [
    "SOCKET_PEER_SCOPE_KEY",
    "BackendVerifier",
    "SocketPeer",
    "socket_peer",
    "Admission",
    "AuthorizationServer",
    "FenceState",
    "FenceStore",
    "FenceReader",
    "FenceReceipt",
    "FenceServer",
    "RestrictiveFence",
    "UnixFenceClient",
    "WorkloadMap",
    "BrowserListener",
    "OutboundListener",
    "add_browser",
    "add_outbound",
    "SocketCustody",
    "PeerRule",
    "ProxyInputs",
    "ProtectedUnixH11Protocol",
    "TrustDenied",
    "WorkloadEnforcer",
    "build_envoy",
    "peer_uid",
    "spire_registration",
]
