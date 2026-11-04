# Design decisions, dependencies and delivery

## Proposed architectural decisions

| ID | Decision / rationale | Consequence and alternative |
|---|---|---|
| HLD-D01 | Modular core plus isolated runtime, inference and persistence boundaries | Useful vertical slices without dozens of microservices; core compromise remains a privileged risk, mitigated not eliminated |
| HLD-D02 | Durable deterministic task coordinator; untrusted stateless role-specific proposal runtime | No general autonomous framework; specialist tasks share scoped tools/model with budgets |
| HLD-D03 | Broker-mediated host LM Studio/Gemma only | Preserves broker-only Z2 egress; source-owner D-02 disposition required before adopting the authority change |
| HLD-D04 | PostgreSQL command transaction across business/control/audit schemas | Atomic state/audit/outbox, no distributed-commit pretense; DB root/single-node failure remain residuals |
| HLD-D05 | Dedicated non-login audit owner and restricted append procedures | App cannot rewrite chain; host/DB superuser requires separate custody and checkpoint residual disclosure |
| HLD-D06 | OPA decisions plus central monotonic epoch/revision fencing | Local signed activation not instantly atomic across cluster; stale instances deny rather than fail open |
| HLD-D07 | Separate durable minimal help host service and static content process | Help acceptance can survive core/cluster failure without exposing histories; host loss remains uncovered |
| HLD-D08 | OIDC BFF sessions with operation assurance and separate actor accounts | Current entitlement/revocation checks needed beyond JWT validity; professional participant is not workforce |
| HLD-D09 | Scoped JSON APIs, persisted SSE and transactional outbox | Duplicate delivery and unknown external outcomes are explicit; no end-to-end exactly-once claim |
| HLD-D10 | Private local cluster, no cloud or police/emergency integration | Cannot meet production redundancy or source police-interface requirements; trace records exclusions |
| HLD-D11 | Independent human artifact approval and classified review | Solo implementor can prepare but cannot self-approve; no fabricated clinical reviewers |
| HLD-D12 | No automatic training, self-modification or unreviewed model change | Improvement through reviewed task-specific evaluation/shadow mode only |

These choices refine the requirements, not formal upstream model decisions. None is a clinical authorization or installation record.

## Admission dependencies and unresolved items

| Blocker / required evidence | Affected capability | Can progress meanwhile |
|---|---|---|
| Actual host CPU/RAM/GPU/disk/ports, Docker/Kubernetes/CNI and host bridge validation | Any local deployment/capacity assertion | Contracts, UI, deterministic modules and fake inference tests |
| Exact supported software versions/image digests and Gemma origin/license/quantization/digest | Model/function admission and reproducible release | Deterministic/manual actor flows; no claim of real-model integration |
| Source-owner review for inference authority, youth mediation flattening and safe-mode help contract (D-02) | Affected integration/authority conformance | Draft interfaces/tests and isolated design demonstration; no claim source issue is closed |
| Real verified fallback content, named maintainer and separate human content review | Participant use | Content bundle structure, tests and review workflow |
| Independent human reviewer and appropriate specialist responsibility | Accepted baseline/high-risk release | Candidate PR preparation, not self-approval |
| Identity provider signal/CAEP capability and workload certificate issuer design | Continuous-access interoperability | Local signed signal contract without claiming external conformance |
| Exact ASVS/ATLAS version/IDs and risk applicability | Standards-traced acceptance of affected controls | Enforce project controls and develop threat scenarios, label mapping incomplete |
| Key custody/recovery, control ledger persistence, tested backup/restore and deletion exceptions | Durable protected operation/recovery evidence | Migration/transaction test development |
| Clinical tier/features, Ontario legal/consent/PHIPA status, SaMD determination and community governance | Any real clinical/user-data operation | Synthetic fixtures only; no parameter enables production |
| Real service catchment/agreements/staffing, external resilient hosting | Real referrals, staffed care and production SLOs | Internal simulators and manual role-play |

Do not treat implementor residence as user location, legal entity identity, clinical credential, blanket Canadian residency evidence or professional reporting exemption. Public-sector/federal obligations, if any, require an actual operator-context assessment.

## Incremental implementation sequence

1. Contracts, host admission and usable foundation: role credentials/accessible UI, static fallback, independent help, minimal session/worker flow and atomic audit. Exit with AT-01/02/04/09/10/13 relevant cases.
2. Deterministic intake/assertions/directory/consent and controlled stub rationale, with matched manual service baseline. Preserve current accepted path.
3. Local model admission and bounded role-scoped worker assistance: source-linked draft, typed tools, lease/cancellation and review. AT-08/14/15/17/18 establish useful actor assistance, not only containment.
4. Queue/handoff/supervisor and consented simulator referral with irreversible boundary, receipts and reconciliation; adverse race/timeout tests.
5. Plans/sharing/continuation, follow-up, outcome, export/delete/retention and isolated restore.
6. All remaining role consoles, governance/security/evidence/aggregate metrics, channels/training simulations, full failure drills and trace review. No deferred source clinical approval becomes a passing demo check.

Every increment gets a reviewable PR describing concrete behavior, covered requirements, meaningful checks and rollback. This design task does not commit/push changes or amend the existing requirements PR. Review HLD before implementation and record implementation-specific decisions against its stable HLD-D IDs.

## Low-level specifications still required

Before each feature: full nested OpenAPI/JSON Schemas; table/foreign-key/index DDL and migration; policy rule inputs/outputs and exact reference IDs; PEP/transaction proof cases; human/workload credential bootstrap; signed activation/dispatch/receipt protocol; bounded UI states and accessibility fixtures; deployment resource/network manifests and measured host bridge; operator commands/runbooks. These are implementation deliverables under this HLD, not gaps that justify claiming unimplemented system readiness.

> This prototype demonstrates control and containment architecture using non-clinical stub logic and synthetic data. It provides no evidence of clinical safety, triage validity, or equity performance, and must not be cited as such.
