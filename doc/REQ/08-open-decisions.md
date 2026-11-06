# Decision answers and system parameters

## Later LLD/workstation/model acceptance — 2026-11-06

The user accepted the recommended local LLD directions and selected this workstation plus `google/gemma-4-12b-qat` in LM Studio. Download availability is user-reported. See the [scoped acceptance record](../LLD/decisions/2026-11-06-implementation-choices-and-model.md). This later instruction supersedes earlier model-selection and proposed-choice wording only within that record’s scope; exact versions/periods and runtime evidence remain pending. Existing numeric values are unchanged.

## Local design acceptance — 2026-11-06

The user approved all five recommendations in [HLD decision options](../HLD/11-decision-requirements-and-options.md). The [acceptance record](../HLD/decisions/2026-11-06-local-design-baseline.md) is authoritative for scope: proxy-managed automated attested workload identity (DEC-01/B), fresh-authority-only private help (DEC-02/A), the proposed event-anchored demo lifecycle (DEC-03/B), separate host recovery journal plus quarantine/independent serving promotion (DEC-04/B), and local inference/youth/safe-mode deltas with separately tracked upstream disposition (DEC-05/A).

This later local overlay supersedes “open/proposed” wording below only for those selected local choices. Original source statuses are preserved; no upstream question is formally closed, product selected, real-account retention period invented, runtime activated or clinical/release approval granted. Existing numerical demo durations and targets are unchanged. Detailed mechanisms and implementation evidence remain pending.

Revision: 2026-11-04. These answers incorporate the user’s stated context: the implementor resides in Ottawa, Canada and has no police links whatsoever. The current system remains a closed synthetic-data demo.

**Confirmed project constraints:** Ottawa-based implementor; no police affiliation or integration; local LM Studio/Gemma; Docker/Kubernetes; independent actor credentials and sessions; human PR review. An actual legal entity, professional qualification, partner contract or independent reviewer has not been identified.

**Proposed engineering defaults:** concrete selections and values below are reviewable implementation answers, not installed components, measured capacity or clinical/legal approval. The inherited source question statuses are retained as provenance; their model nodes have not been changed or formally closed. Clinical/legal/community decisions remain deferred where an engineering answer cannot establish the necessary authority. Suggested stack choices are engineering proposals; they are not a claim that these tools are installed or compatible with the host.

## Parameter use and precedence

[demo-parameters.json](demo-parameters.json) is a machine-readable requirements artifact, not automatically loaded runtime configuration. All times include units. Null means unresolved or unknown; it must never be coerced to zero, permissive access or success. Validate types/ranges and cross-field consistency before implementing configuration. Production startup must reject this demo profile.

Locale, UI limits, retention windows, queue thresholds and test targets are adjustable settings under classified review. Capability absence, police exclusion, synthetic-only admission, approval separation and the demo ceiling are architecture/release constraints: do not implement them as ordinary user-editable toggles. Values have no clinical validation. Benchmark targets are acceptance goals until measured.

Operational defaults apply while the host is running. A stopped laptop cannot meet availability, backup or alert timing targets. Continuous encrypted backups should meet the proposed session RPO only after restore testing demonstrates it.

## Answers to local design decisions

| Decision | Recommended answer / remaining dependency |
|---|---|
| D-01 | Single-node local Kubernetes with enforced default-deny networking, Docker images, private ingress, persistent local storage and separate fallback host process. Select distribution/host routing only after actual host inventory; no hardware capacity claimed. |
| D-02 | Broker-mediated LM Studio; flatten youth enforcement into broker mediation rather than introduce a forbidden authority edge; expose a narrow deterministic human-help path that survives kill. These are local design proposals requiring recorded source-owner disposition where upstream authority contracts conflict. |
| D-03 | Keycloak/OIDC/MFA; distinct accounts and role routes; operation assurance/expiry as `identity`. Actual provider/version/provisioning must pass integration checks. |
| D-04 | PostgreSQL with separate application/audit roles, dedicated audit writer, encrypted host storage/backups and service mTLS; mounted secrets and separate signing-key custody. No cloud KMS/region assurance claim. |
| D-05 | React/TypeScript UI, Python/FastAPI services, OPA/Rego policy, explicit bounded state machine; LM Studio + `google/gemma-4-12b-qat`. Pin supported versions and artifact digest after verification. No general autonomous multi-agent framework. |
| D-06 | First web participant/worker flows with EN/FR and accessibility; then internal SMS/voice/mobile/relay simulators. Ten active sessions is an initial benchmark, not validated throughput. |
| D-07 | Implementor-maintained Ottawa/Ontario fallback, separately reviewed dated official content, separate process/publication outside cluster; full host independence remains unfulfilled. |
| D-08 | Use the grouped, unit-labelled demo defaults in the parameter file; no clinical thresholds are authorized. |
| D-09 | Protected GitHub main, required checks and at least one distinct human reviewer; class-specific specialist review for high-risk changes. If the implementor is alone, prepare candidates but do not fabricate independent approval. |
| D-10 | Describe a synthetic control-and-containment demo, with no clinical/production-readiness claim. This package does not approve upstream source changes or a clinical release. |

