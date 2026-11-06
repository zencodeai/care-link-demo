# Logical interfaces and integration architecture

## Interface principles

Interfaces expose bounded business capabilities, not unrestricted databases, policy admin proxies or generic agent execution. Producer/consumer identity, purpose, authority and evidence required are part of each interface. Messages are versioned and schema validated, but a valid shape is not consent or permission. Detailed paths, payload fields, transport errors and schemas belong to implementation design and are intentionally omitted here.

Requests/results/events carry sufficient correlation, provenance, version and operation identity to reconstruct outcomes, detect stale state and reconcile retries without leaking unnecessary content. Client/model input cannot declare authoritative role, assurance, consent, tier, recipient endpoint or governance state. Unknown/incompatible contracts fail safely; reviewed interface version changes do not silently mutate upstream indicative source contracts.

## Component interface map

| Interface | Producer → consumer | Information / result | Authority and failure behaviour |
|---|---|---|---|
| Actor access and command | Role app → edge → core | Disclosures, needs, corrections, messages and explicit actions | Verified actor/current resource scope; unavailable core is not false successful submission |
| Identity and step-up | Edge/authorized control → identity | Authentication/assurance/revocation evidence | Trusted provider and bound login intent; unavailable proof does not raise assurance |
| Authorized projection/event | Core/data → authorized actor app | Permitted context/state/update | Filter at disclosure boundary, current recipient rights, resumable delivery without cross-session leak |
| Domain state and audit | Core/control → data/audit gateway | Scoped transition, disclosure decision and durable outcome | Consistent accepted state/audit/work intent; failure denies protected success |
| Task and proposal | Coordinator ↔ runtime through broker | Scoped task/context, proposed steps/content and observations | Model data untrusted; no independent tool/store access; cancellation invalidates stale work |
| Model inference | Broker → inference gateway → host bridge/model | Approved context and bounded generated proposal | Exact admitted local model/task, tainted result, no remote fallback |
| Deterministic decision | PEP → policy service | Current authoritative context, permit/deny/review and obligations | Unknown/stale/unsatisfied obligation fails closed; no model decision authority |
| Activation and revocation | Reviewed registry/control → enforcement instances/data | Exact approved version, current restrictions and acknowledgement | Restrictive state fences future effects; rollback retains current negative rights |
| Background work | Durable work intent → jobs → core | Follow-up, reconciliation, expiry and authorized dispatch | Current scope rechecked at execution; enqueue-time approval is insufficient |
| Receiving-service exchange | Core adapter ↔ simulator/receiver | Consented package, clarification, accept/reject/receipt | Recipient-owned confirmation; uncertain send remains unknown pending evidence |
| Directory/content ingestion | Verified owner/feed simulator → knowledge service | Versioned source facts, freshness, correction/suspension | Poisoned/unverified content quarantined; no automatic replacement instructions |
| Independent minimal help | Client/workforce host UI ↔ help service/spool | Opaque own request, recorded/accepted-unconnected state | Own bounded trust/durability, no history; not a staffed connection guarantee |
| Help reconciliation after recovery | Host help/spool → restored core/workforce | Minimal request identity, correlation and observed status | Current authority, idempotent deduplication and accountable acceptance; no stale grant transfer or automatic connected-care status |
| Static publication | Independent reviewed publication → static host → anyone | Verified public crisis information | No runtime/policy/auth/store request dependency; no private data |
| Evidence and telemetry | Approved components → collector / audit/quality → scoped dashboards | Health, denials, traces, evidence and aggregate outcomes | Observation cannot authorize effects; content/identity minimization |
| Backup and recovery | Persistence/control history → isolated restore authority → reviewed target | Snapshot/checkpoints, current authority reconciliation and serving evidence | Quarantine before independently approved promotion; missing current head blocks serving |

## Event delivery and consistency

A durable authoritative record, not a browser cache or model transcript, determines accepted state. Push updates provide timely actor coordination with explicit reconnect/resynchronization; delivery may duplicate or lag and therefore never establishes a new authorization by itself. Every protected event is projected for its current recipient; revoke/takeover cancels future stale output. Previously authorized bytes cannot be recalled. Closed sessions, transports and human ownership remain separate concepts.

Reliable asynchronous work stores intent with the accepted domain transition and reconciles effect outcomes. Only idempotent safe operations may retry automatically without new consequential disclosure. A network timeout after send is not proof no receiver saw it. Version/ownership changes invalidate queued work and require fresh review when material content changes. Background jobs do not hold all actor privileges or public mutable endpoints.

## Synthetic external-system boundary

| Simulator / actor interface | Behaviour represented | What is not established |
|---|---|---|
| MCRT/community navigator intake | Accept/reject/partial/schema rejection/delay and receipt lookup | Real partner agreement, staffed capacity, live dispatch or arrival |
| Crisis-support handoff | Queue, refuse/drop, acceptance/connection confirmation | Actual telephone/carrier or contracted human service |
| Generic summary receiver | Permitted package, optional receipt unavailable | Police-specific fields, recipient or data-sharing workflow |
| Directory feed | Operating changes, holidays/weather/outage/conflict and poisoned record | Verified real local pathway coverage |
| Internal channels/interpretation | Explicit cross-channel continuation and language/relay event flow | Real SMS/voice/mobile/relay/interpretation equivalence or deployment |
| Training/denied emergency test target | Controlled fictional scenarios and guard/network denial evidence | An emergency connector, real endpoint or runtime-callable dispatch tool |

Scenario/training controls are isolated from ordinary service tasks and cannot change another session’s authority or feed live learning. Simulator observations reenter as untrusted content. Real integrations remain deferred and require new scoped agreements/evidence; police integration remains excluded rather than a dormant configurable adapter.

## Contract-source relationship

Existing upstream turn/proposal/broker/consent/audit and closed triage-feature contracts guide logical boundaries. Their indicative nested shapes are not fully implemented normative payloads. Local task/review/control/recovery contracts require explicit versioned design and implementation review later; this HLD neither changes upstream schemas nor implies they already execute. Traceability links requirement concerns to these interfaces, not just to names of future files.

> This prototype demonstrates control and containment architecture using non-clinical stub logic and synthetic data. It provides no evidence of clinical safety, triage validity, or equity performance, and must not be cited as such.
