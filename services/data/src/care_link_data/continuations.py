"""Digest-only AL0 continuation families, explicit fresh proof recovery."""

import secrets
from datetime import timedelta
from uuid import uuid4

from care_link_domain import Actor, ManualError

from .store import Record, Transaction, instant, number, text
from .values import Outcome, integer, stamp, token_digest
from .workforce import WorkforceService


class ContinuationService(WorkforceService):
    def _issue_family(
        self,
        tx: Transaction,
        actor: Actor,
        session: Record,
        key: str,
        *,
        root_family_id: str | None = None,
    ) -> Outcome:
        family_id = str(uuid4())
        token = secrets.token_urlsafe(32)
        expires = self.clock() + timedelta(minutes=10)
        tx.put(
            "family",
            {
                "id": family_id,
                "account_id": actor.account_id,
                "root_family_id": root_family_id or family_id,
                "session_id": session["id"],
                "channel": session["channel"],
                "generation": 1,
                "status": "active",
                "revision": 1,
                "created_at": self.clock(),
            },
        )
        tx.put(
            "token",
            {
                "family_id": family_id,
                "generation": 1,
                "token_hash": token_digest(token),
                "expires_at": expires,
                "consumed_at": None,
                "operation_id": key,
            },
        )
        return Outcome(
            "ContinuationIssued",
            {
                "family_id": family_id,
                "generation": "1",
                "token": token,
                "expires_at": stamp(expires),
                "assurance": "AL0",
                "operation_id": key,
            },
            family_id,
            text(session, "id"),
            True,
        )

    def continuation_issue(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        """Explicit additive issuance protocol; AL0 and no new subject authority."""

        def issue(
            tx: Transaction,
            current_actor: Actor,
            body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, _current = self.require_session(session, guard)
            self.active(row)
            self.expected(body, row)
            if tx.rows(
                "family",
                session_id=row["id"],
                account_id=current_actor.account_id,
                status="active",
                limit=1,
            ):
                raise ManualError("manual.family_already_exists", 409)
            return self._issue_family(tx, current_actor, row, key)

        return self._run(
            actor, "continuation_issue", key, data, session_id, issue, contract="RevisionCommand"
        )

    def continuation_bootstrap(self, actor: Actor, key: str, session_id: str) -> Record:
        """Compatibility helper for source tests; uses the public issuance use case."""
        current = self.session_read(actor, session_id)
        return self.continuation_issue(
            actor, key, {"expected_revision": current["revision"]}, session_id
        )

    def _family(
        self,
        tx: Transaction,
        actor: Actor,
        data: Record,
        session: Record,
        *,
        recovery: bool = False,
    ) -> Record:
        family = tx.get("family", text(data, "family_id"))
        if (
            family is None
            or family["account_id"] != actor.account_id
            or family["session_id"] != session["id"]
            or (family["status"] != "active" and not recovery)
            or family["channel"] != data["channel"]
            or data["channel"] != session["channel"]
        ):
            raise ManualError("manual.continuation_unavailable", 410)
        expected_revision = integer(data["expected_revision"])
        if (expected_revision != number(family, "revision") and not recovery) or (
            recovery and not 1 <= expected_revision <= number(family, "revision")
        ):
            raise ManualError("manual.family_changed", 409)
        return family

    def continuation_rotate(self, actor: Actor, key: str, data: Record) -> Record:
        def rotate(
            tx: Transaction,
            current_actor: Actor,
            body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, _current = self.require_session(session, guard)
            self.active(row)
            family = self._family(tx, current_actor, body, row)
            tokens = tx.rows(
                "token", family_id=family["id"], generation=family["generation"], limit=1
            )
            if not tokens:
                raise ManualError("manual.continuation_unavailable", 410)
            old = tokens[0]
            if (
                old["consumed_at"] is not None
                or instant(old, "expires_at") <= self.clock()
                or not secrets.compare_digest(
                    text(old, "token_hash"), token_digest(text(body, "token"))
                )
            ):
                raise ManualError("manual.continuation_unavailable", 410)
            old["consumed_at"] = self.clock()
            tx.put("token", old)
            family["generation"] = number(family, "generation") + 1
            family["revision"] = number(family, "revision") + 1
            tx.put("family", family)
            token = secrets.token_urlsafe(32)
            expires = self.clock() + timedelta(minutes=10)
            tx.put(
                "token",
                {
                    "family_id": family["id"],
                    "generation": family["generation"],
                    "token_hash": token_digest(token),
                    "expires_at": expires,
                    "consumed_at": None,
                    "operation_id": key,
                },
            )
            return Outcome(
                "ContinuationIssued",
                {
                    "family_id": family["id"],
                    "generation": str(number(family, "generation")),
                    "token": token,
                    "expires_at": stamp(expires),
                    "assurance": "AL0",
                    "operation_id": key,
                },
                text(family, "id"),
                text(row, "id"),
                True,
            )

        return self._run(
            actor,
            "continuation_rotate",
            key,
            data,
            text(data, "session_id"),
            rotate,
            contract="ContinuationRotate",
        )

    def continuation_recover(self, actor: Actor, key: str, data: Record) -> Record:
        def recover(
            tx: Transaction,
            current_actor: Actor,
            body: Record,
            session: Record | None,
            guard: Record | None,
        ) -> Outcome:
            row, _current = self.require_session(session, guard)
            self.active(row)
            family = self._family(tx, current_actor, body, row, recovery=True)
            # This consumes a fresh, exact session/family/recovery-bound proof;
            # a failed DB commit requires a new deliberate ceremony.
            self.authority.recovery_proof(
                current_actor, text(body, "ceremony_id"), text(row, "id"), text(family, "id")
            )
            # A lost recovery reply leaves its successor unknown to the caller.
            # A new exact fresh proof for any known ancestor fences every active
            # successor in the same lineage before issuing one replacement.
            root_family_id = text(family, "root_family_id")
            for successor in tx.rows(
                "family", root_family_id=root_family_id, status="active", limit=2
            ):
                successor["status"] = "revoked"
                successor["revision"] = number(successor, "revision") + 1
                tx.put("family", successor)
            return self._issue_family(tx, current_actor, row, key, root_family_id=root_family_id)

        return self._run(
            actor,
            "continuation_recover",
            key,
            data,
            text(data, "session_id"),
            recover,
            contract="ContinuationRecover",
        )
