"""Request-bound signed human delegation, resolved against current identity authority."""

import base64
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

from care_link_contracts import ContractError, validate_contract
from care_link_domain import Actor, ManualError
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .opa import canonical

Record = dict[str, object]


def _signature(key: Ed25519PublicKey, value: Record) -> None:
    encoded = cast(str, value["signature"])
    raw = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
    if base64.urlsafe_b64encode(raw).rstrip(b"=").decode() != encoded:
        raise ValueError("noncanonical signature")
    key.verify(raw, canonical({k: v for k, v in value.items() if k != "signature"}))


class DelegationVerifier:
    def __init__(
        self,
        core_key: Ed25519PublicKey,
        identity_key: Ed25519PublicKey,
        current_identity: Callable[[Record], Actor],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.core_key, self.identity_key = core_key, identity_key
        self.current_identity, self.clock = current_identity, clock

    def verify(self, envelope: Mapping[str, object], action: str, key: str, path: str) -> Actor:
        # Freeze the entire request before any signature/current-authority call.
        try:
            frozen = cast(Record, json.loads(canonical(dict(envelope))))
            delegation = cast(Record, frozen["delegation"])
            validate_contract("SignedDelegation", delegation)
            evidence = cast(Record, delegation["evidence"])
            claimed = cast(Record, delegation["actor"])
            scope = cast(Record, delegation["scope"])
            arguments = cast(Record, frozen["arguments"])
            paths = cast(Record, frozen["path_arguments"])
            _signature(self.core_key, delegation)
            _signature(self.identity_key, evidence)
            now = self.clock()
            expires = datetime.fromisoformat(cast(str, delegation["expires_at"]))
            evidence_expires = datetime.fromisoformat(cast(str, evidence["expires_at"]))
            verified = datetime.fromisoformat(cast(str, evidence["verified_at"]))
            body_digest = hashlib.sha256(
                canonical({"arguments": arguments, "path_arguments": paths})
            ).hexdigest()
            # Workspace selection is a signed query hint; the gateway checks
            # each projected conversation against the actor's current scope.
            resource = (
                None
                if action == "review_workspace"
                else paths.get("session_id", arguments.get("session_id"))
            )
            if (
                delegation["id"] != key
                or delegation["audience"] != "care-link-data"
                or delegation["method"] != "POST"
                or delegation["path"] != path
                or delegation["body_digest"] != body_digest
                or claimed["kind"] != "human"
                or evidence["kind"] != "human_identity"
                or claimed["workload_id"] != "spiffe://care-link.demo/demo/core"
                or evidence["id"] != claimed["identity_evidence_id"]
                or evidence["principal_id"] != claimed["principal_id"]
                or evidence["role"] != claimed["role"]
                or evidence["action"] != action
                or evidence["request_digest"] != body_digest
                or evidence["nonce"] != delegation["nonce"]
                or evidence["resource_id"] != resource
                or scope["session_id"] != resource
                or not verified <= now < expires <= evidence_expires <= now + timedelta(seconds=1)
            ):
                raise ValueError("delegation binding mismatch")
            actor = self.current_identity(cast(Record, json.loads(canonical(evidence))))
            if (
                actor.identity_evidence_id != evidence["id"]
                or actor.account_id != evidence["principal_id"]
                or actor.role != evidence["role"]
                or str(actor.identity_revision) != evidence["identity_revision"]
                or str(actor.role_revision) != evidence["role_revision"]
                or actor.expires_at <= self.clock()
                or self.clock() >= expires
            ):
                raise ValueError("current identity mismatch")
            deadline = min(expires, actor.request_deadline) if actor.request_deadline else expires
            return replace(actor, request_deadline=deadline)
        except (ContractError, InvalidSignature, KeyError, ValueError, TypeError) as error:
            raise ManualError("manual.delegation_denied") from error
