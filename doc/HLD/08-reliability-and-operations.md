# Reliability, capacity and operations

## Dependency-aware operation

Health distinguishes process alive, dependency ready, manual service ready and AI function admitted. Do not mark a whole session unusable merely because draft generation fails, or mark a referral ready when audit/consent is unavailable. No timeout closes unresolved support; transport loss persists state and reconnect token subject to current authorization. The static page is linked/cached as a content-only bundle in the private UI for connection loss, without caching protected session data in service workers.

| Failure | Containment and user behavior | Recovery condition |
|---|---|---|
| Runtime/LM Studio down, wrong model or saturation | Stop agent tasks, safe templates; worker manual messaging and help continue; no remote inference | Correct artifact/capability probe, bounded queue replay with current state |
| Policy evaluator/registry unavailable | Deny affected protected actions; existing static bundle and minimal help path remain | Current verified bundle/epoch acknowledged before readiness |
| Audit/data DB unavailable | No protected reads/writes or dispatch; no success acknowledgement; help spool/static information | Durable recovery, audit/epoch consistency, reconciliation before new work |
| Identity down | No fresh login/step-up; current offline-valid bounded credentials only where separately permitted; static help available | IdP restored, current entitlement/revocation synchronization |
| Lost/replayed identity/control signal | Event rejected/deduplicated; current-state checks still deny stale effects | Resume sequence/gap recovery; no permissive cache |
| Directory poisoned/stale/unavailable | Quarantine or qualify unknown; do not invent service availability | Reviewed corrected snapshot, new version and audit |
| Simulator/handoff fails or receipt missing | Stay active, show unconfirmed, worker chooses alternative; no duplicate blind send | Idempotent receipt query/reconciliation |
| Worker disconnect/takeover race | Retain assignment pending deterministic protocol; fence generation on reassignment | Authorized worker accepts and confirms; no model continuation as human |
| Cluster loss | Independent host fallback and minimal help request/spool work if host/listener survive | Restore cluster and safe control state; reconcile spool without duplicate requests |
| Whole host/network loss | Cannot guarantee online service or contact; cached static content only if already available | Host/network recovery; full external redundancy is outside demo |
| Disk full/help spool full | Reject unpersisted work honestly, preserve static content where readable | Free/restore capacity, validate audit/spool integrity |
| Security breach/real-data contamination | Fence affected workflow, stop ingestion, quarantine scope and human incident review | Approved corrective action, privacy-safe purge and independent retest |

## Performance and capacity design

Ten active UI sessions, two concurrent inference requests/eight queued are initial acceptance envelope, not measured throughput. Validate active input rate, prompt sizes, EN/FR, warm/cold model, long streams, concurrent review/dispatch, storage latency and two-release memory contention. Resource requests/limits are set from measurements after host inventory; no fabricated RAM/GPU fit claim.

Reserve separate thread/process pools and request limits for human help, session commands, inference and background jobs. A 30-second generation cannot block urgent intake. First response ≤2 s p95; first actionable step/hazard ≤5 s; provisional fixture acuity ≤90 s where interaction permits; plan ≤10 s p99; escalation initiation ≤10 s p95. Acknowledgement is not an actionable step; queue insertion is not connected care. Kill/takeover ≤2 s p95/5 s max; authorization and revocation budgets are distinct. Instrument failed/time-out requests in denominators. Hard realtime scheduling is not claimed.

## Observability and incident control

Use structured OpenTelemetry-compatible traces/logs plus a local collector, time-series store and role-scoped dashboards; select/pin implementation tooling during build. Correlate request/session/task/step/decision/action/attempt IDs without logging raw content, credentials or continuation tokens. Metrics labels exclude person/session IDs; trace evidence is access controlled. Retain operational diagnostics separately from canonical audit. Telemetry outage cannot authorize a protected effect; canonical audit outage denies it.

Dashboard panels: actor/task availability, manual versus AI readiness, inference latency/queue, handoff age/receipt, desired/actual policy epoch, enforcer lag, denials/quarantine, chain health/outbox backlog, DB/storage/backup lag, model/directory/content versions and fallback verification age. Security events reach dashboard ≤5 s, critical alert ≤30 s after validated event; containment target ≤1 s is measured separately from detection. Drift polling ≤30 s cannot be presented as instant detection. Notification means local console/operator delivery unless a reviewed external alert channel exists.

Operational runbooks specify trigger, affected capability, scoped containment, communications, preserving help, evidence, recovery gate and post-review for model failure, policy/audit down, credential compromise, poisoned feed, contaminated data, overload, partner failure, cluster/host loss, chain alarm, backup restore and incompatible release. Begin simulated serious-incident review within four hours; uncertain containment triggers restricted mode immediately. No automatic policy relaxation, model self-update or individual worker performance inference.

## Backup/restore and lifecycle drills

Base backups plus WAL archive target session RPO ≤60 s and RTO ≤300 s while running, subject to actual restored evidence. Test loss at known committed sequence, validate restored sequence/chain, replay latest control ledger/tombstones, reconcile in-flight simulator sends, prove revoked access remains blocked, and expose actual recovery time and lost-state count. Do not claim 60-second RPO from one-minute cron scheduling. Encrypt backups and restrict decryption credentials; same-host copy cannot prove disaster recovery. Seven-day backup expiry and audit retention exceptions remain visible.

Monthly scheduled fallback/kill drills from source intent become a demo runbook obligation while the project is operated; also execute before release and after relevant changes. Drill with Kubernetes stopped and inference/policy/database unavailable; verify content correctness and minimal help acknowledgements independently. A repeatable single-host demonstration does not satisfy source account/DNS/region independence or monthly production SLOs.

> This prototype demonstrates control and containment architecture using non-clinical stub logic and synthetic data. It provides no evidence of clinical safety, triage validity, or equity performance, and must not be cited as such.
