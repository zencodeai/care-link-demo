"""Identity values and ports. No provider or storage side effects on import."""

from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

PRIVILEGED_ROLES = frozenset(
    {"worker", "supervisor", "receiver", "operator", "governance", "auditor", "security", "trainer"}
)
PARTICIPANT_ROLES = frozenset({"pid", "carer", "professional_participant"})


class IdentityError(Exception):
    """Safe failure: never includes tokens, URLs, submitted claims or private identity."""

    def __init__(self, code: str, status: int = 403) -> None:
        self.code = code
        self.status = status
        super().__init__(code)


class ExchangeUncertain(IdentityError):
    def __init__(self) -> None:
        super().__init__("identity.login_uncertain", 503)


def stamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def instant(value: object) -> datetime:
    if not isinstance(value, str):
        raise IdentityError("identity.invalid_time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise IdentityError("identity.invalid_time") from error
    if parsed.tzinfo is None:
        raise IdentityError("identity.invalid_time")
    return parsed.astimezone(UTC)


def text(record: dict[str, object], name: str) -> str:
    value = record.get(name)
    if not isinstance(value, str):
        raise IdentityError("identity.invalid_record", 503)
    return value


@dataclass(frozen=True)
class Principal:
    subject: str
    auth_time: datetime
    mfa: bool
    factors: tuple[str, ...]
    access_token: str
    expires_at: datetime


class Provider(Protocol):
    def authorization_url(self, state: str, nonce: str, verifier: str, fresh: bool) -> str: ...
    def exchange(self, code: str, verifier: str, nonce: str, fresh: bool) -> Principal: ...
    def active(self, access_token: str, subject: str) -> bool: ...
    def revoke(self, access_token: str) -> None: ...


class Transaction(Protocol):
    def get(self, kind: str, key: str) -> dict[str, object] | None: ...
    def put(self, kind: str, key: str, value: dict[str, object]) -> None: ...
    def delete(self, kind: str, key: str) -> None: ...
    def items(self, kind: str) -> Iterator[tuple[str, dict[str, object]]]: ...


class Store(Protocol):
    def transaction(self) -> AbstractContextManager[Transaction]: ...
