"""Exact receiver-audience signature verification and independent current human identity."""

import base64
import hashlib
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

from care_link_contracts import validate_contract
from care_link_domain import Actor, ManualError
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .receiver import Record, canonical


def verify_signature(key: Ed25519PublicKey, data: Record) -> None:
    encoded = cast(str, data["signature"])
    raw = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
    if base64.urlsafe_b64encode(raw).rstrip(b"=").decode() != encoded:
        raise ValueError("noncanonical signature")
    key.verify(raw, canonical({k: v for k, v in data.items() if k != "signature"}).encode())


class ReceiverIdentity:
    def __init__(
        self,
        core_key: Ed25519PublicKey,
        identity_key: Ed25519PublicKey,
        resolve: Callable[[Record], Actor],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.core_key, self.identity_key, self.resolve, self.clock = (
            core_key,
            identity_key,
            resolve,
            clock,
        )

    def verify(self, envelope: Record, action: str, operation_id: str) -> Actor:
        validate_contract("ReceiverEnvelope", envelope)
        try:
            evidence = cast(Record, envelope["evidence"])
            paths = cast(Record, envelope["path_arguments"])
            args = cast(Record, envelope["arguments"])
            verify_signature(self.core_key, envelope)
            verify_signature(self.identity_key, evidence)
            now = self.clock()
            expires = datetime.fromisoformat(cast(str, envelope["expires_at"]))
            proof_expires = datetime.fromisoformat(cast(str, evidence["expires_at"]))
            verified = datetime.fromisoformat(cast(str, evidence["verified_at"]))
            body_digest = hashlib.sha256(
                canonical({"arguments": args, "path_arguments": paths}).encode()
            ).hexdigest()
            if (
                envelope["action"] != action
                or envelope["operation_id"] != operation_id
                or envelope["audience"] != "care-link-receiver"
                or evidence["action"] != action
                or evidence["request_digest"] != body_digest
                or evidence["resource_id"] != paths.get("dispatch_id")
                or evidence["kind"] != "human_identity"
                or evidence["role"] != "receiver"
                or not verified <= now < expires <= proof_expires <= now + timedelta(seconds=1)
                or action == "receiver_decide"
                and args["dispatch_id"] != paths["dispatch_id"]
            ):
                raise ValueError("receiver binding mismatch")
            current = self.resolve(evidence)
            if (
                current.account_id != evidence["principal_id"]
                or current.role != "receiver"
                or str(current.identity_revision) != evidence["identity_revision"]
                or str(current.role_revision) != evidence["role_revision"]
                or current.identity_evidence_id != evidence["id"]
                or not current.mfa
                or current.expires_at <= self.clock()
                or self.clock() >= expires
            ):
                raise ValueError("receiver current identity mismatch")
            return replace(
                current,
                request_deadline=min(current.request_deadline, expires)
                if current.request_deadline
                else expires,
            )
        except (InvalidSignature, KeyError, ValueError, TypeError) as error:
            raise ManualError("receiver.delegation_denied") from error
