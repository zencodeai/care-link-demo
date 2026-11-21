"""Signed, explicitly admitted workload duties with no default positive authority."""

import base64
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType

from care_link_contracts import validate_contract
from care_link_domain import DutyActor, DutyScope, ManualError
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


@dataclass(frozen=True)
class DutyDefinition:
    duty_id: str
    workload_id: str
    operations: tuple[str, ...]
    purposes: tuple[str, ...]
    resource_classes: tuple[str, ...]
    per_run_limit: int
    approval_receipt_id: str
    expires_at: datetime

    def wire(self) -> dict[str, object]:
        return {
            "duty_id": self.duty_id,
            "workload_id": self.workload_id,
            "operations": list(self.operations),
            "purposes": list(self.purposes),
            "resource_classes": list(self.resource_classes),
            "environment": "demo",
            "population": "synthetic",
            "per_run_limit": self.per_run_limit,
            "allow_content_projection": False,
            "allow_human_approval": False,
            "approval_receipt_id": self.approval_receipt_id,
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
        }


@dataclass(frozen=True)
class SignedDutyDefinition:
    definition: DutyDefinition
    actor_id: str
    revision: int
    key_id: str
    signature: str

    @property
    def duty_id(self) -> str:
        return self.definition.duty_id

    def unsigned(self) -> dict[str, object]:
        return {
            "format_version": "care.duty.artifact.v1",
            "definition": self.definition.wire(),
            "actor_id": self.actor_id,
            "revision": str(self.revision),
            "key_id": self.key_id,
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical(self.unsigned())).hexdigest()


