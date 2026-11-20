"""Concrete custody and application adapters, requiring explicit composition ports."""

import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from care_link_core.manual_channels import ManualChannels
from care_link_identity.domain import Store
from care_link_identity.service import IdentityService

if TYPE_CHECKING:
    from .fixtures import ServiceFixtureBuilder


from care_link_domain import Actor
from care_link_identity import interactive_review
from care_link_identity.credential_disposal import fence_session_material
from care_link_identity.crypto import digest
from care_link_identity.manual import ManualIdentityAuthority
from care_link_identity.provisioning import provision_account

from .lifecycle import operation
from .types import JsonRecord


class RunAdmin(Protocol):
    def create(self, run_id: str, scenario: str, operation_id: str) -> dict[str, object]: ...
    def inspect(self, run_id: str) -> dict[str, object]: ...
    def inspect_optional(self, run_id: str) -> dict[str, object] | None: ...
    def close(self, run_id: str, operation_id: str) -> dict[str, object]: ...
    def retire_artifacts(self, run_id: str) -> dict[str, object]: ...


class PrincipalCustody(Protocol):
    def ensure_principal(self, actor: Actor) -> None:
        """Ensure exact existing custody, refusing changed or restricted authority."""
        ...


class IdentityCustody:
    def __init__(
        self,
        store: Store,
        issuer: str,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store, self.issuer, self.clock = store, issuer, clock

    def provision(self, run: JsonRecord) -> None:
        for actor in run["actors"].values():
            key = digest(self.issuer + "\0" + actor["provider_subject"])
            with self.store.transaction() as tx:
                old = tx.get("account", key)
            if old is None:
                provision_account(
                    self.store,
                    self.issuer,
                    actor["provider_subject"],
                    actor["account_id"],
                    [actor["role"]],
                    clock=self.clock,
                )
            with self.store.transaction() as tx:
                row = tx.get("account", key)
                if (
                    row is None
                    or row.get("account_id") != actor["account_id"]
                    or row.get("subject") != actor["provider_subject"]
                    or row.get("roles") != [actor["role"]]
                    or row.get("enabled") is not True
                    or row.get("blocked") is True
                    or row.get("interactive_review_run_id", run["run_id"]) != run["run_id"]
                ):
                    raise ValueError("Exact fresh review account custody required")
                row["interactive_review_run_id"] = run["run_id"]
                tx.put("account", key, row)

    def retire(self, run: JsonRecord) -> None:
        with self.store.transaction() as tx:
            for key, row in tx.items("session"):
                if row.get("review_run_id") == run["run_id"]:
                    row.update({"revoked": True, "access_token": ""})
                    tx.put("session", key, row)
                    fence_session_material(tx, key)
            for key, row in tx.items("intent"):
                if row.get("review_run_id") == run["run_id"]:
                    row.update({"state": "failed", "verifier": "", "nonce": "", "access_token": ""})
                    tx.put("intent", key, row)
            for key, row in tx.items("account"):
                if row.get("interactive_review_run_id") == run["run_id"]:
                    row["enabled"] = False
                    tx.put("account", key, row)


@dataclass(frozen=True)
class ActorLease:
    actor: Actor
    proof_id: str | None = None


class InProcessReviewActors:
    """Real automatic provider callback and live ManualChannels during each command.

    service_for_actor must compose an IdentityService with this exact run's bounded
    policy. It receives private preparation metadata; no unready public registry
    entry is required. Credentials stay in this adapter's process memory.
    """

    def __init__(
        self,
        service_for_actor: Callable[[JsonRecord, JsonRecord], IdentityService],
        channels: ManualChannels,
        principal_custody: PrincipalCustody,
    ) -> None:
        self.service_for_actor, self.channels = service_for_actor, channels
        if not callable(getattr(principal_custody, "ensure_principal", None)):
            raise TypeError("Explicit owned review principal custody required")
        self.principal_custody = principal_custody
        self._services: dict[tuple[str, str], IdentityService] = {}
        self._credentials: dict[tuple[str, str], tuple[str, str]] = {}

    @contextmanager
    def open(
        self, run: JsonRecord, slot: str, verification: JsonRecord | None = None
    ) -> Iterator[ActorLease]:
        actor_spec = run["actors"][slot]
        service = self.service_for_actor(run, actor_spec)
        self._services[run["run_id"], slot] = service
        key = run["run_id"], slot
        binding, raw = self._credentials.get(key, (secrets.token_urlsafe(32), ""))
        if not raw:
            _view, raw = interactive_review.login(service, binding, None)
        proof = None
        if verification is not None:
            request = {**verification, "expected_revision": service.current(raw)["revision"]}
            result, raw = interactive_review.verify(service, raw, binding, request)
            proof = str(result["ceremony_id"])
        self._credentials[key] = binding, raw
        actor = ManualIdentityAuthority(service).authenticate(raw)
        if (
            actor.account_id != actor_spec["account_id"]
            or actor.role != actor_spec["role"]
            or actor.review_run_id != run["run_id"]
            or actor.review_slot_id != slot
            or actor.review_origin != actor_spec["origin"]
        ):
            raise ValueError("Authenticated fixture actor binding mismatch")
        self.principal_custody.ensure_principal(actor)
        with self.channels.open(actor) as connected:
            yield ActorLease(connected, proof)

    def retire(self, run: JsonRecord) -> None:
        for key in list(self._credentials):
            if key[0] == run["run_id"]:
                _binding, raw = self._credentials[key]
                service = self._services[key]
                session_hash = digest(raw)
                with service.store.transaction() as tx:
                    row = tx.get("session", session_hash)
                    if row is not None:
                        if row.get("review_run_id") != run["run_id"]:
                            raise ValueError("Bootstrap credential belongs to another run")
                        row.update({"revoked": True, "access_token": ""})
                        tx.put("session", session_hash, row)
                        fence_session_material(tx, session_hash)
                self.channels.invalidate_binding(run["actors"][key[1]]["account_id"], session_hash)
                del self._credentials[key]
                del self._services[key]


class ServiceReviewAdapter:
    def __init__(
        self,
        run_admin: RunAdmin,
        identity: IdentityCustody,
        fixtures: ServiceFixtureBuilder,
        retire_views: Callable[[str], object],
    ) -> None:
        self.run_admin, self.identity, self.fixtures, self.retire_views = (
            run_admin,
            identity,
            fixtures,
            retire_views,
        )

    def prepare(self, run: JsonRecord, checkpoint: Callable[[], None]) -> JsonRecord:
        if "namespace" not in run["steps"]:
            self.run_admin.create(
                run["run_id"], "plans-consent-directory", operation(run, "namespace")
            )
            run["steps"]["namespace"] = True
            checkpoint()
        self.identity.provision(run)
        selections = self.fixtures.prepare(run, checkpoint)
        actual = self.run_admin.inspect(run["run_id"])
        if actual["state"] != "active" or actual["scenario"] != "plans-consent-directory":
            raise ValueError("Fresh active owned plans namespace required")
        self.fixtures.verify(run, selections)
        self.fixtures.finish(run)
        return selections

    def close(self, run: JsonRecord, checkpoint: Callable[[], None]) -> None:
        # Every stage is an idempotent exact-run fence; an exception keeps closing.
        actual = self.run_admin.inspect_optional(run["run_id"])
        if actual is not None:
            self.run_admin.close(run["run_id"], operation(run, "close"))
        self.identity.retire(run)
        if actual is not None:
            self.run_admin.retire_artifacts(run["run_id"])
        self.retire_views(run["run_id"])
        self.fixtures.retire(run)
        run["steps"]["retired"] = True
        checkpoint()
