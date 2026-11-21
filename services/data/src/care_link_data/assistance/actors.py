"""Ephemeral, task-bound initiating authority ceiling, never persisted credentials.

Restart intentionally loses the ceiling. A fresh authenticated actor command
must resume the task; durable counters, source versions and fences remain in DB.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from care_link_domain import Actor, ManualError


@dataclass(frozen=True, repr=False)
class BoundActor:
    actor: Actor
    deadline: datetime


class TaskActors:
    def __init__(self, clock: Callable[[], datetime], fresh: Callable[[Actor], Actor]) -> None:
        self.clock, self.fresh = clock, fresh
        self._values: dict[str, BoundActor] = {}
        self._lock = threading.Lock()

    def bind(self, task_id: str, actor: Actor, task_deadline: datetime) -> None:
        deadline = min(self.clock() + timedelta(seconds=60), task_deadline, actor.expires_at)
        if deadline <= self.clock():
            raise ManualError("assistance.actor_resumption_required", 409)
        with self._lock:
            self._values = {k: v for k, v in self._values.items() if v.deadline > self.clock()}
            self._values[task_id] = BoundActor(replace(actor, request_deadline=None), deadline)

    def resolve(self, task_id: str) -> Actor:
        with self._lock:
            bound = self._values.get(task_id)
        if bound is None or bound.deadline <= self.clock():
            raise ManualError("assistance.actor_resumption_required", 409)
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
