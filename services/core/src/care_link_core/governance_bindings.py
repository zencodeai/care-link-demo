"""Closed governance HTTP operation bindings from the IMP-08 inventory."""

from dataclasses import dataclass


@dataclass(frozen=True)
class GovernanceRoute:
    action: str
    path: str
    method: str
    contract: str | None
    output: str
    target: str | None


ROUTES = (
    GovernanceRoute(
        "artifact_context",
        "/v1/artifacts/{artifact_digest}/review-context",
        "GET",
        None,
        "GovernanceArtifactContext",
        "artifact_digest",
    ),
    GovernanceRoute(
        "artifact_register", "/v1/artifacts", "POST", "ArtifactRegister", "ArtifactView", None
    ),
    GovernanceRoute(
        "artifact_review", "/v1/artifacts/reviews", "POST", "ArtifactReview", "CommandResult", None
    ),
    GovernanceRoute(
        "activation_create", "/v1/activations", "POST", "ActivationCreate", "ActivationView", None
    ),
    GovernanceRoute(
        "activation_read",
        "/v1/activations/{activation_id}",
        "GET",
        None,
        "ActivationView",
        "activation_id",
    ),
    GovernanceRoute(
        "activation_commit",
        "/v1/activations/{activation_id}/commit",
        "POST",
        "RevisionCommand",
        "ActivationView",
        "activation_id",
    ),
    GovernanceRoute(
        "exception_create", "/v1/exceptions", "POST", "ExceptionCreate", "CommandResult", None
    ),
    GovernanceRoute(
        "incident_create", "/v1/incidents", "POST", "IncidentCreate", "IncidentView", None
    ),
    GovernanceRoute(
        "incident_read", "/v1/incidents/{incident_id}", "GET", None, "IncidentView", "incident_id"
    ),
    GovernanceRoute(
        "incident_transition",
        "/v1/incidents/{incident_id}/transition",
        "POST",
        "IncidentTransition",
        "IncidentView",
        "incident_id",
    ),
    GovernanceRoute("audit_query", "/v1/audit/search", "POST", "AuditQuery", "AuditPage", None),
    GovernanceRoute(
        "metrics_query", "/v1/metrics/query", "POST", "MetricsQuery", "MetricsView", None
    ),
    GovernanceRoute(
        "scoped_access_grant",
        "/v1/access/grants",
        "POST",
        "ScopeGrantCreate",
        "CommandResult",
        None,
    ),
    GovernanceRoute(
        "evidence_export", "/v1/audit/exports", "POST", "AuditQuery", "CommandResult", None
    ),
    GovernanceRoute(
        "audit_export_read",
        "/v1/audit/exports/{export_id}",
        "GET",
        "AuditQuery",
        "AuditPage",
        "export_id",
    ),
    GovernanceRoute("health_read", "/v1/operations/health", "GET", None, "HealthView", None),
)
