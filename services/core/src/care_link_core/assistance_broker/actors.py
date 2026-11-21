"""Broker-held capability ceiling: exact actor/task, sixty seconds, no raw token.

Restart loses the ceiling and requires a fresh authenticated actor command.
Persistent task counters remain at the data gateway. This registry is never
serialized to runtime, the browser, context items or model output.
"""

import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

from care_link_domain import Actor, ManualError
from care_link_knowledge import CatalogDenied, KnowledgeCatalog

from ..assistance import AssistanceGateway
from .ports import Record


class ActorTasks:
    def __init__(self, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.clock = clock
        self.bindings: dict[str, tuple[Actor, datetime]] = {}
        self.lock = threading.Lock()

    def bind(self, actor: Actor, task: Record) -> None:
        if task["human_owner_id"] != actor.account_id:
            raise ManualError("assistance.owner_mismatch", 403)
        expiry = min(
            self.clock() + timedelta(seconds=60),
            actor.expires_at,
            datetime.fromisoformat(cast(str, task["deadline"])),
        )
        with self.lock:
            self.bindings = {
                key: entry for key, entry in self.bindings.items() if entry[1] > self.clock()
            }
            if len(self.bindings) >= 1000:
                raise ManualError("assistance.capacity_unavailable", 503)
            self.bindings[cast(str, task["id"])] = (actor, expiry)

    def resolve(self, task_id: str) -> Actor:
        with self.lock:
            bound = self.bindings.get(task_id)
            if bound is None or bound[1] <= self.clock():
                self.bindings.pop(task_id, None)
                raise ManualError("assistance.actor_resumption_required", 409)
            # A new operation gets its own bounded authorization deadline; this
            # never renews actor/MFA expiry or the broker capability ceiling.
            return replace(bound[0], request_deadline=self.clock() + timedelta(seconds=1))

    def revoke(self, task_id: str) -> None:
        with self.lock:
            self.bindings.pop(task_id, None)


class BoundTaskGateway:
    def __init__(
        self,
        gateway: AssistanceGateway,
        actors: ActorTasks,
        *,
        enqueue: Callable[[Record], None] | None = None,
        remove: Callable[[str], None] | None = None,
        knowledge: KnowledgeCatalog | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.gateway, self.actors = gateway, actors
        self.enqueue, self.remove = enqueue, remove
        self.catalog, self.clock = knowledge, clock

    def knowledge(self, actor: Actor, data: Record) -> Record:
        from care_link_contracts import validate_contract

        validate_contract("KnowledgeQuery", data)
        if self.catalog is None:
            raise ManualError("assistance.knowledge_unavailable", 503)
        try:
            entries = self.catalog.search(
                actor.role, str(data["locale"]), str(data["query"]), now=self.clock()
            )
        except CatalogDenied as error:
            raise ManualError("assistance.knowledge_scope_denied", 403) from error
        return {
            "catalog_digest": self.catalog.digest,
            "entries": entries,
            "notice": "synthetic_demo_information",
        }

    def task_create(self, actor: Actor, key: str, data: Record) -> Record:
        task = self.gateway.task_create(actor, key, data)
        self.actors.bind(actor, task)
        if self.enqueue:
            self.enqueue(task)
        return task

    def task_revise(self, actor: Actor, key: str, data: Record, task_id: str) -> Record:
        task = self.gateway.task_revise(actor, key, data, task_id)
        self.actors.bind(actor, task)
        if self.enqueue:
            self.enqueue(task)
        return task

    def task_cancel(self, actor: Actor, key: str, data: Record, task_id: str) -> Record:
        task = self.gateway.task_cancel(actor, key, data, task_id)
        self.actors.revoke(task_id)
        if self.remove:
            self.remove(task_id)
        return task

    def task_read(self, actor: Actor, task_id: str) -> Record:
        return self.gateway.task_read(actor, task_id)

    def task_context(self, actor: Actor, task_id: str) -> Record:
        return self.gateway.task_context(actor, task_id)

    def draft_read(self, actor: Actor, draft_id: str) -> Record:
        return self.gateway.draft_read(actor, draft_id)

    def draft_context(self, actor: Actor, draft_id: str) -> Record:
        return self.gateway.draft_context(actor, draft_id)

    def draft_review(self, actor: Actor, key: str, data: Record, draft_id: str) -> Record:
        return self.gateway.draft_review(actor, key, data, draft_id)