class SignedDutyRegistry:
    """Signature proves provenance. admitted_digests is separate exact admission.

    Empty admission is the default. The workload callback must authenticate the
    live peer and return its current unfenced generation; absence/failure denies.
    """

    def __init__(
        self,
        definitions: tuple[SignedDutyDefinition, ...] = (),
        *,
        signer_keys: Mapping[str, Ed25519PublicKey] | None = None,
        evidence_keys: Mapping[str, Ed25519PublicKey] | None = None,
        admitted_digests: frozenset[str] = frozenset(),
        approval_receipts: Mapping[str, str] | None = None,
        workload_check: Callable[[str, str], int] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.definitions = tuple(definitions)
        self.signer_keys = MappingProxyType(dict(signer_keys or {}))
        self.evidence_keys = MappingProxyType(dict(evidence_keys or {}))
        self.admitted_digests = admitted_digests
        self.approval_receipts = MappingProxyType(dict(approval_receipts or {}))
        self.workload_check = workload_check
        self.clock = clock
        if len({item.duty_id for item in definitions}) != len(definitions):
            raise ValueError("Duplicate duty definition")

    @staticmethod
    def _verify(key: Ed25519PublicKey, signature: str, content: object) -> None:
        raw = base64.b64decode(
            signature + "=" * (-len(signature) % 4), altchars=b"-_", validate=True
        )
        if base64.urlsafe_b64encode(raw).rstrip(b"=").decode() != signature:
            raise ValueError("Noncanonical signature")
        key.verify(raw, canonical(content))

    def authorize_batch(
        self, actor: DutyActor, action: str, request_digest: str, scope: DutyScope, count: int
    ) -> DutyActor:
        current = self.current(actor, action, request_digest, scope)
        definition = next(item for item in self.definitions if item.duty_id == current.duty_id)
        if type(count) is not int or not 1 <= count <= definition.definition.per_run_limit:
            raise ManualError("manual.duty_batch_limit", 403)
        return current

    def current(
        self, actor: DutyActor, action: str, request_digest: str, scope: DutyScope
    ) -> DutyActor:
        validate_contract("WorkloadActor", actor.wire())
        evidence = actor.evidence()
        validate_contract("DutyEvidence", evidence)
        now = self.clock()
        definition = next(
            (item for item in self.definitions if item.duty_id == actor.duty_id), None
        )
        if (
            definition is None
            or definition.digest not in self.admitted_digests
            or self.approval_receipts.get(definition.definition.approval_receipt_id)
            != definition.digest
        ):
            raise ManualError("manual.duty_not_admitted", 503)
        validate_contract("DutyDefinition", definition.definition.wire())
        duty = definition.definition
        if (
            action not in {"identity_revoke", "job_execute", "lifecycle_due"}
            or action not in duty.operations
            or actor.action != action
            or definition.actor_id != actor.actor_id
            or duty.workload_id != actor.workload_id
            or definition.revision != actor.duty_revision
            or definition.digest != actor.duty_artifact_digest
            or actor.request_digest != request_digest
            or actor.scope != scope
            or not now < duty.expires_at
            or not actor.issued_at
            <= now
            < actor.expires_at
            <= actor.issued_at + timedelta(seconds=1)
            or (actor.request_deadline is not None and actor.request_deadline <= now)
            or scope.purpose not in duty.purposes
            or scope.fields
            or scope.recipient_id is not None
            or actor.task_id is not None
            or actor.originating_human_id is not None
            or (
                action == "identity_revoke"
                and (
                    "identity_signal" not in duty.resource_classes
                    or scope.purpose != "security"
                    or scope.session_id is not None
                    or scope.subject_id is not None
                    or actor.job_id is not None
                )
            )
            or (
                action == "lifecycle_due"
                and (
                    not {"expired_copy", "due_followup"}.issubset(duty.resource_classes)
                    or actor.workload_id != "spiffe://care-link.demo/demo/jobs"
                    or scope.purpose != "rights"
                    or scope.session_id is not None
                    or scope.subject_id is not None
                    or actor.job_id is not None
                )
            )
            or (
                action == "job_execute"
                and (
                    "expired_reservation" not in duty.resource_classes
                    or scope.purpose != "support"
                    or scope.session_id is None
                    or scope.subject_id is None
                    or actor.job_id is None
                )
            )
        ):
            raise ManualError("manual.duty_binding_denied")
        try:
            self._verify(
                self.signer_keys[definition.key_id], definition.signature, definition.unsigned()
            )
            unsigned = {key: value for key, value in evidence.items() if key != "signature"}
            self._verify(self.evidence_keys[actor.workload_id], actor.signature, unsigned)
            if self.workload_check is None:
                raise ValueError("No current workload authority")
            if (
                self.workload_check(actor.workload_id, actor.credential_ref)
                != actor.workload_revision
            ):
                raise ValueError("Workload fence changed")
        except (KeyError, ValueError, InvalidSignature) as error:
            raise ManualError("manual.duty_authority_denied") from error
        finished = self.clock()
        if (
            finished >= actor.expires_at
            or finished >= duty.expires_at
            or (actor.request_deadline is not None and finished >= actor.request_deadline)
        ):
            raise ManualError("manual.duty_expired")
        return actor

    def resolve(
        self,
        delegation: dict[str, object],
        *,
        peer: str,
        method: str,
        path: str,
        audience: str,
        body_digest: str,
        operation_id: str,
        request_digest: str,
        credential_ref: str,
    ) -> DutyActor:
        """Resolve a signed exact HTTP request into registered workload duty identity.

        peer is supplied only by the independently verified workload listener.
        No browser header or arbitrary signed actor alias becomes registry identity.
        """
        from typing import cast

        delegation = cast(dict[str, object], json.loads(canonical(delegation)))
        validate_contract("SignedDelegation", delegation)
        actor = cast(dict[str, object], delegation["actor"])
        evidence = cast(dict[str, object], delegation["evidence"])
        scope = cast(dict[str, object], delegation["scope"])
        if actor.get("kind") != "workload" or evidence.get("kind") != "workload_duty":
            raise ManualError("manual.workload_duty_required")
        registered = next(
            (item for item in self.definitions if item.duty_id == actor["duty_id"]), None
        )
        if (
            registered is None
            or registered.actor_id != actor["actor_id"]
            or registered.definition.workload_id != actor["workload_id"]
            or actor["workload_id"] != peer
            or method != "POST"
            or delegation["method"] != method
            or delegation["path"] != path
            or delegation["audience"] != audience
            or delegation["body_digest"] != body_digest
            or delegation["id"] != operation_id
            or delegation["nonce"] != evidence["nonce"]
            or scope != evidence["scope"]
            or evidence["actor_id"] != actor["actor_id"]
            or evidence["duty_id"] != actor["duty_id"]
            or evidence["workload_id"] != peer
            or evidence["request_digest"] != request_digest
        ):
            raise ManualError("manual.duty_delegation_denied")
        try:
            unsigned = {key: value for key, value in delegation.items() if key != "signature"}
            self._verify(self.evidence_keys[peer], cast(str, delegation["signature"]), unsigned)
            expiry = datetime.fromisoformat(cast(str, delegation["expires_at"]))
            evidence_expiry = datetime.fromisoformat(cast(str, evidence["expires_at"]))
            if not self.clock() < expiry <= evidence_expiry or self.workload_check is None:
                raise ValueError("Expired delegation")
            generation = self.workload_check(peer, credential_ref)
        except (KeyError, ValueError, InvalidSignature) as error:
            raise ManualError("manual.duty_delegation_denied") from error
        resolved = DutyActor(
            cast(str, actor["actor_id"]),
            peer,
            cast(str, actor["duty_id"]),
            cast(str, evidence["id"]),
            cast(str, evidence["duty_artifact_digest"]),
            DutyScope(
                cast(str | None, scope["session_id"]),
                cast(str | None, scope["subject_id"]),
                cast(str, scope["purpose"]),
                tuple(cast(list[str], scope["fields"])),
                cast(str | None, scope["recipient_id"]),
            ),
            cast(str, evidence["action"]),
            request_digest,
            cast(str, evidence["nonce"]),
            datetime.fromisoformat(cast(str, evidence["issued_at"])),
            evidence_expiry,
            cast(str, evidence["signature"]),
            generation,
            registered.revision,
            credential_ref,
            cast(str | None, actor["job_id"]),
            cast(str | None, actor["task_id"]),
            cast(str | None, actor["originating_human_id"]),
            expiry,
        )
        return self.current(resolved, resolved.action, request_digest, resolved.scope)
