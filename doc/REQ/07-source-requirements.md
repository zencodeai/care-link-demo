# Complete source requirement trace

> Scope update (2026-11-04): [Decision answers](08-open-decisions.md) and [demo parameters](demo-parameters.json) establish Ottawa/Ontario context and exclude all police roles, brief sinks, connectors and partnerships from the proposed demo. Earlier police-specific descriptions below are retained only as historical source context and are superseded for implementation; they do not imply a police relationship. Source FR-C6 and AQ-9/AQ-26 are excluded by current user scope, not satisfied. Concrete defaults replace earlier open engineering choices; clinical/legal approvals and hardware-dependent checks remain unresolved.

Source: curated `care-link/model/requirements/*.json`, backed by FRS v1.1. All 114 source statements and their available acceptance criteria are preserved below. Original source priorities/modalities are not demo delivery priority. All evidence status: **not implemented / not assessed in this task**. Trace links locate the proposed technical treatment; they are not proof of coverage.

## Demo disposition rules

- FR-A: closed participant access with anonymous synthetic business persona; exercise channels internally. Live carrier/mobile-store/interpretation coverage and third-party accessibility acceptance remain deferred.
- FR-B: implement assessment and escalation mechanisms using deterministic non-clinical fixtures. Clinical authorship, thresholds and accuracy remain blocked.
- FR-C: synthetic directory and network simulators; real coverage, partner schema agreements and real transfer acceptance deferred.
- FR-D: stub coaching and synthetic plans/follow-up; real clinician/community-authored content and stress validation deferred.
- FR-E: routing preference and audit mechanisms with synthetic cohorts; genuine community co-design, governance approval and measured equity remain deferred.
- FR-F/G: role-played human consoles and operating states; no actual contracted staffing or genuine response-time guarantee.
- FR-H/I: implement enforcement mechanisms and legally labelled stubs; real legal bases, retention approvals, Indigenous agreements and youth rules remain unresolved.
- FR-J/L: structural controls and adversarial tests required for demo, with residual language/security limitations recorded; no universal proof claimed.
- FR-K: synthetic outcomes, incident and metrics mechanisms only; real safety baselines and public reporting obligations deferred.
- NFR: measure locally where meaningful; production SLOs, regulatory determinations, independent audits and real-user usability evidence are not established.

## FR-A1 — Multi-channel access with mid-session continuity

Source: FRS v1.1 §6.1. Priority: P1; modality: SHALL.

The system SHALL accept contact via voice, SMS, web chat, and mobile application, and SHALL preserve session state when a user changes channel mid-session.

Source acceptance:

- A session begun on SMS and continued in-app retains assessment state, crisis plan context, and conversation history without the user repeating information.

Proposed requirement families: TR-ACT-01…03; TR-WF-01; TR-SEC-05; TR-SCP-04. Acceptance groups: AT-01/02/03/13.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-A2 — Fully anonymous, account-free operation

Source: FRS v1.1 §6.1. Priority: P0; modality: SHALL.

The system SHALL be fully functional without account creation, identity verification, or payment.

Source acceptance:

- All crisis-path functions are reachable in an anonymous session.
- No function required for OBJ-1 is gated behind sign-in.

Proposed requirement families: TR-ACT-01…03; TR-WF-01; TR-SEC-05; TR-SCP-04. Acceptance groups: AT-01/02/03/13.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-A3 — Jurisdiction determination before recommendation

Source: FRS v1.1 §6.1. Priority: P0; modality: SHALL.

The system SHALL determine the applicable jurisdiction (province/territory, municipality, and Indigenous community where applicable) from user-provided or explicitly consented location data.

Source acceptance:

- Jurisdiction is established before any pathway recommendation is issued.
- If it cannot be established, the system says so and asks.

Proposed requirement families: TR-ACT-01…03; TR-WF-01; TR-SEC-05; TR-SCP-04. Acceptance groups: AT-01/02/03/13.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-A4 — English/French parity plus interpretation coverage

Source: FRS v1.1 §6.1. Priority: P0; modality: SHALL.

The system SHALL provide functionally equivalent service in English and French, and SHALL support interpretation or translation for at least the ten highest-demand non-official languages per deployment region, plus Indigenous languages where local services exist.

Source acceptance:

- Independent review confirms no material capability gap between EN and FR.
- Language coverage list is configurable per region.

Proposed requirement families: TR-ACT-01…03; TR-WF-01; TR-SEC-05; TR-SCP-04. Acceptance groups: AT-01/02/03/13.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-A5 — WCAG 2.2 AA and low-bandwidth accessibility

Source: FRS v1.1 §6.1. Priority: P0; modality: SHALL.

The system SHALL conform to WCAG 2.2 Level AA and SHALL support screen readers, TTY/IP relay, plain-language mode, and SMS-only low-bandwidth operation.

Source acceptance:

- Third-party accessibility audit passes.
- Full triage and pathway recommendation are achievable over SMS alone.

Proposed requirement families: TR-ACT-01…03; TR-WF-01; TR-SEC-05; TR-SCP-04. Acceptance groups: AT-01/02/03/13.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-A6 — Early role determination (PID / carer / professional)

Source: FRS v1.1 §6.1. Priority: P1; modality: SHALL.

The system SHALL establish within the first exchange whether the user is the PID, a carer, or a professional, and SHALL adapt its interaction mode accordingly.

Source acceptance:

- Role is captured or explicitly marked unknown before assessment proceeds.
- Role can be corrected at any time.

Proposed requirement families: TR-ACT-01…03; TR-WF-01; TR-SEC-05; TR-SCP-04. Acceptance groups: AT-01/02/03/13.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-A7 — Upfront AI/limits-of-confidentiality disclosure

Source: FRS v1.1 §6.1. Priority: P1; modality: SHALL.

The system SHALL disclose, before assessment begins, that it is an AI agent, what it can and cannot do, and the limits of confidentiality.

Source acceptance:

- Disclosure is delivered in plain language in the user's channel and language, in under 30 seconds of speech or 60 words of text, and is retrievable on request.

Proposed requirement families: TR-ACT-01…03; TR-WF-01; TR-SEC-05; TR-SCP-04. Acceptance groups: AT-01/02/03/13.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-A8 — Low-friction session/crisis-plan resume

Source: FRS v1.1 §6.1. Priority: P2; modality: SHOULD.

The system SHOULD allow a returning user to resume a prior session or retrieve a stored crisis plan using a low-friction credential that does not require full identity verification.

Source acceptance:

- Resume succeeds within 10 seconds; anonymous sessions are never auto-linked (see FR-H2).

Proposed requirement families: TR-ACT-01…03; TR-WF-01; TR-SEC-05; TR-SCP-04. Acceptance groups: AT-01/02/03/13.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-B0 — Immediate-hazard interrupt ahead of full assessment

Source: FRS v1.1 §6.2. Priority: P0; modality: SHALL.

At every interaction turn, the system SHALL first detect information indicating a possible medical emergency, active violence, fire, immediate environmental danger, or inability of the user to remain safely engaged. It SHALL initiate the applicable emergency guidance and human-escalation protocol without waiting for completion of the full assessment.

Source acceptance:

- Test scenarios containing an immediate hazard trigger the interrupt within 5 seconds of receipt and before non-essential assessment questions.

Proposed requirement families: TR-WF-02/03; TR-LLM-02; TR-API-01. Acceptance groups: AT-03/08.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-B1 — Structured conversational risk assessment

Source: FRS v1.1 §6.2. Priority: P0; modality: SHALL.

The system SHALL conduct a structured conversational assessment covering, at minimum: imminent danger to self or others; suicidal ideation, plan, intent and access to means; substance involvement; medical emergency indicators; presence and current use or threatened use of weapons; presence of children or other dependants; PID history, diagnosis if known, known triggers, and conflicting reports.

Source acceptance:

- Required elements are captured, explicitly recorded as unknown, or deferred because FR-B0 has triggered.
- A provisional tier may be assigned before completion; any missing safety-critical elements remain visible and trigger continued assessment or human review.

Proposed requirement families: TR-WF-02/03; TR-LLM-02; TR-API-01. Acceptance groups: AT-03/08.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-B2 — Documented, versioned, clinician-authored tier set

Source: FRS v1.1 §6.2. Priority: P0; modality: SHALL.

The system SHALL classify each situation into a documented, versioned, clinician-authored tier set.

Source acceptance:

- Tier definitions exist as a controlled artefact with named clinical authorship and version history.
- Every assignment records the tier-set version used.

Proposed requirement families: TR-WF-02/03; TR-LLM-02; TR-API-01. Acceptance groups: AT-03/08.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-B3 — Medical emergency vs. psychiatric distress routing

Source: FRS v1.1 §6.2. Priority: P0; modality: SHALL.

The system SHALL distinguish **medical emergency** from **psychiatric distress**, directing the former to the EMS pathway through user action or qualified human authorization, and never defaulting the latter to a police pathway.

Source acceptance:

- Test suite of medical-emergency scenarios presents the EMS pathway and initiates human escalation in 100% of cases without autonomous agent contact.
- Test suite of pure psychiatric distress scenarios produces zero unprompted police recommendations.

Proposed requirement families: TR-WF-02/03; TR-LLM-02; TR-API-01. Acceptance groups: AT-03/08.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-B4 — Controlled rationale with user correction/disagreement rights

Source: FRS v1.1 §6.2. Priority: P0; modality: SHALL.

The system SHALL present a concise, controlled rationale derived from the structured assessment record: its provisional conclusion, the reported factors that materially affected it, missing information, uncertainty, and the recommended next action. The user SHALL be able to correct facts, record disagreement, decline a proposed service, or select another available pathway. User disagreement SHALL NOT suppress mandatory human escalation, continuing support, or reassessment.

Source acceptance:

- Every assignment surfaces the controlled rationale without unsupported inference or hidden model reasoning.
- Separate actions exist for correcting information, disagreeing with the assessment, declining the recommendation, and selecting an alternative; each is logged.