## Police independence and revised scope

No police actor, police brief sink, partner contract, connector, data-sharing workflow or law-enforcement analytics belongs in this demo. No automated emergency contact belongs in it either. Historical police-specific source requirements stay in the trace with **excluded by current user scope** disposition. This does not assert FRS conformance for those requirements. Ordinary user-controlled export is not a police integration.

A project’s own independence cannot guarantee what an external service may do, or establish exemption from applicable legal duties. Verify each future service’s governance, catchment and police-involvement conditions independently; do not label a third party “no police links” on the basis that it offers non-police response. No live external service is enabled by these answers.

## Inherited questions: answer and disposition

### AQ-1 — FRS:Q-1

Which organization operates the system, and is it credibly independent of police?

**Disposition: Answered for demo.** Operate as an independent Ottawa-based project maintained by the implementor, with no police affiliation, partnership, account, role, connector, funding dependency or data-sharing arrangement asserted. The legal entity/name is not supplied and must not be invented. An independent project is not thereby a licensed clinical service.

Parameters: `demo-parameters.json` → `operator`. Original register: open; source owner: Sponsor; needed by: Before pilot; blocks: ["pilot"].

### AQ-2 — FRS:Q-2

Initial deployment jurisdictions and verified non-police pathway coverage in each

**Disposition: Answered for demo.** Base the project in Ottawa, Ontario, Canada; use America/Toronto time and English/French UI. Ottawa residence does not determine every user’s location. Require explicit service jurisdiction and catchment confirmation. Use fictional CA-XX/CA-YY services in the demo; Ottawa is a future discovery region, not a claim of verified coverage. Gatineau/Quebec routing is outside the initial jurisdiction.

Parameters: `demo-parameters.json` → `locale`. Original register: open; source owner: Product Owner; needed by: Before pilot; blocks: ["pilot"].

### AQ-3 — FRS:Q-3

Clinical authorship and validation of the T0–T4 tier definitions

**Disposition: Demo mechanism selected; clinical decision deferred.** Use engineering-authored, versioned T0–T4 fixture outputs labelled NON_CLINICAL. A fixture scenario selects a result; the model cannot assign an authoritative clinical tier. Keep the empty core triage-feature contract. Clinician-authored definitions and validation remain prerequisites for any clinical release.

Parameters: `demo-parameters.json` → `triage`. Original register: open; source owner: Clinical Safety Lead; needed by: Before build; blocks: ["build"].

### AQ-4 — FRS:Q-4

Numeric targets for success criteria (§2.3) and FR-K3

**Disposition: Demo targets selected; clinical targets deferred.** Require all approved containment, authorization, hazard-routing and handoff scenarios to pass. Report denominators, unknown outcomes and safety/access/equity companions. No target reduction in police attendance or acceptable clinical under-triage rate is invented. Real-world comparative targets require a baseline and clinical/equity review.

Parameters: `demo-parameters.json` → `evaluation`. Original register: open; source owner: Clinical Safety Committee; needed by: Before pilot; blocks: ["pilot"].

### AQ-5 — FRS:Q-5

Confidence threshold for FR-B7 / FR-F2 escalation

**Disposition: Answered for demo.** Do not use LLM self-reported numeric confidence as a clinical threshold. Escalate on unknown or conflicting safety-critical information, fixture tier T2+, youth/age uncertainty, explicit human request, or parser/policy uncertainty. Unknown confidence cannot mean low risk. A future calibrated clinical threshold remains null.

Parameters: `demo-parameters.json` → `escalation`. Original register: open; source owner: Clinical Safety Committee; needed by: Before build; blocks: ["build"].

### AQ-6 — FRS:Q-6

Mandatory-reporting obligations per jurisdiction and their effect on FR-H4 wording

**Disposition: Demo boundary answered; legal determination deferred.** No real disclosures or mandatory-reporting automation in the synthetic demo. Jurisdiction-specific confidentiality wording and exceptional disclosure rules must be versioned and reviewed before real use. Lack of police affiliation does not create a legal exemption or justify promising absolute confidentiality. Do not infer the operator’s PHIPA status from residence.

Parameters: `demo-parameters.json` → `legal`. Original register: open; source owner: Legal counsel; needed by: Before pilot; blocks: ["pilot"].

