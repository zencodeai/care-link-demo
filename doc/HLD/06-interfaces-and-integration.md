# Interfaces, contracts, events and simulators

## Common contract rules

Use `/api/v1` JSON command/query interfaces, OpenAPI and closed JSON Schemas with nested types, enums, lengths, size bounds, required provenance and unknown-field rejection. IDs are opaque UUIDs; timestamps UTC; client input cannot set actor, assurance, committed tier or governance epoch. Mutation requires request/correlation ID, idempotency key and expected aggregate revision. Reusing a key for different content is 409 conflict. Pagination and field projections are scoped. No arbitrary URLs/files accepted. Implement exact payload schemas before the related endpoint; these are HLD operation definitions, not executable OpenAPI.

All responses include request ID and version; protected successful mutations include committed state/event/audit references. Typed errors: 400 schema/unknown-field; 401 invalid identity; 403 forbidden/consent; 409 stale revision/idempotency; 413 size; 422 unsupported semantic action; 429 budget; 503 unavailable enforcement/audit/model. REQUIRE_HUMAN is a non-executed proposal/review state, never a successful side effect. Error text must not reveal other session existence or secret policy contents. Public help status is explicitly unconfirmed until workforce acceptance.

| Operation family / representative method-path | Caller, input and returned result | Enforcement / effects |
|---|---|---|
| POST `/sessions`; POST `/sessions/{id}/turns` | Participant; disclosure/role/jurisdiction then text+revision; ordered state/event IDs | Admit demo/synthetic; ownership; hazard path before AI; audit state |
| GET `/sessions/{id}`; GET `/sessions/{id}/events` | Authorized participant/assigned worker; SSE cursor | Projection/filter every event; reconnect after committed sequence only |
| POST `/help/requests`; GET `/help/requests/{id}` | Scoped participant to independent help gateway; opaque session ref, language and reply token | Minimal fixed auth/limits, no history; durable local acknowledgement not connection |
| POST `/queue/{id}/assignments`; POST `/handoffs/{id}/confirm`; POST `/sessions/{id}/takeover` | Worker/supervisor; expected revision/generation | Assigned scope, ownership compare-and-set, increment generation/fence output |
| POST `/assertions`; PATCH `/plans/{id}/fields/{field}`; POST `/plans/{id}/shares` | Subject/scoped participant; attributed payload | Operation assurance, per-field authority, conflicts not overwritten |
| POST `/consents`; POST `/consents/{id}/revocations` | Qualified grantor; purpose/recipient/fields/window | Ledger append plus current projection/revision; no model grant |
| GET `/directory`; POST `/directory/{id}/suspensions` | Scoped participant/worker; maintenance/security for suspend | Jurisdiction/freshness/source filter, quarantine no deploy |
| POST `/tasks`; GET `/tasks/{id}`; POST `/tasks/{id}/cancel` | Actor; bounded goal/context refs | Task-type permission, scope/budget, cancellation fence |
| POST `/reviews/{id}/decisions` | Responsible human; accepted exact payload digest/revisions | Current assurance/ownership, expiry, edit requires new digest |
| POST `/referrals`; POST `/referrals/{id}/dispatch`; GET `/referrals/{id}/receipt` | Worker/authorized jobs; approved draft/key | Separate generation/send; current consent, one-use dispatch and reconciliation |
| POST `/followups`; POST `/followups/{id}/cancel`; POST `/outcomes`; POST `/incidents` | Scoped participant/worker/jobs | Separate contact consent, unknown outcomes and incident actions |
| POST `/continuations/redeem`; POST `/rights/exports`; POST `/rights/deletions` | Participant with AL0/AL3 as appropriate | Single-use explicit link, cooling-off, scoped asynchronous rights job |
| POST `/control/activations`; POST `/control/kill`; POST `/control/rollback-proposals` | Scoped governance/operator | Independent approved digests; new epoch, deny self-approval |
| GET `/audit`; GET `/metrics`; GET `/evidence` | Auditor/reviewer under scope | Audited read; coupled/suppressed aggregate schemas |

Private broker operations: lease task, build context, request inference, submit proposal, execute permitted step and release lease. Each binds workload/task/lease generation and current scope; runtime cannot invoke generic core admin endpoints. Private data gateway query/command operations are allowlisted by module/workload and never accept arbitrary SQL. Simulator admin scenario controls are trainer-only, separated from receiving-service APIs.

## Contract catalogue

Retain six upstream indicative contracts as source references: turn envelope, proposal envelope, broker decision, consent record, audit event and closed empty triage features. Create reviewed local normative versions without silently tightening upstream v1. Domain-to-wire mappings explicitly cover consent actor/grantor and audit timestamp/occurred_at. Track exact consumer versions in release manifest. Fields for new local task/control contracts do not mutate authoritative model schemas.

Additional local contracts: `task.v1`, `step_observation.v1`, `draft_review.v1`, `referral.v1`, `receipt.v1`, `help_request.v1`, `policy_request.v1`, `policy_decision.v1`, `activation.v1`, `enforcer_ack.v1`, `control_signal.v1`, `stream_event.v1`, `rights_job.v1`, `checkpoint.v1`. Each needs producer/consumer, schemas, scopes, allowed state transitions, timeout/idempotency and negative fixtures. Event envelope includes ID/type/version/time, subject/ref, correlation, producer identity, aggregate revision, policy epoch and payload reference/digest; protected content is fetched through scoped APIs, not broadcast in signals.

SSE is selected for browser updates with normal HTTP commands. Persist events with sequence and Last-Event-ID recovery; duplicate notifications are allowed and deduplicated client-side. Retention gap returns typed resynchronization to a freshly authorized snapshot. No global cross-session feed. Revocation suppresses subsequent content even if socket remains open momentarily. Channel simulators map voice/SMS/relay events to the same session APIs; no live carrier traffic or transcript engine is assumed.

## Simulator matrix

| Simulator | Data/state and scenarios | Isolation |
|---|---|---|
| MCRT/navigator intake | Own service inbox, schema reject, accept/reject/partial, delay, timeout, idempotent receipt lookup | Synthetic sourced stable recipient IDs only |
| Crisis-line handoff | Queue/accept/refuse/drop and confirmation | No real phone/SIP service; user connection is role-play |
| Generic care-summary receiver | Consented export received/no receipt confirmation | No police-specific address, fields or workflow |
| Directory feed | Structural/operational/availability changes, closure/holiday/weather/outage/conflict/poisoned records | Signed verification-owner ingestion; quarantine |
| Channel/interpretation | Internal text, synthetic voice-event/relay representations, EN/FR and interpretation handoff | Demonstrates contract/state continuity, not real translation/telephony adequacy |
| Denied EMS target | Known resolvable target for forbidden-destination tests | No business connector or network permission; no real contact |

Simulator responses are untrusted on reentry; a poisoned service description cannot promote itself to instruction or recipient truth. Reset requires explicit demo namespace/population and preserves audit unless separately authorized. Real INT-1…INT-9 integrations remain deferred; police-specific source interface is excluded, not a future adapter toggle.

> This prototype demonstrates control and containment architecture using non-clinical stub logic and synthetic data. It provides no evidence of clinical safety, triage validity, or equity performance, and must not be cited as such.