Proposed requirement families: TR-WF-02/03; TR-LLM-02; TR-API-01. Acceptance groups: AT-03/08.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-B5 — Continuous re-assessment during a session

Source: FRS v1.1 §6.2. Priority: P1; modality: SHALL.

The system SHALL continuously re-assess during a session; tiers SHALL be able to escalate or de-escalate and recommendations SHALL update accordingly.

Source acceptance:

- Re-assessment triggers on new risk-relevant information and on a defined interval.
- Tier changes are logged with cause.

Proposed requirement families: TR-WF-02/03; TR-LLM-02; TR-API-01. Acceptance groups: AT-03/08.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-B6 — No tier/score presented as clinical determination

Source: FRS v1.1 §6.2. Priority: P0; modality: SHALL.

The system SHALL NOT present any tier, score, or assessment as a clinical determination. All output SHALL be labelled as decision support.

Source acceptance:

- No user-visible or referral-visible artefact uses diagnostic or determinative language.
- Reviewed by Clinical Safety Lead.

Proposed requirement families: TR-WF-02/03; TR-LLM-02; TR-API-01. Acceptance groups: AT-03/08.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-B7 — Escalate on low confidence rather than guess

Source: FRS v1.1 §6.2. Priority: P1; modality: SHALL.

The system SHALL flag low confidence explicitly and SHALL escalate to a human rather than guess (see FR-F2).

Source acceptance:

- Confidence below the configured threshold produces escalation, not a recommendation.

Proposed requirement families: TR-WF-02/03; TR-LLM-02; TR-API-01. Acceptance groups: AT-03/08.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-B8 — Incorporate existing crisis plan into assessment

Source: FRS v1.1 §6.2. Priority: P2; modality: SHOULD.

The system SHOULD incorporate an existing crisis plan (FR-D4) into assessment, weighting the PID's own documented preferences and history.

Source acceptance:

- Where a crisis plan exists, its content demonstrably influences the recommended pathway.

Proposed requirement families: TR-WF-02/03; TR-LLM-02; TR-API-01. Acceptance groups: AT-03/08.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-C1 — Jurisdiction-specific non-police service directory

Source: FRS v1.1 §6.3. Priority: P0; modality: SHALL.

The system SHALL maintain a jurisdiction-specific directory of non-police response options, including mobile crisis teams, 988 and provincial crisis lines, Indigenous-led services, youth services, community-specific and faith-based services, walk-in urgent mental health clinics, safe beds, sobering centres, warm lines, and peer respite.

Source acceptance:

- Directory coverage verified per deployment region before launch.
- Records carry a last-verified timestamp.

Proposed requirement families: TR-WF-03/06/07; TR-API-04; TR-DAT-01. Acceptance groups: AT-03/04/05/08.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-C2 — Real operating envelope per service, no inferred availability

Source: FRS v1.1 §6.3. Priority: P0; modality: SHALL.

For each service the system SHALL hold its real operating envelope: hours, catchment boundary, current availability or wait time where obtainable, age limits, intoxication and weapons exclusion criteria, and whether it attends independently of police. Unknown or stale availability SHALL be displayed as unknown, never inferred.

Source acceptance:

- No recommendation is issued citing availability data older than the configured freshness threshold without an explicit staleness warning.

Proposed requirement families: TR-WF-03/06/07; TR-API-04; TR-DAT-01. Acceptance groups: AT-03/04/05/08.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-C2a — Directory field provenance and freshness classes

Source: FRS v1.1 §6.3. Priority: P0; modality: SHALL.

Each service-directory field SHALL identify its authoritative source, verification owner, verification method, last-verified time, freshness class, and correction pathway. Structural, operational, near-real-time, and event-specific data SHALL have separate freshness rules.

Source acceptance:

- Records lacking required provenance or exceeding the applicable freshness threshold are not represented as current.
- Critical inaccuracies can be suspended within *[target]* minutes of confirmation.

Proposed requirement families: TR-WF-03/06/07; TR-API-04; TR-DAT-01. Acceptance groups: AT-03/04/05/08.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-C2b — Directory operating states without invented availability

Source: FRS v1.1 §6.3. Priority: P0; modality: SHALL.

The system SHALL support normal operations, temporary closure, regional outage, holiday-hours, severe-weather, API failure, and conflicting-source states without inventing service availability.

Source acceptance:

- Test cases for every directory state produce accurate user-visible qualification and an approved fallback.

Proposed requirement families: TR-WF-03/06/07; TR-API-04; TR-DAT-01. Acceptance groups: AT-03/04/05/08.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-C3 — Never "911 or nothing"

Source: FRS v1.1 §6.3. Priority: P0; modality: SHALL.

The system SHALL present the recommended pathway with expected time-to-response, and SHALL simultaneously state the fallback if that service is unavailable. The user SHALL never be left with "911 or nothing."

Source acceptance:

- Every T1–T2 recommendation includes at least one named alternative or an explicit statement that none exists, plus what to do in that case.

Proposed requirement families: TR-WF-03/06/07; TR-API-04; TR-DAT-01. Acceptance groups: AT-03/04/05/08.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-C4 — Consent-gated structured referral to integrated intake

Source: FRS v1.1 §6.3. Priority: P1; modality: SHALL.

Where a receiving service supports integrated intake, the system SHALL transmit a consent-gated structured referral containing: assessment summary, location and access instructions, known triggers, de-escalation preferences, medications, language and interpretation needs, and dependants present.

Source acceptance:

- Referral schema validated with at least one MCRT partner.
- Transmission blocked absent recorded consent.

Proposed requirement families: TR-WF-03/06/07; TR-API-04; TR-DAT-01. Acceptance groups: AT-03/04/05/08.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-C5 — Warm transfer with confirmed handoff

Source: FRS v1.1 §6.3. Priority: P0; modality: SHALL.

The system SHALL perform a warm transfer to a human service rather than supplying a phone number, wherever the receiving service supports it; SHALL confirm the handoff succeeded; and SHALL remain in session if it fails.

Source acceptance:

- Handoff outcome is recorded for 100% of transfers.
- Failed transfers return the user to an active supported session, not a dead end.

Proposed requirement families: TR-WF-03/06/07; TR-API-04; TR-DAT-01. Acceptance groups: AT-03/04/05/08.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-C6 — Minimized de-escalation brief when police are unavoidable

Source: FRS v1.1 §6.3. Priority: P0; modality: SHALL.

Where police involvement becomes unavoidable, the system SHALL, where consent and law permit, generate a minimized de-escalation brief stating that this is a mental health call and containing only individually consented fields such as PID name and pronouns, known triggers, sensory sensitivities, communication needs, and carer contact. Generation, transmission attempt, transmission channel, and confirmed receipt where supported SHALL be logged separately.

Source acceptance:

- Brief generation succeeds in 100% of eligible test pathways.
- Transmission is attempted only through an approved channel; the system never represents generation as confirmed receipt.
- Each optional field is consent-gated.

Proposed requirement families: TR-WF-03/06/07; TR-API-04; TR-DAT-01. Acceptance groups: AT-03/04/05/08.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-C7 — Pathway outcome recording for evaluation

Source: FRS v1.1 §6.3. Priority: P1; modality: SHALL.

The system SHALL record the outcome of every pathway it recommends or initiates, for evaluation under FR-K.

Source acceptance:

- Outcome capture rate ≥ *[target]* of sessions, via follow-up (FR-D5) or partner data exchange.

Proposed requirement families: TR-WF-03/06/07; TR-API-04; TR-DAT-01. Acceptance groups: AT-03/04/05/08.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-C8 — Systemic service-gap reporting

Source: FRS v1.1 §6.3. Priority: P2; modality: SHOULD.

The system SHOULD detect and surface systemic gaps — repeated unavailability of a service, catchment holes, hours gaps — as reportable intelligence to funders and health authorities.

Source acceptance:

- Quarterly gap report produced automatically.

Proposed requirement families: TR-WF-03/06/07; TR-API-04; TR-DAT-01. Acceptance groups: AT-03/04/05/08.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-D1 — Real-time de-escalation coaching

Source: FRS v1.1 §6.4. Priority: P0; modality: SHALL.

The system SHALL deliver real-time de-escalation coaching in short, concrete, actionable steps suited to a person under acute stress — covering tone, positioning, phrasing, what not to say, and reduction of environmental stimulation.

Source acceptance:

- Guidance units are ≤ *[N]* words, one action each.
- Content clinician-authored and versioned.
- Usability-tested under simulated stress.

Proposed requirement families: TR-WF-08; TR-DAT-01/02. Acceptance groups: AT-06/13.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-D2 — Continuous accompaniment through the event

Source: FRS v1.1 §6.4. Priority: P0; modality: SHALL.

The system SHALL support continuous accompaniment ("stay on the line") through the event, tolerating silence and prompting periodically without pressure.

Source acceptance:

- Session persists through ≥ *[N]* minutes of user silence without termination or escalation-by-timeout.

Proposed requirement families: TR-WF-08; TR-DAT-01/02. Acceptance groups: AT-06/13.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-D3 — Carer safety coaching

Source: FRS v1.1 §6.4. Priority: P0; modality: SHALL.

The system SHALL coach carer safety, including when to leave the room, how to protect other household members, and how to disengage.

Source acceptance:

- Carer-safety guidance is offered proactively at T2 and above, not only on request.

Proposed requirement families: TR-WF-08; TR-DAT-01/02. Acceptance groups: AT-06/13.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-D4 — Consented per-PID crisis plan with attributed fields

Source: FRS v1.1 §6.4. Priority: P1; modality: SHALL.

The system SHALL maintain, with consent, a crisis plan per PID containing: early warning signs, previously effective strategies, preferred responders, medications and prescriber, advance wishes regarding hospitalization and police, emergency contacts, and substitute decision-maker. Every field SHALL retain author, date, consent status, verification status, and disputed status. It SHALL be retrievable in under 10 seconds during a crisis.

Source acceptance:

- Retrieval latency measured under load.
- PID-authored preferences govern where legally and clinically applicable.
- Conflicting factual reports remain attributed rather than silently resolved; safety-relevant conflicts trigger human review.

