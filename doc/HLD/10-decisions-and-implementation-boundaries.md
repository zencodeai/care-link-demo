# Architecture decisions, trade-offs and open issues

## Selected decisions and alternatives

DEC-01…05 recommendations were accepted by the user for local design on 2026-11-06; see the [acceptance record](decisions/2026-11-06-local-design-baseline.md). Other design selections retain their recorded review status; no blanket release or clinical approval is implied. They define how responsibilities interact; they are not installation, certification or clinical approval records.

| ID | Decision and reason | Alternative / trade-off | Reconsider when |
|---|---|---|---|
| HLD-D01 | Modular deterministic core with explicit domain ownership | Service-per-element architecture adds credentials/distributed coordination; monolith containing untrusted runtime weakens isolation | Independent scaling/ownership or privilege evidence justifies extraction |
| HLD-D02 | Bounded role-scoped assistants coordinated by durable core, one isolated proposal runtime initially | Autonomous multi-agent platform adds orchestration/authority laundering risk; simple text generator alone misses observed multi-step coordination | A measured actor task requires isolated specialists/concurrency beyond current coordinator |
| HLD-D03 | Broker-mediated local LM Studio/Gemma and dedicated host inference gateway | Direct runtime inference conflicts with broker-only trust; remote inference conflicts with local requirement | Source-owner disposition or new explicitly reviewed deployment scope |
| HLD-D04 | Scoped persistence gateway and co-located business/control/canonical-audit transaction boundary | Independent audit service provides stronger failure/credential separation but requires explicit consistent publication/recovery protocol | Trust/scale/regulatory needs outweigh local transaction simplicity |
| HLD-D05 | Dedicated audit authority, append-only access and separate integrity checkpoints | Operational logs alone lack canonical integrity; same-host checkpoints remain vulnerable to root/disaster | Independent audit/failure domain becomes available/required |
| HLD-D06 | Current deterministic policy with controlled version activation and future-effect revocation | Login-only or event-only checks preserve stale permission; all-local synchronous checks cost latency/availability | A verified distributed protocol can preserve semantics under scaling |
| HLD-D07 | Direct independent host help/static entry and minimal spool | Core-only help is simpler but lost with edge/cluster; full duplicate platform is costly and still same-host | Real partner staffing or resilient independent hosting is authorized |
| HLD-D08 | Distinct role-scoped OIDC/MFA identities and operation assurance | Role dropdown/shared account/metadata linkage undermines accountability; step-up adds interaction cost | Actual approved anonymous real-user entry changes perimeter requirements |
| HLD-D09 | Versioned logical commands, durable push updates and reliable asynchronous effect reconciliation | Pure polling is simpler but less timely; unconstrained event bus broadens disclosure; neither guarantees exactly-once delivery | Load/network constraints require a measured transport change |
| HLD-D10 | Private single-host Docker/Kubernetes plus isolated simulated partners | Multi-node/region hosting improves resilience but exceeds local demo scope; real integrations need agreements/staffing | Explicit deployment and real-user scope change |
| HLD-D11 | Classified exact-artifact human review separated from proposal/signing/activation | Automation-only/self-approval provides no independent human oversight | No relaxation without an explicit governance change |
| HLD-D12 | Offline reviewed task-specific evolution; no online training/self-modification | Continuous learning could change behaviour without evaluated evidence | Separate training consent, data, safety and change-control design exists |

## Workload identity implementation decision

The architectural requirement is automated attested workload identity, mutual endpoint authentication, identity-based deny rules, controlled rotation/revocation, host-bridge participation and bounded issuer-outage behaviour. DEC-01/B selects standardized proxies with automated attested workload identity as the initial local candidate. Full mesh and application-managed TLS remain comparison alternatives, not implicitly accepted substitutions. Exact products/versions, actual local cost, bypass prevention, host integration and credential/connection revocation evidence remain implementation work. A material family change needs an attributable decision update; no workload trust implementation is yet deployed.

## Decision recommendations