### AQ-7 — FRS:Q-7

SaMD classification determination (NFR-14)

**Disposition: Demo boundary answered; regulatory determination deferred.** Document intended use as a closed synthetic containment prototype without diagnosis or treatment claims. Do not declare the software exempt or assign a medical-device class on that basis alone. Health Canada classification of a future product depends on intended use and functions; obtain the determination before clinical deployment.

Parameters: `demo-parameters.json` → `legal`. Original register: open; source owner: Regulatory lead; needed by: Before build; blocks: ["build"].

### AQ-8 — FRS:Q-8

MCRT referral schema agreement with at least one partner (FR-C4)

**Disposition: Answered for demo; real agreement deferred.** Use a versioned internal referral schema and isolated receiving-service simulator; no partner agreement is claimed. Candidate local services require direct verification of catchment, police independence, consent, interface and acceptance before any later integration. No real connection is enabled.

Parameters: `demo-parameters.json` → `referral`. Original register: open; source owner: Partnerships lead; needed by: Before pilot; blocks: ["pilot"].

### AQ-9 — FRS:Q-9

De-escalation brief format agreement with at least one police service (FR-C6)

**Disposition: Not applicable to revised demo scope.** No police partnership or police-specific brief format will be implemented. Remove the police-recipient actor and police-brief sink from the proposed demo scope. A generic participant-controlled care-summary export may serve user-directed sharing after authorization; it is not addressed/transmitted to police. Mark upstream FR-C6 and related source assumptions as a documented scope divergence, not satisfied or deleted.

Parameters: `demo-parameters.json` → `police`. Original register: open; source owner: Partnerships lead; needed by: Before pilot; blocks: ["pilot"].

### AQ-10 — FRS:Q-10

Retention periods for all data classes (§8.1)

**Disposition: Demo defaults selected; legal retention deferred.** Adopt the synthetic retention schedule in the parameter file. Keep source fixtures and reviewed artifact manifests in version control; expire runtime content independently. Seven-year clinical audit retention is not imposed on a disposable synthetic demo, but its difference from FRS is recorded. Real retention and exception schedules require privacy/legal approval.

Parameters: `demo-parameters.json` → `retention`. Original register: open; source owner: Privacy Officer; needed by: Before build; blocks: ["build"].

### AQ-11 — FRS:Q-11

Whether the system operates under any existing crisis line's licence and governance, or standalone

**Disposition: Answered for demo.** Standalone independent project; no crisis-line licence, institutional sponsorship or partner governance is claimed. A staffed role-play console is not a contracted crisis service. Real-user operation needs its own operator, governance and staffed partner decisions.

Parameters: `demo-parameters.json` → `operator`. Original register: open; source owner: Sponsor; needed by: Before build; blocks: ["build"].

### AQ-12 — FRS:Q-12

Youth safeguarding, mature-minor, parental-access, and mandatory-reporting rules per initial jurisdiction

**Disposition: Demo safeguards selected; legal rules deferred.** Treat possible minor status and unknown age conservatively for human role-play escalation. Do not equate age alone with capacity or automatically give guardians access. Use separate private sessions, field-level permission and recorded disclosure basis. Production mature-minor, capacity and reporting rules need Ontario legal/clinical review; they are not an unrestricted settings dropdown.

Parameters: `demo-parameters.json` → `youth`. Original register: open; source owner: Legal and Clinical Safety Leads; needed by: Before pilot; blocks: ["pilot"].

### AQ-13 — FRS:Q-13

Service-directory ownership, authoritative sources, freshness classes, and critical-correction SLA

**Disposition: Answered for demo.** The implementor is the initial directory maintainer; separate maintenance from approval. Synthetic feeds are authoritative only for fictional services. Real discovery starts with service operators’ official information; aggregators are leads requiring verification. Store per-field source, owner, method, verification time and catchment. Use the freshness/suspension parameters below.

Parameters: `demo-parameters.json` → `directory`. Original register: open; source owner: Product and Operations Leads; needed by: Before build; blocks: ["build"].

### AQ-14 — FRS:Q-14

Human escalation overload states, mutual-aid partners, and maximum wait representations

**Disposition: Answered for demo; staffing deferred.** Role-play the five source operating states with explicit partner status and a manual scenario override. Unknown staffing means unavailable/unknown, never a fabricated wait estimate. No mutual-aid contract exists. Queue waiting never creates a police fallback. Use demo operational thresholds, retain accompaniment and independent help information.

Parameters: `demo-parameters.json` → `queue`. Original register: open; source owner: Operations lead; needed by: Before pilot; blocks: ["pilot"].

### AQ-15 — FRS:Q-15

