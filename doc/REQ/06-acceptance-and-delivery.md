# Acceptance and incremental delivery

> Scope update (2026-11-04): [Decision answers](08-open-decisions.md) and [demo parameters](demo-parameters.json) establish Ottawa/Ontario context and exclude all police roles, brief sinks, connectors and partnerships from the proposed demo. Earlier police-specific descriptions below are retained only as historical source context and are superseded for implementation; they do not imply a police relationship. Source FR-C6 and AQ-9/AQ-26 are excluded by current user scope, not satisfied. Concrete defaults replace earlier open engineering choices; clinical/legal approvals and hardware-dependent checks remain unresolved.

No check in this document has been executed against an implementation. Required results are future acceptance obligations. All technical requirements are proposed and all source FR/NFR obligations retain their original status.

## Acceptance matrix

| Test group | Required evidence and negative cases | Technical requirements |
|---|---|---|
| AT-01 Scope and content | Closed demo admission, synthetic tags, no real connector secrets/tools, notice on UIs/reports, approved static content, stub promotion rejection | TR-SCP-01…05, TR-GOV-03 |
| AT-02 Actors and identity | Separate browser profiles/accounts, role-specific UIs, assignment/ownership, direct API access denial, logout/revocation, AL0…AL3, no self-approval | TR-ACT-01…03, TR-SEC-01/05, TR-GOV-01/02 |
| AT-03 Crisis journey | UC-1/2; disclosure, first-exchange role, hazard interrupt, missing/deferred fields, controlled rationale, corrections/disagreement, options and police qualifications | TR-WF-01…03, TR-LLM-02 |
| AT-04 Human operations | Ungated human request with model down, five overload states, periodic re-triage, takeover fencing, disconnect/silence, failed handoff and no system T1+ termination | TR-WF-04…06, TR-OPS-08 |
| AT-05 Consent and referral | Absent/expired/wrong-purpose/recipient/subject/session/fields/assurance consent, revocation race, duplicate/unknown delivery, receipt unavailable, carer cannot act as PID without basis | TR-WF-07, TR-SEC-02/03/06, TR-API-03/04 |
| AT-06 Plans and follow-up | UC-4/5, PID preferences, attributed conflicts, field sharing/revocation, carer outcomes, scheduled opt-in and cancellation, unknown outcome | TR-WF-08, TR-DAT-01/02 |
| AT-07 Youth | Age-uncertain, coercive guardian, discreet human-help route, guardian disclosure denials, legal stub labels; reviewed routing contract required | TR-WF-09, INV-16 |
| AT-08 Inference/contracts | Real LM Studio/Gemma identity check and proposal round trip; malformed/oversized/unknown keys, injection, claim fabrication, poisoned feeds, timeout/context overflow, nested broker bypass | TR-ARC-01/02, TR-LLM-01…05, TR-API-01/02, TR-SEC-04/08 |
| AT-09 Persistence/audit | Unique event/sequence under concurrency, digest/hash-chain validation, no unauthorized rewrite, crash recovery, outbox reconciliation, pinned deterministic replay with recorded model output | TR-DAT-01…04 |
| AT-10 Deployment/failure | Fresh install, local routing and forbidden probes, simulator isolation, startup health, candidate failure, migration/rollback, kill, audit/model/directory loss and fallback survives cluster outage | TR-OPS-01…09 |
| AT-11 Recovery/load | Isolated backup restore, deletion/revocation restored correctly, measured RPO/RTO; cold/warm latency and declared peak load including failed requests | TR-OPS-10…12 |
| AT-12 Governance/metrics | Human PR approval/checks, immutable artifact receipts, denied stub promotion, companion metrics mandatory, aggregate exposure only, incident/shadow workflow, alert visibility | TR-SEC-07, TR-GOV-01…05, TR-OPS-13 |
| AT-13 Accessibility/channels | Keyboard/screen-reader/contrast/focus checks, plain language and disclosure, EN/FR equivalents, simulated SMS/voice/mobile/relay continuity; unmet real-channel obligations visibly deferred | FR-A1/A4/A5, NFR-10…12, TR-SCP-04 |
| AT-14 Realtime governance | Direct API/job/stream bypass attempts; missing policy input; REQUIRE_HUMAN cannot execute; obligation failure; policy timeout/down/invalid signature; consent/assignment/epoch races; live restrictive activation; lost invalidation notification; stale/disconnected PEP denial; restart/rollback preserves revocations; queued work reauthorizes; audit-before-effect; human-help/static fallback survives. Measure evaluation and propagation budgets under declared load. | TR-GOV-06…12; TR-DAT-03; TR-OPS-08 |
| AT-15 Realtime security | Session/credential revocation mid-stream, forged/replayed/late events and lost notifications; direct API/internal/store/host bypass probes; SSRF/redirect/DNS targets; injection/unsafe output; artifact drift and poisoned feed; exhaustion with human-help capacity retained; scoped deterministic containment and authorized recovery. Every denied effect must remain absent. Measure denial, propagation and detection clocks separately. | TR-SEC-09…16; AT-14; runtime_security |
| AT-16 Standards and governance trace | Verify pinned editions/identifiers, applicable controls and justified exclusions; control-to-PEP/policy/test/evidence/owner mapping; expired exception denied; absent human approval blocks affected capability; no unsupported certification claim. | TR-GOV-13/14; TR-SEC-16; 09-standards-and-runtime-controls.md |
| AT-17 Actor-support agentic workflows | Execute TR-AI-12 across separate actor UIs; inspect scoped plan/tool observations and source-linked drafts; human edit/reject/approval; approval invalidated by changed payload/source; timeout/receipt recovery; cancellation and bounded delegation; no hidden authority or cross-actor leakage. | TR-AI-02…08/10/12/15 |
| AT-18 Mission-critical AI usefulness and continuity | Matched actor-only/AI-assisted scenarios, task-specific Gemma admission, seeded errors/ambiguous hazards, EN/FR and cognitive workload; zero unauthorized effects; AI unavailable/overloaded/wrong while authorized manual service continues; no unsupported clinical-benefit claim. | TR-AI-01/09/11/13/14 |


