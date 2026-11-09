"""Signed local restrictive signals; no SSF/CAEP interoperability claim."""

import base64
import hashlib
from collections.abc import Callable
from datetime import datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .crypto import canonical, digest
from .domain import IdentityError, Store, instant, stamp, text
from .workload_signals import SourceConflict, WorkloadSignals


class SignalReceiver:
    def __init__(
        self,
        store: Store,
        issuer: str,
        audience: str,
        public_key: Ed25519PublicKey,
        account_issuer: str,
        clock: Callable[[], datetime],
        workloads: WorkloadSignals | None = None,
    ) -> None:
        self.store, self.issuer, self.audience = store, issuer, audience
        self.public_key, self.account_issuer, self.clock = public_key, account_issuer, clock
        self.workloads = workloads

    def ingest(self, signal: dict[str, object]) -> dict[str, object]:
        now = self.clock()
        if signal["issuer_id"] != self.issuer or signal["audience"] != self.audience:
            raise IdentityError("identity.signal_issuer_denied")
        age = (now - instant(signal["event_at"])).total_seconds()
        unsigned = {k: v for k, v in signal.items() if k != "signature"}
        content = {k: v for k, v in unsigned.items() if k != "digest"}
        expected = hashlib.sha256(canonical(content)).hexdigest()
        if expected != signal["digest"]:
            raise IdentityError("identity.signal_digest_denied")
        try:
            encoded = text(signal, "signature")
            self.public_key.verify(
                base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)), canonical(unsigned)
            )
        except (InvalidSignature, ValueError) as error:
            raise IdentityError("identity.signal_signature_denied") from error
        signal_key = digest(self.issuer + "\0" + text(signal, "jti"))
        with self.store.transaction() as tx:
            prior = tx.get("signal", signal_key)
            quarantined = (tx.get("issuer", self.issuer) or {}).get("quarantined") is True
            collision = prior is not None and prior.get("digest") != signal["digest"]
        if collision or quarantined:
            return self._quarantine_source(signal, now)
        try:
            if signal["event_type"] == "workload_compromised":
                if self.workloads is None:
                    raise IdentityError("identity.workload_signal_not_admitted", 503)
                return self.workloads.submit(signal, now, age)
            return self._account_signal(signal, now, age)
        except SourceConflict:
            return self._quarantine_source(signal, now)

    def _quarantine_source(self, signal: dict[str, object], now: datetime) -> dict[str, object]:
        # One configured signed source covers both account and workload events.
        # Quarantine therefore removes both authority families before its ACK.
        with self.store.transaction() as tx:
            for issuer in {self.issuer, self.account_issuer}:
                tx.put(
                    "issuer",
                    issuer,
                    {
                        "quarantined": True,
                        "source_issuer": self.issuer,
                        "received_at": stamp(now),
                        "fence_state": "pending",
                    },
                )
        if self.workloads is not None:
            result = self.workloads.quarantine_source(signal, now)
        else:
            with self.store.transaction() as tx:
                head = tx.get("head", digest(self.issuer + "\0" + text(signal, "subject_id"))) or {
                    "sequence": "0"
                }
            result = {
                "jti": signal["jti"],
                "state": "quarantined",
                "accepted_sequence": head["sequence"],
            }
        with self.store.transaction() as tx:
            for issuer in {self.issuer, self.account_issuer}:
                row = tx.get("issuer", issuer)
                if row is None:
                    raise IdentityError("identity.source_quarantine_missing", 503)
                row["fence_state"] = "durable"
                tx.put("issuer", issuer, row)
        return result

    def _account_signal(
        self, signal: dict[str, object], now: datetime, age: float
    ) -> dict[str, object]:
        sequence = int(text(signal, "source_sequence"))
        head_key = digest(self.issuer + "\0" + text(signal, "subject_id"))
        signal_key = digest(self.issuer + "\0" + text(signal, "jti"))
        with self.store.transaction() as tx:
            head = tx.get("head", head_key) or {"sequence": "0", "digest": "0" * 64}
            prior = tx.get("signal", signal_key)
            if prior is not None:
                if prior["digest"] != signal["digest"]:
                    raise SourceConflict()
                return {
                    "jti": signal["jti"],
                    "state": "duplicate",
                    "accepted_sequence": head["sequence"],
                }
            account_key = None
            account = None
            for key, candidate in tx.items("account"):
                if candidate.get("account_id") == signal["subject_id"]:
                    account_key, account = key, candidate
                    break
            if account is None or account_key is None:
                raise IdentityError("identity.signal_subject_denied")
            if age < -5 or age > 60:
                # A verified, mapped restrictive source cannot be ignored while
                # retaining positive account authority. No sequence is accepted;
                # authoritative snapshot recovery is required before regrant.
                account["blocked"] = True
                account["recovery_required"] = True
                tx.put("account", account_key, account)
                tx.put("signal", signal_key, {"digest": signal["digest"], "state": "gap_blocked"})
                return {
                    "jti": signal["jti"],
                    "state": "gap_blocked",
                    "accepted_sequence": head["sequence"],
                }
            if (
                sequence != int(text(head, "sequence")) + 1
                or signal["previous_digest"] != head["digest"]
            ):
                account["blocked"] = True
                tx.put("account", account_key, account)
                state = "gap_blocked"
            else:
                # Signals can only remove authority. role_changed does not infer
                # new grants from a notification; fresh provisioning is separate.
                account["enabled"] = False
                account["revision"] = str(int(text(account, "revision")) + 1)
                tx.put("account", account_key, account)
                head = {
                    "sequence": signal["source_sequence"],
                    "digest": signal["digest"],
                    "event_at": signal["event_at"],
                    "received_at": stamp(now),
                    "fenced_at": stamp(now),
                }
                tx.put("head", head_key, head)
                state = "applied"
            tx.put("signal", signal_key, {"digest": signal["digest"], "state": state})
        return {"jti": signal["jti"], "state": state, "accepted_sequence": head["sequence"]}
