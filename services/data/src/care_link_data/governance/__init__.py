"""Scoped operational governance application use cases."""

from care_link_domain import Actor

from ..store import Record, Transaction, number
from ..values import Outcome
from .activations import Activations
from .artifacts import Artifacts
from .authority import current_human
from .incidents import Incidents
from .projections import required


class Governance(Activations, Artifacts, Incidents):
    def health_read(self, actor: Actor) -> Record:
        def read(
            tx: Transaction, current: Actor, _b: Record, _s: Record | None, _g: Record | None
        ) -> Outcome:
            current_human(tx, current, self.clock())
            control = required(tx, "control", "demo")
            reasons: list[str] = []
            if control["mode"] not in {"normal", "ai_disabled"}:
                reasons.append("governance.capability_restricted")
            from ..activation_fence import activation_current

            active = tx.rows("gov_activation", state="active", limit=1)
            if not active:
                reasons.append("governance.current_activation_unknown")
            elif not activation_current(tx, control):
                reasons.append("governance.current_boot_ack_required")
            return Outcome(
                "HealthView",
                {
                    "capability": "manual",
                    "ready": not reasons,
                    "reasons": reasons,
                    "epoch": str(number(control, "epoch")),
                    "serving_generation": str(number(control, "serving_generation")),
                },
            )

        return self._run(actor, "health_read", None, {}, None, read)


__all__ = ["Governance"]
