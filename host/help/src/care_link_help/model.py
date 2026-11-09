"""Opaque-help values and authority ports; no persistence or HTTP dependencies."""

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

type Action = Literal["create", "status", "accept", "cancel"]
type Wire = dict[str, object]
type Clock = Callable[[], datetime]


def now_utc() -> datetime:
    return datetime.now(UTC)


def timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def canonical(value: Mapping[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


class HelpError(Exception):
    """Safe public failure, without credentials or content."""

    def __init__(self, code: str, status: int = 403) -> None:
        self.code = code
        self.status = status
        super().__init__(code)


@dataclass(frozen=True)
class BrowserContext:
    account_id: str
    role: str
    csrf_token: str


class BrowserSessions(Protocol):
    """Implemented by a separately scoped help-origin BFF, never caller claims."""

    def context(self, cookie: str) -> BrowserContext: ...

    def proof(self, cookie: str, origin: str) -> str: ...


class Authority(Protocol):
    """A fresh call over an authenticated, pinned workload channel."""

    def authorize(self, request: Wire) -> Wire: ...


@dataclass(frozen=True)
class Decision:
    principal_id: str
    nonce: str
    expires_at: datetime
    evidence_digest: str


class ReceiptVerifier(Protocol):
    def verify(self, request: Wire, receipt: Wire, principal_id: str) -> Decision: ...
