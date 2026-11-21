# CARE-Link technical high-level design

> Current authorized implementation · 2026-11-20: [Agentic workflows and role-scoped clinical knowledge](../decisions/2026-11-20-agentic-workflows-and-clinical-rag.md) records the bounded LangGraph architecture, Qwen migration, resource provenance and implementation limits. See session003 evidence for actual qualification; no clinical or deployed-readiness pass is implied.

> Current model direction · 2026-11-20: Qwen3.8-27B replaces the earlier Gemma selection. The current workflow/RAG decision selects LangGraph beneath existing coordinator/broker authority. Historical design evidence remains historical; source implementation and live qualification are recorded separately.

Version 0.4 · Revised 2026-11-06 · DEC-01…05 accepted for local design; implementation/release evidence remains pending.

CARE-Link is an actor-led crisis-support service concept. Its architecture helps clients and carers express needs, supports workers with grounded AI assistance, and coordinates informed service choices and confirmed handoffs. The present implementation target is a closed synthetic demonstrator. Mission-critical service intent drives clear authority, inline enforcement and honest continuity; it is not a claim that a single-host prototype is clinically ready or continuously staffed.

## Purpose and design level

This HLD explains **how the major parts work together, who owns each responsibility, and why the architecture was selected**. It connects requirements to service journeys, component boundaries, logical interfaces, data ownership, trust, deployment, operations and trade-offs. It guides implementation planning. Physical schemas, full API payloads, function signatures, lock algorithms and manifests are deliberately outside this document set. The deleted LLD is not recreated.

The primary architecture decision is a modular deterministic service core, isolated untrusted agent runtime and local inference gateway, a controlled persistence/audit boundary, and an independently served minimal-help/static-information path. Humans retain clinical and consequential service authority; the model proposes within scoped tasks; deterministic services authorize and execute.

## Reading map

| Document | Questions answered |
|---|---|
| [01 — Context and architecture](01-context-and-architecture.md) | Where are the boundaries, major components, owners and allowed dependencies? |
| [02 — Actors and service workflows](02-actors-and-service-workflows.md) | How do actors deliver useful service from intake through follow-up, and what happens when a step fails? |
| [03 — Agentic assistance and inference](03-agentic-assistance-and-inference.md) | Where does AI add value, how does bounded coordination work, and who approves effects? |
| [04 — Safety, security and governance](04-safety-security-and-governance.md) | How are human/workload trust, mesh authentication and runtime decisions enforced? |
| [05 — Data and audit](05-data-and-audit.md) | Who owns data and durable truth, and how are consent, audit, lifecycle and recovery made consistent? |
| [06 — Interfaces and integration](06-interfaces-and-integration.md) | Which components exchange what information, with what authority and failure semantics? |
| [07 — Deployment and delivery](07-deployment-and-delivery.md) | How do logical components map to the local host, Kubernetes and delivery process? |
| [08 — Reliability and operations](08-reliability-and-operations.md) | What survives each failure, how are service targets measured, and how does recovery regain serving authority? |
| [09 — Verification and traceability](09-verification-and-traceability.md) | Where are requirements/architecture elements addressed and how will the design be evaluated? |
| [10 — Decisions and boundaries](10-decisions-and-implementation-boundaries.md) | Which alternatives were selected, what trade-offs remain and what evidence is needed? |
| [11 — Decision requirements and options](11-decision-requirements-and-options.md) | Which choices were compared, which recommendations were accepted, and what remains to verify? |
| [Local decision acceptance](decisions/2026-11-06-local-design-baseline.md) | What did the user approve, and which qualifications remain? |
| [Design inventory](design-inventory.json) | Versioned subsystem ownership and tracked requirements-input revisions |

## Authority and status

The [requirements](../REQ/README.md), explicit later scope clarifications and [actor-support model](../REQ/10-agentic-ai-and-service-model.md) are the inputs. Existing upstream FRS/SAD/model nodes remain references; this HLD does not amend them or import historical approvals. Police-specific source workflows are excluded under current user scope and remain visible as unmet/excluded trace dispositions.

[Demo parameters](../REQ/demo-parameters.json) distinguish accepted DEC-01…05 design meanings from unmeasured numerical defaults/targets. They are not activated runtime settings or clinical thresholds. The [acceptance record](decisions/2026-11-06-local-design-baseline.md) is scoped to those five local choices and their qualifications. Null means unresolved/unknown, never permission. Architecture-fixed prohibitions cannot be enabled by a settings change. Source-owner dispositions for inference/youth/safe-mode authority, actual host capacity, exact software/model pins and independent content/release review remain explicit in document 10.

This revision replaces implementation-level drift with architectural responsibilities and reconciles service, help-path and recovery descriptions. It is a reviewable design, not an assertion of completeness by document counts. No services were built/deployed or performance/clinical claims verified. AI specialist review supports authoring and is not independent human sign-off. The user’s explicit local decision acceptance is recorded separately and does not invent a second reviewer or approve the entire implementation/release.

> This prototype demonstrates control and containment architecture using non-clinical stub logic and synthetic data. It provides no evidence of clinical safety, triage validity, or equity performance, and must not be cited as such.

Later local design acceptance: [LLD recommendations, this workstation and `google/gemma-4-12b-qat`](../LLD/decisions/2026-11-06-implementation-choices-and-model.md). The explicit model choice supersedes earlier local selection; implementation evidence and upstream dispositions remain separate.
