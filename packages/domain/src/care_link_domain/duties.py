"""Immutable workload duty evidence; never a human identity or approval slot."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class DutyScope:
    session_id: str | None
    subject_id: str | None
    purpose: str
    fields: tuple[str, ...] = ()
    recipient_id: str | None = None

    def wire(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "subject_id": self.subject_id,
            "purpose": self.purpose,
            "fields": list(self.fields),
            "recipient_id": self.recipient_id,
        }


@dataclass(frozen=True)
class DutyActor:
    actor_id: str
    workload_id: str
    duty_id: str
    evidence_id: str
    duty_artifact_digest: str
    scope: DutyScope
    action: str
    request_digest: str
    nonce: str
    issued_at: datetime
    expires_at: datetime
    signature: str
    workload_revision: int
    duty_revision: int
    credential_ref: str
    job_id: str | None = None
    task_id: str | None = None
    originating_human_id: str | None = None
    request_deadline: datetime | None = None

    @property
    def account_id(self) -> str:
        """DB context key only; actor_kind remains workload everywhere."""
        return self.actor_id

    def wire(self) -> dict[str, object]:
        return {
            "kind": "workload",
            "actor_id": self.actor_id,
            "workload_id": self.workload_id,
            "duty_id": self.duty_id,
            "job_id": self.job_id,
            "task_id": self.task_id,
            "originating_human_id": self.originating_human_id,
        }

    def evidence(self) -> dict[str, object]:
        def stamp(value: datetime) -> str:
            return value.isoformat().replace("+00:00", "Z")

        return {
            "kind": "workload_duty",
            "id": self.evidence_id,
            "actor_id": self.actor_id,
            "duty_artifact_digest": self.duty_artifact_digest,
            "scope": self.scope.wire(),
            "action": self.action,
            "request_digest": self.request_digest,
            "nonce": self.nonce,
            "issued_at": stamp(self.issued_at),
            "expires_at": stamp(self.expires_at),
            "signature": self.signature,
            "duty_id": self.duty_id,
            "workload_id": self.workload_id,
        }


class DutyAuthorityPort(Protocol):
    def current(
        self, actor: DutyActor, action: str, request_digest: str, scope: DutyScope
    ) -> DutyActor: ...
