"""Immutable source-based referral generations and exact human review."""

import json
from datetime import timedelta
from typing import cast
from uuid import uuid4

from care_link_contracts import validate_contract
from care_link_domain import Actor, ManualError

from .consent import current_fields, grant_current, owns_subject
from .directory import Directory
from .store import Record, Transaction, instant, number, text
from .values import Outcome, canonical, digest, dt, object_value, stamp


class Referrals(Directory):
    def _referral_session(
        self, actor: Actor, resource_id: str, repository: str = "referral"
    ) -> str:
        with self.store.transaction(actor, None, locked=False) as tx:
            row = tx.get(repository, resource_id)
            if row is None:
                raise ManualError("manual.not_found", 404)
            return text(row, "session_id")

    def source_items(self, tx: Transaction, actor: Actor, session: Record) -> list[Record]:
        owner = owns_subject(tx, actor, session)
        allowed = current_fields(tx, actor, session, self.clock()) if not owner else None
        rows: list[tuple[str, Record]] = []
        for kind, repo in (("assertion", "assertion"), ("plan_field", "plan_field")):
            batch = tx.rows(repo, session_id=session["id"], limit=100)
            if len(batch) == 100:
                raise ManualError("manual.source_history_limit", 503)
            rows.extend((kind, row) for row in batch)
        # A newer assertion/field by the same author supersedes the old source.
        latest: dict[tuple[str, str, str], tuple[str, Record]] = {}
        for kind, row in rows:
            field = text(row, "field_key")
            if kind == "plan_field":
                if allowed is not None and field not in allowed:
                    continue
                plan = tx.get("plan", text(row, "plan_id"))
                if plan is None or plan["state"] != "active":
                    continue
            key = (kind, field, text(row, "author_id"))
            old = latest.get(key)
            if old is None or (
                instant(row, "effective_at"),
                number(row, "revision"),
                text(row, "id"),
            ) > (instant(old[1], "effective_at"), number(old[1], "revision"), text(old[1], "id")):
                latest[key] = kind, row
        result: list[Record] = []
        for kind, row in sorted(latest.values(), key=lambda item: text(item[1], "id")):
            value = object_value(json.loads(self.cipher.decrypt(text(row, "value_ciphertext"))))
            verification = row["verification"]
            if any(
                other["field_key"] == row["field_key"]
                and other["author_id"] != row["author_id"]
                and other["value_ciphertext"] != row["value_ciphertext"]
                for _, other in latest.values()
            ):
                # Preserve conflicts; randomized ciphertext cannot establish equality.
                if any(
                    other["field_key"] == row["field_key"]
                    and other["author_id"] != row["author_id"]
                    and object_value(
                        json.loads(self.cipher.decrypt(text(other, "value_ciphertext")))
                    )
                    != value
                    for _, other in latest.values()
                ):
                    verification = "disputed"
            source: Record = {
                "kind": kind,
                "id": row["id"],
                "revision": str(number(row, "revision")),
                "digest": digest(
                    {
                        "field": row["field_key"],
                        "value": value,
                        "author_id": row["author_id"],
                        "verification": verification,
                    }
                ),
                "observed_at": stamp(instant(row, "effective_at")),
                "verification": verification,
            }
            result.append(
                {
                    "selected": {"field": row["field_key"], "source": source},
                    "field": {"field": row["field_key"], "value": value, "sources": [source]},
                }
            )
        if len(result) > 100:
            raise ManualError("manual.source_projection_limit", 503)
        return result

    def _selected_payload(
        self, tx: Transaction, actor: Actor, session: Record, selected: object
    ) -> list[Record]:
        if not isinstance(selected, list):
            raise ManualError("manual.invalid_selection", 422)
        available = self.source_items(tx, actor, session)
        result: list[Record] = []
        seen: set[tuple[str, str]] = set()
        for raw in cast(list[object], selected):
            item = object_value(raw)
            source = object_value(item["source"])
            key = (text(item, "field"), text(source, "id"))
            if key in seen:
                raise ManualError("manual.duplicate_selection", 422)
            seen.add(key)
            match = next((entry for entry in available if entry["selected"] == item), None)
            if match is None:
                raise ManualError("manual.source_stale_or_unshared", 409)
            result.append(object_value(match["field"]))
        return sorted(result, key=lambda item: (text(item, "field"), canonical(item["sources"])))

    def referral_sources(self, actor: Actor, session_id: str) -> Record:
        def read(
            tx: Transaction,
            current: Actor,
            _data: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, _ = self.require_session(session, guard)
            return Outcome(
                "ReferralSourcePage",
                {"items": self.source_items(tx, current, row), "next_cursor": None},
            )

        return self._run(
            actor, "referral_sources", None, {"session_id": session_id}, session_id, read
        )

    def _referral_directory(self, tx: Transaction, service_id: str, revision: object) -> Record:
        if service_id not in self.simulator_services:
            raise ManualError("manual.simulator_mapping_required", 403)
        row = self.lookup_directory(tx, service_id)
        view = self.directory_projection(tx, row)
        facts = object_value(view["facts"])
        if (
            view["revision"] != str(revision)
            or view["state"] != "verified"
            or facts["availability"] != "available_fixture"
        ):
            raise ManualError("manual.directory_not_dispatchable", 409)
        return view

    def referral_payload(self, tx: Transaction, actor: Actor, row: Record) -> Record:
        if row["state"] == "purged":
            raise ManualError("manual.source_content_expired", 410)
        payload = object_value(json.loads(self.cipher.decrypt(text(row, "payload_ciphertext"))))
        session = tx.get("session", text(row, "session_id"))
        if session is None:
            raise ManualError("manual.not_found", 404)
        # Recheck current source disclosure permission without replacing immutable bytes.
        allowed = (
            current_fields(tx, actor, session, self.clock())
            if not owns_subject(tx, actor, session)
            else None
        )
        for raw in cast(list[object], payload["fields"]):
            field = object_value(raw)
            if (
                text(field, "field").startswith("plan.")
                and allowed is not None
                and field["field"] not in allowed
            ):
                raise ManualError("manual.field_scope_denied")
        return payload

    def referral_projection(self, tx: Transaction, actor: Actor, row: Record) -> Record:
        state, consent_id = row["state"], row["consent_id"]
        if row["dispatch_id"] is None and state != "cancelled":
            grant = self.matching_referral_consent(tx, row)
            consent_id = grant["grant_id"] if grant else None
            state = "awaiting_review" if grant else "awaiting_consent"
            review = tx.get("referral_review", text(row, "review_id")) if row["review_id"] else None
            if (
                grant
                and review
                and review["decision"] == "accept"
                and instant(review, "expires_at") > self.clock()
                and review["source_vector"] == self.referral_vector(tx, actor, row)
            ):
                state = "ready"
        return {
            "id": row["id"],
            "revision": str(number(row, "revision")),
            "generation": str(number(row, "generation")),
            "payload": self.referral_payload(tx, actor, row),
            "digest": row["payload_digest"],
            "state": state,
            "consent_id": consent_id,
            "review_id": row["review_id"],
            "dispatch_id": row["dispatch_id"],
        }

    def referral_draft(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        def create(
            tx: Transaction,
            current: Actor,
            body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, _ = self.require_session(session, guard)
            self.active(row)
            self.expected(body, row)
            if body["subject_id"] != row["persona_id"]:
                raise ManualError("manual.subject_scope", 404)
            directory = self._referral_directory(
                tx, text(body, "recipient_service_id"), body["directory_revision"]
            )
            payload: Record = {
                "session_id": row["id"],
                "subject_id": row["persona_id"],
                "recipient_service_id": body["recipient_service_id"],
                "purpose": "referral",
                "fields": self._selected_payload(tx, current, row, body["selected"]),
                "qualifications": object_value(directory["facts"])["qualifications"],
            }
            validate_contract("ReferralPayload", payload)
            referral: Record = {
                "id": str(uuid4()),
                "session_id": row["id"],
                "subject_id": row["persona_id"],
                "recipient_service_id": body["recipient_service_id"],
                "directory_revision": int(str(body["directory_revision"])),
                "generation": 1,
                "revision": 1,
                "payload_ciphertext": self.cipher.encrypt(canonical(payload)),
                "payload_digest": digest(payload),
                "selected": body["selected"],
                "state": "awaiting_consent",
                "consent_id": None,
                "review_id": None,
                "dispatch_id": None,
                "author_id": current.account_id,
                "created_at": self.clock(),
            }
            tx.put("referral", referral)
            self.register_copy(tx, row, "referral", text(referral, "id"))
            return Outcome(
                "ReferralView",
                self.referral_projection(tx, current, referral),
                text(referral, "id"),
            )

        return self._run(
            actor, "referral_draft", key, data, session_id, create, contract="ReferralDraftCreate"
        )

    def referral_read(self, actor: Actor, referral_id: str) -> Record:
        def read(
            tx: Transaction,
            current: Actor,
            _body: Record,
            _session: Record | None,
            _guard: Record | None,
        ) -> Outcome:
            row = tx.get("referral", referral_id)
            if row is None:
                raise ManualError("manual.not_found", 404)
            return Outcome("ReferralView", self.referral_projection(tx, current, row))

        return self._run(
            actor,
            "referral_read",
            None,
            {"referral_id": referral_id},
            self._referral_session(actor, referral_id),
            read,
        )

    def referral_vector(self, tx: Transaction, actor: Actor, row: Record) -> Record:
        snapshot = self._snapshot(tx, actor, text(row, "session_id"))
        vector = self._versions(actor, snapshot)
        service = tx.get("service_guard", text(row, "recipient_service_id"))
        vector["directory"] = str(number(service, "current_revision")) if service else "0"
        return {key: value for key, value in vector.items() if key != "review_run"}

    def matching_referral_consent(
        self, tx: Transaction, referral: Record, grant_id: str | None = None
    ) -> Record | None:
        payload = object_value(
            json.loads(self.cipher.decrypt(text(referral, "payload_ciphertext")))
        )
        fields = {
            text(object_value(field), "field") for field in cast(list[object], payload["fields"])
        }
        grants = tx.rows(
            "consent",
            subject_id=referral["subject_id"],
            session_id=referral["session_id"],
            recipient_kind="service",
            recipient_id=referral["recipient_service_id"],
            purpose="referral",
            limit=100,
        )
        if len(grants) == 100:
            raise ManualError("manual.consent_projection_limit", 503)
        return next(
            (
                grant
                for grant in grants
                if (grant_id is None or grant["grant_id"] == grant_id)
                and object_value(grant["recipient"]).get("directory_revision")
                == str(referral["directory_revision"])
                and fields.issubset(cast(list[str], grant["fields"]))
                and grant_current(tx, grant, self.clock())
            ),
            None,
        )

    @staticmethod
    def review_projection(row: Record) -> Record:
        return {
            "id": row["id"],
            "draft_id": row["referral_id"],
            "decision": row["decision"],
            "reviewer_id": row["reviewer_id"],
            "exact_digest": row["exact_digest"],
            "expires_at": stamp(instant(row, "expires_at")),
            "revision": str(number(row, "revision")),
        }

    def referral_context(self, actor: Actor, referral_id: str) -> Record:
        def read(
            tx: Transaction,
            current: Actor,
            _data: Record,
            _session: Record | None,
            _guard: Record | None,
        ) -> Outcome:
            row = tx.get("referral", referral_id)
            if row is None:
                raise ManualError("manual.not_found", 404)
            grant = self.matching_referral_consent(tx, row)
            review = tx.get("referral_review", text(row, "review_id")) if row["review_id"] else None
            return Outcome(
                "ReferralContext",
                {
                    "referral": {
                        **self.referral_projection(tx, current, row),
                        "consent_id": grant["grant_id"] if grant else None,
                    },
                    "versions": self.referral_vector(tx, current, row),
                    "review": self.review_projection(review) if review else None,
                    "consent_expires_at": stamp(instant(grant, "expires_at")) if grant else None,
                },
            )

        return self._run(
            actor,
            "referral_context",
            None,
            {"referral_id": referral_id},
            self._referral_session(actor, referral_id),
            read,
        )

    def referral_review(self, actor: Actor, key: str, data: Record, referral_id: str) -> Record:
        def review(
            tx: Transaction,
            current: Actor,
            body: Record,
            session: Record | None,
            _guard: Record | None,
        ) -> Outcome:
            row = tx.get("referral", referral_id)
            if row is None or session is None:
                raise ManualError("manual.not_found", 404)
            self.expected(body, row)
            self.active(session)
            if row["dispatch_id"]:
                raise ManualError("manual.generation_already_dispatched", 409)
            if body["decision"] == "edit" or body["edited_text"] is not None:
                raise ManualError("manual.new_source_generation_required", 422)
            if (
                body["draft_id"] != referral_id
                or body["exact_digest"] != row["payload_digest"]
                or body["source_vector"] != self.referral_vector(tx, current, row)
            ):
                raise ManualError("manual.review_stale", 409)
            self._referral_directory(
                tx, text(row, "recipient_service_id"), row["directory_revision"]
            )
            self._selected_payload(tx, current, session, row["selected"])
            grant = self.matching_referral_consent(tx, row)
            if grant is None:
                raise ManualError("manual.exact_consent_required")
            expires = dt(body["expires_at"])
            if not self.clock() < expires <= self.clock() + timedelta(seconds=300):
                raise ManualError("manual.review_interval", 422)
            value: Record = {
                "id": str(uuid4()),
                "referral_id": referral_id,
                "session_id": row["session_id"],
                "decision": body["decision"],
                "reviewer_id": current.account_id,
                "exact_digest": row["payload_digest"],
                "source_vector": body["source_vector"],
                "expires_at": expires,
                "revision": 1,
            }
            tx.put("referral_review", value)
            row.update(
                {
                    "review_id": value["id"],
                    "consent_id": grant["grant_id"],
                    "revision": number(row, "revision") + 1,
                    "state": "ready" if body["decision"] == "accept" else "cancelled",
                }
            )
            tx.put("referral", row)
            return Outcome("ReviewView", self.review_projection(value), text(value, "id"))

        return self._run(
            actor,
            "referral_review",
            key,
            data,
            self._referral_session(actor, referral_id),
            review,
            contract="ReviewCommand",
        )
