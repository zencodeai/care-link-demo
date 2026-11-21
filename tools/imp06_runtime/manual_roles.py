"""Explicit AI extension for the existing protected Core and Data surfaces."""

from dataclasses import dataclass
from pathlib import Path

from care_link_workload_trust import BackendVerifier, UnixFenceClient

from .provider_stop import ProviderStopAuthority
from .releases import ReleaseBindings
from .resources import KnowledgeResources


@dataclass(frozen=True)
class ManualRoleAssistance:
    releases: ReleaseBindings
    verifier: BackendVerifier
    fences: UnixFenceClient
    knowledge: KnowledgeResources
    inference_socket: Path | None = None
    provider_stop: ProviderStopAuthority | None = None

    def __post_init__(self) -> None:
        role = self.verifier.local_spiffe_id
        if not self.releases.knowledge_matches(self.knowledge.catalog.digest):
            raise ValueError("observed knowledge catalog differs from signed serving release")
        if role == "spiffe://care-link.demo/demo/core":
            if (
                self.inference_socket is None
                or not self.inference_socket.is_absolute()
                or self.provider_stop is not None
            ):
                raise ValueError("Core requires only its protected inference egress")
        elif role == "spiffe://care-link.demo/demo/data":
            if self.inference_socket is not None or self.provider_stop is None:
                raise ValueError("Data requires separate provider-stop verification authority")
        else:
            raise ValueError("assisted manual role must be Core or Data")
