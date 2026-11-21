"""Fixed Core-to-data task transport with fresh signed human delegation.

Runtime peer metadata is attested at Core, covered by the body signature, and
rechecked against current workload authority at data. No Actor is serialized.
"""

import base64
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import uuid4

import httpx
from care_link_contracts import parse_contract, validate_contract
from care_link_domain import Actor, ManualError, WorkloadPeer
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ..manual_envelopes import IdentityEvidencePort
from .ports import Record


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def runtime_record(peer: WorkloadPeer) -> Record:
    return {
        "workload_id": peer.workload_id,
        "fence_generation": peer.fence_generation,
        "certificate_digest": peer.certificate_digest,
        "certificate_expires_at": peer.certificate_expires_at.isoformat().replace("+00:00", "Z"),
    }


class TaskReadPort(Protocol):
    def task_read(self, actor: Actor, task_id: str) -> Record: ...


class TaskDelegationSigner:
    def __init__(
        self,
        identity: IdentityEvidencePort,
        key: Ed25519PrivateKey,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.identity, self.key, self.clock = identity, key, clock

    def headers(
        self,
        actor: Actor,
        operation: str,
        task_id: str,
        data: Record,
        peer: WorkloadPeer,
        path: str,
        *,
        reservation: str = "",
    ) -> dict[str, str]:
        key, nonce = str(uuid4()), str(uuid4())
        paths: Record = {
            "task_id": task_id,
            "runtime": runtime_record(peer),
            "reservation": reservation,
        }
        body_digest = hashlib.sha256(
            canonical({"arguments": data, "path_arguments": paths})
        ).hexdigest()
        evidence = self.identity.evidence(
            actor, "assistance_" + operation, body_digest, nonce, None
        )
        expires = min(
            datetime.fromisoformat(str(evidence["expires_at"])), peer.certificate_expires_at
        )
        if actor.request_deadline:
            expires = min(expires, actor.request_deadline)
        if expires <= self.clock():
            raise ManualError("assistance.delegation_expired", 403)
        delegation: Record = {
            "id": key,
            "actor": {
                "kind": "human",
                "principal_id": actor.account_id,
                "workload_id": "spiffe://care-link.demo/demo/core",
                "role": actor.role,
                "assurance": "AL2" if actor.mfa else "AL1",
                "identity_evidence_id": evidence["id"],
                "task_id": task_id,
                "job_id": None,
            },
            "evidence": evidence,
            "scope": {
                "session_id": None,
                "subject_id": None,
                "purpose": "support",
                "fields": [],
                "recipient_id": None,
            },
            "audience": "care-link-data",
            "method": "POST",
            "path": path,
            "body_digest": body_digest,
            "nonce": nonce,
            "expires_at": expires.isoformat().replace("+00:00", "Z"),
        }
        delegation["signature"] = (
            base64.urlsafe_b64encode(self.key.sign(canonical(delegation))).rstrip(b"=").decode()
        )
        validate_contract("SignedDelegation", delegation)
        return {
            "Idempotency-Key": key,
            "X-Assistance-Delegation": canonical(delegation).decode(),
            "X-Assistance-Runtime": canonical(paths["runtime"]).decode(),
            "X-Assistance-Reservation": reservation,
            "Content-Type": "application/json",
        }


class HttpCoordinator:
    def __init__(
        self,
        client: httpx.Client,
        signer: TaskDelegationSigner,
        task_reader: TaskReadPort,
    ) -> None:
        self.client, self.signer, self.task_reader = client, signer, task_reader

    def task_read(self, actor: Actor, task_id: str) -> Record:
        return self.task_reader.task_read(actor, task_id)

    def _call(
        self,
        operation: str,
        actor: Actor,
        task_id: str,
        data: Record,
        peer: WorkloadPeer,
        *,
        reservation: str = "",
    ) -> Record:
        contract = {
            "step_lease": "LeaseCommand",
            "step_renew": "LeaseCommand",
            "reserve_proposal": "RuntimeInferenceRequest",
            "proposal_submit": "Proposal",
            "tool_invoke": "ToolInvoke",
        }[operation]
        data = cast(Record, json.loads(canonical(data)))
        validate_contract(contract, data)
        path = "/internal/v1/data/assistance/" + operation
        if operation in {"step_lease", "step_renew"}:
            path += "/" + task_id
        headers = self.signer.headers(
            actor, operation, task_id, data, peer, path, reservation=reservation
        )
        try:
            with self.client.stream(
                "POST",
                "https://data:8443" + path,
                json=data,
                headers=headers,
                timeout=1,
                follow_redirects=False,
            ) as response:
                response.raise_for_status()
                raw = bytearray()
                for chunk in response.iter_bytes():
                    if len(raw) + len(chunk) > 65536:
                        raise ManualError("assistance.gateway_response_limit", 503)
                    raw.extend(chunk)
            # The internal reservation includes server-authoritative source
            # context; its public TaskView is validated separately by Core.
            if operation == "reserve_proposal":

                def unique(pairs: list[tuple[str, object]]) -> Record:
                    value: Record = {}
                    for key, item in pairs:
                        if key in value:
                            raise ValueError("duplicate key")
                        value[key] = item
                    return value

                result = cast(Record, json.loads(raw, object_pairs_hook=unique))
                if set(result) != {"reservation_id", "task", "sources", "source_vector", "goal"}:
                    raise ValueError("closed reservation result required")
                validate_contract("TaskView", result["task"])
                return result
            output = {
                "step_lease": "LeaseView",
                "step_renew": "LeaseView",
                "tool_invoke": "Observation",
                "proposal_submit": "DraftView",
            }[operation]
            return cast(Record, parse_contract(output, raw.decode()))
        except (httpx.HTTPError, ValueError) as error:
            raise ManualError("assistance.gateway_unavailable", 503) from error

    def step_lease(self, actor: Actor, task_id: str, data: Record, peer: WorkloadPeer) -> Record:
        return self._call("step_lease", actor, task_id, data, peer)

    def step_renew(self, actor: Actor, task_id: str, data: Record, peer: WorkloadPeer) -> Record:
        return self._call("step_renew", actor, task_id, data, peer)

    def reserve_proposal(self, actor: Actor, data: Record, peer: WorkloadPeer) -> Record:
        return self._call("reserve_proposal", actor, str(data["task_id"]), data, peer)

    def proposal_submit(
        self, actor: Actor, data: Record, peer: WorkloadPeer, reservation_id: str
    ) -> Record:
        return self._call(
            "proposal_submit", actor, str(data["task_id"]), data, peer, reservation=reservation_id
        )

    def tool_invoke(self, actor: Actor, data: Record, peer: WorkloadPeer) -> Record:
        return self._call("tool_invoke", actor, str(data["task_id"]), data, peer)
