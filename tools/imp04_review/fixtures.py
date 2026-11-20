"""Fictional fixture preparation through real ManualService command enforcement."""

from collections.abc import Callable
from copy import deepcopy

from care_link_data.control import ManualService
from care_link_domain import Actor

from .adapters import InProcessReviewActors
from .lifecycle import operation
from .types import JsonRecord


class ServiceFixtureBuilder:
    def __init__(
        self,
        service: ManualService,
        actors: InProcessReviewActors,
        directory_preflight: Callable[[JsonRecord, Actor], JsonRecord],
    ) -> None:
        self.service, self.actors = service, actors
        self.directory_preflight = directory_preflight

    def _call(
        self,
        run: JsonRecord,
        checkpoint: Callable[[], None],
        slot: str,
        step: str,
        method: str,
        payload: JsonRecord,
        resource: str | None = None,
        verification: JsonRecord | None = None,
    ) -> JsonRecord:
        steps = run["steps"]
        if step not in steps:
            # Persist the precise first command before dispatch. Retries never use
            # a changed revision/payload with the same idempotency key.
            steps[step] = {"payload": deepcopy(payload), "resource": resource}
            checkpoint()
        journal = steps[step]
        if "result" not in journal:
            with self.actors.open(
                run,
                slot,
                verification if journal["payload"].get("authority_proof_id") is None else None,
            ) as lease:
                body = deepcopy(journal["payload"])
                if (
                    verification is not None
                    and journal["payload"].get("authority_proof_id") is None
                ):
                    if lease.proof_id is None:
                        raise ValueError("Real action-bound authority proof required")
                    body["authority_proof_id"] = lease.proof_id
                    # Proof IDs are one-use session-bound command input. Do not
                    # silently replace one after an uncertain command outcome.
                    if journal["payload"].get("authority_proof_id") is None:
                        journal["payload"] = deepcopy(body)
                        checkpoint()
                    else:
                        body = deepcopy(journal["payload"])
                args = [lease.actor, operation(run, step), body]
                if journal["resource"] is not None:
                    args.append(journal["resource"])
                journal["result"] = getattr(self.service, method)(*args)
            checkpoint()
        return deepcopy(journal["result"])

    def _read(self, run: JsonRecord, slot: str, method: str, resource: str) -> JsonRecord:
        with self.actors.open(run, slot) as lease:
            return getattr(self.service, method)(lease.actor, resource)

    def prepare(self, run: JsonRecord, checkpoint: Callable[[], None]) -> JsonRecord:
        sessions: dict[str, JsonRecord] = {}
        plans: dict[str, JsonRecord] = {}
        for slot in ("pid", "carer", "professional"):
            session = self._call(
                run,
                checkpoint,
                slot,
                slot + ":session",
                "session_create",
                {
                    "tags": {"environment": "demo", "population": "synthetic"},
                    "participant_kind": run["actors"][slot]["role"],
                    "jurisdiction": None,
                    "locale": "en-CA",
                    "channel": "web",
                    "persona_id": None,
                    "fixture_id": None,
                },
            )
            sessions[slot] = session
            current = self._read(run, slot, "session_read", session["id"])
            self._call(
                run,
                checkpoint,
                slot,
                slot + ":report",
                "session_assertions",
                {
                    "expected_revision": current["revision"],
                    "subject_id": session["subject_id"],
                    "field": "observations",
                    "value": {
                        "kind": "text",
                        "text": (
                            "Fictional review report: I prefer a quiet place "
                            "and time to explain my wishes."
                        ),
                    },
                    "supersedes_id": None,
                    "effective_at": run["started_at"],
                },
                session["id"],
            )
            if slot != "pid":
                continue
            current = self._read(run, slot, "session_read", session["id"])
            plan = self._call(
                run,
                checkpoint,
                slot,
                slot + ":plan",
                "plan_create",
                {
                    "expected_revision": current["revision"],
                    "subject_id": session["subject_id"],
                },
            )
            self._call(
                run,
                checkpoint,
                slot,
                slot + ":strategy",
                "plan_field_append",
                {
                    "expected_revision": plan["revision"],
                    "field": "plan.strategies",
                    "value": {
                        "kind": "text",
                        "text": (
                            "Fictional preference: a quiet room, a familiar person, "
                            "and time to speak."
                        ),
                    },
                    "source": None,
                    "safety_relevant": False,
                },
                plan["id"],
            )
            current_plan = self._read(run, slot, "plan_read", plan["id"])
            self._call(
                run,
                checkpoint,
                slot,
                "pid:medication",
                "plan_field_append",
                {
                    "expected_revision": current_plan["revision"],
                    "field": "plan.medication_report",
                    "value": {
                        "kind": "text",
                        "text": (
                            "Fictional self-report for accessibility review: "
                            "I would like a clinician "
                            "to check my medication information with me. This is unverified and "
                            "is not medication advice."
                        ),
                    },
                    "source": None,
                    "safety_relevant": True,
                },
                plan["id"],
            )
            plans[slot] = plan
        pid = sessions["pid"]
        current = self._read(run, "pid", "session_read", pid["id"])
        queue = self._call(
            run,
            checkpoint,
            "pid",
            "pid:human",
            "session_human_request",
            {
                "expected_revision": current["revision"],
                "reason": "user_requested",
            },
            pid["id"],
        )
        assignment = self._call(
            run,
            checkpoint,
            "worker1",
            "worker:reserve",
            "workforce_reserve",
            {
                "worker_id": run["actors"]["worker1"]["account_id"],
                "expected_revision": queue["revision"],
            },
            pid["id"],
        )
        self._call(
            run,
            checkpoint,
            "worker1",
            "worker:accept",
            "workforce_accept",
            {
                "expected_revision": assignment["revision"],
            },
            pid["id"],
        )
        current = self._read(run, "pid", "session_read", pid["id"])
        self._call(
            run,
            checkpoint,
            "pid",
            "pid:grant",
            "consent_grant",
            {
                "expected_revision": current["revision"],
                "subject_id": pid["subject_id"],
                "session_id": pid["id"],
                "purpose": "plan",
                "recipient": {
                    "kind": "account",
                    "account_id": run["actors"]["worker1"]["account_id"],
                },
                "fields": ["plan.strategies"],
                "basis": "self",
                "authority_proof_id": None,
                "effective_at": run["started_at"],
                "expires_at": run["expires_at"],
            },
            verification={
                "purpose": "plan_edit",
                "resource_id": pid["subject_id"],
                "expected_revision": current["revision"],
            },
        )
        current_plan = self._read(run, "worker1", "plan_read", plans["pid"]["id"])
        self._call(
            run,
            checkpoint,
            "worker1",
            "worker:report",
            "plan_field_append",
            {
                "expected_revision": current_plan["revision"],
                "field": "plan.strategies",
                "value": {
                    "kind": "text",
                    "text": (
                        "Fictional worker report: suggest a busy group room. "
                        "This differs from the person's wishes and needs human review."
                    ),
                },
                "source": None,
                "safety_relevant": True,
            },
            plans["pid"]["id"],
        )
        result = {
            slot: {
                "session_id": sessions[slot]["id"],
                "plan_id": plans[slot]["id"] if slot in plans else None,
                "recipient_id": None,
            }
            for slot in sessions
        }
        result["pid"]["recipient_id"] = run["actors"]["worker1"]["account_id"]
        result["worker1"] = {
            "session_id": pid["id"],
            "plan_id": plans["pid"]["id"],
            "recipient_id": None,
        }
        return result

    def verify(self, run: JsonRecord, selections: JsonRecord) -> None:
        for slot, selection in selections.items():
            session = self._read(run, slot, "session_read", selection["session_id"])
            plan = (
                self._read(run, slot, "plan_read", selection["plan_id"])
                if selection["plan_id"]
                else None
            )
            if session["id"] != selection["session_id"] or (
                plan is not None and plan["id"] != selection["plan_id"]
            ):
                raise ValueError("Prepared resources were not confirmed by application custody")

        with self.actors.open(run, "pid") as lease:
            readiness = self.directory_preflight(run, lease.actor)
        if (
            readiness.get("confirmed") is not True
            or set(readiness.get("cases", [])) != {"current", "stale", "suspended", "unknown"}
            or set(readiness.get("locales", [])) != {"en-CA", "fr-CA"}
        ):
            raise ValueError("Actual bilingual populated directory readiness required")
        run["directory_readiness"] = readiness

    def finish(self, run: JsonRecord) -> None:
        self.actors.retire(run)

    def retire(self, run: JsonRecord) -> None:
        self.actors.retire(run)
