"""Explicit host recovery boundaries; values originate in authenticated adapters."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from care_link_domain import Actor, JournalState

from .capture import CaptureMetadata, QuarantineRestore


@dataclass(frozen=True)
class RecoveryHuman:
    account_id: str
    human_id: str
    role: str
    identity_revision: int
    role_revision: int
    expires_at: datetime


class RecoveryAuthority(Protocol):
    def current(self, actor: Actor, operation: str) -> RecoveryHuman: ...

    def approval(
        self,
        actor: Actor,
        ceremony_id: str,
        proposal_id: str,
        binding_digest: str,
        expires_at: datetime,
    ) -> RecoveryHuman: ...

    def still_current(self, human: RecoveryHuman) -> bool: ...


@dataclass(frozen=True)
class CaptureInput:
    objects: Mapping[str, bytes]
    metadata: CaptureMetadata
    capture_at: datetime


class CaptureSource(Protocol):
    def capture(self) -> CaptureInput: ...


class RecoveryTargets(Protocol):
    def create(self, staged: QuarantineRestore, metadata: dict[str, object]) -> None: ...

    def reconcile(
        self, target_id: str, head: JournalState, records: tuple[dict[str, object], ...]
    ) -> dict[str, object]: ...

    def inspect(self, target_id: str) -> str: ...

    def fence_all(self) -> None: ...

    def route(self, target_id: str) -> None: ...

    def enable(self, target_id: str, generation: int) -> None: ...

    def smoke(self, target_id: str, generation: int) -> bool: ...

    def state(self) -> tuple[str | None, int]: ...
