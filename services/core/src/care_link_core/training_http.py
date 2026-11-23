"""Signed Core-to-training transport with a separate audience and fixed origin."""

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
from .training_routes import Record


class HttpTrainingGateway:
    def __init__(
        self,
        client: httpx.Client,
        origin: str,
        identity: IdentityEvidencePort,
        key: Ed25519PrivateKey,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.client, self.origin = client, fixed_origin(origin)
        self.identity, self.key, self.clock = identity, key, clock

    def _request(
        self, actor: Actor, action: str, key: str, arguments: Record, paths: Record, output: str
    ) -> Record:
        deadline = min(
            actor.expires_at,
            actor.request_deadline or actor.expires_at,
            self.clock() + timedelta(seconds=1),
        )
        if actor.role != "trainer" or not actor.mfa or self.clock() >= deadline:
            raise ManualError("training.trainer_required")
        body_digest = hashlib.sha256(
            canonical({"arguments": arguments, "path_arguments": paths})
        ).hexdigest()
        evidence = self.identity.evidence(
            actor, action, body_digest, str(uuid4()), paths.get("scenario_id")
        )
        validate_contract("IdentityEvidence", evidence)
        expires = min(deadline, datetime.fromisoformat(cast(str, evidence["expires_at"])))
        if self.clock() >= expires:
            raise ManualError("manual.deadline_exceeded", 503)
        envelope: Record = {
            "operation_id": key,
            "action": action,
            "audience": "care-link-training",
            "arguments": arguments,
            "path_arguments": paths,
            "evidence": evidence,
            "expires_at": expires.isoformat().replace("+00:00", "Z"),
        }
        envelope["signature"] = (
            base64.urlsafe_b64encode(self.key.sign(canonical(envelope))).rstrip(b"=").decode()
        )
        validate_contract("TrainingEnvelope", envelope)
        try:
            reply = self.client.post(
                self.origin + "/internal/v1/training/" + action,
                json=envelope,
                headers={"Idempotency-Key": key, "Cookie": ""},
                timeout=1.0,
                follow_redirects=False,
            )
        except httpx.HTTPError as error:
            raise ManualError("manual.commit_unknown", 503) from error
        if (
            len(reply.content) > 65536
            or not reply.headers.get("content-type", "").startswith("application/json")
            or self.clock() >= expires
        ):
            raise ManualError("manual.commit_unknown", 503)
        try:
            result = cast(
                Record, parse_contract(output if reply.status_code == 200 else "Error", reply.text)
            )
        except ContractError as error:
            raise ManualError("manual.commit_unknown", 503) from error
        if reply.status_code == 200:
            return result
        if reply.status_code in {403, 404, 409, 422}:
            key = {
                "IDEMPOTENCY_CONFLICT": "manual.idempotency_conflict",
                "REVISION_CONFLICT": "manual.revision_conflict",
            }.get(str(result["code"]), "training.request_denied")
            raise ManualError(key, reply.status_code)
        raise ManualError("manual.commit_unknown", 503)

    def scenario_create(self, actor: Actor, key: str, data: Record) -> Record:
        return self._request(actor, "scenario_create", key, data, {}, "CommandResult")

    def scenario_read(self, actor: Actor, scenario_id: str) -> Record:
        return self._request(
            actor, "scenario_read", str(uuid4()), {}, {"scenario_id": scenario_id}, "ScenarioView"
        )

    def scenario_stop(self, actor: Actor, key: str, scenario_id: str, data: Record) -> Record:
        return self._request(
            actor, "scenario_stop", key, data, {"scenario_id": scenario_id}, "CommandResult"
        )
