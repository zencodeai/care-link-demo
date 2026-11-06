# Reliability, service continuity and operations

## Capability hierarchy

Continuity is defined by what the system can actually deliver, not a single green health indicator. Application/process readiness, dependency readiness, protected manual service and individual AI-function admission are distinct. A recorded request or static contact page is valuable fallback, but neither is a connected human conversation.

| Operating capability | Required dependencies | What actors can honestly expect |
|---|---|---|
| Normal protected service with AI | Actor/worker transport, current identity and authority, core/data/audit, relevant directory/service state, admitted model task | Full authorized manual workflow plus optional grounded AI assistance |
| Protected manual service, AI disabled | Same protected-service dependencies except model/runtime | Worker messaging/context/choice/consent/handoff continue within current rights; no forced acceptance of AI |
| Independent minimal help request | Direct host client/workforce entry, own durable spool and sufficiently current narrow identity trust | Opaque request recorded and possibly accepted-unconnected by eligible role-player; no history access or connection/staffing guarantee |
| Static crisis information | Independent content host and reviewed bundle, reachable network/device | Verified public information, no account/policy/model/business-store dependency |
| Offline/whole-host outage | Only public content already cached on device if available | No assured online service, stored request or staffed connection |

Protected manual service cannot bypass authorization or audit during their outage. Cached identity evidence supports only its specifically admitted bounded scope; valid-but-unexpired credentials alone do not prove current revocation. The independent help trust contract must define allowable freshness and revocation reconciliation before nonpublic acceptance is enabled. If freshness is unavailable/stale, no workforce acceptance or protected history is allowed; static information remains. Fresh login/step-up cannot be invented during identity failure.

## Failure and degradation architecture

| Failure / changed condition | Containment and service behaviour | Recovery evidence before restoring capability |
|---|---|---|
| Model/runtime unavailable, overload or wrong artifact | Disable affected tasks, fence late output, offer templates/manual service and human help | Approved model/task identity and capability evaluation, bounded queue reconciliation |
| Policy evaluator/control state unavailable or stale | Deny affected protected actions, no permissive cache; independent help/static only if their own dependencies hold | Current verified effective state and healthy enforcers |
| Canonical audit/data unavailable | No protected success/read/disclosure/dispatch; preserve supported state without claiming closure | Consistent durable recovery, audit integrity and current authority |
| Identity/provider/issuer outage | No unsupported fresh identity or raised assurance; existing grants only within current validity/freshness bounds | Verified trust/key/identity reconciliation and revocation evidence |
| Lost/replayed control or identity events | Reject/reconcile events and current-state-check every effect | Monotonic authority restored; notifications do not substitute for state |
| Directory stale/conflicting/poisoned | Mark unknown or quarantine, keep provenance and alternatives honest | Corrected reviewed source/version and current suspension state |
| Receiver/transfer failure or uncertain receipt | Retain supported session, explicit unconfirmed/unknown state, human recovery choice | Matching authorized receipt/reconciliation before any repeat disclosure |
| Worker disconnect or takeover | Preserve accountable case state, invalidate obsolete writer/agent output | Confirmed current owner and actual channel connection |
| Main edge/cluster loss | Direct host help/static routes can survive if host/network/trust/spool survive | Cluster trust/current state recovered; reconcile help without duplicates |
| Host/network/storage failure | No whole-host availability claim; previously cached public information only where usable | Host/network/storage restoration plus protected serving validation |
| Security compromise or real-data contamination | Scope-fenced deterministic containment, human incident review and safe mode as needed | Corrective evidence, current credentials/authority and authorized recovery |

No timeout/silence-based automatic termination of unresolved T1+ support is introduced. Authentication may expire and transport may fail, but service state is not thereby resolved. Human handoff changes accountable control; ending the client session is separate from ending an automated segment.

## Performance, capacity and backpressure

Partition critical service/human-help operations from ordinary domain work and optional inference/background work. Slow or saturated generation must not occupy the only path for a human request, manual message or deterministic urgent fixture response. Bound admission and work queues; return explicit busy/manual options instead of spawning unbounded inference or switching remote models. Background processing must not turn a queued consent grant into indefinite permission.

