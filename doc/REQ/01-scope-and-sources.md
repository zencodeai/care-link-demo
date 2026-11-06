# Scope and source analysis

> Current user clarification (2026-11-06): deploy on this workstation and use `google/gemma-4-12b-qat` in local LM Studio, reported already downloaded. This supersedes the earlier model choice reproduced in the historical source table below. See [LLD acceptance](../LLD/decisions/2026-11-06-implementation-choices-and-model.md); metadata/capacity/function verification remains pending.

The intended product is a mission-critical, actor-led client-support service. Agentic AI supports service delivery through scoped context gathering, verified navigation, drafting, coordination and follow-through. The [service model](10-agentic-ai-and-service-model.md) establishes useful actor assistance as a primary requirement alongside realtime security/governance. Synthetic demo restrictions describe the current deployment/evidence boundary, not the entire product purpose.

> Scope update (2026-11-04): [Decision answers](08-open-decisions.md) and [demo parameters](demo-parameters.json) establish Ottawa/Ontario context and exclude all police roles, brief sinks, connectors and partnerships from the proposed demo. Earlier police-specific descriptions below are retained only as historical source context and are superseded for implementation; they do not imply a police relationship. Source FR-C6 and AQ-9/AQ-26 are excluded by current user scope, not satisfied. Concrete defaults replace earlier open engineering choices; clinical/legal approvals and hardware-dependent checks remain unresolved.

## Source authority and findings

| Resource | Interpretation and use |
|---|---|
| `care-link-workspace/requirements.md` | Direct project constraints: comprehensive design, structured implementation, independent actor sessions/credentials/UIs/workflows, PR review, continuous usability, realtime security/governance/audit, local hosting, LM Studio, Gemma 3 4B IT, Docker and Kubernetes. |
| `care-link/docs/source/FRS-v1.1.md` | Product intent, functional requirements and original acceptance criteria. Draft, approved for discovery/architecture only. |
| `care-link/docs/source/SAD-v0.1.md` | Architectural decomposition; subordinate to FRS on product meaning. |
| `care-link/docs/source/HLD-P1-v0.1.md` | Phase One implementation scope: closed, synthetic, simulated services and non-clinical stubs; independent real static crisis information. Subordinate to FRS then SAD for conflicting statements. |
| `care-link/model/` | Curated requirements, invariants, actors/components, data, contracts, policy placeholders, bindings and questions. Useful stable references; not proof of deployed enforcement. |
| `care-link/generated/assurance/` | Reports model/predicate checks passing, implementation/environment not assessed, release eligibility blocked, ceiling `demo_model_only`. Report was inspected, not rerun. |
| `care-link/decisions/ADR-13…` | Proposed structural changes and explicit unresolved inference, youth-routing and safe-mode conflicts. Proposed status is preserved. |
| `backup/care-link-prod` | Historical reference only. Reviewed topology/setup and implementation metadata; not imported as requirements or approved design. Its P4 setup explicitly states no P4 deployment yet. |
| `care-link-demo/README.md` | Says “Production ready care-link system with demo cap”; this is an aspiration contradicted by current source assurance and an otherwise empty implementation checkout. |

The source requirement nodes total 114 (92 functional and 22 non-functional). The complete trace includes every statement and acceptance criterion from those nodes. Source snapshots record hashes and repository revisions so later source drift is visible. Resources were inspected selectively by authority and relevance; no claim is made to have audited every historical production file, secret, model binary, or runtime.

## Scope requirements

- **TR-SCP-01 — Demo boundary.** SHALL admit only issued project participants, use synthetic person-related information and fictional `CA-XX`/`CA-YY` demo jurisdictions, and reject missing/wrong population or environment tags. No real partner connectors, public app registration, clinical validity claim, or operational emergency capability. Verify admission and deployment configuration with negative tests. Source: HLD §§1–2, 11–12; INV-1/12.
- **TR-SCP-02 — Full workflow mechanisms.** SHALL demonstrate intake, structured assessment, controlled rationale, sourced directory selection, granular consent, referral, queue, human handoff, accompaniment, plan management, follow-up and outcomes through actual role UIs and deterministic services. Clinical/legal/community content remains visibly stubbed. Verify source use cases UC-1 through UC-5 with staff role-play.
- **TR-SCP-03 — Continuous usability.** SHALL retain a usable last-known-good demo during incremental development and provide an independent static crisis-information path during failures and maintenance. Local-machine downtime cannot be described as high availability. Verify rollout/rollback and dependency-loss drills.
- **TR-SCP-04 — No silent scope substitution.** SHALL keep unmet channels, real-world validation and release approvals visible as deferred or blocked. Web-only delivery is an intermediate milestone, not satisfaction of voice/SMS/mobile/relay requirements. Verify the release checklist against the full source trace.
- **TR-SCP-05 — Static content exception.** SHALL use real, independently verified Canadian crisis contact content in the fallback service, with owner, verification date and review cadence. This package deliberately contains no contact numbers and does not verify them. Fictional crisis contacts are not acceptable fallback content. Verify content approval before use.

## Conflicts and dispositions

1. FRS anonymous public crisis access versus HLD credentialled participants: implement a closed demo participant credential around an anonymous synthetic business persona. Separate access identity from person identity; no production access claim.
2. User requires LM Studio/Gemma; historical code uses native inference arrangements. User choice controls the new demo. Do not reuse historical inference restrictions as proof that LM Studio works.
3. HLD broker-only Z2 networking versus separate inference egress (§7.6): preserve broker-only runtime egress; propose broker-mediated inference for review (D-02). No direct runtime-to-host inference exception is silently approved.
4. HLD supervisor exposure prose versus INV-15: only aggregate exposure information; no individual worker performance metrics or individual API exports. Record any future desired difference for source-owner resolution.
5. Core triage contract accepts empty `situation_factors` only. Realistic clinical assessment is not authorized by that shape. Store synthetic assessment assertions separately and use explicitly selected fixture scenarios for stub tier outputs; a new clinical feature contract needs review.
6. Youth mediation has no valid declared caller; safe-mode human operations cross killed components. Require explicit interface/authority decisions before those integrations. Maintain visible blocked status instead of inventing authority edges.
7. FRS long-term audit retention and deletion across backups cannot be settled by engineering. Demo retention configuration and restore filtering must be explicit; legal adequacy remains outside this package.

## Proposed design principles

Keep product behavior visible in every increment. Prefer a small number of deployable services with clear internal modules over one service per model element. Preserve trust and credential boundaries even when modules share a process. Avoid reproducing the abandoned project's evidence machinery unless a concrete control needs it. A test report, schema or model predicate alone is not deployed-system evidence.

> This prototype demonstrates control and containment architecture using non-clinical stub logic and synthetic data. It provides no evidence of clinical safety, triage validity, or equity performance, and must not be cited as such.