[Decision requirements and options](11-decision-requirements-and-options.md) preserves the five option comparisons. All five recommended options are now the accepted local design baseline, with their qualifications recorded in the [acceptance record](decisions/2026-11-06-local-design-baseline.md). The remaining work below is product/protocol/evidence or upstream disposition, not a request to approve the same local choices again.

## Open issues and consequences

| Issue / accountable responsibility | Effect on architecture or readiness | Work that can proceed |
|---|---|---|
| Host resources, local cluster/CNI/host routing and trust plane — architecture/operations/security | Resource fit, route enforcement and protected deployment cannot be claimed | Logical interfaces, actor UX and deterministic design |
| Exact software/image/model artifact/license and capability — engineering/security | Reproducibility and AI-function admission unresolved | Manual/template flows and isolated proposal evaluation |
| Upstream D-02 inference/youth/safe-mode disposition — source owner/architecture | DEC-05/A and its three local deltas accepted; upstream conformance remains a separate pending disposition | Document choices, tests and explicit source divergence |
| Independent fallback content owner/reviewer and current verified bundle — safety/operations | No participant use without real reviewed public content | Publication design and fictional actor workflows |
| Independent release/specialist reviewers — maintainer/governance | Candidate cannot become accepted baseline through self-approval | Prepare reviewable artifacts; synthetic design need not stop |
| Fresh-authority help protocol — security/operations | DEC-02/A is accepted: no stale private acceptance; prove current request/status/worker authority or show static-only fallback | Unconditional static information and normal core help design |
| Lifecycle implementation and actual access-account schedule — privacy/product/security | DEC-03/B anchors/dependency/hold model accepted; exact actual-account periods, copy/hold mechanics and purge evidence remain | Logical lifecycle, scoped rights and explicit pending/exception states |
| Recovery journal/protocol verification — recovery/security/governance | DEC-04/B host journal plus separate serving approval accepted; missing trusted current head keeps restore quarantined and same-host disaster remains uncovered | Restore workflow, evidence plan and protected recovery storage evaluation |
| Exact standards versions/control identifiers and interoperability — security/governance | No certification or SSF/CAEP conformance inferred | Project-specific controls and threat/verification planning |
| Clinical/consent/legal/PHIPA/SaMD/community/partner/staffing context — responsible future authorities | No real clinical/data/partner operation or production readiness | Closed non-clinical synthetic demonstrator |

These responsibilities identify needed accountability, not appointed or existing clinical/legal bodies. Missing clinical approval is not an obstacle to architectural design of a synthetic system. Residence does not establish legal entity, qualification, user location, data residency evidence or a blanket reporting exemption.

## Architectural verification and delivery strategy

Deliver useful actor flows incrementally: separate logins/disclosure/manual human request and independent static help; then deterministic attributed intake, knowledge/consent and basic workforce coordination; then task-specific local AI drafts/tools with human review; then receiving-service handoff/receipts/follow-up and plan/rights lifecycle; finally complete operational/governance/audit/aggregate views and adverse-failure/recovery evidence. Keep an accepted usable path rather than deferring all service value behind a compliance framework.

Each increment is evaluated against [requirements acceptance groups](../REQ/06-acceptance-and-delivery.md), including actor-only versus assisted usefulness, adversarial authority boundaries and dependency-loss behaviour. Review is based on behaviours and evidence, not feature counts. Versioned implementation schemas, database mechanisms, exact routes, credentials/manifests and operational commands are future implementation work; they are not generated by this HLD revision and the deleted LLD remains absent.

## Revision review disposition

This revision addresses specialist findings on scope/abstraction drift, normal actor journeys and missing receiver assistance, direct help entry and degraded modes, workload trust ownership, current-context/delegation boundaries, audit independence, lifecycle/continuation recovery and quarantine/promotion. The final integrated review and verification status are recorded in the design inventory. AI review is not the independent human approval required to accept changes. No commit, push, deployment or upstream model change follows from authoring this package.

> This prototype demonstrates control and containment architecture using non-clinical stub logic and synthetic data. It provides no evidence of clinical safety, triage validity, or equity performance, and must not be cited as such.
