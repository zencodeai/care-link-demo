"""Fixed signed adapters for governance, operational health and scoped evidence."""

from uuid import uuid4

from care_link_domain import Actor

from .manual_http import HttpManualGateway, Record


class HttpGovernanceGateway(HttpManualGateway):
    def artifact_context(self, actor: Actor, artifact_digest: str) -> Record:
        return self._result(
            actor,
            "artifact_context",
            str(uuid4()),
            {},
            {"artifact_digest": artifact_digest},
            "GovernanceArtifactContext",
        )

    def artifact_register(self, actor: Actor, key: str, data: Record) -> Record:
        return self._result(actor, "artifact_register", key, data, {}, "ArtifactView")

    def artifact_review(self, actor: Actor, key: str, data: Record) -> Record:
        return self._result(actor, "artifact_review", key, data, {}, "CommandResult")

    def activation_create(self, actor: Actor, key: str, data: Record) -> Record:
        return self._result(actor, "activation_create", key, data, {}, "ActivationView")

    def activation_read(self, actor: Actor, activation_id: str) -> Record:
        return self._result(
            actor,
            "activation_read",
            str(uuid4()),
            {},
            {"activation_id": activation_id},
            "ActivationView",
        )

    def activation_commit(self, actor: Actor, key: str, data: Record, activation_id: str) -> Record:
        return self._result(
            actor,
            "activation_commit",
            key,
            data,
            {"activation_id": activation_id},
            "ActivationView",
        )

    def exception_create(self, actor: Actor, key: str, data: Record) -> Record:
        return self._result(actor, "exception_create", key, data, {}, "CommandResult")

    def incident_create(self, actor: Actor, key: str, data: Record) -> Record:
        return self._result(actor, "incident_create", key, data, {}, "IncidentView")

    def incident_read(self, actor: Actor, incident_id: str) -> Record:
        return self._result(
            actor, "incident_read", str(uuid4()), {}, {"incident_id": incident_id}, "IncidentView"
        )

    def incident_transition(self, actor: Actor, key: str, data: Record, incident_id: str) -> Record:
        return self._result(
            actor, "incident_transition", key, data, {"incident_id": incident_id}, "IncidentView"
        )

    def audit_query(self, actor: Actor, key: str, data: Record) -> Record:
        return self._result(actor, "audit_query", key, data, {}, "AuditPage")

    def metrics_query(self, actor: Actor, key: str, data: Record) -> Record:
        return self._result(actor, "metrics_query", key, data, {}, "MetricsView")

    def scoped_access_grant(self, actor: Actor, key: str, data: Record) -> Record:
        return self._result(actor, "scoped_access_grant", key, data, {}, "CommandResult")

    def evidence_export(self, actor: Actor, key: str, data: Record) -> Record:
        return self._result(actor, "evidence_export", key, data, {}, "CommandResult")

    def audit_export_read(self, actor: Actor, export_id: str, data: Record) -> Record:
        return self._result(
            actor, "audit_export_read", str(uuid4()), data, {"export_id": export_id}, "AuditPage"
        )

    def health_read(self, actor: Actor) -> Record:
        return self._result(actor, "health_read", str(uuid4()), {}, {}, "HealthView")