Proposed requirement families: TR-WF-08; TR-DAT-01/02. Acceptance groups: AT-06/13.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-D5 — Post-crisis follow-up within 24–72 hours

Source: FRS v1.1 §6.4. Priority: P1; modality: SHALL.

The system SHALL offer post-crisis follow-up to the carer within 24–72 hours, covering debrief, validation, and navigation to next steps (primary care, psychiatry referral, case management, respite, income and housing supports).

Source acceptance:

- Follow-up offered in ≥ 95% of eligible sessions where contact is consented.

Proposed requirement families: TR-WF-08; TR-DAT-01/02. Acceptance groups: AT-06/13.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-D6 — Non-crisis capability building and legal-rights education

Source: FRS v1.1 §6.4. Priority: P2; modality: SHOULD.

The system SHOULD provide non-crisis capability building: rehearsal and simulation of crisis conversations; education on the applicable Mental Health Act, rights, and what actually happens if police attend.

Source acceptance:

- Rehearsal module available in each deployment jurisdiction with jurisdiction-correct legal content, reviewed by legal counsel.

Proposed requirement families: TR-WF-08; TR-DAT-01/02. Acceptance groups: AT-06/13.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-D7 — Carer distress/burnout detection with first-class support

Source: FRS v1.1 §6.4. Priority: P1; modality: SHALL.

The system SHALL detect carer distress and burnout indicators and SHALL offer carer-directed supports (respite, carer peer groups, counselling) as a first-class outcome.

Source acceptance:

- Carer-directed referral is an available session outcome with its own tracking, not a sub-case of PID referral.

Proposed requirement families: TR-WF-08; TR-DAT-01/02. Acceptance groups: AT-06/13.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-D8 — Designated multi-carer network with granular permissions

Source: FRS v1.1 §6.4. Priority: P2; modality: SHOULD.

The system SHOULD support a designated carer network — multiple carers around one PID sharing a crisis plan with the PID's consent and granular per-person permissions.

Source acceptance:

- Permissions are per-field and revocable by the PID at any time.

Proposed requirement families: TR-WF-08; TR-DAT-01/02. Acceptance groups: AT-06/13.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-E1 — Optional identity/community preference disclosure

Source: FRS v1.1 §6.5. Priority: P0; modality: SHALL.

The system SHALL allow users to state identity and community preferences (including Black, Indigenous, racialized, newcomer, 2SLGBTQI+, disabled, and faith-based) and SHALL prioritize matched services and responders where they exist. Disclosure SHALL never be required to receive service.

Source acceptance:

- Skipping identity questions has no effect on access, tier, or pathway quality.
- Verified by test.

Proposed requirement families: TR-WF-03; TR-SEC-08; TR-GOV-02/04. Acceptance groups: AT-03/08/12.

