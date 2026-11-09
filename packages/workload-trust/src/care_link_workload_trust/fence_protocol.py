"""Typed cross-custodian restriction interface, with no positive cache or unfence."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol
from uuid import UUID

from .fence import FenceState, TrustDenied


@dataclass(frozen=True)
class FenceReceipt:
    command_id: str
    peer: str
    generation: int
    durable: bool


class RestrictiveFence(Protocol):
    def current(self) -> FenceState: ...
    def restrict(self, peer: str, command_id: str, expected_generation: int) -> FenceReceipt: ...
    def receipt(self, command_id: str) -> FenceReceipt | None: ...


class FenceReader(Protocol):
    def read(self) -> FenceState: ...


class WorkloadMap:
    """Immutable operator-provisioned UUID→exact SPIFFE mapping, never token claims."""

    def __init__(self, subjects: Mapping[str, str]) -> None:
        valid = re.compile(r"spiffe://care-link\.demo/[a-z0-9_-]+/[a-z0-9_-]+\Z")
        if not subjects or len(set(subjects.values())) != len(subjects):
            raise ValueError("unique configured workload identities required")
        for subject, peer in subjects.items():
            if str(UUID(subject)) != subject or valid.fullmatch(peer) is None:
                raise ValueError("canonical subject UUID and demo SPIFFE identity required")
        self.subjects: Mapping[str, str] = MappingProxyType(dict(subjects))

    def resolve(self, subject_id: str) -> str:
        try:
            return self.subjects[subject_id]
        except KeyError as error:
            raise TrustDenied("unknown workload subject") from error


def valid_command(value: str) -> bool:
    if re.fullmatch(r"[0-9a-f]{64}", value):
        return True
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False
