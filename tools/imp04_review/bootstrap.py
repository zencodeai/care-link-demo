"""Private preparation identity composition over real bounded review policy."""

import copy
from collections.abc import Callable
from datetime import datetime

from care_link_core.manual_channels import ManualChannels
from care_link_data.control import ManualService
from care_link_domain import Actor, ManualError
from care_link_identity.crypto import digest
from care_link_identity.interactive_provider import AutomaticReviewProvider
from care_link_identity.manual import ManualIdentityAuthority
from care_link_identity.review_context import ReviewContext
from care_link_identity.service import IdentityService
from care_link_identity.session_policy import InteractiveReviewPolicy

from .types import JsonRecord


class BootstrapIdentityFactory:
    def __init__(self, base: IdentityService, run_source: Callable[[str], JsonRecord]) -> None:
        self.base, self.run_source = base, run_source
        self._providers: dict[tuple[str, str], AutomaticReviewProvider] = {}

    def _contexts(self, run_id: str) -> dict[str, ReviewContext]:
        run = self.run_source(run_id)
        if run.get("run_id") != run_id or run.get("state") not in {"preparing", "ready"}:
            return {}
        return {
            actor["origin"]: ReviewContext(
                origin=actor["origin"],
                run_id=run_id,
                slot_id=actor["slot_id"],
                account_id=actor["account_id"],
                role=actor["role"],
                provider_subject=actor["provider_subject"],
                state="active",
                mode="plans",
                authentication_mode="automatic_review",
                environment="synthetic-review",
                started_at=run["started_at"],
                expires_at=run["expires_at"],
            )
            for actor in run["actors"].values()
        }

    def __call__(self, run: JsonRecord, actor: JsonRecord) -> IdentityService:
        contexts = self._contexts(run["run_id"])
        context = contexts.get(actor["origin"])
        if (
            context is None
            or context.account_id != actor["account_id"]
            or context.role != actor["role"]
        ):
            raise ValueError("Private preparation actor is no longer current")
        policy = InteractiveReviewPolicy(
            context,
            datetime.fromisoformat(run["started_at"]),
            datetime.fromisoformat(run["expires_at"]),
            enabled=True,
        )
        policy.check(context, self.base.clock())
        key = run["run_id"], actor["slot_id"]
        provider = self._providers.get(key)
        if provider is None:
            provider = AutomaticReviewProvider(
                policy, lambda: self._contexts(run["run_id"]), self.base.clock
            )
            self._providers[key] = provider
        elif provider.policy != policy:
            raise ValueError("Review identity policy cannot be replaced or extended")
        return IdentityService(
            self.base.store,
            provider,
            self.base.custody,
            self.base.signer,
            self.base.issuer,
            context.origin,
            self.base.clock,
            review_context=context,
            interactive_policy=policy,
        )


class BootstrapAuthority:
    """Exact private credential routing into the ordinary identity authority."""

    def __init__(self, factory: BootstrapIdentityFactory) -> None:
        self.factory = factory

    def _authority(self, actor: Actor) -> ManualIdentityAuthority:
        with self.factory.base.store.transaction() as tx:
            row = tx.get("session", digest(actor.credential_ref))
        if (
            row is None
            or actor.browser_session_digest != digest(actor.credential_ref)
            or row.get("review_run_id") != actor.review_run_id
            or row.get("review_slot_id") != actor.review_slot_id
            or row.get("review_origin") != actor.review_origin
            or row.get("account_id") != actor.account_id
            or row.get("role") != actor.role
            or actor.review_run_id is None
            or actor.review_slot_id is None
        ):
            raise ManualError("manual.review_actor_mismatch", 403)
        run = self.factory.run_source(actor.review_run_id)
        spec = run["actors"].get(actor.review_slot_id)
        if spec is None:
            raise ManualError("manual.review_actor_mismatch", 403)
        return ManualIdentityAuthority(self.factory(run, spec))

    def current(self, actor: Actor) -> Actor:
        return self._authority(actor).current(actor)

    def recovery_proof(
        self, actor: Actor, ceremony_id: str, session_id: str, family_id: str
    ) -> None:
        self._authority(actor).recovery_proof(actor, ceremony_id, session_id, family_id)

    def consent_proof(
        self,
        actor: Actor,
        proof_id: str,
        subject_id: str,
        session_id: str,
        purpose: str,
        basis: str,
    ) -> None:
        self._authority(actor).consent_proof(
            actor, proof_id, subject_id, session_id, purpose, basis
        )

    def rights_proof(self, actor: Actor, ceremony_id: str, subject_id: str, kind: str) -> None:
        raise ManualError("manual.rights_proof_required")

    def rights_download_proof(self, actor: Actor, ceremony_id: str, subject_id: str) -> None:
        raise ManualError("manual.rights_proof_required")


def compose_fixture_service(
    base: ManualService, authority: BootstrapAuthority, channels: ManualChannels
) -> ManualService:
    """Private engine copy; original serving authority and channel remain intact.

    Store, PDP, journal, cipher, clock, admission manifests and all enforcement
    logic are inherited. Only exact bootstrap identity and its live transport
    observation adapters are supplied for the private fixture procedure.
    """
    service = copy.copy(base)
    service.authority, service.channel = authority, channels
    return service