Assurance levels for cross-channel continuation, crisis-plan access/editing, referral, export, and deletion

**Disposition: Answered for demo.** Retain AL0 resume, AL1 plan view, AL2 plan edit/referral consent and AL3 export/delete/link. These operate inside the separate authenticated participant perimeter. Use one-use continuation credentials, expiry/rotation, step-up and the parameterized cooling-off; emergency access to human help is not gated by these operations.

Parameters: `demo-parameters.json` → `identity`. Original register: open; source owner: Security and Privacy Leads; needed by: Before build; blocks: ["build"].

### AQ-16 — FRS:Q-16

Classified change-control matrix and approval authorities for high-risk changes

**Disposition: Answered for demo; external reviewers still required.** C0 non-behavioral/documentation; C1 ordinary application changes; C2 model/prompt/infrastructure/security behavior; C3 triage, consent, disclosure, emergency, youth and tool-authority changes. Require a distinct human reviewer and class-appropriate specialist review; the implementor cannot approve their own change through another account. If no independent reviewer exists, keep the candidate unmerged and the accepted baseline usable.

Parameters: `demo-parameters.json` → `governance`. Original register: open; source owner: Governance bodies; needed by: Before build; blocks: ["build"].

### AQ-17 — FRS:Q-17

Whether any future autonomous emergency-contact capability will be considered; if so, under what independent approval process

**Disposition: Excluded from current product scope.** No autonomous emergency contact now or on the roadmap. This is an absent capability, not a user-tunable boolean. Any future proposal is a new separately approved scope, architecture and safety case; ordinary configuration cannot enable it.

Parameters: `demo-parameters.json` → `police`. Original register: open; source owner: Sponsor, Clinical Safety, Equity Council and Legal; needed by: Post-pilot only; blocks: ["post-pilot"].

### AQ-18 — SAD:AQ-1

Concrete triage-logic artefact format and the runtime contract between the Assessment state machine and the Triage policy service

**Disposition: Answered for demo.** Use versioned JSON fixture artifacts validated against JSON Schema; separate assessment assertion storage from the closed core triage contract. Broker submits the permitted empty factor shape and pinned tier-set version; stub fixture selection is explicit test context, not model-derived clinical features. Reject unknown fields and preserve source-owner review requirements for any successor clinical contract.

Parameters: `demo-parameters.json` → `triage`. Original register: open; source owner: Clinical Safety Lead; needed by: Before build; blocks: ["build"].

### AQ-19 — SAD:AQ-2

Hazard-screen implementation for the Turn pre-processor and its false-negative budget within the 5 s constraint

**Disposition: Demo mechanism selected; clinical sensitivity deferred.** Run a deterministic fixture hazard screen before model generation; verify every approved hazard scenario triggers within five seconds. Unknown inputs have an uncertainty/human path. No finite keyword suite proves zero clinical false negatives. Measure scenario misses; real sensitivity and false-negative budgets remain unapproved.

Parameters: `demo-parameters.json` → `evaluation`. Original register: open; source owner: Clinical Safety Committee; needed by: Before build; blocks: ["build"].

### AQ-20 — SAD:AQ-3

Consent-ledger schema, expiry semantics, and revocation propagation across in-flight actions

**Disposition: Answered for demo.** Append-only grant/revoke ledger with exact purpose/recipient/subject/session matching and requested-field subset. Require now < expiry. Re-evaluate current revocation state in the transaction that authorizes transmission; record revocation order and in-flight outcomes. Do not cache positive consent decisions across actions. Completed transmissions cannot be reversed.

Parameters: `demo-parameters.json` → `consent`. Original register: open; source owner: Privacy Officer; needed by: Before build; blocks: ["build"].

### AQ-21 — SAD:AQ-4

Service-directory freshness-class thresholds and critical-correction suspension SLA (the [target] in FR-C2a)

**Disposition: Answered for demo.** Use separate structural, operational and near-real-time TTLs; event-specific facts require a fresh check at action time. Stale or missing data is unknown and is never represented as current. Suspend confirmed critical inaccuracies within sixty seconds; record detection/confirmation/suspension timestamps separately. These are demo engineering defaults, not provider guarantees.

Parameters: `demo-parameters.json` → `directory`. Original register: open; source owner: Product and Operations Leads; needed by: Before build; blocks: ["build"].

### AQ-22 — SAD:AQ-5

Static crisis-path content ownership, per-jurisdiction dataset, and independent deploy pipeline

**Disposition: Ownership proposed; publication remains gated.** The implementor owns the independent fallback publication process, with a separate human content reviewer. Maintain an Ottawa/Ontario EN/FR content bundle from official providers, dated and reviewed at least every thirty days and on reported change. Verify content before admitting demo participants. Local fallback must survive cluster failure; whole-host independence requires separate hosting and is not claimed.

