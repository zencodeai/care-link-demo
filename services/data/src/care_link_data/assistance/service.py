"""Authoritative optional assistance. Runtime proposals never own actor authority."""

import json
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from datetime import timedelta
from typing import cast
from uuid import uuid4

from care_link_contracts import validate_contract
from care_link_domain import Actor, ManualError, WorkloadPeer
from care_link_knowledge import CatalogDenied, KnowledgeCatalog

from ..engine import Engine
from ..store import Record, Transaction, instant, number, text
from ..values import digest, dt, object_value, stamp
from .actors import TaskActors
from .profiles import BUDGETS, FIELDS, PROFILES, assert_goal, assert_profile
from .records import Kind
from .records import read as read_record
from .records import save as save_record


def _disabled(_function: str) -> bool:
    return False


def _runtime_denied(_peer: WorkloadPeer) -> bool:
    return False


class AssistanceService:
    def __init__(
        self,
        engine: Engine,
        *,
        admitted: Callable[[str], bool] | None = None,
        runtime_current: Callable[[WorkloadPeer], bool] | None = None,
        knowledge: KnowledgeCatalog | None = None,
        knowledge_regions: Mapping[str, str] | None = None,
    ) -> None:
        self.engine = engine
        self.admitted: Callable[[str], bool] = admitted or _disabled
        # A release admission is distinct from live runtime workload authority.
        self.runtime_current: Callable[[WorkloadPeer], bool] = runtime_current or _runtime_denied
        self.actors = TaskActors(engine.clock, engine.current_actor)
        self.knowledge = knowledge
        self.knowledge_regions = dict(knowledge_regions or {})
        if any(k != "CA-XX" or v != "CA-ON" for k, v in self.knowledge_regions.items()):
            raise ValueError("explicit synthetic CA-XX to CA-ON scenario binding required")

    def read(self, tx: Transaction, kind: Kind, identifier: str) -> Record:
        return read_record(tx, kind, identifier, self.engine.cipher, lock=kind != "invocation")

    def save(self, tx: Transaction, kind: Kind, value: Record, principal: str, sid: str) -> None:
        new = (
            tx.connection.execute(
                "SELECT id FROM assistance.locator WHERE id=%s", (value["id"],)
            ).fetchone()
            is None
            if kind in {"task", "draft"}
            else True
        )
        save_record(tx, kind, value, principal, sid, self.engine.cipher)
        if new:
            session = tx.get("session", sid)
            if session is None:
                raise ManualError("assistance.not_found", 404)
            aggregate = {
                "task": "assistance_task",
                "draft": "assistance_draft",
                "invocation": "assistance_observation",
            }[kind]
            self.engine.register_copy(tx, session, aggregate, text(value, "id"))

    def replay(
        self, tx: Transaction, key: str, action: str, data: Record, target: str
    ) -> Record | None:
        old = tx.connection.execute(
            "SELECT action,request_digest,response_ciphertext "
            "FROM assistance.operation WHERE id=%s",
            (key,),
        ).fetchone()
        if old is None:
            return None
        if old["action"] != action or old["request_digest"] != digest(
            {"target": target, "data": data}
        ):
            raise ManualError("assistance.idempotency_conflict", 409)
        return object_value(
            json.loads(self.engine.cipher.decrypt(text(old, "response_ciphertext")))
        )

    def receipt(
        self,
        tx: Transaction,
        key: str,
        action: str,
        data: Record,
        target: str,
        result: Record,
        actor: Actor,
        sid: str,
    ) -> Record:
        tx.connection.execute(
            "INSERT INTO assistance.operation VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                key,
                actor.account_id,
                sid,
                action,
                digest({"target": target, "data": data}),
                target,
                "task" if action.startswith("task_") else "draft",
                self.engine.cipher.encrypt(json.dumps(result, sort_keys=True)),
            ),
        )
        return result

    def actor_for_task(self, task_id: str) -> Actor:
        return self.actors.resolve(task_id)

    def bind_actor(self, task: Record, actor: Actor) -> None:
        self.actors.bind(text(task, "id"), actor, dt(task["deadline"]))

    def availability(self, actor: Actor) -> Record:
        actor = self.engine.current_actor(actor)
        functions = [f for f in PROFILES if actor.role in PROFILES[f] and self.admitted(f)]
        return {
            "available": bool(functions),
            "functions": functions,
            "reason": None if functions else "assistance.function_disabled",
        }

    def transaction(
        self, actor: Actor, sid: str, action: str, data: Record
    ) -> AbstractContextManager[tuple[Transaction, Actor, Record]]:
        return self.engine.assistance_transaction(actor, sid, action, data)

    def _session(self, actor: Actor, kind: str, identifier: str) -> str:
        # Discovery releases metadata only; final locks and RLS enforce current scope.
        current = self.engine.current_actor(actor)
        if kind not in {"task", "draft"}:
            raise ValueError("Invalid discovery")
        with self.engine.store.transaction(current, None, locked=False) as tx:
            row = tx.connection.execute(
                "SELECT session_id FROM assistance.locator WHERE kind=%s AND id=%s",
                (kind, identifier),
            ).fetchone()
            if row is None or row["session_id"] is None:
                raise ManualError("assistance.not_found", 404)
            return str(row["session_id"])

    @staticmethod
    def view(task: Record) -> Record:
        names = (
            "id",
            "revision",
            "function",
            "scope",
            "state",
            "human_owner_id",
            "deadline",
            "budgets",
            "steps_used",
            "tools_used",
            "control_epoch",
            "completion",
            "safe_reason",
            "binding",
        )
        value = {name: task[name] for name in names}
        validate_contract("TaskView", value)
        return value

    def sources(self, tx: Transaction, task: Record) -> list[Record]:
        scope = object_value(task["scope"])
        fields = cast(list[str], scope["fields"])
        result: list[Record] = []
        rows = tx.rows("assertion", session_id=task["session_id"], limit=100)
        if len(rows) == 100:
            raise ManualError("assistance.reduce_scope", 409)
        superseded = {row["supersedes_id"] for row in rows if row["supersedes_id"]}
        for row in rows:
            if row["id"] in superseded:
                continue
            if row["field_key"] not in fields:
                continue
            value = json.loads(self.engine.cipher.decrypt(text(row, "value_ciphertext")))
            ref: Record = {
                "kind": "assertion",
                "id": row["id"],
                "revision": str(row["revision"]),
                "digest": digest(value),
                "observed_at": stamp(instant(row, "effective_at")),
                "verification": row["verification"],
            }
            result.append(
                {"ref": ref, "text": json.dumps(value, ensure_ascii=False, sort_keys=True)}
            )
        if len(result) > 32:
            raise ManualError("assistance.reduce_scope", 409)
        if self.knowledge is not None:
            session = tx.get("session", text(task, "session_id"))
            if (
                session is None
                or self.knowledge_regions.get(str(session.get("jurisdiction"))) != "CA-ON"
            ):
                raise ManualError("assistance.knowledge_scope_unavailable", 409)
            # Search uses only the already-permitted projection. No cross-client
            # records, external URLs, embeddings or model-chosen stores exist.
            query = (" ".join(text(item, "text") for item in result) or "support handoff")[:500]
            try:
                if "knowledge_sources" in task:
                    entries = self.knowledge.resolve_sources(
                        "worker",
                        text(session, "locale"),
                        cast(list[Record], task["knowledge_sources"]),
                        now=self.engine.clock(),
                    )
                else:
                    entries = self.knowledge.search(
                        "worker", text(session, "locale"), query, now=self.engine.clock()
                    )
            except CatalogDenied as error:
                raise ManualError("assistance.knowledge_unavailable", 503) from error
            result.extend(
                {
                    "ref": entry["source"],
                    "text": entry["text"],
                    "title": entry["title"],
                    "source_url": entry["source_url"],
                    "source_title": entry["source_title"],
                }
                for entry in entries
            )
        if len(result) > 32:
            raise ManualError("assistance.reduce_scope", 409)
        return result

    def knowledge_current(self, task: Record) -> bool:
        expected = self.knowledge.digest if self.knowledge is not None else None
        if task.get("knowledge_digest") != expected:
            return False
        if self.knowledge is None:
            return True
        if self.knowledge_regions.get(str(task.get("knowledge_scenario"))) != "CA-ON":
            return False
        try:
            return self.knowledge.sources_current(
                "worker",
                text(task, "knowledge_locale"),
                cast(list[Record], task.get("knowledge_sources", [])),
                now=self.engine.clock(),
            )
        except (CatalogDenied, ManualError):
            return False

    def _check(self, task: Record, versions: Record, *, active: bool = True) -> None:
        if active and (
            task["state"] in {"completed", "failed", "cancelled"}
            or dt(task["deadline"]) <= self.engine.clock()
        ):
            raise ManualError("assistance.task_terminal", 409)
        if task["source_vector"] != versions:
            raise ManualError("assistance.sources_changed", 409)
        if not self.knowledge_current(task):
            raise ManualError("assistance.knowledge_changed", 409)
        if not self.admitted(text(task, "function")):
            raise ManualError("assistance.function_disabled", 409)

    def task_create(self, actor: Actor, key: str, data: Record) -> Record:
        validate_contract("TaskCreate", data)
        binding, scope = object_value(data["binding"]), dict(object_value(data["scope"]))
        if binding["kind"] != "session" or binding["session_id"] != scope["session_id"]:
            raise ManualError("assistance.binding_unavailable", 409)
        if (
            scope["purpose"] != "support"
            or scope["recipient_id"] is not None
            or not set(cast(list[str], scope["fields"])) <= FIELDS
        ):
            raise ManualError("assistance.scope_unavailable", 409)
        assert_profile(text(data, "function"), actor.role)
        assert_goal(text(data, "function"), text(data, "goal"), text(data, "completion"))
        if not self.admitted(text(data, "function")):
            raise ManualError("assistance.function_disabled", 409)
        sid = text(binding, "session_id")
        with self.transaction(actor, sid, "task_create", data) as (tx, current, versions):
            session = tx.get("session", sid)
            if (
                session is None
                or scope["subject_id"] not in {None, session["persona_id"]}
                or data["expected_revision"] != str(number(session, "revision"))
            ):
                raise ManualError("assistance.stale_scope", 409)
            scope["subject_id"] = session["persona_id"]
            previous = self.replay(tx, key, "task_create", data, sid)
            if previous is not None:
                self.bind_actor(previous, current)
                return previous
            task: Record = {
                "id": str(uuid4()),
                "revision": "1",
                "function": data["function"],
                "scope": scope,
                "binding": binding,
                "state": "scoped",
                "human_owner_id": current.account_id,
                "deadline": stamp(self.engine.clock() + timedelta(seconds=120)),
                "budgets": BUDGETS.copy(),
                "steps_used": 0,
                "tools_used": 0,
                "proposals_used": 0,
                "control_epoch": versions["control_epoch"],
                "completion": data["completion"],
                "goal": data["goal"],
                "safe_reason": None,
                "session_id": sid,
                "source_vector": versions,
                "fence": 0,
                "lease": None,
                "draft_id": None,
                "inputs": data["inputs"],
                "knowledge_digest": self.knowledge.digest if self.knowledge else None,
                "knowledge_locale": session["locale"],
                "knowledge_scenario": session["jurisdiction"],
            }
            admitted_refs = [item["ref"] for item in self.sources(tx, task)]
            task["knowledge_sources"] = [
                ref for ref in admitted_refs if object_value(ref)["kind"] == "protocol"
            ]
            if any(ref not in admitted_refs for ref in cast(list[object], data["inputs"])):
                raise ManualError("assistance.invalid_source", 409)
            self.save(tx, "task", task, current.account_id, sid)
            self.bind_actor(task, current)
            return self.receipt(tx, key, "task_create", data, sid, self.view(task), current, sid)

    def task_read(self, actor: Actor, task_id: str) -> Record:
        sid = self._session(actor, "task", task_id)
        with self.transaction(actor, sid, "task_read", {"id": task_id}) as (
            tx,
            _current,
            _versions,
        ):
            return self.view(self.read(tx, "task", task_id))

    def task_context(self, actor: Actor, task_id: str) -> Record:
        sid = self._session(actor, "task", task_id)
        with self.transaction(actor, sid, "assistance_task_context", {"id": task_id}) as (
            tx,
            _current,
            versions,
        ):
            task = self.read(tx, "task", task_id)
            available = (
                task["source_vector"] == versions
                and self.admitted(text(task, "function"))
                and self.knowledge_current(task)
            )
            return {
                "task": self.view(task),
                "draft_id": task["draft_id"],
                "available": available,
                "reason": None if available else "assistance.sources_changed",
                "execution_fence": str(task["fence"]),
            }

    def task_cancel(self, actor: Actor, key: str, data: Record, task_id: str) -> Record:
        validate_contract("RevisionCommand", data)
        sid = self._session(actor, "task", task_id)
        with self.transaction(actor, sid, "task_cancel", data) as (tx, current, _versions):
            self.actors.revoke(task_id)
            previous = self.replay(tx, key, "task_cancel", data, task_id)
            if previous is not None:
                return previous
            task = self.read(tx, "task", task_id)
            if task["state"] == "cancelled":
                return self.receipt(
                    tx, key, "task_cancel", data, task_id, self.view(task), current, sid
                )
            if data["expected_revision"] != task["revision"]:
                raise ManualError("assistance.stale_revision", 409)
            task.update(
                state="cancelled",
                fence=cast(int, task["fence"]) + 1,
                lease=None,
                revision=str(int(text(task, "revision")) + 1),
            )
            self.save(tx, "task", task, current.account_id, sid)
            return self.receipt(
                tx, key, "task_cancel", data, task_id, self.view(task), current, sid
            )

    def task_revise(self, actor: Actor, key: str, data: Record, task_id: str) -> Record:
        validate_contract("TaskCreate", data)
        sid = self._session(actor, "task", task_id)
        with self.transaction(actor, sid, "task_revise", data) as (tx, current, versions):
            previous = self.replay(tx, key, "task_revise", data, task_id)
            if previous is not None:
                self.bind_actor(previous, current)
                return previous
            task = self.read(tx, "task", task_id)
            if data["expected_revision"] != task["revision"]:
                raise ManualError("assistance.stale_revision", 409)
            if data["binding"] != task["binding"] or data["scope"] != task["scope"]:
                raise ManualError("assistance.scope_revision_unavailable", 409)
            assert_profile(text(data, "function"), current.role)
            assert_goal(text(data, "function"), text(data, "goal"), text(data, "completion"))
            if not self.admitted(text(data, "function")):
                raise ManualError("assistance.function_disabled", 409)
            if (
                task["state"] in {"failed", "cancelled"}
                or dt(task["deadline"]) <= self.engine.clock()
            ):
                raise ManualError("assistance.task_terminal", 409)
            session = tx.get("session", sid)
            if session is None:
                raise ManualError("assistance.not_found", 404)
            task["knowledge_locale"] = session["locale"]
            task["knowledge_scenario"] = session["jurisdiction"]
            # Only this explicit actor revision may select a fresh evidence
            # set. Existing task reads/generation never rerank effective entries.
            task.pop("knowledge_sources", None)
            admitted_refs = [item["ref"] for item in self.sources(tx, task)]
            if any(ref not in admitted_refs for ref in cast(list[object], data["inputs"])):
                raise ManualError("assistance.invalid_source", 409)
            task.update(
                function=data["function"],
                inputs=data["inputs"],
                completion=data["completion"],
                goal=data["goal"],
                knowledge_digest=self.knowledge.digest if self.knowledge else None,
                knowledge_sources=[
                    ref for ref in admitted_refs if object_value(ref)["kind"] == "protocol"
                ],
                proposal_reservation=None,
                source_vector=versions,
                revision=str(int(text(task, "revision")) + 1),
                fence=cast(int, task["fence"]) + 1,
                lease=None,
                draft_id=None,
                state="scoped",
            )
            self.save(tx, "task", task, current.account_id, sid)
            self.bind_actor(task, current)
            return self.receipt(
                tx, key, "task_revise", data, task_id, self.view(task), current, sid
            )
