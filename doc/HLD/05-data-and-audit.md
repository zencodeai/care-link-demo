# Information ownership, consistency and lifecycle

## Information model and ownership

One scoped data/audit gateway mediates application persistence. Initial business, control and canonical audit storage share a PostgreSQL transactional boundary to support consistent accepted effects. Identity state uses a separate database/access boundary; if placed on the same instance/host this is privilege separation, not failure independence. Domain services own meaning and transitions; the gateway owns authorized projections and consistent durable commits. Runtime, edge, jobs and operator do not get arbitrary store access.

| Information aggregate | Meaning / owner | Principal relationships and access |
|---|---|---|
| Access principal and browser session | Identity/edge evidence for actual account | Explicit access to business personas, never inferred identity linking |
| Session, assessment and messages | Session service owns ordered interaction, state and context | Participant and assigned workforce projections; connectivity separate from resolution |
| Information assertion and relationship | Assertion service owns attributed report/history | Author/subject/source/verification/dispute preserved; relationship is not permission |
| Crisis plan and field sharing | Plan service owns PID-led wishes and allowed sharing | Field/purpose/recipient grants with current authority and attribution |
| Consent ledger | Consent service owns grant/revocation history and current effective scope | Subject/grantor/session/recipient/fields/purpose/time; independent from general role permission |
| Directory and knowledge version | Source service owns provenance, freshness, verification and suspension | Versioned approved facts and fictional service operating envelope |
| Queue, assignment and handoff | Workforce service owns request, accountable worker and confirmation | Single conversation owner, scoped context pack, explicit failure/unknown outcomes |
| Task, draft, observation and review | Task coordinator owns bounded work and review provenance | Initiating actor, scope, source/version references and human decision |
| Referral, attempt and receipt | Referral service owns approved package and transmission history | Recipient/consent/review evidence, separate authorization/attempt/receipt |
| Follow-up, outcome and incident | Follow-up/quality services own schedules, observations and remediation | Separate contact consent, carer outcomes and unknown/missing evidence |
| Artifact, activation and authority history | Governance control owns approved effective state | Exact digest/review lineage, revocations and immutable exclusions |
| Canonical audit and checkpoints | Dedicated audit authority owns append-only record | Actor/action/purpose/decision/digests/versions; content minimized and read purpose-limited |
| Rights, lifecycle and recovery metadata | Rights/recovery authority owns disposition and restoration restrictions | All purpose copies, backups, tombstones, holds and serving-promotion evidence |
| Aggregate metrics and evaluation | Quality service owns versioned definitions/projections | Coupled safety/access/equity outcomes, no individual exposure or HR feed |

This is a logical information model. Physical columns, indexes, SQL roles and migration scripts are deferred. Every protected read/write carries current ownership/assignment/field/purpose scope; caller identity alone never authorizes a row or a disclosure.

## Durable decisions and audit

An accepted local business/control transition, its canonical audit record and reliable downstream work intent commit consistently. The initial co-located transactional design avoids pretending that separate stores/network services commit atomically. Exact command/query mechanisms are implementation decisions subject to tests. Failure cannot publish a successful transition whose required audit did not durably commit. Protected disclosure also requires current authorization and an audited disclosure boundary before release.

Audit records what was decided/authorized and what was observed separately. A send authorization is not evidence of receiver delivery; a receipt is not a human connection. Stable logical operation identity supports idempotent reconciliation after retry or lost acknowledgement. Retries cannot bypass current permission to reveal the result. Multiple attempt/security/receipt events may link to one canonical operation without duplicating its effect.

Dedicated write/read identities, append-only access, integrity chaining and independently stored checkpoints limit ordinary tampering. Plain PostgreSQL on a shared host is not immutable against root/owner compromise; separate checkpoints on the same host do not establish external transparency. Audit content is minimized to structured facts/digests and version references. Digests remain potentially sensitive, and metadata alone cannot reconstruct omitted content.

## Side effects and concurrency semantics

Current policy, identity, consent, assignment and source revisions are checked at the effect-authorization boundary. Changes ordered before it block stale work; concurrent ownership/approval has one current accepted outcome. The implementation must enforce this order without assuming a cached permit or a notification proves current authority.

External transmission occurs outside the local transaction. Reliable intent, stable recipient/action identity and receipt reconciliation prevent blind duplicate execution; end-to-end exactly-once delivery is not claimed. After an ambiguous send, status remains unknown until evidence resolves it. Revocation after dispatch authorization may be too late to recall content. Human owners see this distinction and choose an approved recovery path.

