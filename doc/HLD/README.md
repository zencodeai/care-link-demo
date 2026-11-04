# CARE-Link high-level technical design

Version 0.1 · 2026-11-04 · Proposed design for review. This package designs the full synthetic demonstration system and its subsystems; it does not implement, deploy or authorize clinical use. Mission-critical service intent is preserved through accountable actor support, bounded agentic coordination, inline governance/security and continuity of human workflows.

## Design map

| Document | Design responsibility |
|---|---|
| [01 — Context and architecture](01-context-and-architecture.md) | Scope, decisions, containers, trust boundaries and allowed dependencies |
| [02 — Actors and service workflows](02-actors-and-service-workflows.md) | All human interfaces, state machines and end-to-end interaction |
| [03 — Agentic assistance and inference](03-agentic-assistance-and-inference.md) | Role-scoped assistants, task lifecycle, model gateway and capability admission |
| [04 — Safety, security and governance](04-safety-security-and-governance.md) | PDP/PEPs, epoch fencing, signals, controls and safe-mode architecture |
| [05 — Data and audit](05-data-and-audit.md) | Record ownership, transactions, ledger, outbox, retention and replay |
| [06 — Interfaces and integration](06-interfaces-and-integration.md) | APIs, contracts, events, simulators and errors |
| [07 — Deployment and delivery](07-deployment-and-delivery.md) | Docker/Kubernetes/local host, secrets, network, rollout and build structure |
| [08 — Reliability and operations](08-reliability-and-operations.md) | Capacity, performance, dependency loss, recovery, telemetry and runbooks |
| [09 — Verification and traceability](09-verification-and-traceability.md) | Every local requirement, source element and acceptance group mapped to design |
| [10 — Decisions and implementation boundaries](10-decisions-and-implementation-boundaries.md) | Design choices, unresolved dependencies and delivery sequence |
| [Design inventory](design-inventory.json) | Machine-readable subsystem ownership and requirements-file hashes |

## Authority and interpretation

The [requirements](../REQ/README.md), their later scope clarifications and [actor-support model](../REQ/10-agentic-ai-and-service-model.md) define desired behavior. This HLD selects a coherent implementation architecture without changing upstream source models, clinical rules or formal approval status. HLD choices are proposed until reviewed. Conflicting historical police-specific material is excluded under the user's explicit no-police-affiliation/integration scope. Deployment locale Ottawa/Ontario is separate from fictional service jurisdictions CA-XX/CA-YY.

The [parameter artifact](../REQ/demo-parameters.json) is the single source for proposed configurable values. Null never means permission. No parameter is runtime-loaded by this document. Concrete versions, host topology and model digest require implementation verification. Architecture-fixed prohibitions cannot be relaxed through ordinary configuration.

The design is complete at the architectural level: every subsystem has ownership, inputs/outputs, authority, persistence and failure treatment. Implementation still requires normative schemas, code, reviewed manifests, dependency pins, test fixtures and closure of identified admission blockers. No CI run, installed component or measured SLO is claimed.

> This prototype demonstrates control and containment architecture using non-clinical stub logic and synthetic data. It provides no evidence of clinical safety, triage validity, or equity performance, and must not be cited as such.