Parameters: `demo-parameters.json` → `fallback`. Original register: open; source owner: Fallback content owner; needed by: Before pilot; blocks: ["pilot"].

### AQ-23 — SAD:AQ-6

Escalation operating-state thresholds, mutual-aid routing, and maximum-wait representations

**Disposition: Answered for demo.** Use queue thresholds in parameters as fixture behavior only. Explicit unavailable/outage partner states override numerical load. Do not calculate a promised wait without validated live data; display unknown. No escalation from waiting duration to police contact.

Parameters: `demo-parameters.json` → `queue`. Original register: open; source owner: Operations lead; needed by: Before pilot; blocks: ["pilot"].

### AQ-24 — SAD:AQ-7

Per-operation assurance levels for continuation, plan access/edit, referral, export, deletion

**Disposition: Answered for demo.** Same assurance policy as AQ-15; one configuration source for all channels. Every sensitive action checks current role/ownership/consent independently of possession of a continuation token.

Parameters: `demo-parameters.json` → `identity`. Original register: open; source owner: Security and Privacy Leads; needed by: Before build; blocks: ["build"].

### AQ-25 — SAD:AQ-8

Referral schema and per-partner adapter model with at least one MCRT

**Disposition: Answered for demo.** Canonical referral JSON schema plus adapter-specific mappings, all versioned. Internal simulator supports acceptance, rejection, timeout, partial acceptance and schema rejection. Stable idempotency keys, outbox and receipt reconciliation are required. No real partner adapter can be activated without a separately reviewed agreement.

Parameters: `demo-parameters.json` → `referral`. Original register: open; source owner: Partnerships lead; needed by: Before pilot; blocks: ["pilot"].

### AQ-26 — SAD:AQ-9

De-escalation brief format and confirmed-receipt handling per police service

**Disposition: Not applicable to revised demo scope.** No police recipient, connector, service agreement, receipt workflow or police brief. Generic care-summary export is distinct, subject to own-data/consent controls. Preserve upstream question and requirement references as excluded scope; a later police workflow cannot be enabled with configuration.

Parameters: `demo-parameters.json` → `police`. Original register: open; source owner: Partnerships lead; needed by: Before pilot; blocks: ["pilot"].

### AQ-27 — SAD:AQ-10

Retention engine rules per data class and jurisdiction

**Disposition: Answered for demo.** Use scheduled expiry with tombstones and restore-time filtering. Content expiry, durable audit metadata and repository fixtures are different classes. Reject undefined retention classes. Real legal hold and clinical record schedules remain unapproved; use the demo retention schedule only.

Parameters: `demo-parameters.json` → `retention`. Original register: open; source owner: Privacy Officer; needed by: Before build; blocks: ["build"].

### AQ-28 — SAD:AQ-11

Indigenous-data classification tagging and framework-specific storage/access routing

**Disposition: Demo mechanism selected; community governance deferred.** Use only synthetic governance tags: unspecified, First Nations, Inuit, Metis, urban Indigenous, or a fictional community identifier. Self-declared service preference is not authority to classify a real person or Nation. No automatic ethnicity inference or blanket OCAP substitution. Real storage/access rules require the applicable community agreement before collection.

Parameters: `demo-parameters.json` → `indigenous_governance`. Original register: open; source owner: Indigenous data governance partner; needed by: Before build; blocks: ["build"].

### AQ-29 — SAD:AQ-12

SaMD classification and its effect on the change-control and validation architecture

**Disposition: Regulatory determination deferred.** Keep intended-use/version history, classified changes, artifact evidence and release gates ready to attach the eventual regulatory assessment. Do not choose a SaMD class or compliance pathway without an actual intended-use assessment.

Parameters: `demo-parameters.json` → `legal`. Original register: open; source owner: Regulatory lead; needed by: Before build; blocks: ["build"].

### AQ-30 — SAD:AQ-13

Classified change-control matrix wired to the release-gating pipeline

**Disposition: Answered for demo.** Implement the AQ-16 classification in required PR checks and release manifests. Bind independent reviewer receipts to the exact artifact digests; invalidate approval after material change. No editable approval flag and no self-approval.

Parameters: `demo-parameters.json` → `governance`. Original register: open; source owner: Governance bodies; needed by: Before build; blocks: ["build"].

### AQ-31 — SAD:AQ-14

Whether/how a future autonomous emergency-contact capability could ever be architected under independent approval

**Disposition: Excluded from current product scope.** Same absent-capability rule as AQ-17. No autonomous emergency connector, endpoint credential, network route or feature toggle will be shipped.

