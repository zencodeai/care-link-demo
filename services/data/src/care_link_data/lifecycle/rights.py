"""Own-subject AL3 rights, minimized progress and one-use current exports."""

import json
from datetime import timedelta
from typing import cast
from uuid import uuid4

from care_link_contracts import validate_contract
from care_link_domain import Actor, ManualError

from ..projections import assertion_view
from ..store import Record, Transaction, instant, number, text
from ..values import Outcome, canonical, integer, object_value, stamp
from .followup import Followup
from .views import rights_view


class Rights(Followup):
    @staticmethod
    def _own_persona(tx: Transaction, actor: Actor, subject_id: str) -> Record:
        persona = tx.get("persona", subject_id)
        if (
            not persona
            or persona["account_id"] != actor.account_id
            or persona["kind"] != actor.role
        ):
            raise ManualError("manual.not_found", 404)
        return persona

    def _rights_scope(self, actor: Actor, subject_id: str) -> str:
        with self.store.transaction(actor, None, locked=False, queue=True) as tx:
            self._own_persona(tx, actor, subject_id)
            rows = tx.rows(
                "session", persona_id=subject_id, participant_account_id=actor.account_id, limit=100
            )
            if not rows or len(rows) == 100:
                raise ManualError("manual.rights_scope_unavailable", 404)
            return text(max(rows, key=lambda r: (instant(r, "created_at"), text(r, "id"))), "id")

    def _export(self, tx: Transaction, actor: Actor, request: Record) -> Record:
        subject_id = text(request, "subject_id")
        self._own_persona(tx, actor, subject_id)
        guard = tx.get("subject", subject_id)
        if guard is None or guard["delete_state"] != "active":
            raise ManualError("manual.not_found", 404)
        # Explicit bounded scope over every own session. No overflow truncation.
        tx.scope(None, queue=True)
        sessions = tx.rows(
            "session", persona_id=subject_id, participant_account_id=actor.account_id, limit=100
        )
        if len(sessions) == 100:
            raise ManualError("manual.export_scope_limit", 503)
        assertions: list[Record] = []
        plans: list[Record] = []
        outcomes: list[str] = []
        for session in sessions:
            sid = text(session, "id")
            tx.scope(sid)
            reports = tx.rows(
                "assertion",
                session_id=sid,
                subject_id=subject_id,
                author_id=actor.account_id,
                limit=100,
            )
            if len(reports) == 100:
                raise ManualError("manual.export_scope_limit", 503)
            for report in reports:
                copies = tx.rows("copy", aggregate_id=report["id"], limit=2)
                if len(copies) != 1:
                    raise ManualError("manual.copy_inventory_required", 503)
                if copies[0]["state"] != "purged":
                    assertions.append(assertion_view(report, self.cipher, json.loads))
            rows = tx.rows("plan", session_id=sid, subject_id=subject_id, limit=100)
            if len(rows) == 100:
                raise ManualError("manual.export_scope_limit", 503)
            for plan in rows:
                fields = tx.rows(
                    "plan_field", plan_id=plan["id"], author_id=actor.account_id, limit=100
                )
                if len(fields) == 100:
                    raise ManualError("manual.export_scope_limit", 503)
                latest: dict[str, Record] = {}
                for field in fields:
                    copies = tx.rows("copy", aggregate_id=field["id"], limit=2)
                    if len(copies) != 1:
                        raise ManualError("manual.copy_inventory_required", 503)
                    if copies[0]["state"] == "purged":
                        continue
                    field_key = text(field, "field_key")
                    if field_key not in latest or number(field, "revision") > number(
                        latest[field_key], "revision"
                    ):
                        latest[field_key] = field
                if len(latest) > 32:
                    raise ManualError("manual.export_scope_limit", 503)
                values = [assertion_view(f, self.cipher, json.loads) for f in latest.values()]
                # Plan fields use the same closed AssertionView shape plus source.
                for view, field in zip(values, latest.values(), strict=True):
                    view["source"] = field["source"]
                plans.append(
                    {
                        "id": plan["id"],
                        "subject_id": subject_id,
                        "revision": str(number(plan, "revision")),
                        "state": plan["state"],
                        "fields": values,
                        "retired_at": stamp(instant(plan, "retired_at"))
                        if plan["retired_at"]
                        else None,
                    }
                )
            observed = tx.rows("outcome", session_id=sid, actor_id=actor.account_id, limit=100)
            if len(observed) == 100:
                raise ManualError("manual.export_scope_limit", 503)
            outcomes.extend(text(r, "id") for r in observed)
        if len(assertions) > 500 or len(plans) > 50 or len(outcomes) > 500:
            raise ManualError("manual.export_scope_limit", 503)
        tx.scope(text(request, "session_id"))
        result: Record = {
            "export_id": request["download_id"],
            "subject_id": subject_id,
            "created_at": stamp(instant(request, "requested_at")),
            "assertions": assertions,
            "plans": plans,
            "outcome_refs": outcomes,
            "exceptions": ["other_author_private_content_excluded"],
        }
        validate_contract("ExportView", result)
        return result

    def rights_create(self, actor: Actor, key: str, data: Record) -> Record:
        validate_contract("RightsCreate", data)
        sid = self._rights_scope(actor, text(data, "subject_id"))

        def apply(
            tx: Transaction, current: Actor, body: Record, _s: Record | None, _g: Record | None
        ) -> Outcome:
            subject_id = text(body, "subject_id")
            self._own_persona(tx, current, subject_id)
            subject = tx.get("subject", subject_id)
            if subject is None or subject["delete_state"] != "active":
                raise ManualError("manual.not_found", 404)
            if integer(body["expected_revision"]) != number(subject, "authority_revision"):
                raise ManualError("manual.stale_revision", 409)
            tx.scope(sid)
            prior_ceremony = tx.rows("rights", ceremony_id=body["ceremony_id"], limit=1)
            if prior_ceremony:
                raise ManualError("manual.ceremony_already_bound", 409)
            self.authority.rights_proof(
                current, text(body, "ceremony_id"), subject_id, text(body, "kind")
            )
            tx.scope(sid)
            request: Record = {
                "id": str(uuid4()),
                "subject_id": subject_id,
                "requester_id": current.account_id,
                "session_id": sid,
                "kind": body["kind"],
                "ceremony_id": body["ceremony_id"],
                "revision": 1,
                "state": "requested",
                "requested_at": self.clock(),
                "deadline": self.clock() + timedelta(hours=24),
                "exceptions": [],
                "download_id": None,
                "export_ciphertext": None,
                "export_expires_at": None,
                "downloaded_at": None,
            }
            if body["kind"] == "export":
                request["download_id"] = str(uuid4())
                request["export_expires_at"] = self.clock() + timedelta(minutes=15)
                result = self._export(tx, current, request)
                request["export_ciphertext"] = self.cipher.encrypt(canonical(result))
                request["state"] = "completed"
            else:
                control = tx.get("control", "demo")
                if control is None:
                    raise ManualError("manual.bootstrap_missing", 503)
                scope: Record = {
                    "session_id": None,
                    "subject_id": subject_id,
                    "purpose": "rights",
                    "fields": [],
                    "recipient_id": None,
                }
                self.append_restriction(
                    tx,
                    key,
                    control,
                    {
                        "kind": "subject_delete",
                        "subject_id": subject_id,
                        "rights_request_id": request["id"],
                        "subject_revision": str(number(subject, "authority_revision") + 1),
                        "effective_at": stamp(self.clock()),
                    },
                    scope,
                )
                subject["delete_state"] = "restricted"
                subject["authority_revision"] = number(subject, "authority_revision") + 1
                tx.put("subject", subject)
                # Restriction immediately denies private projections; durable jobs
                # honor it even if content minimization needs reconciliation.
                tx.connection.execute(
                    "UPDATE care.follow_up SET state='cancelled',revision=revision+1,fence=fence+1 "
                    "WHERE subject_id=%s AND state IN ('anchor_pending','scheduled','claimed')",
                    (subject_id,),
                )
                request["state"] = "eligible"
                request["exceptions"] = [
                    "backup_erasure_pending_IMP09",
                    "physical_erasure_not_proven",
                ]
            tx.put("rights", request)
            if body["kind"] == "export":
                session = tx.get("session", sid)
                if session is None:
                    raise ManualError("manual.not_found", 404)
                # The export itself is inventoried with immutable 15-minute expiry.
                self.register_lifecycle_copy(
                    tx, session, "export", text(request, "id"), expiry=request["export_expires_at"]
                )
            return Outcome("RightsView", rights_view(request), text(request, "id"), sid)

        def replay(
            tx: Transaction, current: Actor, _b: Record, _s: Record | None, _g: Record | None
        ) -> Outcome:
            tx.scope(sid)
            rows = tx.rows(
                "rights", ceremony_id=data["ceremony_id"], requester_id=current.account_id, limit=2
            )
            if len(rows) != 1:
                raise ManualError("manual.not_found", 404)
            return Outcome("RightsView", rights_view(rows[0]))

        return self._run(actor, "rights_create", key, data, None, apply, replay=replay)

    def rights_read(self, actor: Actor, rights_id: str) -> Record:
        def read(
            tx: Transaction, current: Actor, _b: Record, _s: Record | None, _g: Record | None
        ) -> Outcome:
            metadata = tx.peek("rights", rights_id)
            if metadata is not None:
                tx.scope(text(metadata, "session_id"))
            row = tx.get("rights", rights_id)
            if row is None or row["requester_id"] != current.account_id:
                raise ManualError("manual.not_found", 404)
            self._own_persona(tx, current, text(row, "subject_id"))
            return Outcome("RightsView", rights_view(row))

        return self._run(actor, "rights_read", None, {"rights_id": rights_id}, None, read)

    def export_download(self, actor: Actor, rights_id: str) -> Record:
        def read(
            tx: Transaction, current: Actor, _b: Record, _s: Record | None, _g: Record | None
        ) -> Outcome:
            metadata = tx.peek("rights", rights_id)
            if metadata is not None:
                tx.scope(text(metadata, "session_id"))
            row = tx.get("rights", rights_id)
            if (
                row is None
                or row["requester_id"] != current.account_id
                or row["kind"] != "export"
                or row["state"] != "completed"
                or row["downloaded_at"] is not None
                or row["export_expires_at"] is None
                or instant(row, "export_expires_at") <= self.clock()
            ):
                raise ManualError("manual.export_unavailable", 404)
            self.authority.rights_download_proof(
                current, text(row, "ceremony_id"), text(row, "subject_id")
            )
            current_export = self._export(tx, current, row)
            if not row["export_ciphertext"]:
                raise ManualError("manual.export_unavailable", 404)
            materialized = object_value(
                json.loads(self.cipher.decrypt(text(row, "export_ciphertext")))
            )
            # Scope changes may narrow disclosure; fresh projections always win.
            materialized_ids = {
                text(cast(Record, r), "id") for r in cast(list[object], materialized["assertions"])
            }
            current_export["assertions"] = [
                r
                for r in cast(list[Record], current_export["assertions"])
                if r["id"] in materialized_ids
            ]
            original_plans = {
                text(cast(Record, p), "id"): object_value(p)
                for p in cast(list[object], materialized["plans"])
            }
            selected_plans: list[Record] = []
            for plan in cast(list[Record], current_export["plans"]):
                old = original_plans.get(text(plan, "id"))
                if old is None:
                    continue
                ids = {text(object_value(f), "id") for f in cast(list[object], old["fields"])}
                plan["fields"] = [f for f in cast(list[Record], plan["fields"]) if f["id"] in ids]
                selected_plans.append(plan)
            current_export["plans"] = selected_plans
            current_export["outcome_refs"] = [
                i
                for i in cast(list[str], current_export["outcome_refs"])
                if i in cast(list[str], materialized["outcome_refs"])
            ]
            row["downloaded_at"] = self.clock()
            row["export_ciphertext"] = None
            row["revision"] = number(row, "revision") + 1
            tx.put("rights", row)
            copies = tx.rows("copy", aggregate_id=rights_id, limit=2)
            if len(copies) != 1:
                raise ManualError("manual.copy_inventory_required", 503)
            copy = copies[0]
            copy["state"] = "purged"
            tx.put("copy", copy)
            return Outcome("ExportView", current_export)

        return self._run(actor, "export_download", None, {"rights_id": rights_id}, None, read)
