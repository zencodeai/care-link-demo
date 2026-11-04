# CARE-Link Demo

CARE-Link Demo is an independent, Ottawa-based project for demonstrating mental-health crisis-support workflows with synthetic data, simulated services, human oversight and deterministic controls around an LLM.

The repository currently contains technical requirements and proposed system parameters. Application implementation, deployment and operational validation have not yet been established. It is not approved for real crisis use or production deployment.

## Project scope

- Closed access for authorized project participants, using fictional scenarios and non-clinical stub content.
- Separate credentials, sessions, interfaces and workflows for participants, crisis-worker role-players, supervisors and other authorized roles.
- Demonstrations of intake, service discovery, consent, referrals, human handoff, crisis planning, follow-up and audit.
- No police affiliation, partnership, police-facing role, connector, brief workflow or data-sharing arrangement. No autonomous emergency contact capability.
- Ottawa, Ontario context, `America/Toronto` time and English/French interfaces; fictional service jurisdictions remain separate from the implementor’s location.
- An independent static crisis-information path using verified real contact content, with content review required before participant use.

## Agentic AI supports the actors

Role-scoped assistants help participants express needs and help workers retrieve context, compare verified service options, prepare editable summaries/referrals and track authorized handoffs. A bounded agent workflow can plan, request permitted tools, observe results and propose recovery steps. Humans retain clinical and consequential service decisions; deterministic controls enforce security, consent and governance at each step. Authorized manual service workflows remain usable when AI is unavailable.

See the [agentic service model and comparable-system research](doc/REQ/10-agentic-ai-and-service-model.md) for actor responsibilities, evidence limits and acceptance requirements. Mission-critical service quality is the objective; the current synthetic demo does not establish clinical readiness.

## Planned technical direction

Local deployment uses Docker images and Kubernetes, with LM Studio running Gemma 3 4B IT on the host. The model proposes content and actions; deterministic services control authorization, consent, committed state and execution. Human help must remain accessible when inference is unavailable.

The proposed stack includes React/TypeScript, Python/FastAPI, PostgreSQL, Keycloak/OIDC and OPA/Rego. These are design selections awaiting implementation checks. Exact versions, model artifacts, host capacity and network enforcement must be verified. Changes follow human-reviewed GitHub PRs, with independent approval for the accepted baseline.

## Requirements and decisions

Start with the [technical requirements index](doc/REQ/README.md).

| Document | Contents |
|---|---|
| [Scope and sources](doc/REQ/01-scope-and-sources.md) | Source authority, demo boundaries and scope divergences |
| [Actors and workflows](doc/REQ/02-actors-and-workflows.md) | Role permissions, credentials and user journeys |
| [Architecture and interfaces](doc/REQ/03-architecture-and-interfaces.md) | Components, LLM boundaries and contracts |
| [Data, security and governance](doc/REQ/04-data-security-governance.md) | Persistence, consent, audit and review controls |
| [Deployment and operations](doc/REQ/05-deployment-and-operations.md) | Local hosting, recovery and observability requirements |
| [Acceptance and delivery](doc/REQ/06-acceptance-and-delivery.md) | Verification obligations and incremental milestones |
| [Source requirement trace](doc/REQ/07-source-requirements.md) | 114 inherited requirements and 16 invariants |
| [Decision answers](doc/REQ/08-open-decisions.md) | Answers to 53 inherited questions and local design decisions |
| [Demo parameters](doc/REQ/demo-parameters.json) | Proposed engineering defaults; not automatically loaded runtime configuration |

The decision answers record the current Ottawa context and police exclusions. Historical police-specific source requirements remain traceable as excluded scope; they are not implemented or claimed as satisfied. Clinical, legal, regulatory and community approvals remain distinct from engineering defaults.

## Implementation status

No application startup or deployment commands are available yet. Begin with the acceptance document’s baseline decisions and first usable intake milestone. Preserve a working accepted demo as later workflows are added; record measured results separately from proposed timing and capacity targets.

The sibling `care-link` repository supplies the source system model. The abandoned `care-link-prod` implementation is historical reference only; its credentials, deployment approvals and readiness claims are not inherited here.

> This prototype demonstrates control and containment architecture using non-clinical stub logic and synthetic data. It provides no evidence of clinical safety, triage validity, or equity performance, and must not be cited as such.