All 16 source invariants SHALL have component and deployed-system verification where applicable. Predicate fixtures do not discharge networking, timing, fallback, replay, natural-language or user-safety residuals. Use the invariant statements and verification/residual notes preserved in the complete trace. A critical containment failure blocks demo release.

## Delivery sequence

| Increment | User-visible exit | Required checks before acceptance |
|---|---|---|
| 0 — Baseline decisions | Reviewed requirements, selected local topology/stack/auth; static fallback content and local smoke path | Resolve D-01…05 to the extent required by increment 1; source conflict decisions; preserve remaining blockers. |
| 1 — Usable intake | Distinct participant/worker/operator logins, role routes, disclosure, synthetic session, human request and static fallback | AT-01/02; relevant AT-03/04/10; private demo entry. No simulated success presented as actual service connection. |
| 2 — Controlled conversation | Local Gemma proposals, deterministic stub assessment, controlled rationale, sourced synthetic directory, corrections | AT-03/08/09; broker/network enforcement; model failure leaves increment 1 usable. |
| 3 — Human handoff | Queues, context pack, worker acceptance, supervisor takeover, referral with consent and real simulator receipts | AT-04/05/07/09/10; all overload and transfer-failure cases. |
| 4 — Planning and continuation | Plan sharing, explicit continuation, follow-up inbox, outcome capture, export/deletion | AT-02/06/09/11; UC-4/5 and restore filtering. |
| 5 — Complete demo | Remaining actor consoles, governance/audit/security dashboards, incident/shadow workflows, simulated channels and all use cases | Entire matrix including AT-14…18, all invariants, source disposition review, documented limitations and human-reviewed release bundle. |

Each increment SHALL use a focused PR describing user behavior, requirements covered, checks/evidence, remaining limitations and rollback. Human review SHALL precede merge/deployment of the accepted baseline. Keep an executable smoke scenario covering participant intake → human request → assigned worker, plus fallback availability. Do not postpone all useful workflows until a separate conformance platform is finished.

## Definition of done

A demo release requires reproducible local setup, distinct role credentials, verified contracts, full workflow demonstrations, safe failure behavior, durable audit, version-pinned artifacts, meaningful negative tests and reviewed documentation. Every source requirement SHALL have an implementation disposition and evidence reference or an explicit deferred/blocked reason; the supplied trace is the planning baseline, not implementation coverage.

FRS P0 real-world approvals, clinical validity, community governance, legal/regulatory positions, nationwide languages/channels, partner contracts, production availability and real users remain outside demo acceptance. No “production ready” claim follows from completion. Changing this ceiling requires a separate source-owner/governance decision and evidence; removing a banner or configuration flag cannot authorize it.

> This prototype demonstrates control and containment architecture using non-clinical stub logic and synthetic data. It provides no evidence of clinical safety, triage validity, or equity performance, and must not be cited as such.

Actor support is a primary exit criterion: increments 2–3 SHALL include a worker’s source-linked draft/options/review workflow, bounded multi-step observation and handoff recovery, verified by AT-17/18. Containment checks alone cannot accept the agentic service functionality.
