"""Framework-independent authority ports for the protected manual service.

These values originate in authenticated server adapters, never browser JSON.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


class ManualError(Exception):
    def __init__(self, code: str, status: int = 403) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class Actor:
    account_id: str
    role: str
    identity_revision: int
    role_revision: int
    auth_time: datetime
    mfa: bool
    browser_session_digest: str
    transport_generation: int
    credential_ref: str = field(repr=False)
    expires_at: datetime
    identity_evidence_id: str
    request_deadline: datetime | None = None
    review_run_id: str | None = None
    review_slot_id: str | None = None
    review_origin: str | None = None


@dataclass(frozen=True)
class JournalState:
    journal_id: str
    generation: int
    tip: int
    tip_digest: str
    restriction_barrier: int
    serving_generation: int
    observed_at: datetime


class AuthorityPort(Protocol):
    def current(self, actor: Actor) -> Actor: ...

    def recovery_proof(
        self, actor: Actor, ceremony_id: str, session_id: str, family_id: str
    ) -> None: ...


class PolicyPort(Protocol):
    def evaluate(self, request: dict[str, object]) -> dict[str, object]: ...


class JournalPort(Protocol):
    def head(self) -> JournalState: ...

    def append(self, request: dict[str, object]) -> JournalState: ...


class CipherPort(Protocol):
    def encrypt(self, value: str) -> str: ...

    def decrypt(self, value: str) -> str: ...


class ChannelPort(Protocol):
    def current(
        self, account_id: str, browser_session_digest: str, transport_generation: int
    ) -> bool: ...


@dataclass(frozen=True)
class WorkloadPeer:
    """Server-observed attested peer, never deserialized from caller JSON."""

    workload_id: str
    fence_generation: int
    certificate_digest: str
    certificate_expires_at: datetime
