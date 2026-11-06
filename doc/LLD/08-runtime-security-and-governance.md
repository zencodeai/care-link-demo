# Runtime security, governance and artifact activation

## Single authorization pipeline

All human commands, internal calls, agent tools, jobs, reads, streams and exports use: authenticate current peer/human→validate closed schema/bounds→resolve metadata-only authority→evaluate PDP→satisfy obligations→final guarded current-state check→commit canonical audit and state/effect intent→release projection or invoke authorized effect. An authorization bootstrap endpoint returns only ownership/assignment/consent/source versions and predicates, not transcript/plan values. Caller/model input is never a role/assurance/consent fact.

PolicyInput binds operation ID, originating principal plus workload/task/job, action, exact resource/scope/purpose/fields, tags/jurisdiction, payload digest, current identity/roles/subject/session/assignment/directory/resource revisions, policy/control/serving epochs, journal barrier, consent/review metadata, artifacts, mode, audit readiness and explicit unknowns. The closed wire contract is insufficient by itself: constructors accept only verified server lookups and deny incomplete authority. PDP output binds that exact canonical input digest and vector, bundle digest, reasons, expiry and closed obligation union. PERMIT expires≤1000ms and is one-operation, never cached. Evaluation target p95≤50ms, timeout200ms; full authorization budget≤1000ms. Retry does not extend the original deadline.

Obligations are audit_before_effect, project_fields, exact_human_review and approved_template. Unknown kind, failed audit, impossible projection, mismatched digest or missing review denies. REQUIRE_HUMAN creates an authorized review item; it is not a provisional permit. Independent emergency guard and immutable scope exclusions deny police integration/autonomous emergency contact/real-data or production promotion even if a faulty bundle says permit.

## PEP ownership

| Boundary | PEP / final authority |
|---|---|
| Browser admission/request | BFF current identity + core operation PEP; no forwarded caller authority |
| Business read/write | Data gateway named projection/command, guard/revision check and field filters |
| Agent step/tool/model context | Broker/task PEP, durable capability and source/lease/budget validation |
| Worker handoff/message/receiver package | Workforce/referral and receiving projection PEP, current ownership/consent |
| Stream/export | Per-event/download disclosure PEP and canonical audit-before-bytes |
| Jobs/retry/dispatch | Original purpose plus job identity, current permission and one-use effect authorization |
| Activation/hold/exception/recovery | Control PEP with actual independent human receipt, exact digest and expiry |
| Private host help | Narrow fresh authority decision + spool own-request predicate, no general PDP/history bypass |
| Network/store/host | Proxy peer/method policy plus CNI/firewall/DB grants, independently tested |

## Approval and activation algorithm

Artifact manifest binds type/version/source revision/digest, compatibility, population/content class, required change class/evidence and signer provenance. Register immutable bytes; verify Ed25519 signature with current trusted signer keys. Signature proves provenance, not human authority. Determine C0..C3 with the source classification matrix; ambiguous or model/clinical/consent/tool-authority changes get high-risk review, never routine UI classification. Reviewer receipt stores exact digest, authority class, actual human identity, decision and expiry/evidence. Proposer≠reviewer human, even with multiple accounts; agent/CI identity is never a human.

Activation state proposed→staged→ready→active/rejected/superseded. Stage immutable candidate in evaluators; require each required instance ACK exact digest/epoch/boot ID after validation and self-check. New process/restart invalidates prior ACK. Relaxation waits all required healthy ACKs and applicable human review before guarded epoch switch. Restrictive activation first commits current restrictive fence/journal barrier at central boundary, then notifies instances; lagging/disconnected instances deny affected operations. Bundle evaluators switch atomically per instance; final authority requires current central epoch/digest so an old evaluator cannot issue useful permission. Events accelerate propagation≤1000ms target but no notification is trusted as sole enforcement.

Rollback is a new higher epoch selecting a compatible earlier artifact, retaining latest credential/consent/sharing/deletion/hold restrictions and serving generation. No epoch decrement, old review resurrection or independent mixing of component versions. Failed activation stays restricted/current safe bundle; record desired/effective/ACK state. Future effective_at is checked server-side; clock uncertainty blocks time-sensitive activation. Secret/signing key rotation requires overlap/revocation lineage and exact artifact evidence.

Exceptions bind a specific overridable rule, scope, artifact/epoch, independent approver receipt, compensating control and expiry. Check expiry at every final authorization, not just a cleanup job. Never waive fixed no-police/no-autonomous-emergency, synthetic-only, no-self-approval or demo ceiling. Expired/unsupported exceptions deny affected permission. Clinical/legal/community judgement not encoded as a deterministic approved rule remains human/stubbed and cannot be inferred by the PDP.

