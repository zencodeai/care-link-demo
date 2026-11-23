"""Ephemeral, task-bound initiating authority ceiling, never persisted credentials.

Restart intentionally loses the ceiling. A fresh authenticated actor command
must resume the task; durable counters, source versions and fences remain in DB.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from care_link_domain import Actor, InferenceActorRequest, ManualError


@dataclass(frozen=True, repr=False)
class BoundActor:
    actor: Actor
    deadline: datetime
    revision: str


def anchor(actor: Actor) -> tuple[object, ...]:
    """The initiating identity and channel, apart from its one-use request proof."""
    return (
        actor.account_id,
        actor.role,
        actor.identity_revision,
        actor.role_revision,
        actor.auth_time,
        actor.mfa,
        actor.browser_session_digest,
        actor.transport_generation,
        actor.review_run_id,
        actor.review_slot_id,
        actor.review_origin,
    )


class TaskActors:
    def __init__(self, clock: Callable[[], datetime], fresh: Callable[[Actor], Actor]) -> None:
        self.clock, self.fresh = clock, fresh
        self._values: dict[str, BoundActor] = {}
        self._lock = threading.Lock()

    def bind(self, task_id: str, actor: Actor, task_deadline: datetime, revision: str) -> None:
        deadline = min(self.clock() + timedelta(seconds=60), task_deadline, actor.expires_at)
        if deadline <= self.clock():
            raise ManualError("assistance.actor_resumption_required", 409)
        with self._lock:
            self._values = {k: v for k, v in self._values.items() if v.deadline > self.clock()}
            self._values[task_id] = BoundActor(
                replace(actor, request_deadline=None), deadline, revision
            )

    def _binding(self, task_id: str) -> BoundActor:
        with self._lock:
            bound = self._values.get(task_id)
        if bound is None or bound.deadline <= self.clock():
            raise ManualError("assistance.actor_resumption_required", 409)
        return bound

    def revision(self, task_id: str) -> str:
        return self._binding(task_id).revision

    def refresh(
        self,
        command: InferenceActorRequest,
        mint: Callable[[InferenceActorRequest], Actor],
        *,
        job_deadline: datetime | None = None,
    ) -> Actor:
        bound = self._binding(command.task_id)
        if command.revision != bound.revision:
            raise ManualError("assistance.stale_revision", 409)
        now = self.clock()
        deadline = min(now + timedelta(seconds=1), bound.deadline)
        if job_deadline is not None:
            deadline = min(deadline, job_deadline)
        if now >= deadline:
            raise ManualError("assistance.inference_actor_expired", 409)
        actor = mint(command)
        if actor.request_deadline is None or anchor(actor) != anchor(bound.actor):
            raise ManualError("assistance.inference_actor_changed", 403)
        authority_deadline = min(deadline, actor.request_deadline, actor.expires_at)
        if self.clock() >= authority_deadline or self._binding(command.task_id) is not bound:
            raise ManualError("assistance.actor_resumption_required", 409)
        return replace(actor, request_deadline=authority_deadline)

    def resolve(self, task_id: str) -> Actor:
        bound = self._binding(task_id)
        # An immutable one-second request budget applies to each fresh operation;
        # neither this deadline nor the registry refreshes identity/MFA freshness.
        actor = self.fresh(
            replace(
                bound.actor,
                request_deadline=min(self.clock() + timedelta(seconds=1), bound.deadline),
            )
        )
        if self.clock() >= bound.deadline:
            raise ManualError("assistance.actor_resumption_required", 409)
        return actor

    def revoke(self, task_id: str) -> None:
        with self._lock:
            self._values.pop(task_id, None)
