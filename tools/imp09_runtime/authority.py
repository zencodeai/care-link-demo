"""Host-bound adapter over current identity and separately provisioned human IDs."""

from collections.abc import Mapping
from datetime import datetime

from care_link_domain import Actor, ManualError
from care_link_identity import IdentityService
from care_link_identity.manual import ManualIdentityAuthority
from care_link_identity.promotion import consume_promotion_proof
from care_link_recovery_control.ports import RecoveryHuman


class IdentityRecoveryAuthority:
    def __init__(self, service: IdentityService, human_ids: Mapping[str, str]) -> None:
        # Provision this mapping outside business snapshots, under maintenance
        # custody. A second account belonging to one person shares its human ID.
        self.service = service
        self.human_ids = dict(human_ids)
        if not self.human_ids or any(not v for v in self.human_ids.values()):
            raise ValueError("Explicit trusted account to human identity mapping required")
        self.credentials: dict[str, Actor] = {}

    def current(self, actor: Actor, operation: str) -> RecoveryHuman:
        current = ManualIdentityAuthority(self.service).current(actor)
        roles = {
            "promotion_approve": {"security", "governance"},
            "promotion_read": {"operator", "security", "governance"},
            "evidence_promotion": {"operator", "security", "governance"},
            "restore_read": {"operator", "security"},
        }.get(operation, {"operator"})
        now = self.service.clock()
        human_id = self.human_ids.get(current.account_id)
        if (
            not human_id
            or current.role not in roles
            or current.account_id != actor.account_id
            or current.identity_revision != actor.identity_revision
            or current.role_revision != actor.role_revision
            or not current.mfa
            or not 0 <= (now - current.auth_time).total_seconds() < 300
            or current.expires_at <= now
        ):
            raise ManualError("recovery.current_human_required")
        self.credentials[current.account_id] = current
        return RecoveryHuman(
            current.account_id,
            human_id,
            current.role,
            current.identity_revision,
            current.role_revision,
            current.expires_at,
        )

    def approval(
        self,
        actor: Actor,
        ceremony_id: str,
        proposal_id: str,
        binding_digest: str,
        expires_at: datetime,
    ) -> RecoveryHuman:
        human = self.current(actor, "promotion_approve")
        consume_promotion_proof(
            self.service, actor, ceremony_id, proposal_id, binding_digest, expires_at
        )
        return human

    def still_current(self, human: RecoveryHuman) -> bool:
        actor = self.credentials.get(human.account_id)
        if actor is None:
            return False
        try:
            # Preserve the exact role/revisions of approval; account role changes
            # cannot be silently translated into a new approval.
            operation = "promotion_approve" if human.role != "operator" else "promotion_execute"
            return self.current(actor, operation) == human
        except ManualError:
            return False
