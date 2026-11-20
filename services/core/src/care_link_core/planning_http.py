"""Fixed named HTTP operations for planning; shared transport verifies all DTOs."""

from uuid import uuid4

from care_link_domain import Actor

from .manual_http import HttpManualGateway, Record


class HttpPlanningGateway(HttpManualGateway):
    def own_reports_read(self, actor: Actor, session_id: str) -> Record:
        return self._result(
            actor, "own_reports_read", str(uuid4()), {}, {"session_id": session_id}, "OwnReportPage"
        )

    def plan_create(self, actor: Actor, key: str, data: Record) -> Record:
        return self._result(actor, "plan_create", key, data, {}, "PlanView")

    def plan_read(self, actor: Actor, plan_id: str) -> Record:
        return self._result(actor, "plan_read", str(uuid4()), {}, {"plan_id": plan_id}, "PlanView")

    def plan_field_append(self, actor: Actor, key: str, data: Record, plan_id: str) -> Record:
        return self._result(actor, "plan_field_append", key, data, {"plan_id": plan_id}, "PlanView")

    def plan_retire(self, actor: Actor, key: str, data: Record, plan_id: str) -> Record:
        return self._result(actor, "plan_retire", key, data, {"plan_id": plan_id}, "PlanView")

    def consent_grant(self, actor: Actor, key: str, data: Record) -> Record:
        return self._result(actor, "consent_grant", key, data, {}, "ConsentView")

    def consent_read(self, actor: Actor, grant_id: str) -> Record:
        return self._result(
            actor, "consent_read", str(uuid4()), {}, {"grant_id": grant_id}, "ConsentView"
        )

    def consent_revoke(self, actor: Actor, key: str, data: Record, grant_id: str) -> Record:
        return self._result(
            actor, "consent_revoke", key, data, {"grant_id": grant_id}, "CommandResult"
        )

    def directory_search(self, actor: Actor, key: str, data: Record) -> Record:
        return self._result(actor, "directory_search", key, data, {}, "DirectoryPage")

    def directory_read(self, actor: Actor, service_id: str) -> Record:
        return self._result(
            actor, "directory_read", str(uuid4()), {}, {"service_id": service_id}, "DirectoryView"
        )

    def directory_ingest(self, actor: Actor, key: str, data: Record) -> Record:
        return self._result(actor, "directory_ingest", key, data, {}, "DirectoryView")

    def directory_suspend(self, actor: Actor, key: str, data: Record, service_id: str) -> Record:
        return self._result(
            actor, "directory_suspend", key, data, {"service_id": service_id}, "CommandResult"
        )
