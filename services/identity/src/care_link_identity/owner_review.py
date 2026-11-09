"""Narrow fresh-MFA owner access-review recovery, never an ambient login grant.

The configured owner can review only its own overdue project access through a
separately composed maintenance callback. Ordinary identity routes reject these
intents. No cookie/session/role is issued; an explicit bound confirmation renews
only the thirty-day review date after fresh provider and local guard checks.
"""

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from .crypto import digest, token
from .domain import ExchangeUncertain, IdentityError, Transaction, instant, stamp, text
from .service import IdentityService


@dataclass(frozen=True)
class OwnerReviewProof:
    proof_id: str
    account_id: str
    purpose: str
    expires_at: datetime


class OwnerAccessReview:
    def __init__(self, identity: IdentityService, owner_account_id: str) -> None:
        if str(UUID(owner_account_id)) != owner_account_id:
            raise ValueError("exact main owner account UUID required")
        self.identity, self.owner_account_id = identity, owner_account_id

    def _owner(self, tx: Transaction) -> tuple[str, dict[str, object]]:
        owner = next(
            (
                (key, row)
                for key, row in tx.items("account")
                if row.get("account_id") == self.owner_account_id
            ),
            None,
        )
        if owner is None:
            raise IdentityError("identity.owner_review_denied")
        key, row = owner
        issuer = tx.get("issuer", self.identity.issuer)
        roles = row.get("roles")
        if (
            row.get("enabled") is not True
            or row.get("blocked") is True
            or row.get("deprovisioned_at") is not None
            or (issuer and issuer.get("quarantined") is True)
            or not isinstance(roles, list)
            or "operator" not in roles
        ):
            raise IdentityError("identity.owner_review_denied")
        return key, row

    def begin(self, browser_binding: str) -> dict[str, object]:
        if len(browser_binding) < 32:
            raise IdentityError("identity.owner_review_binding_required")
        now, state, nonce, verifier = self.identity.clock(), token(), token(), token()
        proof_id = str(uuid4())
        with self.identity.store.transaction() as tx:
            _key, owner = self._owner(tx)
            tx.put(
                "intent",
                digest(state),
                {
                    "id": proof_id,
                    "purpose": "owner_access_review",
                    "state": "pending",
                    "binding": digest(browser_binding),
                    "nonce": nonce,
                    "verifier": self.identity.custody.encrypt(verifier),
                    "created_at": stamp(now),
                    "expires_at": stamp(now + timedelta(minutes=5)),
                    "account_id": self.owner_account_id,
                    "revision": owner["revision"],
                    "role_revision": owner["role_revision"],
                },
            )
            tx.put("intent", proof_id, {"state_hash": digest(state)})
        return {
            "intent_id": proof_id,
            "authorization_url": self.identity.provider.authorization_url(
                state, nonce, verifier, True
            ),
            "expires_at": stamp(now + timedelta(minutes=5)),
        }

    def complete(
        self, state: str, code: str, browser_binding: str, returned_issuer: str | None = None
    ) -> OwnerReviewProof:
        now = self.identity.clock()
        if returned_issuer is not None and returned_issuer != self.identity.issuer:
            raise IdentityError("identity.owner_review_denied")
        key = digest(state)
        with self.identity.store.transaction() as tx:
            intent = tx.get("intent", key)
            if (
                intent is None
                or intent.get("purpose") != "owner_access_review"
                or intent.get("state") != "pending"
                or instant(intent["expires_at"]) <= now
                or not secrets.compare_digest(text(intent, "binding"), digest(browser_binding))
            ):
                raise IdentityError("identity.owner_review_denied")
            _owner_key, owner = self._owner(tx)
            if (
                owner["revision"] != intent["revision"]
                or owner["role_revision"] != intent["role_revision"]
            ):
                raise IdentityError("identity.owner_review_denied")
            intent["state"] = "redeeming"
            tx.put("intent", key, intent)
        try:
            principal = self.identity.provider.exchange(
                code,
                self.identity.custody.decrypt(text(intent, "verifier")),
                text(intent, "nonce"),
                True,
            )
            now = self.identity.clock()
            if not principal.mfa or not 0 <= (now - principal.auth_time).total_seconds() <= 300:
                raise IdentityError("identity.owner_review_mfa_required")
            if not self.identity.provider.active(principal.access_token, principal.subject):
                raise IdentityError("identity.owner_review_current_authority_unavailable", 503)
            with self.identity.store.transaction() as tx:
                _owner_key, owner = self._owner(tx)
                if (
                    owner.get("subject") != principal.subject
                    or owner["revision"] != intent["revision"]
                    or owner["role_revision"] != intent["role_revision"]
                    or instant(intent["expires_at"]) <= self.identity.clock()
                ):
                    raise IdentityError("identity.owner_review_denied")
                intent.update(
                    {
                        "state": "completed",
                        "verifier": "",
                        "nonce": "",
                        "review_consumed": False,
                        "access_token": self.identity.custody.encrypt(principal.access_token),
                        "auth_time": stamp(principal.auth_time),
                        "expires_at": stamp(
                            min(principal.expires_at, instant(intent["expires_at"]))
                        ),
                    }
                )
                tx.put("intent", key, intent)
            return OwnerReviewProof(
                text(intent, "id"),
                self.owner_account_id,
                "review_own_access",
                instant(intent["expires_at"]),
            )
        except IdentityError as error:
            with self.identity.store.transaction() as tx:
                current = tx.get("intent", key)
                if current and current.get("state") == "redeeming":
                    current.update(
                        {
                            "state": "uncertain"
                            if isinstance(error, ExchangeUncertain)
                            else "failed",
                            "verifier": "",
                            "nonce": "",
                            "access_token": "",
                        }
                    )
                    tx.put("intent", key, current)
            raise

    def confirm(self, proof_id: str, browser_binding: str, *, approve: bool) -> bool:
        with self.identity.store.transaction() as tx:
            reference = tx.get("intent", proof_id)
            intent = tx.get("intent", text(reference, "state_hash")) if reference else None
            if (
                reference is None
                or intent is None
                or intent.get("purpose") != "owner_access_review"
                or intent.get("state") != "completed"
                or intent.get("review_consumed") is not False
                or instant(intent["expires_at"]) <= self.identity.clock()
                or not secrets.compare_digest(text(intent, "binding"), digest(browser_binding))
            ):
                raise IdentityError("identity.owner_review_denied")
            _owner_key, owner = self._owner(tx)
            subject = text(owner, "subject")
        if not self.identity.provider.active(
            self.identity.custody.decrypt(text(intent, "access_token")), subject
        ):
            raise IdentityError("identity.owner_review_current_authority_unavailable", 503)
        with self.identity.store.transaction() as tx:
            owner_key, owner = self._owner(tx)
            current = tx.get("intent", text(reference, "state_hash")) if reference else None
            now = self.identity.clock()
            if (
                current is None
                or current.get("review_consumed") is not False
                or current.get("state") != "completed"
                or instant(current["expires_at"]) <= now
                or owner["revision"] != current["revision"]
                or owner["role_revision"] != current["role_revision"]
                or (now - instant(current["auth_time"])).total_seconds() > 300
            ):
                raise IdentityError("identity.owner_review_denied")
            current.update({"review_consumed": True, "access_token": ""})
            tx.put("intent", text(reference, "state_hash"), current)
            if approve is True:
                owner.update(
                    {
                        "reviewed_at": stamp(now),
                        "access_review_due_at": stamp(now + timedelta(days=30)),
                    }
                )
                tx.put("account", owner_key, owner)
                tx.put(
                    "retention_record",
                    str(uuid4()),
                    {
                        "account_id": self.owner_account_id,
                        "record_class": "minimal_audit",
                        "payload": {
                            "action": "owner_access_review",
                            "actor_id": self.owner_account_id,
                        },
                        "event_at": stamp(now),
                        "dependencies": [],
                        "last_dependency_ended_at": None,
                        "owner": "main",
                        "state": "active",
                    },
                )
            return approve is True
