# Data, transactions, audit and lifecycle

## Ownership and schema boundaries

PostgreSQL is the initial durable store. Separate identity database, business schemas, control schema and audit schema/login grants; no shared app superuser. `data-gateway` exposes scoped queries/commands; runtime, edge, jobs, core and operator do not hold arbitrary DB credentials. Tables carry opaque ID, demo/synthetic tags where applicable, purpose, owner/subject, revision, timestamps and artifact lineage. Migration history is versioned. Local storage encryption is a deployment property, not proof from database configuration.

| Aggregate / records | Owning module and relationships |
|---|---|
| Access identity / account-session / step-up | Identity/BFF; account ID maps explicitly to business session access, never inferred PID identity |
| Session / ordered turn / message / assessment / tier history | Session module; session→many turns/events/assertions; conversation generation fences writers |
| Person / carer relationship / assertion | Assertion module; relationship grants no automatic access; multiple disputed reports coexist |
| Plan / field assertion / share grant | Plan module; field-level author, subject, verification, dispute and consent references |
| Directory record / source-field version / suspension | Directory module; immutable snapshots and current effective pointer; separate freshness per field |
| Consent event / current projection | Consent module; append-only grant/revoke; exact subject/purpose/recipient/session/field binding |
| Queue item / assignment / handoff / help reference | Human operations; unique active owner, partner/transport state separate from service outcome |
| Task / step / observation / lease / draft / approval | Task module; links input/source revisions and exact review payload to action |
| Referral / transmission attempt / receipt / reconciliation | Referral module; immutable approved payload snapshot, recipient ID, dedup key; explicit unknown state |
| Follow-up / contact consent / outcome / incident | Follow-up/quality modules; separate consent, dispatch cancellation, attributed outcomes and corrective actions |
| Artifact / review / signature / activation / policy epoch / revocation | Control module; immutable reviews and monotonic effective revisions |
| Audit event / chain head / checkpoint | Dedicated audit authority; canonical operation linkage and digest, no raw content by default |
| Event stream / outbox / delivery dedup / deletion tombstone | Command infrastructure; transactional intent, ordered delivery and restore filtering |

Required indexes include session+sequence, aggregate+revision, task lease deadline, pending outbox available time, recipient+idempotency key, consent subject/purpose/recipient/session and queue state/priority/time. Uniqueness constraints enforce monotonic identities and one effective assignment. No physical ERD/schema migration is claimed; DDL must encode these relationships and validate unknown-field/foreign-key constraints before implementation acceptance.

## Atomic command and audit design

Avoid a distributed transaction between independent business/audit databases. Business/control/audit schemas reside on one PostgreSQL transactional instance initially. The command gateway invokes restricted stored procedures with no permission to directly alter the audit chain. A dedicated non-login audit owner controls an append function; no normal human/workload assumes that role. Append function is executable only within approved command procedures (use a dedicated procedure-owner chain with no direct app grant), pins schema search path and input validation. Read roles cannot invoke writes. Database superuser remains a privileged residual, not an immutable-store guarantee.

A protected command locks affected aggregate/current epoch/consent/assignment rows in fixed order; validates expected revisions, exact payload binding and expiry; allocates the canonical audit sequence/head under lock; writes state, hash-chained audit event, stream event and outbox intent; commits once. Failure rolls back all changes and returns no successful result. Canonical serialization/explicit timestamps and genesis convention are versioned before building the chain. No hash of raw guessable sensitive fields is advertised as anonymization.

Queries that disclose protected data commit a disclosure audit decision before returning permitted projection; enforce the same epoch/revision condition at materialization/serialization boundary. If control changes before delivery, suppress response and reevaluate; already sent bytes cannot be recalled. Log denied decisions if audit is healthy. When central audit fails, block protected operations and keep only narrow help/static fallback with honest local outage diagnostics.

Canonical audit event is unique on logical operation ID. Repeating identical idempotency key returns committed permitted outcome only after current read authorization; different payload yields conflict. Attempt, receipt, policy activation, security denial and access events are separate linked facts, not duplicates of the action event. Chain-head locking is acceptable for initial ten-session demo; measure contention before partitioning and never silently change chain semantics.

## Outbox and irreversible effects

A core job leases an outbox entry with generation, retrieves exact authorized payload through core, and requests dispatch authorization immediately before send. Dispatcher holds the common authorization fence while recording one-use dispatch authorization and attempt in the atomic command. This commit defines the irreversible **authorization** ordering point. Network send is outside the transaction. Revocation ordered earlier blocks authorization; revocation ordered later cannot guarantee withdrawal of an already authorized send. Worker must attempt promptly within the permit deadline or reacquire; no replay of stale permits.

After crash before/after network send, delivery is unknown until queried against simulator dedup/receipt. Never blindly resend when acceptance may have occurred. Receiver deduplicates stable action key and payload digest. External exactly-once delivery is not claimed. Generation, authorized dispatch, attempted channel, response and receipt are separately visible. Reconciliation also checks payload retention and revoked sharing before any new disclosure.

## Retention, deletion and backups

Use the requirements parameter schedule: runtime sessions/person/referral/replay seven days, plans thirty days, consent/security thirty days, audit/aggregate metadata ninety days, backups seven days. These are synthetic engineering defaults, not legal schedules. Source-controlled fixtures/manifests are separate. Redact/minimize identity references; actual login metadata has its own reviewed retention procedure before external participants.

AL3 export/delete creates a scoped job. Export filters owned/authorized records, includes provenance/unknowns and a manifest, and exposes a short-lived authenticated download; format JSON with attachment references, no third-party private content. Deletion creates durable tombstone, revokes grants/continuations and cancels pending work before purging eligible active content within 24 hours. Explain retained audit exceptions. Backup expiry completes within seven days; restore must apply latest surviving tombstones/revocations before access. Preserve the control/tombstone recovery ledger separately from data snapshots so a pre-deletion backup cannot resurrect access.

Backups combine reviewed base backups plus continuous WAL archival to encrypted separate host storage with measured lag. A sixty-second check schedule alone cannot establish a sixty-second RPO. Rebuild isolated restore target, validate timeline/schema/chain/manifest, apply current control ledger, reconcile unknown sends, then readiness. Full-host loss can lose local backup unless a separately approved recovery copy exists.

## Replay and aggregate analytics

Replay uses encrypted short-lived synthetic input snapshots, recorded model outputs and pinned deterministic artifact versions. Compare canonical deterministic outcomes; no expectation of bit-identical regenerated LLM text. Audit digests alone cannot reconstruct omitted content. Metrics projection reads approved outcome aggregates, always couples police-avoidance with safety/access/equity/unknown counts, and suppresses individual exposure and undersized groups. No identifiable HR feed, training pipeline or real community dataset exists.

[PostgreSQL continuous archiving documentation](https://www.postgresql.org/docs/current/continuous-archiving.html) is the reference for base-backup/WAL recovery; selected version and actual recovery timings remain to be verified.

> This prototype demonstrates control and containment architecture using non-clinical stub logic and synthetic data. It provides no evidence of clinical safety, triage validity, or equity performance, and must not be cited as such.