## Security signals and deterministic containment

| Validated trigger | Bounded response | Recovery |
|---|---|---|
| Malformed/schema/forbidden request | Deny exact operation, safe error and linked security event | Correct input; no automatic participant ban |
| Poisoned/unsigned/conflicting feed | Quarantine record/version; preserve admitted alternatives/unknown status | Source-owner correction and reviewed admission |
| Compromised account/workload | Journalled identity/workload fence; stop new operations, subscriptions, queued work; drain active channels | Current credentials rotated, human containment review, fresh local grants |
| Critical containment drift | Restrict affected capability/workload immediately; AI disable/safe mode if validated broad breach | Exact approved manifest/network/identity proof and authorized recovery |
| Low-confidence anomaly | Scope-limited rate reduction/review, preserve mandatory help | Human triage; no model-triggered global shutdown |
| Real-data contamination | Fence affected data/capability, isolate evidence, incident review | Authorized minimization/cleanup under rights/hold rules; no uncontrolled export |

Drift check at startup, activation, readiness and every 30seconds target compares approved digests/endpoints/privilege/network/issuer state; compromised monitoring cannot grant permission. Denial is before effect; response propagation, drift discovery, dashboard≤5seconds and critical alert≤30seconds are distinct measurements. Quarantine release is a new current human-authorized action; no automatic scope expansion.

## Standards register

Local controls LC-IDENTITY, LC-SCOPE, LC-CONSENT, LC-AGENT, LC-NETWORK, LC-ARTIFACT, LC-AUDIT, LC-LIFECYCLE, LC-RECOVERY and LC-OPERATIONS map to the requirement controls and concrete tests in chapter13. Each record includes risk family, operation/PEP/PDP owner, policy digest, negative test/evidence status, residual and human role. Exact OWASP ASVS5.0.0, OWASP LLM2025/agentic and MITRE ATLAS identifiers remain unresolved until pinned official artifacts and applicable denominator are verified. No invented numeric technique IDs, certification or claimed clause-level ISO review. The [REQ standards baseline](../REQ/09-standards-and-runtime-controls.md) remains the reference for NIST AI RMF/Zero Trust, ISO42001, SSF/CAEP and optional OSCAL distinctions. These frameworks guide governance/control evidence; none is a universal runtime engine. This design implements local deterministic policy and explicitly scoped identity signaling, with interoperability still unassessed.

## Mechanical change-class floor

The [source HLD-P1](../../../care-link/docs/source/HLD-P1-v0.1.md) §§10.1–10.3 defines the following floors, inspected as evidence for this specification. Classifier takes the maximum of changed governed-domain metadata, artifact kind and trusted changed-path map; caller-declared class below that floor is rejected. Unknown path/domain is high-risk review, never C0. Changes to the classifier/path map itself require C3 review. Review receipts bind exact artifact digest/source revision, actual authority class and human identity; eligibility is a governed list.

| Class | Floor trigger | Required review/evidence treatment |
|---|---|---|
| C0 | Cosmetic, no functional/safety/privacy surface | Independent peer review and CI |
| C1 | Functional with no safety/consent/equity/security surface; ordinary verified directory records | Independent peer plus owner; CI/regression |
| C2 | Security/privacy/content/topology/model/prompt, non-triage policy, legal/protocol/static/jurisdiction/egress changes | Owner and security plus privacy/content authority where applicable; conformance/adversarial subset |
| C3 | Triage/tier/thresholds, consent/disclosure, emergency guard, tool permissions or triage feature contract | Applicable clinical/equity/privacy/security/operations authority; full conformance, shadow comparison and predefined observable rollback trigger |

Planned path floors include `packages/domain/assessment/**`, consent/disclosure rules, broker tool registry/guard and triage contracts→C3; prompt/model, policy, deploy/network, static publication and jurisdiction config→at least C2; nonsafety application code/directory records→at least C1. Actual repository path classification is a signed reviewed artifact when implementation paths exist; semantic domain changes cannot hide behind a UI filename. No clinical/community/real-service authority is fabricated for synthetic fixtures: those artifacts remain stub/demo-only, with project review distinguished from source clinical approval and real capabilities blocked. Local DEC acceptance does not retroactively approve future artifact bytes.

The [local control register](control-register.json) materializes each control owner, planned policy rule, enforcing boundary, threat, test family, residual and unresolved exact standard mapping. Rule names are proposed local identifiers, not asserted existing Rego rules or official framework identifiers.
