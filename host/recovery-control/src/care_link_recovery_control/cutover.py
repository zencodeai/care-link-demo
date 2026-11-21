"""Ordered generation cutover; the ledger, router and DB never pretend atomicity."""

from datetime import datetime
from typing import TYPE_CHECKING

from care_link_domain import ManualError

from .coordinator import head_binding, human_value, mapping
from .encoding import stamp
from .ledger import MAX_GENERATION

if TYPE_CHECKING:
    from .coordinator import RecoveryCoordinator


CUTOVER_BOUNDARIES = (
    "maintenance",
    "fenced_old",
    "routed_target",
    "enabled_target",
    "before_smoke",
)


def execute_cutover(
    coordinator: RecoveryCoordinator, proposal: dict[str, object], state: dict[str, object]
) -> None:
    c = coordinator
    c.require_host_custody()
    c.require_fresh_proposal(proposal, state)
    expiry = datetime.fromisoformat(str(proposal["expires_at"]).replace("Z", "+00:00"))
    approver = human_value(proposal["approver"])
    proposer = human_value(proposal["proposer"])
    operator = human_value(proposal["operator"])
    if c.clock() >= expiry or not all(
        c.authority.still_current(h) for h in (approver, proposer, operator)
    ):
        raise ManualError("recovery.approval_authority_expired", 409)
    target = c.get_record(state, "targets", str(proposal["target_id"]))
    evidence, binding = mapping(target["evidence"]), mapping(proposal["binding"])
    generation = int(str(binding["serving_generation"]))
    approved_head = mapping(target["head"])

    def current() -> None:
        c.require_host_custody()
        if (
            c.clock() >= expiry
            or head_binding(c.journal.head()) != approved_head
            or c.targets.inspect(str(target["id"])) != evidence["target_digest"]
            or not all(c.authority.still_current(h) for h in (approver, proposer, operator))
        ):
            raise ManualError("recovery.approval_invalidated", 409)

    def persist(step: str) -> None:
        proposal["state"] = step
        proposal["revision"] = int(str(proposal["revision"])) + 1
        proposal[step + "_at"] = stamp(c.clock())
        c.ledger.save(state)
        if c.crash_hook is not None:
            c.crash_hook(step)
        current()

    # The durable gate denies before touching either independent system.
    state["serving"] = None
    persist("maintenance")
    try:
        c.targets.fence_all()
        persist("fenced_old")
        c.targets.route(str(target["id"]))
        persist("routed_target")
        if c.targets.state() != (str(target["id"]), 0):
            raise ManualError("recovery.router_not_restricted", 503)
        c.targets.enable(str(target["id"]), generation)
        persist("enabled_target")
        if c.targets.state() != (str(target["id"]), generation):
            raise ManualError("recovery.target_generation_mismatch", 503)
        if c.crash_hook is not None:
            c.crash_hook("before_smoke")
        current()
        if not c.targets.smoke(str(target["id"]), generation):
            raise ManualError("recovery.manual_smoke_failed", 503)
        current()
        proposal.update(
            state="smoke_verified",
            revision=int(str(proposal["revision"])) + 1,
            smoke_verified_at=stamp(c.clock()),
        )
        target.update(state="serving", revision=int(str(target["revision"])) + 1)
        state["serving"] = {
            "target_id": target["id"],
            "generation": generation,
            "head": approved_head,
            "proposal_id": proposal["id"],
        }
        state["next_generation"] = generation + 1 if generation < MAX_GENERATION else None
        c.ledger.save(state)
    except BaseException:
        # Never rewind router or recover automatically from an uncertain gap.
        state["serving"] = None
        proposal["state"] = "invalidated"
        target["state"] = "fenced"
        try:
            c.targets.fence_all()
        finally:
            c.ledger.save(state)
        raise
