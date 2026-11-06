# Canonical audit, lifecycle, rights and aggregate evidence

## Audit append and checkpoints

Accepted local domain/control transitions, disclosure decisions and reliable work intent append canonical audit inside the same PostgreSQL transaction. Audit authority is a narrowly callable dedicated writer, not a remote async logging acknowledgement. canonical UNIQUE(operation_id) records one logical command outcome; attempts, observations, receipts and security events are linked records with separate event IDs. Projection reads allocate a logical disclosure operation. Denials with available audit are durable even though domain work is rejected; when audit itself fails, deny private success and use redacted local diagnostics pending reconciliation.

Audit entry hash=`SHA256(previous_hash || canonical_event_without_hash_signature)` under an explicitly versioned canonical JSON encoding (sorted keys, UTF-8, finite integers, no floats for authoritative values). Record input/output digests, actor/workload/purpose, operation/trace/resource references, decision/reasons/obligations, policy/source/model/prompt versions and actual outcome. No raw conversation/prompt/hidden reasoning by default. Digests/linkable references remain access-controlled sensitive metadata.

Lock audit head after all authority/domain locks, allocate sequence and append event+new head atomically. Sequence never reused; aborted append does not publish a head. Checkpoint every 60seconds target to separately credentialled host journal: stream/sequence/hash, schema/encoding version, previous checkpoint and signature. Chain validation detects ordinary unauthorized mutation; same-host root/owner can defeat local controls. Retain partition boundary manifests before approved90-day pruning; pruning records first/last sequence/hash/checkpoint and retained exceptions, never silently restarts a chain. Checkpoint is integrity evidence, not independent disaster transparency.

## Copy inventory and retention algorithm

Every persisted person-purpose copy registers content locator, classification, subject/session parents, purpose, authoritative anchor, duration, source/dependent links and encryption custody. Include plan snapshots, drafts, replay snapshots, temporary export, projections/caches, simulator packages and backups. No unregistered long-lived copy. Cache is bounded transient and invalidated on rights changes; private browser caches are disabled. Reference-only audit/control records retain minimized dependency-bound exceptions.

| Class | Anchor and existing duration | Eligibility condition |
|---|---|---|
| Session/person/carer purpose | explicit closure of last relevant parent +7days | All relevant parents closed; unresolved parent remains anchor_pending |
| Referral/receipt/package | later parent closure and terminal/reconciled delivery +7days | Unknown delivery not automatically terminal; review unresolved copy separately |
| Plan/justified snapshot | explicit retirement +30days | Active plan remains active; PID deletion uses faster existing rights target |
| Consent content/history | later relevant parent closure and expiry/revoke +30days | Minimal negative history retained while dependent grants/copies/backups exist |
| Replay | capture +7days | Recorded observations only; encryption and access scope |
| Security / audit metadata | event +30/+90days | Explicit held exceptions and chain boundary proof |
| Aggregates | reporting interval close +90days | Suppression/purpose controls; no individual exposure records |
| Backup | immutable capture +7days | Restore/retry cannot renew expiry |
| Actual account/linkage metadata | separate minimum-needed schedule | Exact periods unresolved; no synthetic7day default; block account-retention acceptance pending schedule |
| Recovery/hold/approval restrictions | until every restorable copy/dependent grant accounted for | Minimize linkability; accountable dependency review, not infinite unexamined TTL |

Purge job claims bounded batch (proposed 100 copies) then locks control/subject/lifecycle graph. Verify current anchor, dependency closure, hold scope, rights/tombstone, expiry and current policy. Detect graph cycles/unclassified child→review_needed; never infer eligible. Ordinary cleanup cannot delete active parent-dependent content. A longer plan uses independently justified minimized snapshot or explicit source-unavailable marker; it cannot dereference purged session data silently. Authenticated engineering hold/release is journalled; hold at eligibility check wins before deletion. A hold arriving after physical deletion is recorded as too late, never creates data. Hold expiry/release reevaluates, does not automatically purge without current authorization.

## Rights requests and exports

AL3 own-subject proof, post-cooling fresh MFA and exact scope are required for export/delete/link. Link identity is not enabled by this design; explicit new reviewed ceremony needed. For deletion: requested→eligible or held→active_purged→backup_pending→completed/completed_with_exceptions, with failed/reconciliation_needed branches. If no backup/dependent exception remains, active_purged may complete directly. For export: requested→eligible→completed only after scoped materialization and canonical audit; it never invokes purge. A completed export still requires fresh authorized download and expires independently. Show requested scope, affected copies, holds/retained reasons, progress and deadlines. Existing eligible active-delete target24hours and full backup expiry7days are targets, not proof/legal approval. Unknown delivery/dependency/hold may produce reported partial completion rather than false success.

Deletion first appends durable restrictive tombstone/intent outside business restore, denies future disclosure and cancels pending jobs/reviews, then schedules per-copy minimization. Ordinary DB DELETE/file unlink is not physical erasure from WAL/filesystem/snapshots. Backup catalog tracks immutable capture, expiry, encryption object/key and deletion coverage; restore always reapplies current tombstones/revocations/holds. Verified retained exceptions stay documented. No expiry extension caused by export/restore.

Export materialization is a scoped encrypted purpose copy with proposed 15-minute download expiry and one-use download authorization, no public URL. Regenerate/check current permitted fields at download; cannot return other-author private reports merely because target subject is mentioned. Large result is bounded into explicit pages/chunks with a manifest; refuse if configured bounds cannot safely cover it rather than silently dropping records. Download must reauthorize and audit before bytes, then expire temporary content/key per copy inventory. Cancellation/revocation blocks later download; delivered bytes cannot be recalled.

## Metrics, audit grants and evaluation

Auditor metadata access requires exact purpose/time-window grant; content access requires additional scoped grant≤15minutes and field filtering. Operator has no standing audit-store/transcript browse. Query allowlist only action/time/scoped references with page limits; exports share current authorization. Log no tokens, raw prompts/text or arbitrary unbounded labels. Alert IDs correlate to protected canonical records where available without copying payloads.

Metric definitions version denominator, period, cohort, unknown/missing counts and suppression. Police-avoidance measures are never serialized alone; safety/access/equity companions are required in UI/API/export even when unknown. This is synthetic service-outcome analysis, never police integration or policing profiles. Exposure is aggregate only; individual worker/session exposure keys and exports are absent. Minimum cohort30; below threshold suppress all comparable sensitive values and complementary/differencing views, not return zero. Exact count disclosure and repeated-query combinations require disclosure review; no claim this alone provides formal privacy. Synthetic disparity alert5 percentage points is a fixture alert, not clinical/equity evidence.

Evaluate matched actor-only versus assisted cases with counterbalanced order and independently reviewed rubric: actionable verified option, meaningful human connection, critical/noncritical fact accuracy, omission, unsupported claims, consent/handoff correctness, editing/rejection, workload, client agency, EN/FR/accessibility and failure distributions. Preserve raw counts/missingness and versioned scenario evidence; do not train from feedback. Seeded critical errors/unauthorized effects allowed0; noncritical summary accuracy95% target. No clinical noninferiority margin or real clinical benefit inferred.
