"""Server-configured review context; host labels never grant actor authority."""

from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID


@dataclass(frozen=True)
class ReviewContext:
    origin: str
    run_id: str
    slot_id: str
    account_id: str
    role: str
    provider_subject: str | None = None
    state: str = "active"
    mode: str | None = None
    authentication_mode: str | None = None
    environment: str | None = None
    expires_at: str | None = None
    started_at: str | None = None

    def __post_init__(self) -> None:
        url = urlsplit(self.origin)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.path
            or url.query
            or url.fragment
        ):
            raise ValueError("Exact HTTPS review origin required")
        for value in (self.run_id, self.account_id):
            if str(UUID(value)) != value:
                raise ValueError("Canonical review context UUID required")
        roles = {
            "participant": "pid",
            "pid": "pid",
            "carer": "carer",
            "professional": "professional_participant",
            "worker1": "worker",
            "worker2": "worker",
            "supervisor": "supervisor",
        }
        if roles.get(self.slot_id) != self.role or self.state not in {
            "active",
            "closing",
            "closed",
        }:
            raise ValueError("Explicit review actor slot/state required")
        if self.provider_subject is not None and not self.provider_subject:
            raise ValueError("Nonempty provider subject required")

    def binding(self) -> dict[str, object]:
        return {
            "review_run_id": self.run_id,
            "review_slot_id": self.slot_id,
            "review_origin": self.origin,
        }
