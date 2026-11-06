# Local LLD choices, workstation and model acceptance — 2026-11-06

Status: **accepted for local design**. This records the user's decision in the conversation, not a signed release certificate or deployment instruction.

## Approval evidence

The user wrote:

> Approove recommentded choices:
>
> - Deployment will take  place on this workstation
> - LLM is google/gemma-4-12b-qat already downloaded in LMStudio

The context was the [LLD decision table](../14-decisions-and-admission-gates.md). This accepts its recommended directions and the [LLD implementation selections](../00-baseline-and-design-decisions.md), with the explicit workstation and model clarifications below. The approver is the user in this conversation; no legal identity, independent second reviewer, professional qualification or upstream authority is inferred.

## Accepted directions and remaining evidence

| ID | Accepted local decision | What acceptance does not establish |
|---|---|---|
| LLD-D01 | React/TypeScript, Python/FastAPI, PostgreSQL, Keycloak/OIDC and OPA stack direction | Exact compatible versions, licenses/security review and installed components |
| LLD-D02 | Gateway-owned business/control/audit transaction, stable guards and initial global final-authorization guard | Tested DB isolation/privileges or measured contention |
| LLD-D03 | BFF cookie sessions, server-held OIDC tokens and separately scoped one-use continuation | Provider integration or assurance/credential recovery test results |
| LLD-D04 | Durable DB work/outbox with polling/wake hints | Exactly-once network delivery or a passing crash-recovery test |
| LLD-D05 | Authenticated host journal and explicit DB barrier reconciliation | Host-root/disaster recency or filesystem durability proof |
| LLD-D06 | Versioned REST commands/queries plus current-authorized SSE notifications | Runtime streaming/revocation correctness |
| LLD-D07 | Closed JSON Schema/OpenAPI contracts and decimal-string revisions | Deployed API conformance or runtime safety |
| LD-01 | **This workstation** is the deployment target; inventory and choose the smallest tested local Kubernetes/CNI binding | Host hardware/resource inventory, actual ports/routes/CNI or capacity |
| LD-02 | Retain the stack direction and pin supported compatible component versions | Any unstated version or existing installation |
| LD-03 | SPIRE+Envoy is the preferred initial proxy/issuer candidate to evaluate under DEC-01/B, retaining the cost comparison | Final versions, certificate lifetime, host attestation, deployment or bypass/rotation proof |
| LD-04 | **`google/gemma-4-12b-qat` in local LM Studio** replaces the earlier Gemma 3 4B IT selection | Exact file/artifact digest, format/quantization, license, tokenizer/template, loaded API ID or per-function capability |
| LD-05 | Separate minimum-needed account/linkage retention schedule; no synthetic TTL substitution | Exact account-retention periods |
| LD-06 | Continuing-host journal/generation-gate design with crash testing | A trusted current head after host loss/rollback/compromise |
| LD-07 | Independently verify real fallback content and EN/FR publication before participant use | Content verification or an appointed independent reviewer |
| LD-08 | Pin official standards artifacts and extract applicable verified identifiers | Exact control IDs, applicability denominator, interoperability or certification |
| LD-09 | Independent actual human identities and appropriate class-specific review/repository protections | Appointment of reviewers, configuration of protections or release approval |
| LD-10 | Preserve accepted local deltas and explicit upstream divergence | Upstream source-owner disposition |
| LD-11 | Keep real clinical/youth/legal/community/partner/staffing capabilities disabled/stubbed pending proper scope decisions | Real-user, clinical or production authority |
| LD-12 | Measure the existing workload/budgets and actor-only/assisted baseline on this workstation | Capacity, latency, efficacy or permission to increase budgets based on the model name |
| LD-13 | Keep identity linking disabled until a separately designed/reviewed ceremony | A new identity-link capability |

Existing explicit engineering defaults are accepted as **starting design parameters**, with numerical values unchanged and performance unmeasured. Null/unknown periods, versions, credentials and proofs remain unknown. The model download is **user-reported**, not independently inspected. The identifier's spelling, including `qat`, is preserved exactly and is not used to infer a file format, quantization, architecture or capability. `model_identifier` is the user-selected identity; `loaded_model_id` is a separate runtime value to verify.

## Precedence and authority

The workstation target and explicit model choice supersede earlier local model-selection wording in requirements/HLD/LLD. Broker-mediated host LM Studio, no remote fallback, synthetic-only scope, no police integration/autonomous emergency contact, current deterministic authorization and human accountability remain required. Earlier source documents, source snapshots and the [prior HLD acceptance record](../../HLD/decisions/2026-11-06-local-design-baseline.md) retain their original historical meaning; they are not silently rewritten or reported as new upstream approvals.

This approval is local design acceptance. It does not execute or authorize installation, model loading/download, server configuration, deployment, runtime activation, PR publication, merge or production/clinical operation. A future implementation request carries its own authorized scope; this record is not a standing order to perform those actions. Evidence-dependent admission tests and required independent implementation/release reviews remain distinct from choosing the design.

## Provenance and follow-through

The following SHA-256 values identify the exact pre-acceptance bytes; the annotated current files intentionally differ:

- `doc/LLD/00-baseline-and-design-decisions.md`: `dc5f24daad608504a5ad6f6d7ef6f2044f6fc2408d17d330bf7305524aafc28d`
- `doc/LLD/14-decisions-and-admission-gates.md`: `5907cbbd49823b7ed75b099dfbbea296021bcd375c1c74c4610178e0e5277a95`
- `doc/LLD/implementation-defaults.json`: `743f795d7b16c4983a9e85c8a9c18a43a9485448459bd3feb8cca74dd17efc6c`
- `doc/REQ/demo-parameters.json`: `25689e4d1792d1f65284e0416061e40ee70fd6d36833e0973c53e6064c832771`

Active documentation, parameters, model-pin schemas/fixtures and inventories reflect this acceptance. Intentional input-hash revisions retain previous/new digests and this record reference. No runtime verification occurred.
