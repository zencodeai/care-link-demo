"""Fixed signed governance dispatch behind the data gateway's verified envelope."""

from collections.abc import Awaitable, Callable
from typing import cast

from care_link_contracts import validate_contract
from care_link_domain import Actor
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from .store import Record

Envelope = Callable[[Request, str], Awaitable[tuple[Actor, str, Record, Record]]]

# action, output, optional target, command (key/data) versus read
BINDINGS = (
    ("artifact_context", "GovernanceArtifactContext", "artifact_digest", False),
    ("artifact_register", "ArtifactView", None, True),
    ("artifact_review", "CommandResult", None, True),
    ("activation_create", "ActivationView", None, True),
    ("activation_commit", "ActivationView", "activation_id", True),
    ("activation_read", "ActivationView", "activation_id", False),
    ("exception_create", "CommandResult", None, True),
    ("incident_create", "IncidentView", None, True),
    ("incident_transition", "IncidentView", "incident_id", True),
    ("incident_read", "IncidentView", "incident_id", False),
    ("scoped_access_grant", "CommandResult", None, True),
    ("audit_query", "AuditPage", None, True),
    ("metrics_query", "MetricsView", None, True),
    ("evidence_export", "CommandResult", None, True),
    ("audit_export_read", "AuditPage", "export_id", False),
    ("health_read", "HealthView", None, False),
)


def attach_governance_gateway(app: FastAPI, service: object, envelope: Envelope) -> None:
    def attach(name: str, output: str, target: str | None, command: bool) -> None:
        method = cast(Callable[..., Record], getattr(service, name))

        async def handle(request: Request) -> JSONResponse:
            actor, key, args, paths = await envelope(request, name)
            arguments: list[object] = [actor]
            if command:
                arguments.extend([key, args])
            if target:
                arguments.append(paths[target])
            if name == "audit_export_read":
                arguments.append(args)
            result = await run_in_threadpool(method, *arguments)
            validate_contract(output, result)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})

        app.add_api_route("/internal/v1/data/" + name, handle, methods=["POST"])

    for row in BINDINGS:
        attach(*row)
