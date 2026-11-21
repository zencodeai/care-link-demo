"""Ephemeral metadata dispatch; no actor credentials, patient content or execution.

Core queues explicit authenticated actor requests. An independently attested
runtime consumes one reference; Data leases and durable budgets still arbitrate
execution. Restart deliberately loses pending work and requires an actor retry
or revision. This queue provides no automatic retry or delivery guarantee.
"""

import threading
from collections import OrderedDict
from typing import Protocol, cast

from care_link_contracts import validate_contract
from care_link_domain import Actor, ManualError

from .actors import ActorTasks
from .ports import Record


class TaskContextPort(Protocol):
    def task_context(self, actor: Actor, task_id: str) -> Record: ...


class WorkQueue:
    def __init__(self, actors: ActorTasks, gateway: TaskContextPort) -> None:
        self.actors, self.gateway = actors, gateway
        self._pending: OrderedDict[str, str] = OrderedDict()
        self._lock = threading.Lock()

    def enqueue(self, task: Record) -> None:
        validate_contract("TaskView", task)
        if task["state"] != "scoped":
            return
        task_id, revision = str(task["id"]), str(task["revision"])
        with self._lock:
            if task_id not in self._pending and len(self._pending) >= 8:
                # The task may already be committed. Exact actor retry reuses
                # its idempotency key; never manufacture another task/revision.
                raise ManualError("assistance.capacity_unavailable", 503)
            self._pending[task_id] = revision

    def remove(self, task_id: str) -> None:
        with self._lock:
            self._pending.pop(task_id, None)

    def claim(self) -> Record:
        # A bounded snapshot prevents hostile callers from holding this request
        # open while another actor continuously adds work.
        for _ in range(8):
            with self._lock:
                if not self._pending:
                    break
                task_id, revision = self._pending.popitem(last=False)
            try:
                actor = self.actors.resolve(task_id)
                context = self.gateway.task_context(actor, task_id)
                validate_contract("AssistanceTaskContext", context)
                task = cast(Record, context["task"])
                if (
                    not context["available"]
                    or task["id"] != task_id
                    or task["revision"] != revision
                    or task["state"] != "scoped"
                    or "execution_fence" not in context
                ):
                    continue
                item: Record = {
                    "task_id": task_id,
                    "task_revision": revision,
                    "fence": context["execution_fence"],
                }
                validate_contract("RuntimeWorkItem", item)
                return item
            except ManualError:
                # Lost/revoked custody and inaccessible tasks are consumed,
                # never assigned fresh authority by a background worker.
                continue
        return {"task_id": None, "task_revision": None, "fence": None}
