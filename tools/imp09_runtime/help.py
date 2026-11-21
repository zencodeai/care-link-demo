"""Current host-spool adapter for the canonical minimal import boundary."""

from collections.abc import Callable
from datetime import datetime

from care_link_data.recovery import HelpSnapshot
from care_link_domain import ManualError
from care_link_help import Spool


class SpoolHelpAuthority:
    def __init__(self, spool: Spool, current_workload: Callable[[], bool]) -> None:
        self.spool, self.current_workload = spool, current_workload

    def current(self, request: dict[str, object]) -> HelpSnapshot:
        if not self.current_workload():
            raise ManualError("recovery.help_workload_denied")
        snapshot = self.spool.reconciliation_snapshot(str(request["help_id"]))
        return HelpSnapshot(
            str(snapshot["help_id"]),
            int(str(snapshot["revision"])),
            str(snapshot["status"]),
            datetime.fromisoformat(str(snapshot["local_created_at"])),
            str(snapshot["local_event_digest"]),
        )