Technical treatment: [04-data-security-governance.md](04-data-security-governance.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-E2 — Indigenous-led service prioritization with distinct governance

Source: FRS v1.1 §6.5. Priority: P0; modality: SHALL.

Where a user identifies an Indigenous service preference, or agrees to culturally matched options, the system SHALL prioritize locally appropriate Indigenous-led services where available. The user SHALL remain able to select another service without reduced access or additional friction. Governance SHALL distinguish First Nations, Inuit, Métis, urban Indigenous, and Nation- or community-specific requirements.

Source acceptance:

- Verified per deployment region with the applicable Indigenous governance partners; tests confirm that declining matched routing does not alter tier, access, or queue priority.

Proposed requirement families: TR-WF-03; TR-SEC-08; TR-GOV-02/04. Acceptance groups: AT-03/08/12.

Technical treatment: [04-data-security-governance.md](04-data-security-governance.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-E3 — Explicit police-involvement-risk statement per pathway

Source: FRS v1.1 §6.5. Priority: P0; modality: SHALL.

The system SHALL explicitly state the police-involvement risk associated with each pathway it presents.

Source acceptance:

- Every presented option carries a plain-language statement of whether, and under what conditions, police may attend.

Proposed requirement families: TR-WF-03; TR-SEC-08; TR-GOV-02/04. Acceptance groups: AT-03/08/12.

Technical treatment: [04-data-security-governance.md](04-data-security-governance.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-E4 — Recorded anti-police preference honoured where possible

Source: FRS v1.1 §6.5. Priority: P0; modality: SHALL.

The system SHALL support a recorded preference against police involvement. It SHALL prioritize pathways documented as responding independently of police and transmit the preference in consented referrals. It SHALL clearly distinguish a user preference from a guarantee where police attendance remains under third-party control.

Source acceptance:

- The system does not itself recommend police below T4 unless a human-approved protocol requires it.
- Every pathway states whether the receiving service may independently request police.
- Any departure from the preference is logged, justified, and reviewed.

Proposed requirement families: TR-WF-03; TR-SEC-08; TR-GOV-02/04. Acceptance groups: AT-03/08/12.

Technical treatment: [04-data-security-governance.md](04-data-security-governance.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-E5 — Pre-deployment and ongoing bias audit with remediation

Source: FRS v1.1 §6.5. Priority: P0; modality: SHALL.

The system SHALL undergo pre-deployment and ongoing bias audit measuring triage tier assignment, escalation-to-police recommendation rate, and referral quality for disparity across race, Indigenous identity, language, immigration status, disability, and neighbourhood income. Disparity above the defined threshold SHALL trigger a documented remediation process.

Source acceptance:

- Audit methodology approved by the Equity Council.
- Audit runs at least quarterly.
- Remediation is tracked to closure.

Proposed requirement families: TR-WF-03; TR-SEC-08; TR-GOV-02/04. Acceptance groups: AT-03/08/12.

Technical treatment: [04-data-security-governance.md](04-data-security-governance.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-E6 — Binding co-design/review authority for affected communities

Source: FRS v1.1 §6.5. Priority: P0; modality: SHALL.

The system SHALL be co-designed and reviewed by an advisory body including people with lived experience, carers from affected communities, and Indigenous partners. That body SHALL have authority to require changes to triage logic.

Source acceptance:

- Council terms of reference grant binding review authority.
- Change requests tracked with dispositions.

Proposed requirement families: TR-WF-03; TR-SEC-08; TR-GOV-02/04. Acceptance groups: AT-03/08/12.

Technical treatment: [04-data-security-governance.md](04-data-security-governance.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-E7 — Exclusion of criminal-history/immigration/police-contact features

Source: FRS v1.1 §6.5. Priority: P1; modality: SHALL.

The system SHALL NOT use criminal-history, immigration-status, or police-contact-history data as an input to risk triage.

Source acceptance:

- Verified by data-lineage review of all triage features.

Proposed requirement families: TR-WF-03; TR-SEC-08; TR-GOV-02/04. Acceptance groups: AT-03/08/12.

Technical treatment: [04-data-security-governance.md](04-data-security-governance.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-E8 — Culturally adapted content and guidance

Source: FRS v1.1 §6.5. Priority: P2; modality: SHOULD.

The system SHOULD present content and guidance in a manner adapted to cultural context (family involvement norms, faith practices, stigma framing) where the user has indicated a preference.

Source acceptance:

- Adaptations authored by community partners, not generated unreviewed.

Proposed requirement families: TR-WF-03; TR-SEC-08; TR-GOV-02/04. Acceptance groups: AT-03/08/12.

Technical treatment: [04-data-security-governance.md](04-data-security-governance.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-F1 — Ungated "get me a human" command

Source: FRS v1.1 §6.6. Priority: P0; modality: SHALL.

The system SHALL provide an ungated "get me a human" command at every point, in every channel.

Source acceptance:

- Command recognized in all supported languages and channels.
- No gating, no confirmation friction, no re-triage precondition.

Proposed requirement families: TR-WF-04…06; TR-OPS-08/09; TR-SEC-06. Acceptance groups: AT-04/05/10.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-F2 — Automatic escalation on defined trigger conditions

Source: FRS v1.1 §6.6. Priority: P0; modality: SHALL.

The system SHALL automatically escalate to a human crisis worker when any of the following holds: tier ≥ T2; suicidal intent with plan is expressed; agent confidence is below threshold; the user is a minor; or defined complexity or duration limits are exceeded.

Source acceptance:

- 100% of triggering conditions produce escalation in the test suite.
- Escalation latency measured and reported.

Proposed requirement families: TR-WF-04…06; TR-OPS-08/09; TR-SEC-06. Acceptance groups: AT-04/05/10.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-F3 — No system-initiated session termination while risk unresolved

Source: FRS v1.1 §6.6. Priority: P0; modality: SHALL.

The system SHALL NOT terminate a session on its own initiative while risk is unresolved. Sessions end by user choice or by handoff to a human worker.

Source acceptance:

- No timeout-based termination path exists for sessions at T1 or above.

Proposed requirement families: TR-WF-04…06; TR-OPS-08/09; TR-SEC-06. Acceptance groups: AT-04/05/10.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-F4 — No autonomous emergency-service contact

Source: FRS v1.1 §6.6. Priority: P0; modality: SHALL.

During pilot and initial general availability, the system SHALL NOT independently contact emergency services. Where emergency intervention may be necessary, it SHALL urgently connect the user to a qualified human worker, support the user in contacting emergency services directly, and remain present where the channel permits.

Source acceptance:

- Tool permissions make autonomous emergency contact technically impossible.
- All emergency-service contact is user-initiated or human-authorized and is logged with the authorizing actor.
- Any future autonomous capability requires a separately approved safety case and release decision.

Proposed requirement families: TR-WF-04…06; TR-OPS-08/09; TR-SEC-06. Acceptance groups: AT-04/05/10.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-F5 — Supervisor observation with interrupt/take-over

Source: FRS v1.1 §6.6. Priority: P1; modality: SHALL.

The system SHALL support supervisor observation of live sessions with interrupt and take-over capability.

Source acceptance:

- Take-over transfers control within *[N]* seconds without dropping the user.

Proposed requirement families: TR-WF-04…06; TR-OPS-08/09; TR-SEC-06. Acceptance groups: AT-04/05/10.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-F6 — Safe degradation to static pre-approved crisis contacts

Source: FRS v1.1 §6.6. Priority: P0; modality: SHALL.

The system SHALL degrade safely: on model failure, tool failure, or connectivity loss it SHALL present static, pre-approved crisis contacts rather than nothing.

Source acceptance:

- Fallback content is served from an independent path that does not depend on the model or the service directory.
- Verified by chaos testing.

Proposed requirement families: TR-WF-04…06; TR-OPS-08/09; TR-SEC-06. Acceptance groups: AT-04/05/10.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-F7 — Visible human-escalation state and expected wait

Source: FRS v1.1 §6.6. Priority: P1; modality: SHALL.

The system SHALL make the human escalation state visible to the user — that a human has been requested, the expected wait, and that the agent remains present meanwhile.

Source acceptance:

- Wait communication updates at defined intervals; see FR-G4.

Proposed requirement families: TR-WF-04…06; TR-OPS-08/09; TR-SEC-06. Acceptance groups: AT-04/05/10.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-F8 — Documented operating states for human escalation

Source: FRS v1.1 §6.6. Priority: P0; modality: SHALL.

The system SHALL implement documented normal, elevated-load, severe-load, partner-unavailable, and regional-outage states for human escalation. Each state SHALL define user messaging, maximum stated wait, re-triage frequency, queue priority rules, mutual-aid routes, supervisor alerts, and fallback behaviour.

Source acceptance:

- Operational tests demonstrate correct behaviour in every state.
- The system never represents a human as imminently available when partner status is unknown or unavailable.

Proposed requirement families: TR-WF-04…06; TR-OPS-08/09; TR-SEC-06. Acceptance groups: AT-04/05/10.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-G1 — Absorb low-acuity contacts to protect staff capacity

Source: FRS v1.1 §6.7. Priority: P1; modality: SHALL.

The system SHALL absorb low-acuity, informational, and repeat-navigation contacts so that human staff time concentrates on high-acuity work.

Source acceptance:

- Measured shift in human-handled contact acuity mix against baseline, without increase in under-triage (FR-K3).

Proposed requirement families: TR-WF-05/06; TR-LLM-02; TR-GOV-04. Acceptance groups: AT-04/08/12.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-G2 — Auto-generated session summaries and referral docs

Source: FRS v1.1 §6.7. Priority: P1; modality: SHALL.

The system SHALL auto-generate session summaries and referral documentation for the receiving human worker.

Source acceptance:

- Worker-rated accuracy ≥ *[target]*.
- Worker edits summary rather than authoring it.

Proposed requirement families: TR-WF-05/06; TR-LLM-02; TR-GOV-04. Acceptance groups: AT-04/08/12.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-G3 — Context pack on transfer so the caller need not retell

Source: FRS v1.1 §6.7. Priority: P0; modality: SHALL.

On transfer, the system SHALL provide the worker a context pack — history, prior contacts where consented, crisis plan, language needs — so the caller does not retell their story.

Source acceptance:

- Context pack available to the worker before or at the moment of connection in ≥ 95% of transfers.

Proposed requirement families: TR-WF-05/06; TR-LLM-02; TR-GOV-04. Acceptance groups: AT-04/08/12.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-G4 — Queue management with periodic re-triage during wait

Source: FRS v1.1 §6.7. Priority: P1; modality: SHALL.

The system SHALL manage queues: hold, reassure, and continue supporting contacts awaiting a human, with periodic re-triage so deterioration is detected during the wait.

Source acceptance:

- Re-triage occurs at defined intervals throughout the wait.
- Deterioration promotes queue position per protocol.

Proposed requirement families: TR-WF-05/06; TR-LLM-02; TR-GOV-04. Acceptance groups: AT-04/08/12.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-G5 — Per-worker exposure tracking, performance-use prohibited

Source: FRS v1.1 §6.7. Priority: P2; modality: SHOULD.

The system SHOULD track per-worker exposure to high-acuity and traumatic content and flag configured thresholds to supervisors for debrief and rotation.

Source acceptance:

- Exposure metrics available to supervisors.
- Constraint: this data SHALL NOT be used for individual performance management or discipline.

Proposed requirement families: TR-WF-05/06; TR-LLM-02; TR-GOV-04. Acceptance groups: AT-04/08/12.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-G6 — On-shift reference material and debrief prompts

Source: FRS v1.1 §6.7. Priority: P2; modality: SHOULD.

The system SHOULD provide on-shift reference material, protocol lookup, and post-call debrief prompts.

Source acceptance:

- Protocol lookup returns jurisdiction-correct results in under 5 seconds.

Proposed requirement families: TR-WF-05/06; TR-LLM-02; TR-GOV-04. Acceptance groups: AT-04/08/12.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-H1 — PIPEDA/provincial privacy law/OCAP® compliance

Source: FRS v1.1 §6.8. Priority: P0; modality: SHALL.

The system SHALL comply with PIPEDA, applicable provincial health privacy legislation (including PHIPA, HIA, and Quebec Law 25), and OCAP® principles for Indigenous data.

Source acceptance:

- Privacy Impact Assessment completed and approved per jurisdiction before deployment.

Proposed requirement families: TR-DAT-01…04; TR-SEC-01/03/05. Acceptance groups: AT-02/05/06/09/11.

Technical treatment: [04-data-security-governance.md](04-data-security-governance.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-H2 — Granular revocable per-purpose consent, no silent linking

Source: FRS v1.1 §6.8. Priority: P0; modality: SHALL.

The system SHALL obtain granular, revocable consent per disclosure purpose. Anonymous sessions SHALL NOT be silently linked to identified records.

Source acceptance:

- Consent is recorded per purpose with timestamp and scope.
- Linking requires an explicit user action.

Proposed requirement families: TR-DAT-01…04; TR-SEC-01/03/05. Acceptance groups: AT-02/05/06/09/11.

Technical treatment: [04-data-security-governance.md](04-data-security-governance.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-H3 — Canadian data residency, encryption, RBAC, access logging

Source: FRS v1.1 §6.8. Priority: P0; modality: SHALL.

The system SHALL store all data in Canada, encrypt in transit and at rest, and enforce role-based access with complete access logging.

Source acceptance:

- Data residency verified contractually and technically.
- Access logs immutable and retained per policy.

Proposed requirement families: TR-DAT-01…04; TR-SEC-01/03/05. Acceptance groups: AT-02/05/06/09/11.

Technical treatment: [04-data-security-governance.md](04-data-security-governance.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-H4 — No disclosure to police/employers/insurers/immigration/CP absent compulsion

Source: FRS v1.1 §6.8. Priority: P0; modality: SHALL.

The system SHALL NOT disclose session content to police, employers, insurers, immigration authorities, or child protection except where legally compelled, and SHALL state the limits of confidentiality in plain language before assessment begins.

Source acceptance:

- Confidentiality statement delivered per FR-A7.
- Any compelled disclosure is logged and, where lawful, disclosed to the user.

Proposed requirement families: TR-DAT-01…04; TR-SEC-01/03/05. Acceptance groups: AT-02/05/06/09/11.

Technical treatment: [04-data-security-governance.md](04-data-security-governance.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-H5 — User-initiated deletion and export

Source: FRS v1.1 §6.8. Priority: P1; modality: SHALL.

The system SHALL support user-initiated deletion and export of their data.

Source acceptance:

- Deletion completes within *[N]* days across all stores and backups; export in a machine-readable format.

Proposed requirement families: TR-DAT-01…04; TR-SEC-01/03/05. Acceptance groups: AT-02/05/06/09/11.

Technical treatment: [04-data-security-governance.md](04-data-security-governance.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-H6 — No training use of crisis content without explicit opt-in

Source: FRS v1.1 §6.8. Priority: P0; modality: SHALL.

The system SHALL NOT use crisis conversation content for model training without separate, explicit, opt-in consent.

Source acceptance:

- Training data pipelines exclude conversation content by default; inclusion requires a per-user consent record.

Proposed requirement families: TR-DAT-01…04; TR-SEC-01/03/05. Acceptance groups: AT-02/05/06/09/11.

Technical treatment: [04-data-security-governance.md](04-data-security-governance.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-H7 — Data minimization and class-based retention limits

Source: FRS v1.1 §6.8. Priority: P1; modality: SHALL.

The system SHALL apply data minimization: collect only what is required for the current pathway, and apply retention limits by data class.

Source acceptance:

- Retention schedule approved by the Privacy Officer and enforced automatically.

Proposed requirement families: TR-DAT-01…04; TR-SEC-01/03/05. Acceptance groups: AT-02/05/06/09/11.

Technical treatment: [04-data-security-governance.md](04-data-security-governance.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-I1 — Minor detection routed to youth safeguarding protocol

Source: FRS v1.1 §6.9. Priority: P0; modality: SHALL.

The system SHALL detect or establish when the user or PID may be a minor and SHALL route the session to a jurisdiction-appropriate youth safeguarding protocol and qualified human worker. Age uncertainty SHALL be recorded rather than guessed.

Source acceptance:

- Youth and age-uncertain scenarios trigger the correct protocol and human escalation in 100% of the approved test suite.

Proposed requirement families: TR-WF-09; TR-SEC-03; TR-DAT-01. Acceptance groups: AT-07.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-I2 — Discreet private-help path when a guardian may be the danger

Source: FRS v1.1 §6.9. Priority: P0; modality: SHALL.

The system SHALL support the possibility that a parent, guardian, carer, household member, or professional contacting the system may be the source of danger or coercion. It SHALL provide a discreet path for the young person to request private human help where the channel permits.

Source acceptance:

- Abuse, coercive-control, and unsafe-guardian scenarios do not automatically disclose the young person's content to the contacting adult.

Proposed requirement families: TR-WF-09; TR-SEC-03; TR-DAT-01. Acceptance groups: AT-07.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-I3 — Jurisdiction-configured, legally reviewed youth consent rules

Source: FRS v1.1 §6.9. Priority: P0; modality: SHALL.

Youth consent, mature-minor capacity, parental access, mandatory reporting, school-professional duties, and confidential youth-service rules SHALL be configured and legally reviewed per jurisdiction.

Source acceptance:

- Legal approval is recorded before youth service is enabled in a jurisdiction; user-facing confidentiality language matches the configured rule set.

Proposed requirement families: TR-WF-09; TR-SEC-03; TR-DAT-01. Acceptance groups: AT-07.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-I4 — Youth data minimization; no guardian access without basis

Source: FRS v1.1 §6.9. Priority: P0; modality: SHALL.

The system SHALL minimize collection and disclosure of youth data and SHALL not expose a youth crisis plan, location, or conversation to a guardian without a documented legal and consent basis.

Source acceptance:

- Access-control tests prevent unauthorized guardian access and log every disclosure decision and basis.

Proposed requirement families: TR-WF-09; TR-SEC-03; TR-DAT-01. Acceptance groups: AT-07.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-I5 — Youth-specific service directory fields

Source: FRS v1.1 §6.9. Priority: P1; modality: SHALL.

The service directory SHALL identify youth-specific services, age bands, guardian requirements, confidential-access rules, hours, and police-involvement conditions.

Source acceptance:

- Youth pathways are verified separately from adult pathways before launch.

Proposed requirement families: TR-WF-09; TR-SEC-03; TR-DAT-01. Acceptance groups: AT-07.

Technical treatment: [02-actors-and-workflows.md](02-actors-and-workflows.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-J1 — No diagnosis, prescription, or medication adjustment

Source: FRS v1.1 §6.10. Priority: P0; modality: SHALL.

The system SHALL NOT diagnose, prescribe, or adjust medication.

Source acceptance:

- No separate acceptance criterion in this model node; use the statement and reviewed technical acceptance.

Proposed requirement families: TR-SEC-06/08; TR-LLM-02/04. Acceptance groups: AT-05/08.

Technical treatment: [04-data-security-governance.md](04-data-security-governance.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-J2 — No self-harm method/means-acquisition assistance

Source: FRS v1.1 §6.10. Priority: P0; modality: SHALL.

The system SHALL NOT provide actionable method instructions, optimization, comparative lethality information, or assistance acquiring means relating to suicide or self-harm. This prohibition SHALL NOT prevent clinician-approved means-safety guidance or environmental risk-reduction steps.

Source acceptance:

- No separate acceptance criterion in this model node; use the statement and reviewed technical acceptance.

Proposed requirement families: TR-SEC-06/08; TR-LLM-02/04. Acceptance groups: AT-05/08.

Technical treatment: [04-data-security-governance.md](04-data-security-governance.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-J3 — No claiming to be human; AI disclosure on request

Source: FRS v1.1 §6.10. Priority: P0; modality: SHALL.

The system SHALL NOT claim or imply that it is human. It SHALL disclose that it is an AI agent at session start and whenever asked.

Source acceptance:

- No separate acceptance criterion in this model node; use the statement and reviewed technical acceptance.

Proposed requirement families: TR-SEC-06/08; TR-LLM-02/04. Acceptance groups: AT-05/08.

Technical treatment: [04-data-security-governance.md](04-data-security-governance.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-J4 — No substituting for therapeutic/peer relationships

Source: FRS v1.1 §6.10. Priority: P0; modality: SHALL.

The system SHALL NOT represent itself as a substitute for therapeutic or peer relationships, and SHALL actively route toward human connection.

Source acceptance:

- No separate acceptance criterion in this model node; use the statement and reviewed technical acceptance.

Proposed requirement families: TR-SEC-06/08; TR-LLM-02/04. Acceptance groups: AT-05/08.

Technical treatment: [04-data-security-governance.md](04-data-security-governance.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-J5 — No engagement-maximizing / dependency-forming patterns

Source: FRS v1.1 §6.10. Priority: P0; modality: SHALL.

The system SHALL NOT employ engagement-maximizing patterns, including streaks, dependency-forming rapport, retention nudges, or artificial scarcity.

Source acceptance:

- No separate acceptance criterion in this model node; use the statement and reviewed technical acceptance.

Proposed requirement families: TR-SEC-06/08; TR-LLM-02/04. Acceptance groups: AT-05/08.

Technical treatment: [04-data-security-governance.md](04-data-security-governance.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-J6 — No involuntary-committal or apprehension influence

Source: FRS v1.1 §6.10. Priority: P0; modality: SHALL.

The system SHALL NOT make, recommend, or influence involuntary-committal or apprehension determinations.

Source acceptance:

- No separate acceptance criterion in this model node; use the statement and reviewed technical acceptance.

Proposed requirement families: TR-SEC-06/08; TR-LLM-02/04. Acceptance groups: AT-05/08.

Technical treatment: [04-data-security-governance.md](04-data-security-governance.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-J7 — No profiling beyond own care; no law-enforcement analytics integration

Source: FRS v1.1 §6.10. Priority: P0; modality: SHALL.

The system SHALL NOT be used to build a profile of an individual for any purpose beyond their own care, and SHALL NOT be integrated with law-enforcement analytics.

Source acceptance:

- No separate acceptance criterion in this model node; use the statement and reviewed technical acceptance.

Proposed requirement families: TR-SEC-06/08; TR-LLM-02/04. Acceptance groups: AT-05/08.

Technical treatment: [04-data-security-governance.md](04-data-security-governance.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-J8 — No reinforcing harmful self-beliefs or self-directed contempt

Source: FRS v1.1 §6.10. Priority: P0; modality: SHALL.

The system SHALL NOT reinforce a user's harmful beliefs about themselves, and SHALL NOT validate self-directed contempt as a means of maintaining rapport.

Source acceptance:

- No separate acceptance criterion in this model node; use the statement and reviewed technical acceptance.

Proposed requirement families: TR-SEC-06/08; TR-LLM-02/04. Acceptance groups: AT-05/08.

Technical treatment: [04-data-security-governance.md](04-data-security-governance.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-K1 — Full session logging supporting independent audit

Source: FRS v1.1 §6.11. Priority: P0; modality: SHALL.

The system SHALL log every session with tier assigned, pathway recommended, pathway actually taken, and outcome, in a form supporting independent audit.

Source acceptance:

- Audit dataset schema approved by the Clinical Safety Committee; independent auditor able to reproduce reported metrics.

Proposed requirement families: TR-GOV-03…05; TR-DAT-01/04. Acceptance groups: AT-09/12.

Technical treatment: [04-data-security-governance.md](04-data-security-governance.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-K2 — Core objective measures reported quarterly

Source: FRS v1.1 §6.11. Priority: P0; modality: SHALL.

The system SHALL report its core objective measures: proportion of engaged crises resolved without police attendance, and rate of injury or death in encounters where the system was involved.

Source acceptance:

- Reported at least quarterly to the Clinical Safety Committee and publicly per FR-K5.

Proposed requirement families: TR-GOV-03…05; TR-DAT-01/04. Acceptance groups: AT-09/12.

Technical treatment: [04-data-security-governance.md](04-data-security-governance.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-K2a — Police-avoidance metrics never reported in isolation

Source: FRS v1.1 §6.11. Priority: P0; modality: SHALL.

Police-avoidance metrics SHALL only be reported with the corresponding safety, access, and equity measures: under-triage, over-triage, injury or death, completed handoff, unmet-service rate, repeat crisis, user-reported coercion, time to meaningful human connection, and disparity by community.

Source acceptance:

- No dashboard, public report, or internal target presents police avoidance as an isolated success measure.
- Metric definitions and denominators are independently auditable.

Proposed requirement families: TR-GOV-03…05; TR-DAT-01/04. Acceptance groups: AT-09/12.

Technical treatment: [04-data-security-governance.md](04-data-security-governance.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-K3 — Under-/over-triage tracked against targets

Source: FRS v1.1 §6.11. Priority: P0; modality: SHALL.

The system SHALL track under-triage (missed high risk) and over-triage (unnecessary escalation) against defined targets, reviewed by the Clinical Safety Committee.

Source acceptance:

- Both rates computed with confidence intervals.
- Breach of target triggers documented review.

Proposed requirement families: TR-GOV-03…05; TR-DAT-01/04. Acceptance groups: AT-09/12.

Technical treatment: [04-data-security-governance.md](04-data-security-governance.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-K4 — Mandatory post-incident review for death/serious injury/police outcome

Source: FRS v1.1 §6.11. Priority: P0; modality: SHALL.

The system SHALL support incident reporting, root-cause analysis, and mandatory post-incident review of any death, serious injury, or police-involved outcome.

Source acceptance:

- Review initiated within *[N]* hours of notification.
- Findings tracked to corrective action.

Proposed requirement families: TR-GOV-03…05; TR-DAT-01/04. Acceptance groups: AT-09/12.

Technical treatment: [04-data-security-governance.md](04-data-security-governance.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-K5 — Public periodic performance and equity reporting

Source: FRS v1.1 §6.11. Priority: P1; modality: SHALL.

The system operator SHALL publish aggregate performance and equity metrics publicly at defined intervals.

Source acceptance:

- Public report published at least annually; includes FR-E5 disparity findings whether favourable or not.

Proposed requirement families: TR-GOV-03…05; TR-DAT-01/04. Acceptance groups: AT-09/12.

Technical treatment: [04-data-security-governance.md](04-data-security-governance.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-K6 — A/B and shadow evaluation without live high-acuity exposure

Source: FRS v1.1 §6.11. Priority: P1; modality: SHALL.

The system SHALL support A/B and shadow evaluation of triage logic changes without exposing users to unvalidated logic in live high-acuity sessions.

Source acceptance:

- Shadow mode produces comparison data with no effect on live recommendations at T2 and above.

Proposed requirement families: TR-GOV-03…05; TR-DAT-01/04. Acceptance groups: AT-09/12.

Technical treatment: [04-data-security-governance.md](04-data-security-governance.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-L1 — Model proposes; deterministic policy services hold final authority

Source: FRS v1.1 §6.12. Priority: P0; modality: SHALL.

The language model MAY propose content or actions but SHALL NOT have final authority over triage policy, consent validity, lawful disclosure, emergency contact, identity linking, or referral transmission. These decisions SHALL be enforced by deterministic, versioned policy services.

Source acceptance:

- Architecture and adversarial tests demonstrate that prompt content cannot bypass policy controls or directly invoke restricted actions.

Proposed requirement families: TR-ARC-01/02; TR-LLM-01…05; TR-SEC-01…08; TR-GOV-01…03. Acceptance groups: AT-02/05/08/10/12.

Technical treatment: [03-architecture-and-interfaces.md](03-architecture-and-interfaces.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-L2 — Allow-listed, least-privileged, validated, auditable tools

Source: FRS v1.1 §6.12. Priority: P0; modality: SHALL.

All tools SHALL be allow-listed, least-privileged, schema-validated, authenticated, rate-limited, and auditable. Tool parameters and outputs SHALL be validated before use in a user-facing response or external action.

Source acceptance:

- Unauthorized tools and malformed parameters are rejected; every invocation records actor, purpose, inputs, policy decision, result, and version.

Proposed requirement families: TR-ARC-01/02; TR-LLM-01…05; TR-SEC-01…08; TR-GOV-01…03. Acceptance groups: AT-02/05/08/10/12.

Technical treatment: [03-architecture-and-interfaces.md](03-architecture-and-interfaces.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-L3 — Machine-verifiable consent record required, never inferred

Source: FRS v1.1 §6.12. Priority: P0; modality: SHALL.

Consent-gated actions SHALL require a machine-verifiable consent record matching the purpose, recipient, data fields, expiry, and session. The model SHALL NOT infer consent from conversational tone or silence.

Source acceptance:

- Referral, disclosure, session linking, and data-sharing tests fail closed when the consent record is absent, expired, or scope-mismatched.

Proposed requirement families: TR-ARC-01/02; TR-LLM-01…05; TR-SEC-01…08; TR-GOV-01…03. Acceptance groups: AT-02/05/08/10/12.

Technical treatment: [03-architecture-and-interfaces.md](03-architecture-and-interfaces.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-L4 — Service/legal/protocol/emergency facts from approved sources only

Source: FRS v1.1 §6.12. Priority: P0; modality: SHALL.

Service facts, legal content, clinical protocols, and emergency contacts SHALL come only from approved versioned sources, not model generation.

Source acceptance:

- Red-team prompts cannot cause fabricated service, legal, or protocol facts to be presented as authoritative.

Proposed requirement families: TR-ARC-01/02; TR-LLM-01…05; TR-SEC-01…08; TR-GOV-01…03. Acceptance groups: AT-02/05/08/10/12.

Technical treatment: [03-architecture-and-interfaces.md](03-architecture-and-interfaces.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-L5 — Protection against injection, poisoning, exfiltration, cross-session leakage

Source: FRS v1.1 §6.12. Priority: P0; modality: SHALL.

The system SHALL protect against prompt injection, tool-output injection, poisoned directory feeds, data exfiltration, malicious file or URL content, and cross-session data leakage.

Source acceptance:

- Pre-release and annual red-team suites cover each attack class; critical findings block release.

Proposed requirement families: TR-ARC-01/02; TR-LLM-01…05; TR-SEC-01…08; TR-GOV-01…03. Acceptance groups: AT-02/05/08/10/12.

Technical treatment: [03-architecture-and-interfaces.md](03-architecture-and-interfaces.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-L6 — Kill switch, rollback, and safe mode preserving the fallback

Source: FRS v1.1 §6.12. Priority: P0; modality: SHALL.

The operator SHALL maintain an immediate kill switch, model/prompt/policy rollback, feature-level disablement, and safe-mode capability that preserves the independent static crisis path.

Source acceptance:

- Authorized operators can disable affected capabilities within *[target]* minutes without removing FR-F6 fallback access.

Proposed requirement families: TR-ARC-01/02; TR-LLM-01…05; TR-SEC-01…08; TR-GOV-01…03. Acceptance groups: AT-02/05/08/10/12.

Technical treatment: [03-architecture-and-interfaces.md](03-architecture-and-interfaces.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-L7 — Explicit expiring continuation; no metadata-based identity linking

Source: FRS v1.1 §6.12. Priority: P1; modality: SHALL.

Cross-channel continuation SHALL use an explicit, expiring continuation mechanism. Caller ID, device fingerprint, IP address, or similar metadata SHALL NOT silently establish identity or link anonymous sessions.

Source acceptance:

- Session continuity works with user action; tests confirm anonymous sessions cannot be silently linked.
- Assurance levels are defined separately for resuming a session, viewing or editing a crisis plan, sharing data, and export/deletion.

Proposed requirement families: TR-ARC-01/02; TR-LLM-01…05; TR-SEC-01…08; TR-GOV-01…03. Acceptance groups: AT-02/05/08/10/12.

Technical treatment: [03-architecture-and-interfaces.md](03-architecture-and-interfaces.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## FR-L8 — Classified change control for high-risk changes

Source: FRS v1.1 §6.12. Priority: P0; modality: SHALL.

High-risk changes to triage logic, confidence thresholds, consent rules, emergency workflows, or tool permissions SHALL follow classified change control with clinical, equity, privacy, security, and operational approvals as applicable.

Source acceptance:

- Change records identify class, approvers, validation evidence, shadow results, rollout plan, and rollback trigger before deployment.

Proposed requirement families: TR-ARC-01/02; TR-LLM-01…05; TR-SEC-01…08; TR-GOV-01…03. Acceptance groups: AT-02/05/08/10/12.

Technical treatment: [03-architecture-and-interfaces.md](03-architecture-and-interfaces.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## NFR-1 — Monthly availability ≥ 99.95%, 24/7/365

Source: FRS v1.1 §7.1. Priority: P1; modality: SHALL.

Availability ≥ 99.95% measured monthly, 24/7/365.

Source acceptance:

- No separate acceptance criterion in this model node; use the statement and reviewed technical acceptance.

Proposed requirement families: TR-OPS-01…13; TR-SEC-08; TR-GOV-02/03. Acceptance groups: AT-08…13.

Technical treatment: [05-deployment-and-operations.md](05-deployment-and-operations.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## NFR-10 — Stressed-condition usability validation

Source: FRS v1.1 §7.3. Priority: P1; modality: SHALL.

Usability validated with carers under simulated stress conditions, including at least: low light, one-handed operation, background noise, and interruption.

Source acceptance:

- No separate acceptance criterion in this model node; use the statement and reviewed technical acceptance.

Proposed requirement families: TR-OPS-01…13; TR-SEC-08; TR-GOV-02/03. Acceptance groups: AT-08…13.

Technical treatment: [05-deployment-and-operations.md](05-deployment-and-operations.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## NFR-11 — Crisis path completable at Grade 6 reading level

Source: FRS v1.1 §7.3. Priority: P1; modality: SHALL.

Core crisis path completable at a Grade 6 reading level.

Source acceptance:

- No separate acceptance criterion in this model node; use the statement and reviewed technical acceptance.

Proposed requirement families: TR-OPS-01…13; TR-SEC-08; TR-GOV-02/03. Acceptance groups: AT-08…13.

Technical treatment: [05-deployment-and-operations.md](05-deployment-and-operations.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## NFR-12 — Usability testing includes P4 and lived-experience participants

Source: FRS v1.1 §7.3. Priority: P1; modality: SHALL.

Usability testing SHALL include participants from the communities identified in P4 and participants with lived experience of crisis.

Source acceptance:

- No separate acceptance criterion in this model node; use the statement and reviewed technical acceptance.

Proposed requirement families: TR-OPS-01…13; TR-SEC-08; TR-GOV-02/03. Acceptance groups: AT-08…13.

Technical treatment: [05-deployment-and-operations.md](05-deployment-and-operations.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## NFR-13 — Annual third-party pentest and red-team

Source: FRS v1.1 §7.4. Priority: P0; modality: SHALL.

Annual third-party penetration test and red-team evaluation, including adversarial testing against FR-J prohibitions.

Source acceptance:

- No separate acceptance criterion in this model node; use the statement and reviewed technical acceptance.

Proposed requirement families: TR-OPS-01…13; TR-SEC-08; TR-GOV-02/03. Acceptance groups: AT-08…13.

Technical treatment: [05-deployment-and-operations.md](05-deployment-and-operations.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## NFR-14 — SaMD classification assessment and compliance

Source: FRS v1.1 §7.4. Priority: P0; modality: SHALL.

The operator SHALL assess classification as Software as a Medical Device under Health Canada guidance and comply with the resulting obligations.

Source acceptance:

- No separate acceptance criterion in this model node; use the statement and reviewed technical acceptance.

Proposed requirement families: TR-OPS-01…13; TR-SEC-08; TR-GOV-02/03. Acceptance groups: AT-08…13.

Technical treatment: [05-deployment-and-operations.md](05-deployment-and-operations.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## NFR-15 — Treasury Board ADM Directive / AIA compliance (federal)

Source: FRS v1.1 §7.4. Priority: P0; modality: SHALL.

Where operated by or for a federal institution, the system SHALL comply with the Treasury Board Directive on Automated Decision-Making at the applicable impact level, including Algorithmic Impact Assessment.

Source acceptance:

- No separate acceptance criterion in this model node; use the statement and reviewed technical acceptance.

Proposed requirement families: TR-OPS-01…13; TR-SEC-08; TR-GOV-02/03. Acceptance groups: AT-08…13.

Technical treatment: [05-deployment-and-operations.md](05-deployment-and-operations.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## NFR-16 — Alignment with Canadian AI governance law

Source: FRS v1.1 §7.4. Priority: P0; modality: SHALL.

The system SHALL align with applicable Canadian AI governance legislation and guidance in force at deployment.

Source acceptance:

- No separate acceptance criterion in this model node; use the statement and reviewed technical acceptance.

Proposed requirement families: TR-OPS-01…13; TR-SEC-08; TR-GOV-02/03. Acceptance groups: AT-08…13.

Technical treatment: [05-deployment-and-operations.md](05-deployment-and-operations.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## NFR-17 — Per-session version recording for forensic reconstruction

Source: FRS v1.1 §7.4. Priority: P0; modality: SHALL.

Model, prompt, tool, and triage-logic versions SHALL be recorded per session for forensic reconstruction.

Source acceptance:

- No separate acceptance criterion in this model node; use the statement and reviewed technical acceptance.

Proposed requirement families: TR-OPS-01…13; TR-SEC-08; TR-GOV-02/03. Acceptance groups: AT-08…13.

Technical treatment: [05-deployment-and-operations.md](05-deployment-and-operations.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## NFR-17a — Safety case, hazard log, and threat models before pilot

Source: FRS v1.1 §7.4. Priority: P0; modality: SHALL.

A documented clinical safety case, hazard log, privacy threat model, cybersecurity threat model, and misuse-case analysis SHALL be approved before pilot and maintained through change control.

Source acceptance:

- No separate acceptance criterion in this model node; use the statement and reviewed technical acceptance.

Proposed requirement families: TR-OPS-01…13; TR-SEC-08; TR-GOV-02/03. Acceptance groups: AT-08…13.

Technical treatment: [05-deployment-and-operations.md](05-deployment-and-operations.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## NFR-17b — Mandatory threat-model coverage list

Source: FRS v1.1 §7.4. Priority: P0; modality: SHALL.

Threat modelling SHALL include malicious false reports, coercive carers, intimate-partner surveillance, account takeover, location spoofing, fabricated crisis-plan content, prompt injection, poisoned service feeds, emergency-service swatting, insider access, compelled disclosure, denial of service, and discriminatory summaries.

Source acceptance:

- No separate acceptance criterion in this model node; use the statement and reviewed technical acceptance.

Proposed requirement families: TR-OPS-01…13; TR-SEC-08; TR-GOV-02/03. Acceptance groups: AT-08…13.

Technical treatment: [05-deployment-and-operations.md](05-deployment-and-operations.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## NFR-18 — Per-jurisdiction configurability without code deploy

Source: FRS v1.1 §7.5. Priority: P1; modality: SHALL.

Jurisdictional rules, service directories, consent language, and legal content SHALL be configurable per province/territory without code deployment.

Source acceptance:

- No separate acceptance criterion in this model node; use the statement and reviewed technical acceptance.

Proposed requirement families: TR-OPS-01…13; TR-SEC-08; TR-GOV-02/03. Acceptance groups: AT-08…13.

Technical treatment: [05-deployment-and-operations.md](05-deployment-and-operations.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## NFR-19 — Triage logic as versioned reviewable artefact

Source: FRS v1.1 §7.5. Priority: P1; modality: SHALL.

Triage logic SHALL be a versioned, reviewable artefact separable from application code.

Source acceptance:

- No separate acceptance criterion in this model node; use the statement and reviewed technical acceptance.

Proposed requirement families: TR-OPS-01…13; TR-SEC-08; TR-GOV-02/03. Acceptance groups: AT-08…13.

Technical treatment: [05-deployment-and-operations.md](05-deployment-and-operations.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## NFR-2 — Degraded-mode crisis path availability ≥ 99.99%

Source: FRS v1.1 §7.1. Priority: P0; modality: SHALL.

The crisis path SHALL survive partial system failure; degraded mode per FR-F6 SHALL remain available at ≥ 99.99%.

Source acceptance:

- No separate acceptance criterion in this model node; use the statement and reviewed technical acceptance.

Proposed requirement families: TR-OPS-01…13; TR-SEC-08; TR-GOV-02/03. Acceptance groups: AT-08…13.

Technical treatment: [05-deployment-and-operations.md](05-deployment-and-operations.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## NFR-20 — Automated directory freshness checks and flagging

Source: FRS v1.1 §7.5. Priority: P1; modality: SHALL.

Service directory records SHALL support automated freshness checks and SHALL flag records past their verification interval.

Source acceptance:

- No separate acceptance criterion in this model node; use the statement and reviewed technical acceptance.

Proposed requirement families: TR-OPS-01…13; TR-SEC-08; TR-GOV-02/03. Acceptance groups: AT-08…13.

Technical treatment: [05-deployment-and-operations.md](05-deployment-and-operations.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## NFR-3 — No maintenance window removes the crisis path

Source: FRS v1.1 §7.1. Priority: P0; modality: SHALL.

No scheduled maintenance window SHALL remove the crisis path.

Source acceptance:

- No separate acceptance criterion in this model node; use the statement and reviewed technical acceptance.

Proposed requirement families: TR-OPS-01…13; TR-SEC-08; TR-GOV-02/03. Acceptance groups: AT-08…13.

Technical treatment: [05-deployment-and-operations.md](05-deployment-and-operations.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## NFR-4 — Session-state RTO ≤ 5 min / RPO ≤ 1 min

Source: FRS v1.1 §7.1. Priority: P1; modality: SHALL.

Recovery Time Objective ≤ 5 minutes; Recovery Point Objective ≤ 1 minute for session state.

Source acceptance:

- No separate acceptance criterion in this model node; use the statement and reviewed technical acceptance.

Proposed requirement families: TR-OPS-01…13; TR-SEC-08; TR-GOV-02/03. Acceptance groups: AT-08…13.

Technical treatment: [05-deployment-and-operations.md](05-deployment-and-operations.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## NFR-5 — First response ≤ 2 s p95

Source: FRS v1.1 §7.2. Priority: P1; modality: SHALL.

First response to user input: ≤ 2 seconds at p95.

Source acceptance:

- No separate acceptance criterion in this model node; use the statement and reviewed technical acceptance.

Proposed requirement families: TR-OPS-01…13; TR-SEC-08; TR-GOV-02/03. Acceptance groups: AT-08…13.

Technical treatment: [05-deployment-and-operations.md](05-deployment-and-operations.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## NFR-6 — Safety-step and hazard-recognition latency budgets

Source: FRS v1.1 §7.2. Priority: P0; modality: SHALL.

First actionable safety step or question: ≤ 5 seconds from session start at p95. Immediate-hazard recognition: ≤ 5 seconds from receipt of relevant information. Initial provisional acuity: ≤ 90 seconds at p95 where interaction conditions permit. Full assessment duration SHALL be monitored by channel and acuity but SHALL NOT be rushed to meet a universal maximum.

Source acceptance:

- No separate acceptance criterion in this model node; use the statement and reviewed technical acceptance.

Proposed requirement families: TR-OPS-01…13; TR-SEC-08; TR-GOV-02/03. Acceptance groups: AT-08…13.

Technical treatment: [05-deployment-and-operations.md](05-deployment-and-operations.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## NFR-7 — Crisis-plan retrieval ≤ 10 s p99

Source: FRS v1.1 §7.2. Priority: P1; modality: SHALL.

Crisis plan retrieval: ≤ 10 seconds at p99 (see FR-D4).

Source acceptance:

- No separate acceptance criterion in this model node; use the statement and reviewed technical acceptance.

Proposed requirement families: TR-OPS-01…13; TR-SEC-08; TR-GOV-02/03. Acceptance groups: AT-08…13.

Technical treatment: [05-deployment-and-operations.md](05-deployment-and-operations.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## NFR-8 — Human-escalation initiation ≤ 10 s p95

Source: FRS v1.1 §7.2. Priority: P1; modality: SHALL.

Human escalation connection initiated: ≤ 10 seconds from trigger at p95.

Source acceptance:

- No separate acceptance criterion in this model node; use the statement and reviewed technical acceptance.

Proposed requirement families: TR-OPS-01…13; TR-SEC-08; TR-GOV-02/03. Acceptance groups: AT-08…13.

Technical treatment: [05-deployment-and-operations.md](05-deployment-and-operations.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## NFR-9 — Peak concurrent load without degradation

Source: FRS v1.1 §7.2. Priority: P1; modality: SHALL.

The system SHALL sustain peak concurrent load of *[N]* sessions per region without degradation of NFR-5 through NFR-8.

Source acceptance:

- No separate acceptance criterion in this model node; use the statement and reviewed technical acceptance.

Proposed requirement families: TR-OPS-01…13; TR-SEC-08; TR-GOV-02/03. Acceptance groups: AT-08…13.

Technical treatment: [05-deployment-and-operations.md](05-deployment-and-operations.md); verification: [06-acceptance-and-delivery.md](06-acceptance-and-delivery.md), plus the category disposition above.

## Invariant obligations

All statements below are copied from the curated invariant registry. Verify formal core, deployed behavior and residual controls separately.

### INV-1

No agent-actor request to an emergency target ever returns PERMIT, under any input, any injection, any config

Verification class: **partially_expressible**.

The per-request predicate (deny emergency target for machine actor) is a fully executable static check. What is NOT reducible to a decidable predicate is the universal clause 'under any input, any injection, any config': it quantifies over an unbounded adversarial input space (prompt injection, parameter smuggling, unicode/homoglyph targets, chained sub-actions, recipient aliasing). No terminating predicate can prove the negative over that space; two sub-problems are themselves undecidable/heuristic — (a) resolves_to_emergency_service() must recognise an emergency target under homoglyph/alias obfuscation, and (b) 'any config' asserts non-existence of a bypassing configuration across all future bundles.

Residual control: Multi-layer structural enforcement (absent capability + network deny-list + guard with no machine PERMIT branch) reduces the residual to defence-in-depth; the dedicated adversarial suite (§7.5 conformance layer) exercises injection, tool confusion, parameter smuggling, recipient aliasing, unicode/homoglyph and chained sub-actions, all required to yield DENY + security event. Assurance is by exhaustive-attack testing, not proof.

Required verification methods: static_predicate_test, adversarial_suite, network_policy_test.

Source requirement traces: "FR-F4", "FR-J6", "R-11", "PH-5"

### INV-2

No consent-gated action executes without a matching, unexpired, scoped ledger record

Verification class: **fully_expressible**.

Consent evaluation is defined as an exact match on purpose and recipient, a superset check on fields, and a validity-window check against an append-only ledger. Every operand is a structured field; the decision is total and side-effect-free. Revocation-propagation to in-flight actions (AQ-3) is an explicit timing test but does not make the predicate non-decidable.

Required verification methods: static_predicate_test, adversarial_suite.

Source requirement traces: "FR-L3", "FR-H2", "FR-H6"

### INV-3

No user-visible service/legal/protocol claim exists without a sourced reference fetched that session

Verification class: **partially_expressible**.

The structural half is fully executable: every DECLARED response_claim must carry a sourced_item_id that resolves to a `sourced` context item fetched this session, and the broker rejects the envelope otherwise. The residual that no predicate can decide is COMPLETENESS — whether a given span of the free-text candidate_response actually constitutes a 'service/legal/protocol claim' that should have been declared. Detecting an undeclared factual claim embedded in natural-language prose is a semantic/NL-classification judgement, not a decidable check over structured fields. A model could assert a fact in prose without emitting a corresponding response_claim.

Residual control: Mitigated structurally by routing all assessment-explanatory text through EL-RAT (templated, sourced/structured inputs only; raw model text never surfaced) and by re-tainting downstream results as untrusted. Residual claim-detection is covered by the adversarial suite (direct/indirect prompt injection into user text, crisis-plan free text, directory description fields, file/URL content) which asserts no fabricated fact reaches the user.

Required verification methods: static_predicate_test, adversarial_suite.

Source requirement traces: "FR-L4", "FR-C2a", "R-9"

### INV-4

No tool outside the session capability token executes

Verification class: **fully_expressible**.

Set membership of the requested tool in a per-session allow-list plus budget/expiry/jurisdiction/tier checks are all decidable over structured fields. There is no dynamic tool registration, so the allow-list is a closed signed set.

Required verification methods: static_predicate_test, adversarial_suite.

Source requirement traces: "FR-L2", "FR-L5"

### INV-5

Z2 makes no network call other than to the broker

Verification class: **expressible_with_harness**.

The rule is a decidable network-policy predicate (destination == broker), but conformance is a property of the deployed network/mesh configuration rather than a value computable from an application data structure. Verifying it requires executing the environment — attempting egress from Z2 to arbitrary destinations and asserting they are dropped — i.e. a runtime network-policy test, not a static evaluation of a request object. The dedicated model-inference exception path also must be shown to reach only the model endpoint.

Residual control: Enforced by absent capability + network/IAM (HLD PP-3 top tiers) and verified by a network-policy conformance test in every environment; chaos/egress probes assert no Z2 destination other than the broker (and the audited inference path) is reachable.

Required verification methods: network_policy_test, adversarial_suite.

Source requirement traces: "FR-L1", "FR-L5", "NFR-17b"

### INV-6

Every consequential action produces exactly one conformant, hash-chained audit event before its result is returned

Verification class: **fully_expressible**.

Cardinality (exactly one), schema conformance, hash-chain linkage and ordering-before-return are all mechanically checkable given an enumerated set of 'consequential action' categories (the audit event `action.category` enum fixes that set). The audit-conformance test asserts every consequential action emitted a valid event.

Required verification methods: static_predicate_test.

Source requirement traces: "FR-L2", "FR-K1", "NFR-17"

### INV-7

Anonymous sessions are never linked without an explicit AL3 act; no metadata raises assurance

Verification class: **fully_expressible**.

Two decidable checks: (1) a link edge requires an explicit AL3 authorizing act to exist; (2) the assurance function's input set provably excludes the enumerated metadata fields — verifiable by inspecting the function's domain and by a test asserting two sessions from the same device/IP are never linked without an AL3 act. Both are structural and testable.

Required verification methods: static_predicate_test, access_control_test, adversarial_suite.

Source requirement traces: "FR-L7", "FR-H2", "FR-A2"

### INV-8

Static fallback serves correct content with the entire runtime account down

Verification class: **expressible_with_harness**.

This is not a per-event logical predicate over a data structure; it is an operational property that can only be established by executing a destructive drill — tearing down the runtime account and asserting the fallback still serves correct content. It is a decidable pass/fail assertion, but only relative to an executed chaos scenario and a content-correctness oracle, not statically.

Residual control: Scheduled fallback-independence test (monthly per §14.3) that destroys the runtime account's workloads in staging and asserts correct static content; independence is also structurally underwritten by separate account/pipeline/DNS/credentials (verified, not assumed).

Required verification methods: chaos_drill.

Source requirement traces: "FR-F6", "FR-C3", "NFR-2", "PH-1"

### INV-9

Kill switch reaches safe mode within target, and does not disable the fallback

Verification class: **expressible_with_harness**.

Timing ('within target') and the negative ('does not disable the fallback') are pass/fail assertions that require executing a timed kill drill in a live environment; they are not statically decidable from a request object. Additionally the threshold KILL_TARGET is an unresolved open parameter (P1Q-4 / the [target] in FR-L6), so the predicate is not even fully parameterised until that value is set.

Residual control: Monthly timed kill-switch drill whose measured time-to-safe-mode and fallback-availability are gate inputs (§10.4). An untested kill switch is treated as a decoration.

Required verification methods: chaos_drill.

Source requirement traces: "FR-L6", "FR-F6"

### INV-10

No triage feature schema contains criminal-history, immigration-status, or police-contact fields

Verification class: **fully_expressible**.

A pure set-disjointness check over the declared field names of a static, versioned schema artefact — decidable by inspection and enforceable at the gate. This is the most cleanly expressible invariant in the set: no runtime, no NL, no unbounded quantifier.

Required verification methods: schema_inspection.

Source requirement traces: "FR-E7", "R-2", "R-3"

### INV-11

Police-avoidance metrics cannot be serialized without companion measures

Verification class: **fully_expressible**.

The coupling is enforced structurally in the type system and API: the police-avoidance field is not independently serializable. It is verifiable by type-level inspection and by asserting no API/dashboard/export endpoint returns the field without its companions. Decidable and enforced at compile/interface time.

Required verification methods: type_system, static_predicate_test.

Source requirement traces: "FR-K2a", "FR-K2", "FR-K3"

### INV-12

No artefact with `content_class: stub` promotes above `demo`

Verification class: **fully_expressible**.

A universal check over the promotion manifest that every artefact's content_class field is not 'stub', combined with two further decidable checks (interface destination in test-double network; population==synthetic). All operands are structured fields on signed registry artefacts; the gate evaluates them mechanically.

Required verification methods: static_predicate_test, schema_inspection.

Source requirement traces: "PH-3", "FR-L8"

### INV-13

Deterministic components replay bit-identically at pinned versions

Verification class: **expressible_with_harness**.

Bit-identical equality of re-executed output is a decidable comparison, but establishing it requires actually re-running the deterministic components against recorded envelopes at pinned versions inside the replay harness — an environment execution, not a static predicate over a data structure. The invariant is also explicitly scoped to exclude the non-deterministic model, so it is a property of a subsystem under replay rather than a universal system predicate.

Residual control: Replay harness asserts bit-identical output for deterministic components on every audited session; the stateless, version-stamped design makes replay well-defined. Model non-determinism is handled by reporting policy-decision divergence rather than asserting equality.

Required verification methods: replay_harness.

Source requirement traces: "FR-K1", "NFR-17"

### INV-14

Session at T1+ never terminates on system initiative

Verification class: **partially_expressible**.

The tier gate (committed_tier >= T1) and the permitted-cause set are decidable, and 'no timeout-based termination path exists' is verifiable by code-path/reachability analysis. The residual is the notion of 'system initiative': proving that NO execution path (including crashes, unhandled exceptions, dependency failures, or a compromised model inducing an edge-case) ever ends a T1+ session is a reachability property over the whole distributed system, not a single decidable predicate — it approaches the halting/total-coverage problem and cannot be discharged by one runtime check.

Residual control: Structural: no timeout-termination code path at T1+ (asserted by test), and the session gateway re-routes to the static path on any failure signal rather than dropping. Chaos exercises (§12.9) assert that on model/broker/PDP/directory failure and network partition the user reaches the static path or an honest degraded message — i.e. is not dropped — covering the failure-induced termination residual empirically.

Required verification methods: static_predicate_test, chaos_drill.

Source requirement traces: "FR-F3", "FR-F6"

### INV-15

Exposure metrics are not readable at individual granularity by any role

Verification class: **fully_expressible**.

A check over the role/scope model: no role is granted a per-individual exposure-read capability, and the aggregate scope is not co-grantable with any HR/management role. Both are decidable by inspecting the (closed, governed) scope grants and separation-of-duty rules, and testable via access-control tests. Every read being audited is an additional structural assertion.

Required verification methods: access_control_test, schema_inspection.

Source requirement traces: "FR-G5"

### INV-16

No youth-session content is disclosed to the contacting adult without a recorded legal-and-consent basis, and the discreet human-help path is reachable on every youth-flagged turn

Verification class: **partially_expressible**.

The disclosure half is a decidable access-control predicate: no edge from youth-flagged session content to the contacting-adult principal without a recorded legal-and-consent basis whose scope covers the disclosure. The residual: (a) classifying a span as 'youth-session content' and the principal as the 'contacting adult' depends on session-role tagging that is only as good as the upstream (stub) youth detection, and (b) 'the discreet help path is reachable on every youth-flagged turn' is an availability/coverage property established by exercising the flow, not by a single static check.

Residual control: Access-control test asserts no disclosure path youth_content -> contacting_adult without the basis record; the HLD §14.2 coercive-guardian youth adversarial scenarios exercise it; a per-turn UI-availability check covers the discreet-path reachability. Youth-content tagging is a stub in Phase One (FR-I3 rules await legal review).

Required verification methods: access_control_test, adversarial_suite.

Source requirement traces: "FR-I2", "FR-I4"

> This prototype demonstrates control and containment architecture using non-clinical stub logic and synthetic data. It provides no evidence of clinical safety, triage validity, or equity performance, and must not be cited as such.