Parameters: `demo-parameters.json` → `police`. Original register: open; source owner: Sponsor, Clinical Safety, Equity Council and Legal; needed by: Post-pilot only; blocks: ["post-pilot"].

### AQ-32 — HLD:P1Q-1

Cloud provider and the two Canadian regions

**Disposition: Not applicable to local demo.** No cloud provider or two-region deployment is required for this host-local demo. Processing/storage location is the configured Ottawa host, subject to verification that telemetry, backups and inference do not leave the allowed boundary. Local residence alone is not proof of data residency. Production regional redundancy remains deferred.

Parameters: `demo-parameters.json` → `deployment`. Original register: open; source owner: Architect + Security; needed by: M0; blocks: ["M0"].

### AQ-33 — HLD:P1Q-2

Policy engine selection (OPA/Rego vs Cedar) and bundle signing approach

**Disposition: Engineering selection proposed.** Select OPA/Rego for deterministic policy evaluation and sign immutable bundle digests with a dedicated Ed25519 release key. Verify signature/key identity before activation; key custody is distinct from CI/application credentials. Keep policy approval semantics outside the LLM. Validate selected runtime/library versions during implementation rather than treating this choice as installed.

Parameters: `demo-parameters.json` → `stack`. Original register: open; source owner: Architect + Security; needed by: M1; blocks: ["M1"].

### AQ-34 — HLD:P1Q-3

Inference provider, Canadian-region guarantee, retention and training terms

**Disposition: Answered for demo.** Inference is local LM Studio with `google/gemma-4-12b-qat` on the Ottawa host, broker-mediated only. Disable prompt/content logging and remote telemetry where supported; prove behavior in acceptance tests. No remote inference fallback, no training pipeline. Exact model artifact digest and supported server features must be measured before acceptance.

Parameters: `demo-parameters.json` → `inference`. Original register: open; source owner: Procurement + Security; needed by: M2; blocks: ["M2"].

### AQ-35 — HLD:P1Q-4

Kill-switch target time (the [target] in FR-L6) for Phase One measurement

**Disposition: Demo target selected.** Measure safe-mode acknowledgement within two seconds p95 and five seconds maximum across the declared test load. Any maximum miss fails the drill. Cancel/fence pending model responses, block new actions and preserve human request/fallback; do not kill the only help route.

Parameters: `demo-parameters.json` → `operations`. Original register: open; source owner: Operations + Security; needed by: M5; blocks: ["M5"].

### AQ-36 — HLD:P1Q-5

Directory freshness-class thresholds and correction SLA for the synthetic directory

**Disposition: Answered for demo.** Use the same directory freshness and suspension settings as AQ-21; one parameter source prevents drift between runtime, UI and tests.

Parameters: `demo-parameters.json` → `directory`. Original register: open; source owner: Product + Operations; needed by: M4; blocks: ["M4"].

### AQ-37 — HLD:P1Q-6

Retention durations for synthetic corpora and audit content-access grants

**Disposition: Answered for demo.** Expire synthetic runtime records and replay corpora according to the retention table. Audit content access grants last at most fifteen minutes, require justification and are audited. Digests/metadata are not free of sensitivity merely because content is omitted.

Parameters: `demo-parameters.json` → `retention`. Original register: open; source owner: Privacy Officer; needed by: M3; blocks: ["M3"].

### AQ-38 — HLD:P1Q-7

Composition and terms of reference for the Phase One red team

**Disposition: Demo approach selected; reviewer recruitment pending.** Use an independent human security reviewer plus implementor as test operator; add clinical/equity expertise before clinical or community claims. Scope attacks to isolated demo accounts/simulators; prohibit real-service traffic, give content warnings and stop/debrief options, and log findings without real crisis stories. Automated red-team generation is supplementary and cannot replace independent review.

Parameters: `demo-parameters.json` → `participants`. Original register: open; source owner: Security; needed by: M9; blocks: ["M9"].

### AQ-39 — HLD:P1Q-8

Participant recruitment, safeguarding protocol and compensation

**Disposition: Demo recruitment boundary selected.** Begin with adult, informed, opt-in project collaborators exercising fictional scenarios. No recruitment of people currently seeking crisis care; no request for personal histories. Allow immediate withdrawal, content controls and debrief. Default unpaid collaborator testing; do not recruit public usability subjects until consent, independent safeguards and a stated compensation budget are agreed.

Parameters: `demo-parameters.json` → `participants`. Original register: open; source owner: Product + Equity Council; needed by: M2; blocks: ["M2"].

### AQ-40 — HLD:P1Q-9

Indigenous data classification tagging design

**Disposition: Answered for demo.** Use the same explicit synthetic tagging mechanism as AQ-28. No real Indigenous personal/community data or inferred affiliation; no claim that an engineering tag implements a community governance framework.

