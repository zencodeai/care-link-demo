"""Leases, shared counters, server context and typed broker observations."""

import json
from collections.abc import Callable
from datetime import timedelta
from typing import cast
from uuid import uuid4

from care_link_contracts import validate_contract
from care_link_domain import Actor, ManualError, WorkloadPeer
from care_link_knowledge import CatalogDenied

from .. import projections
from ..assistance_jobs import InferenceAuthority
from ..store import Record, Transaction, text
from ..values import digest, dt, object_value, stamp
from .profiles import TOOLS
from .service import AssistanceService


class AssistanceExecution(AssistanceService):
    def _peer(self, peer: WorkloadPeer) -> str:
        if (
            peer.workload_id != "spiffe://care-link.demo/demo/runtime"
            or peer.certificate_expires_at <= self.engine.clock()
        ):
            raise ManualError("assistance.runtime_required")
        if not self.runtime_current(peer):
            raise ManualError("assistance.runtime_fenced", 409)
        return peer.workload_id

    def _stored_peer(self, task: Record) -> WorkloadPeer:
        lease = object_value(task["lease"]) if task["lease"] else {}
        if not lease or not isinstance(lease.get("owner_generation"), int):
            raise ManualError("assistance.stale_lease", 409)
        peer = WorkloadPeer(
            text(lease, "owner"),
            cast(int, lease["owner_generation"]),
            text(lease, "owner_certificate"),
            dt(lease.get("owner_certificate_expires_at")),
        )
        self._peer(peer)
        return peer

    def _lease(self, task: Record, data: Record, peer: WorkloadPeer) -> Record:
        owner = self._peer(peer)
        lease = object_value(task["lease"]) if task["lease"] else {}
        if (
            data.get("expected_task_revision", data.get("expected_revision")) != task["revision"]
            or data["fence"] != str(task["fence"])
            or not lease
            or data["step_id"] != lease["step_id"]
            or lease["owner"] != owner
            or lease.get("owner_generation") != peer.fence_generation
            or lease.get("owner_certificate") != peer.certificate_digest
            or lease.get("owner_certificate_expires_at") != stamp(peer.certificate_expires_at)
            or dt(lease["expires_at"]) <= self.engine.clock()
            or peer.certificate_expires_at <= self.engine.clock()
        ):
            raise ManualError("assistance.stale_lease", 409)
        self._stored_peer(task)
        return lease

    def step_lease(self, actor: Actor, task_id: str, data: Record, peer: WorkloadPeer) -> Record:
        validate_contract("LeaseCommand", data)
        owner = self._peer(peer)
        sid = self._session(actor, "task", task_id)
        with self.transaction(actor, sid, "step_lease", data) as (tx, current, versions):
            task = self.read(tx, "task", task_id)
            self._check(task, versions)
            if task["state"] == "awaiting_human":
                raise ManualError("assistance.human_resumption_required", 409)
            if data["expected_revision"] != task["revision"] or data["fence"] != str(task["fence"]):
                raise ManualError("assistance.stale_revision", 409)
            lease = object_value(task["lease"]) if task["lease"] else {}
            if lease and dt(lease["expires_at"]) > self.engine.clock():
                raise ManualError("RESOURCE_BUSY", 409)
            if task["steps_used"] == 4:
                raise ManualError("assistance.step_budget", 409)
            task["steps_used"] = cast(int, task["steps_used"]) + 1
            task["fence"] = cast(int, task["fence"]) + 1
            expiry = min(dt(task["deadline"]), self.engine.clock() + timedelta(seconds=10))
            task["lease"] = {
                "step_id": data["step_id"],
                "owner": owner,
                "owner_generation": peer.fence_generation,
                "owner_certificate": peer.certificate_digest,
                "owner_certificate_expires_at": stamp(peer.certificate_expires_at),
                "expires_at": stamp(expiry),
            }
            task["state"] = "planning"
            self.save(tx, "task", task, current.account_id, sid)
            return self._lease_view(task)

    @staticmethod
    def _lease_view(task: Record) -> Record:
        lease = object_value(task["lease"])
        return {
            "task_id": task["id"],
            "step_id": lease["step_id"],
            "fence": str(task["fence"]),
            "expires_at": lease["expires_at"],
            "task_revision": task["revision"],
        }

    def step_renew(self, actor: Actor, task_id: str, data: Record, peer: WorkloadPeer) -> Record:
        validate_contract("LeaseCommand", data)
        sid = self._session(actor, "task", task_id)
        with self.transaction(actor, sid, "step_renew", data) as (tx, current, versions):
            task = self.read(tx, "task", task_id)
            self._check(task, versions)
            lease = self._lease(task, data, peer)
            # Renewal never extends beyond five seconds from the current claim.
            if dt(lease["expires_at"]) - self.engine.clock() > timedelta(seconds=5):
                raise ManualError("assistance.renew_too_early", 409)
            lease["expires_at"] = stamp(
                min(dt(task["deadline"]), self.engine.clock() + timedelta(seconds=10))
            )
            self.save(tx, "task", task, current.account_id, sid)
            return self._lease_view(task)

    def reserve_proposal(self, actor: Actor, data: Record, peer: WorkloadPeer) -> Record:
        """Reserve before each model call or parser repair; rejected output still counts."""
        validate_contract("RuntimeInferenceRequest", data)
        tid = text(data, "task_id")
        sid = self._session(actor, "task", tid)
        with self.transaction(actor, sid, "inference_request", data) as (tx, current, versions):
            task = self.read(tx, "task", tid)
            self._check(task, versions)
            self._lease(task, data, peer)
            if cast(int, task["proposals_used"]) >= 2:
                raise ManualError("assistance.proposal_budget", 409)
            task["proposals_used"] = cast(int, task["proposals_used"]) + 1
            reservation = str(uuid4())
            task["proposal_reservation"] = reservation
            sources = self.sources(tx, task)
            self.save(tx, "task", task, current.account_id, sid)
            return {
                "reservation_id": reservation,
                "task": self.view(task),
                "sources": sources,
                "source_vector": versions,
                "goal": task.get("goal", "prepare_summary"),
            }

    def proposal_submit(
        self, actor: Actor, data: Record, peer: WorkloadPeer, reservation_id: str
    ) -> Record:
        validate_contract("Proposal", data)
        tid = text(data, "task_id")
        sid = self._session(actor, "task", tid)
        with self.transaction(actor, sid, "proposal_submit", data) as (tx, current, versions):
            task = self.read(tx, "task", tid)
            self._check(task, versions)
            self._lease(task, data, peer)
            if task.get("proposal_reservation") != reservation_id:
                raise ManualError("assistance.proposal_reservation", 409)
            sources = self.sources(tx, task)
            refs = [item["ref"] for item in sources]
            if (
                not data["sources"]
                or any(ref not in refs for ref in cast(list[object], data["sources"]))
                or data["next"] is not None
                or not data["candidate_text"]
            ):
                raise ManualError("assistance.invalid_proposal", 409)
            # Admission checks grounding; the coordinator establishes current provenance.
            value: Record = {
                "id": str(uuid4()),
                "revision": "1",
                "task_id": tid,
                "task_revision": task["revision"],
                "task_fence": task["fence"],
                "kind": "summary",
                "text_ciphertext": self.engine.cipher.encrypt(text(data, "candidate_text")),
                "sources": data["sources"],
                "payload_digest": digest(
                    {
                        "text": data["candidate_text"],
                        "sources": data["sources"],
                        "scope": task["scope"],
                        "source_vector": versions,
                    }
                ),
                "source_vector": versions,
                "state": "review_pending",
                "expires_at": stamp(self.engine.clock() + timedelta(seconds=300)),
                "original_ciphertext": self.engine.cipher.encrypt(""),
                "ai_provenance": True,
            }
            self.save(tx, "draft", value, current.account_id, sid)
            task.update(
                draft_id=value["id"], state="awaiting_human", lease=None, proposal_reservation=None
            )
            self.save(tx, "task", task, current.account_id, sid)
            return self.draft_view(value)

    def tool_invoke(self, actor: Actor, data: Record, peer: WorkloadPeer) -> Record:
        validate_contract("ToolInvoke", data)
        tid, iid = text(data, "task_id"), text(data, "invocation_id")
        sid = self._session(actor, "task", tid)
        with self.transaction(actor, sid, "tool_invoke", data) as (tx, current, versions):
            task = self.read(tx, "task", tid)
            self._check(task, versions)
            self._lease(task, data, peer)
            arguments = object_value(data["arguments"])
            tool = text(arguments, "tool")
            row = tx.connection.execute(
                "SELECT body FROM assistance.invocation WHERE id=%s", (iid,)
            ).fetchone()
            if row:
                old = self.read(tx, "invocation", iid)
                if old["request_digest"] != digest(data):
                    raise ManualError("assistance.invocation_conflict", 409)
                return object_value(old["result"])
            if cast(int, task["tools_used"]) >= 3:
                raise ManualError("assistance.tool_budget", 409)
            task["tools_used"] = cast(int, task["tools_used"]) + 1
            scope = object_value(task["scope"])
            allowed = (
                tool in TOOLS and tool == "session_read" and arguments.get("session_id") == sid
            )
            fields = cast(list[str], arguments.get("fields", []))
            allowed = allowed and set(fields) <= set(cast(list[str], scope["fields"]))
            sources = self.sources(tx, task) if allowed else []
            outcome: Record = {
                "kind": "failure",
                "code": "CAPABILITY_DISABLED",
                "retryable": False,
                "safe_reason": "assistance.tool_disabled",
            }
            if allowed:
                session, guard = tx.get("session", sid), tx.get("guard", sid)
                if session is None or guard is None:
                    raise ManualError("assistance.not_found", 404)
                refs = [object_value(item["ref"]) for item in sources]
                identifiers = {ref["id"] for ref in refs}
                assertions = [
                    projections.assertion_view(row, self.engine.cipher, json.loads)
                    for row in tx.rows("assertion", session_id=sid, limit=100)
                    if row["id"] in identifiers and row["field_key"] in fields
                ]
                value = {
                    "tool": "session_read",
                    "session": projections.session_view(tx, session, guard),
                    "assertions": assertions,
                }
                outcome = {"kind": "success", "value": value}
            elif (
                tool == "protocol_read"
                and self.knowledge is not None
                and arguments.get("artifact_digest") == self.knowledge.digest
                and arguments.get("locale") == task.get("knowledge_locale")
            ):
                try:
                    entry = self.knowledge.section(
                        "worker",
                        text(task, "knowledge_locale"),
                        text(arguments, "section_id"),
                        now=self.engine.clock(),
                    )
                except CatalogDenied:
                    entry = None
                permitted = self.sources(tx, task)
                if entry is not None and entry["source"] in [item["ref"] for item in permitted]:
                    sources = [{"ref": entry["source"], "text": entry["text"]}]
                    outcome = {
                        "kind": "success",
                        "value": {
                            "tool": "protocol_read",
                            "template_id": object_value(entry["source"])["id"],
                            "text": entry["text"],
                            "source": entry["source"],
                        },
                    }
            result: Record = {
                "observation_id": str(uuid4()),
                "invocation_id": iid,
                "task_id": tid,
                "task_revision": task["revision"],
                "taint": "untrusted",
                "sources": [item["ref"] for item in sources],
                "result": outcome,
            }
            validate_contract("Observation", result)
            self.save(
                tx,
                "invocation",
                {"id": iid, "task_id": tid, "request_digest": digest(data), "result": result},
                current.account_id,
                sid,
            )
            self.save(tx, "task", task, current.account_id, sid)
            return result

    def draft_view(self, value: Record) -> Record:
        result = {
            name: value[name]
            for name in (
                "id",
                "revision",
                "task_id",
                "kind",
                "sources",
                "payload_digest",
                "source_vector",
                "state",
            )
        }
        result["text"] = self.engine.cipher.decrypt(text(value, "text_ciphertext"))
        validate_contract("DraftView", result)
        return result

    def context_snapshot(self, actor: Actor, task_id: str) -> Record:
        sid = self._session(actor, "task", task_id)
        with self.transaction(actor, sid, "inference_context", {"task_id": task_id}) as (
            tx,
            _actor,
            versions,
        ):
            task = self.read(tx, "task", task_id)
            self._check(task, versions)
            lease = object_value(task["lease"]) if task["lease"] else {}
            if (
                task["state"] not in {"planning", "running"}
                or not lease
                or dt(lease["expires_at"]) <= self.engine.clock()
            ):
                raise ManualError("assistance.stale_lease", 409)
            self._stored_peer(task)
            return {
                "task": self.view(task),
                "sources": self.sources(tx, task),
                "source_vector": versions,
                "goal": task["goal"],
                "fence": task["fence"],
                "lease": task["lease"],
                "allowed_tools": sorted(
                    TOOLS | frozenset({"protocol_read"} if self.knowledge else ())
                ),
            }

    def inference_current(
        self,
        tx: Transaction,
        record: Record,
        actor_for_task: Callable[[str], Actor],
        *,
        fresh_actor: Callable[[Record, str], Actor] | None = None,
        operation: str = "reserve",
    ) -> InferenceAuthority | bool:
        """Current callback for data-owned durable job slots, before their locks.

        Resolving an actor uses server-held identity references, never job fields.
        Failure fences delivery but must allow observed compute completion to free
        the old slot. No caller can convert a job ID into actor authority.
        """
        try:
            tid = str(record["task_id"])
            actor = self.engine.current_actor(
                fresh_actor(record, operation) if fresh_actor is not None else actor_for_task(tid)
            )
            sid = self._session(actor, "task", tid)
            tx.connection.execute(
                "SELECT set_config('care_link.principal',%s,true), "
                "set_config('care_link.review_run',%s,true)",
                (actor.account_id, actor.review_run_id or ""),
            )
            tx.scope(sid)
            guard = self.engine.assistance_guard(tx, actor, sid)
            task = self.read(tx, "task", tid)
            self._check(task, guard.versions)
            lease = object_value(task["lease"]) if task["lease"] else {}
            peer = self._stored_peer(task)
            if (
                task["state"] not in {"planning", "running"}
                or task["revision"] != str(record["revision"])
                or str(task["fence"]) != str(record["fence"])
                or lease.get("step_id") != str(record["step_id"])
            ):
                return False
            expiry = min(
                guard.valid_until,
                dt(task["deadline"]),
                dt(lease["expires_at"]),
                peer.certificate_expires_at,
                dt(record["deadline"]),
            )
            return InferenceAuthority(expiry) if expiry > self.engine.clock() else False
        except (ManualError, KeyError, ValueError):
            return False
