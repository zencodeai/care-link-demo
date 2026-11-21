"""Fresh serving admission, composed at data, dispatch and edge boundaries."""

from dataclasses import replace

from care_link_domain import JournalState, ManualError

from .coordinator import RecoveryCoordinator, mapping
from .ledger import MAX_GENERATION


class BoundGenerationJournal:
    """Journal view scoped to one exact DB/edge generation target.

    The signed host generation ledger is authoritative in addition to the live
    restriction journal. A router file or restored DB cannot grant admission.
    """

    def __init__(self, coordinator: RecoveryCoordinator, target_id: str) -> None:
        self.coordinator = coordinator
        self.target_id = target_id

    def head(self) -> JournalState:
        c = self.coordinator
        c.require_host_custody()
        head, records = c.journal.snapshot()
        generation = 0
        with c.ledger.exclusive():
            state = c.ledger.load()
            if state["serving"] is not None:
                serving = mapping(state["serving"])
                proposal = c.get_record(state, "promotions", str(serving["proposal_id"]))
                expected = (self.target_id, int(str(serving["generation"])))
                approved = mapping(serving["head"])
                # A prior fence can be reconciled by an independently approved
                # promotion. A new fence always revokes that promotion, even
                # though the host generation ledger still names its target.
                fenced_after_approval = any(
                    int(str(entry["sequence"])) > int(str(approved["tip"]))
                    and mapping(entry["command"])["kind"] == "serving_fence"
                    for entry in records
                )
                continuous = (
                    head.journal_id == approved["journal_id"]
                    and str(head.generation) == approved["journal_generation"]
                    and head.tip >= int(str(approved["tip"]))
                    and head.restriction_barrier >= int(str(approved["restriction_barrier"]))
                    and (
                        head.tip != int(str(approved["tip"]))
                        or head.tip_digest == approved["head_digest"]
                    )
                )
                if (
                    serving["target_id"] == self.target_id
                    and proposal["state"] == "smoke_verified"
                    and continuous
                    and not fenced_after_approval
                    and 1 <= expected[1] <= MAX_GENERATION
                    and c.targets.state() == expected
                ):
                    generation = expected[1]
        # A concurrent restriction after this snapshot is caught by the owning
        # request's final fresh barrier comparison, as for the raw JournalPort.
        return replace(head, serving_generation=generation)

    def append(self, request: dict[str, object]) -> JournalState:
        self.coordinator.journal.append(request)
        return self.head()

    def admits(self, generation: int) -> bool:
        try:
            return generation > 0 and self.head().serving_generation == generation
        except (ManualError, OSError, ValueError):
            return False

    def require(self, generation: int) -> None:
        if not self.admits(generation):
            raise ManualError("recovery.generation_fenced", 503)