Parameters: `demo-parameters.json` → `indigenous_governance`. Original register: open; source owner: Indigenous data governance partner; needed by: M3; blocks: ["M3"].

### AQ-41 — HLD:P1Q-10

Which two synthetic jurisdictions, and whether they shadow real jurisdictional structures

**Disposition: Answered for demo.** Retain CA-XX and CA-YY as visibly fictional Ontario-inspired administrative fixtures. Keep Ontario/Ottawa deployment locale separate from synthetic service jurisdiction. A Quebec-inspired fixture would require its own reviewed configuration; cross-river location cannot silently inherit Ontario rules.

Parameters: `demo-parameters.json` → `locale`. Original register: open; source owner: Product + Legal; needed by: M4; blocks: ["M4"].

### AQ-42 — HLD:P1Q-11

Whether the audit checkpoint publication uses an internal or external transparency mechanism

**Disposition: Demo mechanism selected; independence limited.** Publish signed audit-chain checkpoints every sixty seconds to a separate local append-only target with separate credentials; audit-reader access cannot alter them. Export checkpoint digests with release evidence. This detects some tampering but is not an independent external transparency service and cannot withstand total host compromise. External publication remains deferred.

Parameters: `demo-parameters.json` → `audit`. Original register: open; source owner: Security + Governance; needed by: M8; blocks: ["M8"].

### AQ-43 — HLD:P1Q-12

Definition of "critical finding" for adversarial gate-blocking

**Disposition: Answered for demo.** Critical means any unauthorized disclosure/action, cross-session leakage, consent bypass, machine emergency reachability, identity/approval forgery, audit-integrity bypass, stub promotion, or loss of both supported interaction and fallback. One confirmed reproducible critical finding blocks release until fixed and independently retested. Do not reduce severity merely because data is synthetic.

Parameters: `demo-parameters.json` → `evaluation`. Original register: open; source owner: Security + Clinical Safety; needed by: M1; blocks: ["M1", "promotion above demo"].

### AQ-44 — FRS:FR-C7[param]

Outcome capture rate target for pathway-outcome recording (FR-C7)

**Disposition: Demo target selected.** Require every scripted recommended pathway to have an outcome record. Record pending, declined, unavailable and unknown explicitly; unknown is a captured outcome state, not a successful care outcome. Report both capture coverage and confirmed successful handoff separately.

Parameters: `demo-parameters.json` → `evaluation`. Original register: open; source owner: TBD; needed by: TBD; blocks: [].

### AQ-45 — FRS:FR-D1[param]

Maximum words per de-escalation guidance unit (FR-D1)

**Disposition: Demo content limit selected.** Use at most twenty-five words per guidance unit and one action per unit; human-authored NON_CLINICAL placeholder text only. EN/FR must be reviewed independently for meaning and stress usability. This is an adjustable presentation limit, not clinical endorsement.

Parameters: `demo-parameters.json` → `content`. Original register: open; source owner: TBD; needed by: TBD; blocks: [].

### AQ-46 — FRS:FR-D2[param]

Minutes of tolerated user silence before prompting (FR-D2)

**Disposition: Demo behavior selected.** Prompt gently after two minutes of silence, then at most once every five minutes; include a discreet/silent mode. No session termination or risk promotion solely due to silence. Verify at least thirty minutes of silence plus longer clock-advanced tests. Alert an already assigned worker when the approved fixture requires it.

Parameters: `demo-parameters.json` → `content`. Original register: open; source owner: TBD; needed by: TBD; blocks: [].

### AQ-47 — FRS:FR-E5[param]

Acceptable disparity threshold and the authority to change it (FR-E5 / §13.2)

**Disposition: Clinical/equity threshold deferred; demo diagnostic selected.** Do not encode a universal acceptable disparity as clinically approved. Use a five-percentage-point absolute gap as a synthetic test alert only, with denominators, missingness and minimum cohort size. It does not prove fairness and cannot approve deployment. Only an authorized equity/clinical governance decision may set production thresholds.

Parameters: `demo-parameters.json` → `evaluation`. Original register: open; source owner: TBD; needed by: TBD; blocks: ["pilot"].

### AQ-48 — FRS:FR-F2[param]

Complexity/duration escalation-limit values (FR-F2)

**Disposition: Demo triggers selected.** Request a human after ten assessment turns or ten minutes of active automated assessment, two consecutive invalid proposals, conflicting safety reports, unresolved critical fields, youth/age uncertainty or any explicit request. These are conservative fixture triggers, not termination limits. Accompaniment continues after triggering.

Parameters: `demo-parameters.json` → `escalation`. Original register: open; source owner: TBD; needed by: TBD; blocks: [].

