# Actors, access and workflows

> Scope update (2026-11-04): [Decision answers](08-open-decisions.md) and [demo parameters](demo-parameters.json) establish Ottawa/Ontario context and exclude all police roles, brief sinks, connectors and partnerships from the proposed demo. Earlier police-specific descriptions below are retained only as historical source context and are superseded for implementation; they do not imply a police relationship. Source FR-C6 and AQ-9/AQ-26 are excluded by current user scope, not satisfied. Concrete defaults replace earlier open engineering choices; clinical/legal approvals and hardware-dependent checks remain unresolved.

Sources: FRS §§4, 6, 10; HLD §§2.3, 8, 9; INV-2/7/14/15/16. All humans are project staff or authorized test participants exercising synthetic scenarios.

## Agentic assistance in actor workflows

The service model includes role-scoped AI assistants that gather permitted context, retrieve verified options, draft work, propose next steps and track authorized outcomes. Human actors retain service responsibility; deterministic controls retain decision/execution authority. The [actor-assistance matrix and bounded task lifecycle](10-agentic-ai-and-service-model.md) are part of these requirements (TR-AI-01…15), including worker review, manual continuity and an end-to-end referral scenario. Agentic AI is not limited to a participant chatbot or an output filter.

## Role requirements

**TR-ACT-01.** Each actor instance SHALL have a distinct account, credential, login session and audit identity. A role change SHALL require authorization and a new explicitly scoped session; changing a UI dropdown cannot confer privileges. Concurrent browser profiles SHALL exercise separate identities. Multiple role accounts for one tester SHALL not satisfy independent approval requirements. Verify identity and cross-role/cross-session denial tests.

| Actor / principal | Dedicated UI and workflow | Permitted scope / boundary |
|---|---|---|
| Carer participant | Carer intake, coaching, service choice, own attributed reports, scoped consent, follow-up | Own session and specifically shared plan fields; cannot claim PID consent or obtain private PID/youth content by relationship alone. |
| PID participant | PID-led intake, own preferences, crisis plan, field sharing/revocation, correction, discreet help | Own synthetic record subject to operation assurance; carer assertions remain attributed. |
| Professional participant | Professional intake and attributed observations | Participant scope; selecting professional does not create workforce authority. |
| Crisis worker | Assigned queue, context pack, human conversation, editable summary/referral draft, accept handoff | Assigned sessions only. Takes actions under own identity; cannot retroactively turn agent proposals into human authorization. |
| Supervisor | Queue operations, scoped observe/interrupt/takeover, aggregate exposure | Explicit observation/takeover scopes; no individual exposure reporting. |
| MCRT / navigator role-player | Simulated service intake inbox, accept/reject/partial receipt/status | Only consented referral fields for own simulated service; no general conversation access. Community navigator is a receiving-service specialization. |
| Operator / SRE | Health dashboard, operating-state controls, kill/rollback request | No standing session, audit-store or database read; can propose config, cannot approve own change. |
| Governance reviewer | Registry, proposed changes, evidence and approval/rejection | No normal conversation access; records class-specific human reviews. Clinical, equity, privacy, Indigenous governance and security reviews are distinct responsibilities. |
| Auditor / equity analyst | Scoped audit search, aggregate metrics and evidence export | Read-only, time bounded, content only by explicit agreed scope; no writes. |
| Security reviewer | Security events, quarantine, controlled adversarial runs | Separate security scopes; no default conversation browsing. |
| Runtime / agent | No human login UI; operational status in operator UI | Workload identity, proposal only; no participant or worker impersonation. |
| Platform services / CI deployer | Service health and deployment logs | Unique least-privilege workload credentials; deployer cannot read business stores. |

**TR-ACT-02.** SHALL enforce object ownership, assignment, purpose and field filtering at API/repository boundaries on every read/write, not only in UI routes. Worker reassignment and revoked sharing SHALL take effect on subsequent access and live subscriptions. Verify direct HTTP requests and existing stream revocation.

