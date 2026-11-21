"""Signed named requests with fresh identity, gateway metadata and real PDP preflight.

The data gateway still rebuilds policy and guards under its transaction boundary;
this preliminary permit never substitutes for final gateway authorization.
"""

import base64
import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast
from uuid import UUID, uuid4

import httpx
from care_link_contracts import CONTRACT_NAMES, parse_contract, validate_contract
from care_link_domain import Actor, ManualError, PolicyPort
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .governance_bindings import ROUTES as GOVERNANCE_ROUTES
from .manual_identity import canonical, fixed_origin

GOVERNANCE_PURPOSES = {
    route.action: (
        "security"
        if route.action.startswith("incident_")
        else "audit"
        if route.action in {"audit_query", "metrics_query", "evidence_export", "audit_export_read"}
        else "service_operations"
        if route.action == "health_read"
        else "governance"
    )
    for route in GOVERNANCE_ROUTES
}

Record = dict[str, object]


class IdentityEvidencePort(Protocol):
    def evidence(
        self, actor: Actor, action: str, request_digest: str, nonce: str, resource: object
    ) -> Record: ...


class SignedEnvelopeFactory:
    def __init__(
        self,
        data_client: httpx.Client,
        data_origin: str,
        identity: IdentityEvidencePort,
        policy: PolicyPort,
        core_private_key: Ed25519PrivateKey,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.client, self.origin, self.identity = data_client, fixed_origin(data_origin), identity
        self.policy, self.key, self.clock = policy, core_private_key, clock

    @staticmethod
    def _actor(actor: Actor, evidence_id: object, *, target: bool = False) -> Record:
        return {
            "kind": "human",
            "principal_id": actor.account_id,
            # The policy input describes the proposed data operation, while the
            # delegation names its actual signing core workload.
            "workload_id": "spiffe://care-link.demo/demo/data"
            if target
            else "spiffe://care-link.demo/demo/core",
            "role": actor.role,
            "assurance": "AL2" if actor.mfa else "AL1",
            "identity_evidence_id": evidence_id,
            "task_id": None,
            "job_id": None,
        }

    @staticmethod
    def _scope(action: str, resource: object) -> Record:
        return {
            "session_id": resource,
            "subject_id": None,
            "purpose": GOVERNANCE_PURPOSES[action]
            if action in GOVERNANCE_PURPOSES
            else "service_operations"
            if action.startswith("workforce_") or action in {"queue_list", "control_change"}
            else "follow_up"
            if action.startswith(
                ("followup_", "post_crisis_", "participant_inbox", "inbox_message_")
            )
            else "rights"
            if action.startswith(("rights_", "export_download", "hold_"))
            else "plan"
            if action.startswith("plan_")
            else "governance"
            if action == "directory_ingest"
            else "security"
            if action == "directory_suspend"
            else "support",
            "fields": [],
            "recipient_id": None,
        }

    def _delegation(
        self,
        actor: Actor,
        action: str,
        key: str,
        args: Record,
        paths: Record,
        scope: Record,
        path: str,
    ) -> Record:
        if actor.request_deadline is not None and actor.request_deadline <= self.clock():
            raise ManualError("manual.deadline_exceeded", 503)
        body_digest = hashlib.sha256(
            canonical({"arguments": args, "path_arguments": paths})
        ).hexdigest()
        nonce = str(uuid4())
        evidence = self.identity.evidence(actor, action, body_digest, nonce, scope["session_id"])
        expires = datetime.fromisoformat(cast(str, evidence["expires_at"]))
        if actor.request_deadline is not None:
            expires = min(expires, actor.request_deadline)
        if expires <= self.clock():
            raise ManualError("manual.deadline_exceeded", 503)
        delegation: Record = {
            "id": key,
            "actor": self._actor(actor, evidence["id"]),
            "evidence": evidence,
            "scope": scope,
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
        return delegation

    def build(
        self, actor: Actor, action: str, key: str, arguments: Record, path_arguments: Record
    ) -> Record:
        # Preserve the earliest request deadline across all preflight work.
        started_deadline = self.clock() + timedelta(seconds=1)
        actor = replace(
            actor,
            request_deadline=min(started_deadline, actor.request_deadline)
            if actor.request_deadline
            else started_deadline,
        )
        # Freeze all caller input before doing remote work.
        if str(UUID(key)) != key:
            raise ManualError("manual.invalid_operation", 400)
        args, paths = cast(
            tuple[Record, Record], tuple(json.loads(canonical([arguments, path_arguments])))
        )
        resource = (
            None
            if action == "review_workspace"
            else paths.get("session_id", args.get("session_id"))
        )
        scope = self._scope(action, resource)
        # Public contract inventory limits the fixed set of named HTTP targets.
        if "Gateway_" + action not in CONTRACT_NAMES:
            raise ManualError("manual.unsupported_operation", 400)
        # Argument/path schemas are checked through the gateway contract after
        # composition below; unknown names cannot select arbitrary HTTP paths.
        payload = args if action != "operation_status" else {"operation_id": paths["operation_id"]}
        payload_digest = hashlib.sha256(
            canonical(
                {
                    "contract_version": "care.v1",
                    "action": action,
                    "session_id": resource,
                    "payload": payload,
                }
            )
        ).hexdigest()
        metadata_args: Record = {"action": action, "scope": scope, "payload_digest": payload_digest}
        if action in GOVERNANCE_PURPOSES or action.startswith(
            (
                "plan_",
                "consent_",
                "directory_",
                "referral_",
                "dispatch_",
                "receipt_",
                "dispatcher_",
                "task_",
                "draft_",
                "assistance_",
                "followup_",
                "post_crisis_",
                "outcome",
                "participant_inbox",
                "inbox_message_",
                "rights_",
                "export_download",
                "hold_",
            )
        ):
            metadata_args["planning"] = {
                "action": action,
                "operation_id": key,
                "arguments": args,
                "path_arguments": paths,
            }
        metadata_paths: Record = {"session_id": resource} if resource is not None else {}
        metadata_key = str(uuid4())
        preflight = self._delegation(
            actor,
            action,
            metadata_key,
            metadata_args,
            metadata_paths,
            scope,
            "/internal/v1/data/authority",
        )
        metadata_request = {"delegation": preflight, **metadata_args}
        validate_contract("MetadataRequest", metadata_request)
        try:
            response = self.client.post(
                self.origin + "/internal/v1/data/authority",
                json=metadata_request,
                headers={"Idempotency-Key": metadata_key, "Cookie": ""},
                timeout=1.0,
                follow_redirects=False,
            )
        except httpx.HTTPError as error:
            raise ManualError("manual.authority_unavailable", 503) from error
        if response.status_code != 200:
            raise ManualError(
                "manual.authority_unavailable"
                if response.status_code >= 500
                else "manual.gateway_denied",
                503 if response.status_code >= 500 else 403,
            )
        if len(response.content) > 65536 or not response.headers.get("content-type", "").startswith(
            "application/json"
        ):
            raise ManualError("manual.invalid_gateway_response", 503)
        metadata = cast(Record, parse_contract("MetadataResult", response.text))
        if metadata["complete"] is not True:
            raise ManualError("manual.gateway_denied")
        # Obtain a new request-bound identity receipt after metadata resolution;
        # preflight latency can never renew the actual request's deadline.
        delegation = self._delegation(
            actor, action, key, args, paths, scope, "/internal/v1/data/" + action
        )
        evidence = cast(Record, delegation["evidence"])
        request: Record = {
            "operation_id": key,
            "actor": self._actor(actor, evidence["id"], target=True),
            "action": action,
            "scope": metadata.get("resolved_scope", scope),
            "tags": {"environment": "demo", "population": "synthetic"},
            "jurisdiction": args.get("jurisdiction") if action == "session_create" else None,
            "versions": metadata["versions"],
            "payload_digest": payload_digest,
            "consent_id": metadata.get("consent_id"),
            "review_id": metadata.get("review_id"),
            "bundle_digest": metadata["bundle_digest"],
            "artifact_digests": metadata.get("artifact_digests", []),
            "mode": metadata["mode"],
            # Successful metadata is itself audited inside the gateway.
            "audit_ready": True,
            "authority_complete": True,
            "authority_facts": metadata["authority_facts"],
        }
        if "directory_bindings" in metadata:
            request["directory_bindings"] = metadata["directory_bindings"]
        if "disclosure_grants" in metadata:
            request["disclosure_grants"] = metadata["disclosure_grants"]
        if "referral_payload_digest" in metadata:
            request["referral_payload_digest"] = metadata["referral_payload_digest"]
        validate_contract("PolicyInput", request)
        decision = self.policy.evaluate(request)
        validate_contract("PolicyDecision", decision)
        if (
            decision["decision"] != "PERMIT"
            or decision["binding_digest"] != hashlib.sha256(canonical(request)).hexdigest()
            or decision["versions"] != metadata["versions"]
            or decision["bundle_digest"] != metadata["bundle_digest"]
            or decision["obligations"] != [{"kind": "audit_before_effect"}]
            or datetime.fromisoformat(cast(str, decision["expires_at"])) <= self.clock()
            or datetime.fromisoformat(cast(str, delegation["expires_at"])) <= self.clock()
        ):
            raise ManualError("manual.policy_denied")
        result: Record = {
            "arguments": args,
            "path_arguments": paths,
            "delegation": delegation,
            "decision": decision,
        }
        validate_contract("Gateway_" + action, result)
        return result