The [parameter artifact](../REQ/demo-parameters.json) provides proposed capacity/latency/kill/takeover/control/alert budgets. Source first-response, actionable-step, plan retrieval and escalation-initiation objectives are measured separately from model completion. An acknowledgement is not an actionable safety step, and queue insertion is not connected care. Evaluate warm/cold inference, EN/FR/context size, concurrent actor review/dispatch and failure cases on actual host resources. Include failures/timeouts and missing outcomes in measurements. No numerical target in this HLD is an observed throughput, clinical sensitivity or hard realtime scheduling guarantee.

Single-host power/backup/maintenance constraints prevent claiming production availability, regional redundancy or independent whole-account/DNS fallback. The local RPO/RTO goals require restored evidence while the system is operated; a periodic backup check alone does not establish them. Capacity/resources and replica choices remain deployment evidence decisions.

## Observability and accountable response

Operational telemetry exposes service capability, task/queue/handoff progress, inference saturation, desired/effective policy state, workload trust/revocation lag, denied/quarantined effects, audit integrity, outbox uncertainty, storage/backup lag and fallback content freshness. Scoped dashboards serve operator/security/governance roles; they do not grant clinical transcript access or approval. Trace correlations link service/task/decision/effect without copying raw content or tokens into logs; aggregate metrics avoid person/session identifiers and individual workforce surveillance.

Separate canonical audit truth from diagnostic logs. Diagnostic outage does not authorize work; audit failure prevents protected results. Detection, validated containment, propagation, user-visible state and operator alert clocks are distinct. Unknown health is not healthy, and an alert after a prohibited action is not prevention. Preapproved deterministic controls may deny/fence a known compromised scope; restoring access, relaxing policy or promoting recovered data needs accountable human authority and evidence. AI can draft incident/runbook context but cannot decide its own recovery permission.

Runbooks cover model/policy/audit/identity/workload trust loss, poisoned feed, credential compromise, contaminated data, overload, handoff uncertainty, cluster/host loss, backup/restore and failed release. Each defines impact, containment, retained help path, truthful communication, evidence, recovery owner and post-review. Participant safeguarding takes precedence over continuing a fictional simulation.

## Backup, quarantine and serving recovery

Backups include required business state/version evidence and integrity anchors, under dedicated access and encrypted storage. Recovery-critical consent/revocation/tombstone/hold history must be retained independently of an old business snapshot and long enough to govern every restorable copy. Separate host storage still shares disaster/root risks. Missing or stale current history is a real recovery limitation, not grounds to assume empty restrictions.

Recovery proceeds through these architectural stages:

1. **Isolate:** restore into quarantine with no actor/runtime/dispatch reader or serving authority. Validate backup origin, scope, integrity, encryption/version compatibility and completeness.
2. **Reconcile current truth:** obtain an independently trusted current control head, apply newest rights/holds/negative grants and reconcile uncertain external effects. The backup cannot attest that its own history is latest. Invalidate stale credentials, continuations, approvals and work ownership rather than resurrect them.
3. **Validate:** demonstrate audit consistency, expected recovery point, retained/deleted scope, current access denials and no duplicate effect. Report real loss/unknowns and exceptions.
4. **Approve serving:** a distinct authorized human reviews the exact recovered target/current authority evidence. Restore-worker success is not promotion permission; changed state invalidates stale approval.
5. **Promote safely:** fence obsolete serving ownership, reconcile the final authority changes and switch only the validated target. Cutover interruption stays restricted until the serving authority is reconciled. Independent help/static stay available where their own host dependencies permit.
6. **Resume by capability:** verify current identity/policy/manual smoke, reconcile queued work and admit AI functions separately. Only then show normal readiness.

Detailed cutover/storage mechanisms require implementation tests rather than a fictional distributed atomic swap. Drills verify model-down manual service, main-cluster-down direct host fallback/help, kill without losing static content, restore that preserves revocations/deletions and uncertain-send reconciliation. Whole-host/disaster recovery remains an explicit separate environment decision.

> This prototype demonstrates control and containment architecture using non-clinical stub logic and synthetic data. It provides no evidence of clinical safety, triage validity, or equity performance, and must not be cited as such.