## Retention, rights and dependencies

Lifecycle policy owns both duration and the authoritative event from which it is measured. DEC-03/B accepts the event-anchored per-purpose schedule in the table below for local synthetic design; it replaces an unspecified creation-time default. The actual-account metadata schedule remains a separate unresolved item. Shared demo durations remain proposed parameters, not legal retention approval. Real access-account metadata has a separate schedule.

Records, purpose-bound copies, plan snapshots, replay data, temporary exports and backups form lifecycle dependencies. A longer-lived plan cannot silently depend on a purged short-lived session assertion: either retain a minimized independently justified attributed snapshot or make the source unavailable explicitly. Copying cannot evade deletion. Authenticated holds and releases apply to their documented scope/dependents; missing rules, unresolved anchors or contradictory authority block unsafe purge rather than infer approval.

Rights processing distinguishes requested, eligible, held, active-content purged, backup pending, completed with explicit retained exceptions and failed/reconciliation needed. Eligibility or file unlink is not proof of physical erasure from WAL, snapshots or other copies. User export/deletion requires current operation assurance and own-data scope; output cannot include unrelated private reports. Retained minimal audit/control references and legal/demo exceptions are explained honestly.


### Accepted local lifecycle anchors — DEC-03/B

| Class | Accepted anchor / interpretation | Existing duration |
|---|---|---|
| Session-purpose content and person/carer records | Explicit session/last relevant parent closure; unresolved session stays anchor-pending | 7 days |
| Referral/receipt | Later of session closure and terminal/reconciled delivery outcome | 7 days |
| Plan and justified plan-purpose snapshot | Ordinary cleanup from explicit plan retirement; active plans do not expire merely from creation age. Verified PID deletion uses the faster rights target rather than an additional 30-day delay | 30 days |
| Consent history | Later of relevant parent closure and effective expiry/revocation; preserve minimal dependent revocation/recovery evidence with reported exception | 30 days |
| Replay | Capture time | 7 days |
| Security / audit / aggregate metrics | Event time or closed reporting interval, with audit closure/pruning evidence | 30 / 90 / 90 days |
| Backup | Immutable capture time; retry/restore does not renew expiry | 7 days |
| Actual account metadata | Separate minimum-needed active-account/deprovision/recovery policy; exact periods not accepted by this decision | Unresolved |
| Recovery restrictions/approval history | Cover every restorable copy and dependent grant/receipt; review retained linkability | Dependency-bound exception, not a new blanket TTL |

The existing eligible active-deletion and backup-expiry targets remain unchanged. Scoped authenticated engineering holds/releases and all purpose copies are included; blocked rules/holds are reported, not treated as successful purge. This is a local engineering interpretation, not legal retention approval or an assertion of upstream lifecycle conformance.

## Recovery authority and serving promotion

Backups preserve authorized state and provenance, not a licence to reactivate old access. DEC-04/B selects a separately credentialled host recovery-control journal and checkpoints outside the restored business store and cluster-managed volume lifecycle. Current identity/consent/sharing restrictions, deletion/hold and relevant control history must survive separately from point-in-time business restore. Cross-store publication uses an explicitly reconciled durable workflow; there is no fictional atomic file-and-database commit. If the latest required authority history is unavailable, restoration remains blocked from serving.

Restore lifecycle: isolated quarantine, validate inventory/integrity/version, reconcile current independently trusted authority/rights/holds and uncertain effects, validate scoped access, obtain separate human serving approval, then fence obsolete generation and promote the approved target. The restored snapshot cannot certify its own current consent/revocation state. A signed old head proves origin, not recency. Changed target/control state invalidates stale promotion evidence. Credentials/continuation tokens/queued approvals are not blindly restored. The accepted design retains same-host loss/root-compromise limitations; it is not an off-host witness or disaster-recency guarantee. Detailed journal publication/recency, trust/cutover mechanisms and promotion tests are implementation work; operational stages are specified in document 08.

## Replay and analytical use

Replay uses pinned deterministic components, approved synthetic input snapshots and recorded model observations. It compares deterministic service outcomes, not regenerated model text. Shadow evaluation has no live decision authority and cannot train the model automatically. Metrics distinguish observation/unknown from actual successful outcome, couple police-avoidance with safety/access/equity and suppress individual exposure and unsafe small-group inference. No secondary real-person training or policing analytics is introduced.

> This prototype demonstrates control and containment architecture using non-clinical stub logic and synthetic data. It provides no evidence of clinical safety, triage validity, or equity performance, and must not be cited as such.
