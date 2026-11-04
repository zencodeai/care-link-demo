# Architecture and interface requirements

> Scope update (2026-11-04): [Decision answers](08-open-decisions.md) and [demo parameters](demo-parameters.json) establish Ottawa/Ontario context and exclude all police roles, brief sinks, connectors and partnerships from the proposed demo. Earlier police-specific descriptions below are retained only as historical source context and are superseded for implementation; they do not imply a police relationship. Source FR-C6 and AQ-9/AQ-26 are excluded by current user scope, not satisfied. Concrete defaults replace earlier open engineering choices; clinical/legal approvals and hardware-dependent checks remain unresolved.

Sources: SAD §§4–8; HLD §§5–7, 13; six model contracts; ADR-13 (proposed). Deployment grouping and endpoint examples below are proposed design choices, not existing implementation.

## Components and authority

**TR-ARC-01.** SHALL preserve logical zones Z0 independent fallback, Z1 edge, Z2 untrusted runtime, Z3 safety core, Z4 sourced knowledge/data, Z5 human operations and Z6 control/audit. Each authoritative decision SHALL have exactly one deterministic owner. Every model proposal and nested agent step SHALL pass through the broker. Verify component dependency rules and deployed traffic probes.

| Proposed deployable | Modules and authority |
|---|---|
| Web UI / edge API | Role routes, session gateway, disclosure, participant authentication, transport/reconnect, human-help entry; no policy authority in browser. |
| Runtime | Stateless prompt construction consumer and proposal generator; session context only; no datastore credentials, capability token or partner connector. |
| Safety/application API | Broker enforcement, emergency guard, deterministic policy modules, assessment state transitions, consent, directory, plans, queue and referral orchestration. Internal module APIs preserve authority boundaries; extracted services remain possible. |
| Inference adapter | Dedicated broker-owned narrow interface to host LM Studio, destination pinning, timeouts, concurrency and digest telemetry. Separate deployment where necessary to enforce networking. |
| Simulator service(s) | MCRT, crisis-line handoff, generic care-summary recipient, denied EMS target, interpretation/channel and directory-feed simulators. No external routes. |
| Audit writer / reader | Dedicated writer identity and append-only commit; separately scoped reader/export path. Application cannot mutate historical records. |
| Persistence | Proposed PostgreSQL, separated database roles/schemas for sessions, plans, consent, referrals, registry and audit; backup/restore. Choice requires D-04. |
| Static fallback | Independent content host and publication process, no runtime/auth/database/directory dependency. |

Logical model elements need not each become a network service. Conversely, colocating incompatible privileges must not make the runtime or operator able to read/write restricted stores. The final design SHALL include a model-element-to-module/deployment map and allowed-call matrix before implementation acceptance (**TR-ARC-02**).

## LLM and bounded agent behavior

**TR-LLM-01.** SHALL use local LM Studio with Gemma 3 4B IT as requested. Record exact model artifact origin/digest, quantization, loaded model identifier, LM Studio version, inference interface, prompt digest, decoding settings, context/output limits and applicable license review. “Gemma” in a UI label is insufficient identification. No model download or server configuration is authorized by this documentation task.

**TR-LLM-02.** SHALL use the model only to propose conversational wording, assessment extraction candidates, summary drafts and allowed action candidates. It SHALL NOT determine committed tier, consent, legal basis, role, jurisdiction, recipient, identity link, or action permission. Controlled assessment rationale and service/legal/protocol facts SHALL be assembled from approved structured inputs and sourced templates. Never expose model hidden reasoning or stream unchecked tokens to participants.

**TR-LLM-03.** The agent framework SHALL provide explicit state transitions, bounded steps/tokens/tool budgets, cancellation, correlation, validated envelopes and replayable deterministic orchestration. Proposed baseline is a small explicit state machine; no multi-agent framework is required by the source. Any library choice requires D-05 and must preserve broker enforcement for every step. No self-registration of tools, indefinite loops, autonomous browsing, shell execution, or cross-session memory.

**TR-LLM-04.** SHALL reject malformed/oversized/unknown-field proposals and any invalid sourced claim or taint provenance as a whole, with no partial action execution. Bounded retry SHALL not delay hazard guidance/human help. Model timeout, unavailable model, context overflow and cancellation SHALL yield a safe template and retain support. Verify using real local inference and a deliberately adversarial fake proposer; a successful mocked call does not prove LM Studio integration.

**TR-LLM-05.** Runtime egress SHALL remain broker-only pending D-02. Proposed inference flow: runtime requests inference through broker; a constrained broker-owned adapter invokes the pinned host endpoint and returns untrusted output. Authorization is never relaxed to accommodate an SDK. Host listener access SHALL be restricted to approved local/cluster sources; avoid public binding. Verify pod-to-host reachability and denial of arbitrary destination substitution. Host routing, TLS/auth boundary and streaming/JSON support require capability checks, not assumptions.