### AQ-49 — FRS:FR-F5[param]

Maximum take-over transfer time (FR-F5)

**Disposition: Demo target selected.** Supervisor takeover completes within two seconds p95 and five seconds maximum under declared load, including cancellation/fencing of agent delivery. A timeout preserves existing support and reports failure; it must not announce successful takeover.

Parameters: `demo-parameters.json` → `operations`. Original register: open; source owner: TBD; needed by: TBD; blocks: [].

### AQ-50 — FRS:FR-G2[param]

Worker-rated summary-accuracy target (FR-G2)

**Disposition: Demo target selected.** Require every safety-critical structured fact and source attribution in the approved synthetic summary to be correct, with zero fabricated facts; target at least ninety-five percent correct required noncritical fields. A worker reviews/edits before use; do not equate this fixture metric with clinical summary validity.

Parameters: `demo-parameters.json` → `evaluation`. Original register: open; source owner: TBD; needed by: TBD; blocks: [].

### AQ-51 — FRS:FR-H5[param]

Days to complete user-initiated deletion across stores and backups (FR-H5)

**Disposition: Demo deletion target selected.** Remove eligible runtime content from active stores within twenty-four hours; expire backup copies within seven days and apply tombstones before any restore becomes accessible. Preserve only explicitly retained minimal audit metadata, report exceptions and do not claim all personal data is erased if retained metadata remains linkable. No crypto-erasure claim without verified key isolation.

Parameters: `demo-parameters.json` → `retention`. Original register: open; source owner: TBD; needed by: TBD; blocks: [].

### AQ-52 — FRS:FR-K4[param]

Hours to initiate mandatory post-incident review (FR-K4)

**Disposition: Demo response target selected.** For a reported simulated serious incident, acknowledge and enter restricted mode immediately when containment is uncertain; begin documented review within four hours. A real participant-safeguarding event takes priority over the simulation and requires human support/escalation under the participation protocol. Four hours is a demo operational target, not a statutory deadline.

Parameters: `demo-parameters.json` → `operations`. Original register: open; source owner: TBD; needed by: TBD; blocks: [].

### AQ-53 — FRS:NFR-9[param]

Peak concurrent sessions per region sustained without degradation (NFR-9)

**Disposition: Initial test envelope selected; capacity unverified.** Target ten concurrent active UI sessions, two concurrent inference jobs and eight queued inference requests, with explicit backpressure and independent human-help capacity. This is a starting benchmark, not measured capacity. Reduce accepted demo load or improve resources if source latency budgets fail; do not silently relax latency or use remote inference.

Parameters: `demo-parameters.json` → `capacity`. Original register: open; source owner: TBD; needed by: TBD; blocks: [].

## Realtime governance clarification

[TR-GOV-06…12](04-data-security-governance.md) specify inline enforcement, effective policy epochs, live activation/revocation, execution checks, fail-closed behavior and preserved human help. `demo-parameters.json` → `runtime_governance` contains proposed latency and propagation targets. These extend AQ-16/AQ-30/AQ-33 and D-02/D-08/D-09; no upstream question is formally closed or clinical approval granted. AT-14 verifies the runtime behavior.

## External evidence consulted

Checked 2026-11-04. External sources support jurisdiction context only; they neither endorse CARE-Link nor approve these proposed parameters.

- Ontario privacy guidance treats consent/capacity in context; residence and a guardian relationship alone do not settle access rights: [Information and Privacy Commissioner of Ontario — Consent and your personal health information](https://www.ipc.on.ca/en/health-individuals/consent-and-your-personal-health-information).
- A future medical-device assessment must consider software intended use and functions: [Health Canada — Software regulated as a medical device](https://www.canada.ca/en/health-canada/services/drugs-health-products/medical-devices/activities/announcements/questions-answers-software-regulated-medical-device.html).
- Ottawa describes a community alternative-response program, but this is neither a CARE-Link partnership nor proof of zero institutional police links: [City of Ottawa — What is ANCHOR](https://ottawa.ca/en/family-and-social-services/community-safety-and-well-being-cswb-plan/priorities/mental-well-being/alternate-neighbourhood-crisis-response-anchor/what-anchor) and [City of Ottawa — June 2026 expansion memorandum](https://ottawa.ca/en/city-hall/open-transparent-and-accountable-government/public-disclosure/memoranda-issued-members-council/memoranda-issued-community-and-social-services/memo-update-expansion-alternate-neighbourhood-crisis-response-anchor-mental-health-and-substance-use-0).

> This prototype demonstrates control and containment architecture using non-clinical stub logic and synthetic data. It provides no evidence of clinical safety, triage validity, or equity performance, and must not be cited as such.
