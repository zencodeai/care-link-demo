"""Durable dispatch intent, fresh one-use authorization and honest reconciliation."""

import json
from typing import cast
from uuid import uuid4

from care_link_contracts import ContractError, validate_contract
from care_link_domain import Actor, ManualError

from .referrals import Referrals
from .store import Record, Transaction, instant, number, text
from .values import Outcome, dt, object_value


class Dispatches(Referrals):
    @staticmethod
    def dispatch_projection(row: Record) -> Record:
        return {
            "dispatch_id": row["id"],
            "referral_id": row["referral_id"],
            "revision": str(number(row, "revision")),
            "state": row["state"],
            "attempt_count": row["attempt_count"],
            "receipt_id": row["receipt_id"],
        }

    def send_ready(
        self, tx: Transaction, actor: Actor, referral: Record, dispatch: Record | None = None
    ) -> Record:
        session = tx.get("session", text(referral, "session_id"))
        if session is None:
            raise ManualError("manual.not_found", 404)
        self.active(session)
        control = tx.get("control", "demo")
        if control is None or control["mode"] not in {"normal", "ai_disabled"}:
            raise ManualError("manual.dispatch_fenced")
        self._referral_directory(
            tx, text(referral, "recipient_service_id"), referral["directory_revision"]
        )
        self._selected_payload(tx, actor, session, referral["selected"])
        grant_id = (
            text(dispatch, "consent_id")
            if dispatch
            else text(referral, "consent_id")
            if referral["consent_id"]
            else None
        )
        grant = self.matching_referral_consent(tx, referral, grant_id)
        review_id = (
            text(dispatch, "review_id")
            if dispatch
            else text(referral, "review_id")
            if referral["review_id"]
            else None
        )
        review = tx.get("referral_review", review_id) if review_id else None
        if grant is None:
            raise ManualError("manual.exact_consent_required")
        if (
            review is None
            or review["decision"] != "accept"
            or review["reviewer_id"] != actor.account_id
            or review["exact_digest"] != referral["payload_digest"]
            or instant(review, "expires_at") <= self.clock()
            or review["source_vector"] != self.referral_vector(tx, actor, referral)
        ):
            raise ManualError("manual.review_stale", 409)
        return grant

    def referral_dispatch(self, actor: Actor, key: str, data: Record, referral_id: str) -> Record:
        def enqueue(
            tx: Transaction,
            current: Actor,
            body: Record,
            _session: Record | None,
            _guard: Record | None,
        ) -> Outcome:
            referral = tx.get("referral", referral_id)
            if referral is None:
                raise ManualError("manual.not_found", 404)
            self.expected(body, referral)
            if referral["dispatch_id"] is not None:
                raise ManualError("manual.generation_already_dispatched", 409)
            if (
                body["generation"] != str(referral["generation"])
                or body["exact_payload_digest"] != referral["payload_digest"]
                or body["review_id"] != referral["review_id"]
                or body["consent_id"] != referral["consent_id"]
            ):
                raise ManualError("manual.dispatch_binding_mismatch", 409)
            self.send_ready(tx, current, referral)
            row: Record = {
                "id": str(uuid4()),
                "referral_id": referral_id,
                "session_id": referral["session_id"],
                "payload_digest": referral["payload_digest"],
                "consent_id": body["consent_id"],
                "review_id": body["review_id"],
                "owner_id": current.account_id,
                "revision": 1,
                "state": "pending",
                "attempt_count": 0,
                "receipt_id": None,
                "receipt": None,
                "authorization_id": None,
                "fence": 0,
                "created_at": self.clock(),
            }
            tx.put("dispatch", row)
            referral.update(
                {"dispatch_id": row["id"], "revision": number(referral, "revision") + 1}
            )
            tx.put("referral", referral)
            return Outcome("DispatchView", self.dispatch_projection(row), text(row, "id"))

        validate_contract("DispatchRequest", data)
        return self._run(
            actor,
            "referral_dispatch",
            key,
            {**data, "referral_id": referral_id},
            self._referral_session(actor, referral_id),
            enqueue,
        )

    def _dispatch_row(self, tx: Transaction, dispatch_id: str) -> Record:
        row = tx.get("dispatch", dispatch_id)
        if row is None:
            raise ManualError("manual.not_found", 404)
        return row

    def dispatch_read(self, actor: Actor, dispatch_id: str) -> Record:
        def read(
            tx: Transaction,
            _current: Actor,
            _data: Record,
            _session: Record | None,
            _guard: Record | None,
        ) -> Outcome:
            return Outcome(
                "DispatchView", self.dispatch_projection(self._dispatch_row(tx, dispatch_id))
            )

        return self._run(
            actor,
            "dispatch_read",
            None,
            {"dispatch_id": dispatch_id},
            self._referral_session(actor, dispatch_id, "dispatch"),
            read,
        )

    def receipt_read(self, actor: Actor, dispatch_id: str) -> Record:
        def read(
            tx: Transaction,
            _current: Actor,
            _data: Record,
            _session: Record | None,
            _guard: Record | None,
        ) -> Outcome:
            row = self._dispatch_row(tx, dispatch_id)
            if row["receipt"] is None:
                raise ManualError("manual.receipt_unavailable", 404)
            return Outcome("ReceiptView", object_value(row["receipt"]))

        return self._run(
            actor,
            "receipt_read",
            None,
            {"dispatch_id": dispatch_id},
            self._referral_session(actor, dispatch_id, "dispatch"),
            read,
        )

    def _authorize(self, actor: Actor, dispatch_id: str, expected: object) -> Record:
        def authorize(
            tx: Transaction,
            current: Actor,
            body: Record,
            _session: Record | None,
            _guard: Record | None,
        ) -> Outcome:
            dispatch = self._dispatch_row(tx, dispatch_id)
            self.expected(body, dispatch)
            referral = tx.get("referral", text(dispatch, "referral_id"))
            if (
                referral is None
                or dispatch["owner_id"] != current.account_id
                or dispatch["state"] != "pending"
            ):
                raise ManualError("manual.dispatch_not_pending", 409)
            self.send_ready(tx, current, referral, dispatch)
            fence = number(dispatch, "fence") + 1
            authorization: Record = {
                "id": str(uuid4()),
                "dispatch_id": dispatch_id,
                "session_id": dispatch["session_id"],
                "fence": fence,
                "versions": self.referral_vector(tx, current, referral),
                "payload_digest": dispatch["payload_digest"],
                "consumed_at": None,
                "created_at": self.clock(),
            }
            tx.put("authorization", authorization)
            dispatch.update(
                {
                    "authorization_id": authorization["id"],
                    "fence": fence,
                    "state": "authorized",
                    "revision": number(dispatch, "revision") + 1,
                }
            )
            tx.put("dispatch", dispatch)
            return Outcome("DispatchView", self.dispatch_projection(dispatch), dispatch_id)

        return self._run(
            actor,
            "dispatch_authorize",
            str(uuid4()),
            {"dispatch_id": dispatch_id, "expected_revision": expected},
            self._referral_session(actor, dispatch_id, "dispatch"),
            authorize,
        )

    def _consume(self, actor: Actor, dispatch_id: str) -> Record:
        def consume(
            tx: Transaction,
            current: Actor,
            _body: Record,
            _session: Record | None,
            _guard: Record | None,
        ) -> Outcome:
            dispatch = self._dispatch_row(tx, dispatch_id)
            referral = tx.get("referral", text(dispatch, "referral_id"))
            if (
                referral is None
                or dispatch["owner_id"] != current.account_id
                or dispatch["state"] != "authorized"
            ):
                raise ManualError("manual.authorization_used", 409)
            self.send_ready(tx, current, referral, dispatch)
            authorization = tx.get("authorization", text(dispatch, "authorization_id"))
            if (
                authorization is None
                or authorization["consumed_at"] is not None
                or authorization["fence"] != dispatch["fence"]
            ):
                raise ManualError("manual.authorization_used", 409)
            authorization["consumed_at"] = self.clock()
            tx.put("authorization", authorization)
            tx.put(
                "dispatch_attempt",
                {
                    "id": str(uuid4()),
                    "authorization_id": authorization["id"],
                    "dispatch_id": dispatch_id,
                    "session_id": dispatch["session_id"],
                    "fence": dispatch["fence"],
                    "created_at": self.clock(),
                },
            )
            dispatch.update(
                {
                    "state": "attempted",
                    "attempt_count": number(dispatch, "attempt_count") + 1,
                    "revision": number(dispatch, "revision") + 1,
                }
            )
            tx.put("dispatch", dispatch)
            return Outcome(
                "SimulatorSend",
                {
                    "dispatch_id": dispatch_id,
                    "authorization_id": authorization["id"],
                    "payload_digest": dispatch["payload_digest"],
                    "generation": str(referral["generation"]),
                    "payload": self.referral_payload(tx, current, referral),
                },
                dispatch_id,
            )

        return self._run(
            actor,
            "dispatch_consume",
            str(uuid4()),
            {"dispatch_id": dispatch_id},
            self._referral_session(actor, dispatch_id, "dispatch"),
            consume,
        )

    def _observe(
        self, actor: Actor, dispatch_id: str, receipt: Record | None, safe_reason: str | None = None
    ) -> Record:
        def observe(
            tx: Transaction,
            _current: Actor,
            _body: Record,
            _session: Record | None,
            _guard: Record | None,
        ) -> Outcome:
            row = self._dispatch_row(tx, dispatch_id)
            if row["state"] not in {
                "attempted",
                "unknown",
                "reconciliation_needed",
                "received",
                "partial",
                "accepted",
                "rejected",
            }:
                raise ManualError("manual.dispatch_not_attempted", 409)
            referral = tx.get("referral", text(row, "referral_id"))
            if referral is None:
                raise ManualError("manual.not_found", 404)
            tx.put(
                "dispatch_observation",
                {
                    "id": str(uuid4()),
                    "dispatch_id": dispatch_id,
                    "session_id": row["session_id"],
                    "receipt": receipt,
                    "safe_reason": safe_reason,
                    "created_at": self.clock(),
                },
            )
            if receipt is None:
                if row["state"] == "attempted":
                    row["state"] = "unknown"
            else:
                validate_contract("ReceiptView", receipt)
                if (
                    receipt["dispatch_id"] != dispatch_id
                    or receipt["payload_digest"] != row["payload_digest"]
                    or receipt["recipient_service_id"] != referral["recipient_service_id"]
                ):
                    raise ManualError("manual.receipt_binding_mismatch", 503)
                status = receipt["status"]
                if status in {"unavailable", "not_found"}:
                    if row["receipt"] is None:
                        row["state"] = "reconciliation_needed"
                else:
                    payload = object_value(
                        cast(
                            Record,
                            json.loads(self.cipher.decrypt(text(referral, "payload_ciphertext"))),
                        )
                    )
                    fields = {
                        text(object_value(field), "field")
                        for field in cast(list[object], payload["fields"])
                    }
                    accepted = set(cast(list[str], receipt["accepted_fields"]))
                    if (
                        not accepted.issubset(fields)
                        or status == "accepted"
                        and accepted != fields
                        or status == "partial"
                        and not (set() < accepted < fields)
                        or status in {"received", "rejected", "clarification_requested"}
                        and accepted
                    ):
                        raise ManualError("manual.receipt_fields_invalid", 503)
                    old_receipt = object_value(row["receipt"]) if row["receipt"] else None
                    stale = old_receipt is not None and (
                        dt(receipt["observed_at"]) < dt(old_receipt["observed_at"])
                        or old_receipt["status"] != "received"
                        and status == "received"
                    )
                    if stale:
                        return Outcome("DispatchView", self.dispatch_projection(row), dispatch_id)
                    row["receipt"], row["receipt_id"] = receipt, receipt["id"]
                    row["state"] = (
                        "reconciliation_needed" if status == "clarification_requested" else status
                    )
            row["revision"] = number(row, "revision") + 1
            tx.put("dispatch", row)
            referral["state"] = row["state"]
            referral["revision"] = number(referral, "revision") + 1
            tx.put("referral", referral)
            return Outcome("DispatchView", self.dispatch_projection(row), dispatch_id)

        return self._run(
            actor,
            "dispatch_observe",
            str(uuid4()),
            {"dispatch_id": dispatch_id, "receipt": receipt, "safe_reason": safe_reason},
            self._referral_session(actor, dispatch_id, "dispatch"),
            observe,
        )

    def _dispatch_intent(
        self, actor: Actor, key: str, data: Record, dispatch_id: str, action: str
    ) -> Record:
        def intent(
            tx: Transaction,
            _current: Actor,
            body: Record,
            _session: Record | None,
            _guard: Record | None,
        ) -> Outcome:
            row = self._dispatch_row(tx, dispatch_id)
            self.expected(body, row)
            return Outcome("DispatchView", self.dispatch_projection(row), dispatch_id)

        return self._run(
            actor,
            action,
            key,
            {**data, "dispatch_id": dispatch_id},
            self._referral_session(actor, dispatch_id, "dispatch"),
            intent,
        )

    def dispatcher_send(self, actor: Actor, key: str, data: Record, dispatch_id: str) -> Record:
        """Operator-triggered outbox pump: pending is never a transmission permit."""
        validate_contract("RevisionCommand", data)
        if self.receiver is None:
            raise ManualError("manual.receiver_unavailable", 503)
        current = self._dispatch_intent(actor, key, data, dispatch_id, "dispatcher_send")
        if current["state"] == "pending":
            self._authorize(actor, dispatch_id, current["revision"])
        elif current["state"] != "authorized":
            # Crash or lost response can never cause a second blind send.
            return self.dispatch_reconcile(
                actor, str(uuid4()), {"expected_revision": current["revision"]}, dispatch_id
            )
        package = self._consume(actor, dispatch_id)
        recipient = text(object_value(package["payload"]), "recipient_service_id")
        try:
            receipt = self.receiver.send(recipient, package)
        except (TimeoutError, ConnectionError):
            receipt = None
        try:
            return self._observe(actor, dispatch_id, receipt)
        except ContractError:
            return self._observe(actor, dispatch_id, None, "invalid_receipt")
        except ManualError as error:
            if error.code not in {
                "manual.receipt_binding_mismatch",
                "manual.receipt_fields_invalid",
            }:
                raise
            return self._observe(actor, dispatch_id, None, "invalid_receipt")

    def dispatch_reconcile(self, actor: Actor, key: str, data: Record, dispatch_id: str) -> Record:
        validate_contract("RevisionCommand", data)
        current = self._dispatch_intent(actor, key, data, dispatch_id, "dispatch_reconcile")
        if current["state"] in {"pending", "authorized", "cancelled"}:
            raise ManualError("manual.no_attempt_to_reconcile", 409)
        if self.receiver is None:
            raise ManualError("manual.receiver_unavailable", 503)
        # Metadata disclosure is guarded first; no lock survives the fixed port call.
        with self.store.transaction(
            actor, self._referral_session(actor, dispatch_id, "dispatch"), locked=False
        ) as tx:
            row = self._dispatch_row(tx, dispatch_id)
            referral = tx.get("referral", text(row, "referral_id"))
            if referral is None:
                raise ManualError("manual.not_found", 404)
            recipient, payload_digest = (
                text(referral, "recipient_service_id"),
                text(row, "payload_digest"),
            )
        try:
            receipt = self.receiver.lookup(recipient, dispatch_id, payload_digest)
        except (TimeoutError, ConnectionError):
            receipt = None
        try:
            return self._observe(actor, dispatch_id, receipt)
        except ContractError:
            return self._observe(actor, dispatch_id, None, "invalid_receipt")
        except ManualError as error:
            if error.code not in {
                "manual.receipt_binding_mismatch",
                "manual.receipt_fields_invalid",
            }:
                raise
            return self._observe(actor, dispatch_id, None, "invalid_receipt")