## Contracts

**TR-API-01.** SHALL define complete versioned JSON Schemas/OpenAPI before implementing each endpoint, including nested objects, enums, limits, timestamps, identifiers, unknown-field rejection, authorization, typed errors and failure mode. Existing contracts contain indicative nested type strings; they are not complete normative wire schemas. Tightening an accepted shape requires explicit versioning/migration, not silent reinterpretation. UI/server/simulator contract tests SHALL share fixtures.

| Existing model contract | Required implementation behavior |
|---|---|
| `turn_envelope.v1` | Immutable session/turn IDs, channel/role/jurisdiction, captured/unknown/deferred state, committed tier, provenance-labelled context, version stamps, demo/synthetic tags. Capability summary only. |
| `proposal_envelope.v1` | Candidate text, sourced claim references, action IDs/tools/parameters/provenance/purpose/idempotency; provisional tier remains non-authoritative. |
| `broker_decision.v1` | PERMIT/DENY/REQUIRE_HUMAN, typed reasons/obligations, audit reference before result, every returning tool result re-tainted `untrusted`. |
| `consent_record.v1` | Subject/grantor/assurance, exact purpose and recipient, field set, legal/consent basis, session binding, grant/expiry/revocation, scope hash. |
| `audit_event.v1` | Event/sequence/hash chain/time/trace/session/actor/action, decision and consent references, digests, all artifact versions, environment, data classes and severity. |
| `triage_features.v1` | Closed empty `situation_factors` plus tier-set version. No added clinical or prohibited factors; reject unknown nested keys. |

**TR-API-02.** SHALL specify application operations for session/turn submission, event subscription/reconnect, human request, assignment/takeover, consent grant/revoke, plan field sharing, directory query/suspension, referral/receipt, continuation, export/delete, operating-state control, kill/rollback and scoped audit export. Each SHALL declare method/path/version, request/response schema, actor/scope, side effects, idempotency, ordering, limits and errors. These are contract obligations; no endpoint is claimed to exist.

**TR-API-03.** SHALL use optimistic state revisions and monotonic event sequence numbers to reject stale writes and allow reconnect without duplicate actions. No exactly-once network-delivery claim. Stable request IDs, transactional outbox/deduplication and receipt reconciliation SHALL provide one committed logical outcome per idempotency key. Reuse with different payload SHALL be rejected.

**TR-API-04.** Simulator contracts SHALL cover accept/reject/timeout/partial/schema rejection, warm-transfer queue/drop/refusal, receipt unavailable for generic care summaries, denied EMS target and poisoned directory records. Contracted real integrations INT-1…INT-9 remain simulated/deferred; no production credentials or emergency dialing tools SHALL be present.


## Runtime governance enforcement architecture

[TR-GOV-06…12](04-data-security-governance.md) require inline enforcement beyond deployment review. The design SHALL include a PEP/PDP call map for every protected operation, a signed policy-bundle activation controller, authoritative revision/epoch checks, a scoped dispatch-authorization mechanism and per-enforcer activation acknowledgements. These can be modules within the existing deployables; a new service for every concern is not required. Include human APIs, background jobs, repositories and streams alongside the agent broker. No workload may access a protected store or connector through an unmediated alternate path.

Extend the versioned contract inventory with policy evaluation request/decision, activation/acknowledgement and revocation records. Define atomicity, error codes, obligation completion, expiry, idempotency and the irreversible effect boundary; validate them with AT-14. Transport notifications are supplementary to authoritative execution checks. Safe-mode human-help has its own narrow contract and remains subject to D-02 source-owner disposition.

> This prototype demonstrates control and containment architecture using non-clinical stub logic and synthetic data. It provides no evidence of clinical safety, triage validity, or equity performance, and must not be cited as such.

Runtime security SHALL implement [TR-SEC-09…16](04-data-security-governance.md), including authenticated invalidation signals, authoritative reconciliation, egress enforcement, resource controls and drift containment. Specify signal validation/replay/gap-recovery contracts and separate CAEP identity events from custom consent/policy events. The [standards baseline](09-standards-and-runtime-controls.md) defines the reference architecture and traceability obligations.

## Actor-assistance runtime

[TR-AI-01…15](10-agentic-ai-and-service-model.md) require a role-scoped task coordinator, structured plan/checkpoint state, typed tool registry, observation handling, review inbox and outcome reconciliation. These are logical modules in the bounded runtime/application design, not a mandate for autonomous multi-agent services. Add versioned task, step, review/approval, observation and completion contracts under TR-API-01/02. Persist provenance and actor/task identities separately. Protected tools pass the same broker/PEP checks as every other operation. AI disablement must preserve authorized human workflows.
