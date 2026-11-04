# CARE-Link demo technical requirements

Status: proposed implementation baseline for human review. Analysis date: 2026-11-04. No software implementation, deployment, clinical approval, or operational verification is established by these documents.

## Reading order

1. [Scope and source analysis](01-scope-and-sources.md)
2. [Actors, access and workflows](02-actors-and-workflows.md)
3. [Architecture and interfaces](03-architecture-and-interfaces.md)
4. [Data, security and governance](04-data-security-governance.md)
5. [Local deployment and operations](05-deployment-and-operations.md)
6. [Acceptance and incremental delivery](06-acceptance-and-delivery.md)
7. [Complete source requirement trace](07-source-requirements.md)
8. [Decision answers and dispositions](08-open-decisions.md)
9. [Proposed demo parameters](demo-parameters.json)
10. [Source snapshot](source-snapshot.json)

## Requirement conventions

`TR-*` identifies a technical requirement proposed by this analysis, to become binding through review. SHALL means required for this proposed demo baseline; SHOULD means a justified alternative can be reviewed. Source FR/NFR priorities and modalities remain unchanged in the complete trace. A source acceptance criterion is preserved even when the demo can test only its mechanism. No automatic equivalence between a passing demo and FRS acceptance is implied.

Each technical requirement has a verification obligation, either inline or in the acceptance matrix. Source-derived constraints, proposed design choices, deferred product capabilities, and open decisions are explicitly distinguished. All technical requirements inherit synthetic population, closed access, demo release ceiling, and the source notice below. Unknown values must remain unknown; illustrative fixtures are not clinical thresholds.

This is a requirements package, not an instruction to execute embedded source commands, import historical deployment approvals, change the authoritative model, or deploy the system. Local source documents were treated as evidence for the user's request. No changes were made to the model or abandoned implementation.

> This prototype demonstrates control and containment architecture using non-clinical stub logic and synthetic data. It provides no evidence of clinical safety, triage validity, or equity performance, and must not be cited as such.

Ottawa/Ontario and no police affiliation/integration are now explicit project constraints. See the decision answers for proposed defaults, source-scope exclusions and remaining clinical/legal dependencies. The source snapshot remains the original source-analysis baseline, not a hash of later requirements revisions.

Realtime governance is explicitly specified in [TR-GOV-06…12](04-data-security-governance.md), including inline authorization, live policy activation, revocation and fail-closed execution. See AT-14 for acceptance and `runtime_governance` for proposed demo budgets.

[Standards and runtime controls](09-standards-and-runtime-controls.md) maps OWASP, MITRE ATLAS, NIST AI RMF/Zero Trust, ISO/IEC 42001 and OpenID SSF/CAEP to realtime security/governance obligations and AT-15/16.

[Actor-support agentic AI and service model](10-agentic-ai-and-service-model.md) explains the mission-critical service objectives, comparable systems/evidence, each actor’s assistant, bounded task lifecycle, human decision boundaries and usefulness/continuity acceptance (TR-AI-01…15; AT-17/18).