**TR-ACT-03.** SHALL implement prototype OIDC/MFA and workforce separation, with source assurance levels AL0 continuation, AL1 possession proof, AL2 reauthentication, AL3 step-up/cooling-off. Exact TTLs, cooling-off duration and provider remain D-03. Metadata SHALL never increase assurance. Verify expiry, replay, logout, account revocation and step-up negatives. Participant access identity is necessary even where the business session contains no synthetic PID identifier.

## Participant journey and state

**TR-WF-01.** Before assessment, SHALL disclose AI identity, non-clinical demo status, confidentiality limits, channel/language and role; collect user-provided jurisdiction and record unknown values. Source disclosure limit is 60 text words or 30 seconds speech. Persistent demo banner and per-turn labels SHALL not be mistaken for clinical content. Verify each role and supported language.

**TR-WF-02.** Each turn SHALL evaluate the synthetic immediate-hazard interrupt before optional assessment or model generation; preserve captured/unknown/deferred assessment fields, attributed conflict and corrections. Stub tier and escalation decisions SHALL be deterministic, versioned and marked NON_CLINICAL. Model confidence SHALL never serve as calibrated clinical confidence. Verify hazard, unknown, disagreement and conflicting-report fixtures.

**TR-WF-03.** SHALL present controlled rationale, uncertainties, source-qualified options, police-involvement qualifications and a named alternative or explicit absence. Correction, disagreement, declining a service and choosing another SHALL be separate logged actions. None cancels mandatory human escalation or accompaniment. Verify those actions independently.

**TR-WF-04.** “Get me a human” SHALL bypass model generation, assessment completion, consent-to-referral and capability budgeting for optional tools. Session states SHALL distinguish active, human-requested, queued, worker-assigned, handoff-pending, human-controlled, degraded and ended. Only user choice or confirmed handoff ends unresolved T1+ support. Disconnect/silence is a transport state, not a resolution. Verify refresh, reconnect, duplicate events and failure during each state.

**TR-WF-05.** Queues SHALL represent normal, elevated-load, severe-load, partner-unavailable and regional-outage states, with explicit messaging, uncertainty, priority, re-triage schedule and supervisor alerts. Stub scheduling values require declared fixture configuration; unknown partner availability SHALL not imply imminent connection. Verify all five states and deterioration while waiting.

**TR-WF-06.** Handoff SHALL reserve/assign a worker, prepare the authorized context pack, obtain worker acceptance, transfer control atomically and record completion. Failed/dropped transfer SHALL preserve active support. Supervisor takeover SHALL fence pending agent responses so stale output is never delivered after human ownership. Verify racing worker acceptance, agent output, user disconnect and takeover.

**TR-WF-07.** Referral SHALL preview recipient, purpose and selected fields, record qualifying consent, recheck authorization/consent at execution, send only to a sourced simulator and track generation, attempt, channel and receipt separately. Timeout means unknown delivery, not failure or confirmed receipt. Reconcile before retry; deduplicate with a stable idempotency key. Verify consent revocation races and partial acceptance.

**TR-WF-08.** Crisis plans SHALL support PID-led preferences, author/date/verification/dispute per field, per-person sharing, revocation, and human review of safety-relevant conflicts. Follow-up SHALL require separate contact consent, use the source 24–72-hour window, and support cancel/opt-out; demo delivery uses an internal inbox and controllable clock. Carer support SHALL be a first-class outcome. Verify UC-4/5 and cancellation before delivery.

**TR-WF-09.** Youth/age-uncertain fixtures SHALL request qualified human help, enforce documented disclosure basis and expose discreet private help every flagged turn where the channel permits. No guardian auto-access. Until reviewed youth-routing and legal-content contracts exist, mark legal rules stubbed and integrations blocked. Verify coercive guardian and cross-account disclosure attempts.

> This prototype demonstrates control and containment architecture using non-clinical stub logic and synthetic data. It provides no evidence of clinical safety, triage validity, or equity performance, and must not be cited as such.
