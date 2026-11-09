"""Browser identity use cases with short durable guards and fresh provider checks."""

import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

from .crypto import Custody, ReceiptSigner, digest, token
from .domain import (
    PARTICIPANT_ROLES,
    PRIVILEGED_ROLES,
    ExchangeUncertain,
    IdentityError,
    Provider,
    Store,
    Transaction,
    instant,
    stamp,
    text,
)


class IdentityService:
    def __init__(
        self,
        store: Store,
        provider: Provider,
        custody: Custody,
        signer: ReceiptSigner,
        issuer: str,
        origin: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store, self.provider, self.custody, self.signer = store, provider, custody, signer
        self.issuer, self.origin, self.clock = issuer, origin, clock

    def provision(self, subject: str, account_id: str, roles: list[str]) -> None:
        """Offline provisioning hook; no route automatically grants roles from claims.

        Caller must be a separately authorized provisioning tool. This method is
        deliberately absent from the browser/internal HTTP API.
        """
        if not set(roles) <= PRIVILEGED_ROLES | PARTICIPANT_ROLES:
            raise IdentityError("identity.invalid_role")
        key = digest(self.issuer + "\0" + subject)
        with self.store.transaction() as tx:
            old = tx.get("account", key)
            if old is not None:
                raise IdentityError("identity.provision_conflict", 409)
            tx.put(
                "account",
                key,
                {
                    "account_id": account_id,
                    "subject": subject,
                    "roles": roles,
                    "created_at": stamp(self.clock()),
                    "reviewed_at": stamp(self.clock()),
                    "access_review_due_at": stamp(self.clock() + timedelta(days=30)),
                    "enabled": True,
                    "revision": "1",
                    "role_revision": "1",
                },
            )

    def _account(self, tx: Transaction, subject: str, role: str) -> dict[str, object]:
        account = tx.get("account", digest(self.issuer + "\0" + subject))
        issuer = tx.get("issuer", self.issuer)
        if (
            account is None
            or account.get("enabled") is not True
            or account.get("blocked") is True
            or (
                account.get("access_review_due_at") is None
                or instant(account["access_review_due_at"]) <= self.clock()
            )
            or (issuer and issuer.get("quarantined") is True)
            or not isinstance(account.get("roles"), list)
            or role not in cast(list[object], account["roles"])
        ):
            raise IdentityError("identity.account_unavailable")
        return account

    def login_start(
        self,
        role: str,
        binding: str,
        ceremony_id: str | None = None,
        session_hash: str | None = None,
        previous_raw_session: str | None = None,
    ) -> tuple[dict[str, object], str]:
        if role not in PRIVILEGED_ROLES | PARTICIPANT_ROLES:
            raise IdentityError("identity.invalid_role")
        now, state, nonce, verifier = self.clock(), token(), token(), token()
        intent_id = str(uuid4())
        record: dict[str, object] = {
            "id": intent_id,
            "binding": digest(binding),
            "nonce": nonce,
            "verifier": self.custody.encrypt(verifier),
            "role": role,
            "created_at": stamp(now),
            "expires_at": stamp(now + timedelta(minutes=5)),
            "state": "pending",
            "ceremony_id": ceremony_id,
            "session_hash": session_hash,
        }
        with self.store.transaction() as tx:
            if previous_raw_session is not None:
                previous_hash = digest(previous_raw_session)
                previous = tx.get("session", previous_hash)
                if (
                    previous
                    and previous.get("origin") == self.origin
                    and previous.get("binding") == digest(binding)
                ):
                    record["previous_session_hash"] = previous_hash
            tx.put("intent", digest(state), record)
            tx.put("intent", intent_id, {"state_hash": digest(state)})
        url = self.provider.authorization_url(
            state, nonce, verifier, bool(ceremony_id) or role in PRIVILEGED_ROLES
        )
        return {
            "intent_id": intent_id,
            "authorization_url": url,
            "expires_at": record["expires_at"],
        }, state

    def callback(
        self,
        state: str,
        code: str,
        binding: str,
        returned_issuer: str | None = None,
        provider_error: bool = False,
    ) -> tuple[dict[str, object], str | None, str | None]:
        key, now = digest(state), self.clock()
        with self.store.transaction() as tx:
            intent = tx.get("intent", key)
            if (
                intent is None
                or intent.get("purpose") == "owner_access_review"
                or not secrets.compare_digest(text(intent, "binding"), digest(binding))
                or instant(intent["expires_at"]) <= now
                or intent.get("state") != "pending"
            ):
                raise IdentityError("identity.invalid_login_intent")
            if returned_issuer is not None and returned_issuer != self.issuer:
                intent.update({"state": "failed", "verifier": ""})
                tx.put("intent", key, intent)
                failed = True
            elif provider_error:
                intent.update({"state": "failed", "verifier": ""})
                tx.put("intent", key, intent)
                failed = True
            else:
                intent["state"] = "redeeming"
                tx.put("intent", key, intent)
                failed = False
        if failed:
            raise IdentityError("identity.login_cancelled")
        try:
            principal = self.provider.exchange(
                code,
                self.custody.decrypt(text(intent, "verifier")),
                text(intent, "nonce"),
                bool(intent.get("ceremony_id")) or text(intent, "role") in PRIVILEGED_ROLES,
            )
            if text(intent, "role") in PRIVILEGED_ROLES and not principal.mfa:
                raise IdentityError("identity.mfa_required")
            now = self.clock()
            with self.store.transaction() as tx:
                if instant(intent["expires_at"]) <= now or principal.expires_at <= now:
                    raise IdentityError("identity.expired_login")
                account = self._account(tx, principal.subject, text(intent, "role"))
                if intent.get("ceremony_id"):
                    session_hash = text(intent, "session_hash")
                    session = tx.get("session", session_hash)
                    ceremony = tx.get("ceremony", text(intent, "ceremony_id"))
                    if (
                        session is None
                        or ceremony is None
                        or not self._usable_session(session, now)
                        or session.get("revision") != account["revision"]
                        or session.get("role_revision") != account["role_revision"]
                        or session.get("account_id") != account["account_id"]
                        or ceremony.get("session_hash") != session_hash
                        or not principal.mfa
                        or (now - principal.auth_time).total_seconds() > 300
                        or principal.auth_time
                        < instant(intent["created_at"]) - timedelta(seconds=5)
                    ):
                        raise IdentityError("identity.invalid_stepup")
                    intent.update(
                        {
                            "proof_subject": principal.subject,
                            "proof_auth_time": stamp(principal.auth_time),
                            "proof_mfa": principal.mfa,
                            "proof_consumed": False,
                        }
                    )
                    retired = dict(session)
                    retired.update({"revoked": True, "access_token": "", "replaced_locally": True})
                    tx.put("session", session_hash, retired)
                    raw_session = token()
                    replacement_hash = digest(raw_session)
                    intent["session_hash"] = replacement_hash
                    ceremony["session_hash"] = replacement_hash
                    tx.put("ceremony", text(intent, "ceremony_id"), ceremony)
                    session.update(
                        {
                            "auth_time": stamp(principal.auth_time),
                            "mfa": True,
                            "csrf": token(),
                            "last_seen": stamp(now),
                            "factors": list(principal.factors),
                            "access_token": self.custody.encrypt(principal.access_token),
                            "expires_at": stamp(
                                min(principal.expires_at, now + timedelta(hours=1))
                            ),
                        }
                    )
                    tx.put("session", replacement_hash, session)
                    proof_id: str | None = text(intent, "id")
                else:
                    previous_hash = intent.get("previous_session_hash")
                    if isinstance(previous_hash, str):
                        previous = tx.get("session", previous_hash)
                        # The exact predecessor was securely captured while its
                        # origin and browser binding matched at login_start.
                        # Later protocol-metadata rebinding must not preserve it.
                        if previous and previous.get("origin") == self.origin:
                            previous.update(
                                {"revoked": True, "access_token": "", "replaced_locally": True}
                            )
                            tx.put("session", previous_hash, previous)
                    raw_session = token()
                    proof_id = None
                    session = {
                        "account_id": account["account_id"],
                        "created_at": stamp(now),
                        "subject": principal.subject,
                        "role": intent["role"],
                        "mfa": principal.mfa,
                        "factors": list(principal.factors),
                        "auth_time": stamp(principal.auth_time),
                        "expires_at": stamp(min(principal.expires_at, now + timedelta(hours=1))),
                        "last_seen": stamp(now),
                        "revision": account["revision"],
                        "role_revision": account["role_revision"],
                        "csrf": token(),
                        "binding": digest(binding),
                        "origin": self.origin,
                        "access_token": self.custody.encrypt(principal.access_token),
                        "revoked": False,
                    }
                    tx.put("session", digest(raw_session), session)
                intent.update({"state": "completed", "verifier": "", "nonce": ""})
                tx.put("intent", key, intent)
                view = self._view(session)
            return view, raw_session, proof_id
        except IdentityError as error:
            with self.store.transaction() as tx:
                latest = tx.get("intent", key)
                if latest and latest.get("state") == "redeeming":
                    latest.update(
                        {
                            "state": "uncertain"
                            if isinstance(error, ExchangeUncertain)
                            else "failed",
                            "verifier": "",
                            "nonce": "",
                        }
                    )
                    tx.put("intent", key, latest)
            raise

    def _view(self, session: dict[str, object]) -> dict[str, object]:
        return {
            "account_id": session["account_id"],
            "role": session["role"],
            "assurance": "AL2"
            if (self.clock() - instant(session["auth_time"])).total_seconds() <= 300
            else "AL1",
            "expires_at": session["expires_at"],
            "auth_time": session["auth_time"],
            "revision": session["revision"],
        }

    def _usable_session(self, session: dict[str, object], now: datetime) -> bool:
        return (
            session.get("revoked") is not True
            and session.get("origin") == self.origin
            and instant(session["expires_at"]) > now
            and (
                session.get("role") not in PRIVILEGED_ROLES
                or (
                    session.get("mfa") is True
                    and (now - instant(session["last_seen"])).total_seconds() < 900
                )
            )
        )

    def current(self, raw_session: str) -> dict[str, object]:
        now, key = self.clock(), digest(raw_session)
        with self.store.transaction() as tx:
            session = tx.get("session", key)
            if session is None or not self._usable_session(session, now):
                raise IdentityError("identity.session_unavailable", 401)
            account = self._account(tx, text(session, "subject"), text(session, "role"))
            if (
                session["revision"] != account["revision"]
                or session["role_revision"] != account["role_revision"]
            ):
                raise IdentityError("identity.session_revoked", 401)
        if not self.provider.active(
            self.custody.decrypt(text(session, "access_token")), text(session, "subject")
        ):
            raise IdentityError("identity.current_authority_unavailable", 503)
        with self.store.transaction() as tx:
            latest = tx.get("session", key)
            account = self._account(tx, text(session, "subject"), text(session, "role"))
            if (
                latest is None
                or not self._usable_session(latest, self.clock())
                or latest.get("subject") != session["subject"]
                or latest.get("role") != session["role"]
                or latest.get("revision") != account["revision"]
                or latest.get("role_revision") != account["role_revision"]
                or account["revision"] != session["revision"]
                or account["role_revision"] != session["role_revision"]
            ):
                raise IdentityError("identity.session_revoked", 401)
            latest["last_seen"] = stamp(self.clock())
            tx.put("session", key, latest)
        return latest

    def session_view(self, raw_session: str) -> dict[str, object]:
        return self._view(self.current(raw_session))

    def issue_help_proof(self, raw_session: str, origin: str) -> str:
        if origin != self.origin:
            raise IdentityError("identity.origin_denied")
        session = self.current(raw_session)
        proof_id = str(uuid4())
        with self.store.transaction() as tx:
            tx.put(
                "proof",
                proof_id,
                {
                    "session_hash": digest(raw_session),
                    "account_id": session["account_id"],
                    "expires_at": stamp(self.clock() + timedelta(seconds=1)),
                    "consumed": False,
                    "audience": "care-link-help",
                },
            )
        return proof_id

    def browser_context(self, raw_session: str) -> dict[str, object]:
        session = self.current(raw_session)
        return {
            "account_id": session["account_id"],
            "role": session["role"],
            "csrf_token": session["csrf"],
        }

    def help_authorize(self, request: dict[str, object]) -> dict[str, object]:
        now = self.clock()
        deadline = instant(request["deadline"])
        if not now < deadline <= now + timedelta(seconds=1):
            raise IdentityError("identity.help_deadline")
        proof_id = text(request, "browser_proof_ref")
        with self.store.transaction() as tx:
            proof = tx.get("proof", proof_id)
            if (
                proof is None
                or proof.get("consumed") is True
                or instant(proof["expires_at"]) <= now
            ):
                raise IdentityError("identity.help_proof_unavailable")
            session = tx.get("session", text(proof, "session_hash"))
            if session is None or not self._usable_session(session, now):
                raise IdentityError("identity.help_proof_unavailable")
            account = self._account(tx, text(session, "subject"), text(session, "role"))
            if (
                account["revision"] != session["revision"]
                or account["role_revision"] != session["role_revision"]
            ):
                raise IdentityError("identity.help_proof_unavailable")
            if request["action"] == "accept" and (
                session["role"] not in {"worker", "supervisor"} or session.get("mfa") is not True
            ):
                raise IdentityError("identity.worker_required")
            if request["action"] == "reconcile":
                raise IdentityError("identity.reconciliation_not_admitted")
            proof["consumed"] = True
            tx.put("proof", proof_id, proof)
        # Revalidate current provider status for this exact decision; no cached proof grant.
        if not self.provider.active(
            self.custody.decrypt(text(session, "access_token")), text(session, "subject")
        ):
            raise IdentityError("identity.current_authority_unavailable", 503)
        with self.store.transaction() as tx:
            latest = tx.get("session", text(proof, "session_hash"))
            account = self._account(tx, text(session, "subject"), text(session, "role"))
            if (
                latest is None
                or not self._usable_session(latest, self.clock())
                or latest.get("subject") != session["subject"]
                or latest.get("role") != session["role"]
                or latest.get("revision") != account["revision"]
                or latest.get("role_revision") != account["role_revision"]
                or account["revision"] != session["revision"]
                or account["role_revision"] != session["role_revision"]
                or self.clock() >= deadline
                or instant(proof["expires_at"]) <= self.clock()
            ):
                raise IdentityError("identity.help_proof_unavailable")
            receipt: dict[str, object] = {
                "operation_id": request["operation_id"],
                "help_id": request["help_id"],
                "request_digest": request["request_digest"],
                "principal_id": session["account_id"],
                "action": request["action"],
                "decision": "PERMIT",
                "identity_revision": account["revision"],
                "role_revision": account["role_revision"],
                "one_use_nonce": request["nonce"],
                "issued_at": stamp(self.clock()),
                "expires_at": stamp(deadline),
                "issuer_id": "care-link-identity",
                "audience": "care-link-help",
                "key_id": self.signer.key_id,
            }
            receipt["signature"] = self.signer.sign(receipt)
            return receipt

    def logout(self, raw_session: str, operation_id: str) -> dict[str, object]:
        key = digest(raw_session)
        with self.store.transaction() as tx:
            previous = tx.get("operation", operation_id)
            if previous:
                if previous.get("session_hash") != key or previous.get("action") != "logout":
                    raise IdentityError("identity.operation_conflict", 409)
                return {
                    "operation_id": operation_id,
                    "state": "committed",
                    "resource_id": None,
                    "revision": previous["revision"],
                    "audit_ref": previous["audit_ref"],
                }
            session = tx.get("session", key)
            if session is None or session.get("origin") != self.origin:
                raise IdentityError("identity.session_unavailable", 401)
            encrypted_access = text(session, "access_token")
            upstream_state = (
                "confirmed" if session.get("upstream_revocation") == "confirmed" else "pending"
            )
            session["revoked"] = True
            session["access_token"] = ""
            session["upstream_revocation"] = upstream_state
            tx.put("session", key, session)
            audit_ref = str(uuid4())
            tx.put(
                "operation",
                operation_id,
                {
                    "action": "logout",
                    "session_hash": key,
                    "revision": session["revision"],
                    "audit_ref": audit_ref,
                    "event_at": stamp(self.clock()),
                },
            )
        # Local fencing does not depend on upstream availability. Provider-side
        # revocation is separate and never claimed instantaneous or atomic.
        try:
            if encrypted_access:
                self.provider.revoke(self.custody.decrypt(encrypted_access))
                upstream_state = "confirmed"
        except IdentityError:
            upstream_state = "pending"
        with self.store.transaction() as tx:
            latest = tx.get("session", key)
            if latest:
                latest["upstream_revocation"] = upstream_state
                tx.put("session", key, latest)
        return {
            "operation_id": operation_id,
            "state": "committed",
            "resource_id": None,
            "revision": session["revision"],
            "audit_ref": audit_ref,
        }
