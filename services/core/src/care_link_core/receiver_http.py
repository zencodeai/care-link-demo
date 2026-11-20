"""Fixed receiver HTTPS port with request-bound current identity and Core signature."""

import base64
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import httpx
from care_link_contracts import ContractError, parse_contract, validate_contract
from care_link_domain import Actor, ManualError
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .manual_envelopes import IdentityEvidencePort
from .manual_identity import canonical, fixed_origin
from .referral_ports import Record


class HttpReceiverGateway:
    def __init__(
        self,
        client: httpx.Client,
        origin: str,
        identity: IdentityEvidencePort,
        key: Ed25519PrivateKey,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not httpx.URL(origin).host:
            raise ValueError("Receiver origin requires a host")
        self.client, self.origin = client, fixed_origin(origin)
        self.identity, self.key, self.clock = identity, key, clock

    def _request(
        self, actor: Actor, action: str, key: str, arguments: Record, paths: Record, output: str
    ) -> Record:
        deadline = min(
            actor.request_deadline or actor.expires_at, self.clock() + timedelta(seconds=1)
        )
        if actor.role != "receiver" or not actor.mfa or self.clock() >= deadline:
            raise ManualError("manual.receiver_authority_required")
        body_digest = hashlib.sha256(
            canonical({"arguments": arguments, "path_arguments": paths})
        ).hexdigest()
        evidence = self.identity.evidence(
            actor, action, body_digest, str(uuid4()), paths.get("dispatch_id")
        )
        validate_contract("IdentityEvidence", evidence)
        expires = min(deadline, datetime.fromisoformat(cast(str, evidence["expires_at"])))
        envelope: Record = {
            "operation_id": key,
            "action": action,
            "audience": "care-link-receiver",
            "arguments": arguments,
            "path_arguments": paths,
            "evidence": evidence,
            "expires_at": expires.isoformat().replace("+00:00", "Z"),
        }
        envelope["signature"] = (
            base64.urlsafe_b64encode(self.key.sign(canonical(envelope))).rstrip(b"=").decode()
        )
        validate_contract("ReceiverEnvelope", envelope)
        try:
            reply = self.client.post(
                self.origin + "/internal/v1/receiver/" + action,
                json=envelope,
                headers={"Idempotency-Key": key, "Cookie": ""},
                timeout=1.0,
                follow_redirects=False,
            )
        except httpx.HTTPError as error:
            raise ManualError("manual.receiver_result_unknown", 503) from error
        if reply.status_code != 200:
            raise ManualError(
                "manual.receiver_unavailable"
                if reply.status_code >= 500
                else "manual.receiver_denied",
                503 if reply.status_code >= 500 else 403,
            )
        if len(reply.content) > 65536 or not reply.headers.get("content-type", "").startswith(
            "application/json"
        ):
            raise ManualError("manual.invalid_receiver_response", 503)
        if self.clock() >= expires:
            raise ManualError("manual.deadline_exceeded", 503)
        try:
            return cast(Record, parse_contract(output, reply.text))
        except ContractError as error:
            raise ManualError("manual.receiver_result_unknown", 503) from error

    def receiver_inbox(self, actor: Actor, data: Record) -> Record:
        return self._request(actor, "receiver_inbox", str(uuid4()), data, {}, "ReceiverPackagePage")

    def receiver_package(self, actor: Actor, dispatch_id: str) -> Record:
        return self._request(
            actor,
            "receiver_package",
            str(uuid4()),
            {},
            {"dispatch_id": dispatch_id},
            "ReferralPayload",
        )

    def receiver_detail(self, actor: Actor, dispatch_id: str) -> Record:
        return self._request(
            actor,
            "receiver_detail",
            str(uuid4()),
            {},
            {"dispatch_id": dispatch_id},
            "ReceiverDetail",
        )

    def receiver_decide(self, actor: Actor, key: str, data: Record) -> Record:
        return self._request(
            actor, "receiver_decide", key, data, {"dispatch_id": data["dispatch_id"]}, "ReceiptView"
        )
