"""Human review preserves AI provenance and never dispatches a message or referral."""

from datetime import timedelta
from typing import cast

from care_link_contracts import validate_contract
from care_link_domain import Actor, ManualError

from ..store import Record, text
from ..values import digest, dt, stamp
from .execution import AssistanceExecution


class AssistanceCoordinator(AssistanceExecution):
    @staticmethod
    def current_draft(task: Record, draft: Record) -> bool:
        return (
            task["draft_id"] == draft["id"]
            and task["revision"] == draft.get("task_revision")
            and task["fence"] == draft.get("task_fence")
        )

    def draft_read(self, actor: Actor, draft_id: str) -> Record:
        sid = self._session(actor, "draft", draft_id)
        with self.transaction(actor, sid, "draft_read", {"id": draft_id}) as (
            tx,
            _current,
            versions,
        ):
            draft = self.read(tx, "draft", draft_id)
            task = self.read(tx, "task", text(draft, "task_id"))
            if (
                draft["source_vector"] != versions
                or not self.knowledge_current(task)
                or task["state"] == "cancelled"
                or not self.current_draft(task, draft)
            ):
                draft["state"] = "stale"
            return self.draft_view(draft)

    def draft_context(self, actor: Actor, draft_id: str) -> Record:
        sid = self._session(actor, "draft", draft_id)
        with self.transaction(actor, sid, "assistance_draft_context", {"id": draft_id}) as (
            tx,
            _current,
            versions,
        ):
            draft = self.read(tx, "draft", draft_id)
            task = self.read(tx, "task", text(draft, "task_id"))
            sources = self.sources(tx, task)
            refs = [item["ref"] for item in sources]
            if (
                draft["source_vector"] != versions
                or not self.knowledge_current(task)
                or not self.current_draft(task, draft)
                or task["state"] == "cancelled"
                or any(ref not in refs for ref in cast(list[object], draft["sources"]))
                or dt(draft["expires_at"]) <= self.engine.clock()
            ):
                draft["state"] = "stale"
            return {
                "draft": self.draft_view(draft),
                "original_text": self.engine.cipher.decrypt(text(draft, "original_ciphertext")),
                "sources": sources,
                "scope": task["scope"],
                "expires_at": draft["expires_at"],
                "expected_effect": "unsent_draft",
                "ai_provenance": True,
            }

    def draft_review(self, actor: Actor, key: str, data: Record, draft_id: str) -> Record:
        validate_contract("ReviewCommand", data)
        sid = self._session(actor, "draft", draft_id)
        with self.transaction(actor, sid, "draft_review", data) as (tx, current, versions):
            previous = self.replay(tx, key, "draft_review", data, draft_id)
            if previous is not None:
                return previous
            draft = self.read(tx, "draft", draft_id)
            task = self.read(tx, "task", text(draft, "task_id"))
            if (
                data["draft_id"] != draft_id
                or data["expected_revision"] != draft["revision"]
                or data["exact_digest"] != draft["payload_digest"]
                or data["source_vector"] != draft["source_vector"]
            ):
                raise ManualError("assistance.stale_review", 409)
            if draft["state"] not in {"proposed", "review_pending"}:
                raise ManualError("assistance.review_terminal", 409)
            decision = text(data, "decision")
            if decision != "reject":
                if not self.current_draft(task, draft):
                    raise ManualError("assistance.stale_review", 409)
                if task["state"] != "awaiting_human":
                    raise ManualError("assistance.stale_review", 409)
                # Human review is a fresh authorized command, after the execution slice ended.
                self._check(task, versions, active=False)
                refs = [s["ref"] for s in self.sources(tx, task)]
                if (
                    draft["source_vector"] != versions
                    or any(ref not in refs for ref in cast(list[object], draft["sources"]))
                    or dt(draft["expires_at"]) <= self.engine.clock()
                ):
                    raise ManualError("assistance.stale_review", 409)
            expiry = dt(data["expires_at"])
            if not self.engine.clock() < expiry <= self.engine.clock() + timedelta(seconds=300):
                raise ManualError("assistance.review_expiry", 409)
            if decision == "edit":
                if not data["edited_text"]:
                    raise ManualError("assistance.edit_required", 422)
                draft["text_ciphertext"] = self.engine.cipher.encrypt(text(data, "edited_text"))
                draft["payload_digest"] = digest(
                    {
                        "text": data["edited_text"],
                        "sources": draft["sources"],
                        "scope": task["scope"],
                        "source_vector": versions,
                    }
                )
                draft["revision"] = str(int(text(draft, "revision")) + 1)
                # Edited material needs a fresh exact review; it is not accepted implicitly.
                draft["state"] = "review_pending"
                draft["expires_at"] = stamp(expiry)
            else:
                if data["edited_text"] is not None:
                    raise ManualError("assistance.unexpected_edit", 422)
                draft["state"] = "accepted" if decision == "accept" else "rejected"
                if self.current_draft(task, draft):
                    task["state"] = "completed"
                    self.actors.revoke(text(task, "id"))
            self.save(tx, "draft", draft, current.account_id, sid)
            self.save(tx, "task", task, current.account_id, sid)
            result = {
                "id": key,
                "draft_id": draft_id,
                "decision": decision,
                "reviewer_id": current.account_id,
                "exact_digest": draft["payload_digest"],
                "expires_at": stamp(expiry),
                "revision": draft["revision"],
            }

            return self.receipt(tx, key, "draft_review", data, draft_id, result, current, sid)
