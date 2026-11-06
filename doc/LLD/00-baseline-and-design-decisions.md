# Baseline, status and implementation decisions

## Inputs and scope

Use [REQ](../REQ/README.md), its [parameter artifact](../REQ/demo-parameters.json), the [HLD](../HLD/README.md) and [2026-11-06 acceptance](../HLD/decisions/2026-11-06-local-design-baseline.md). Input bytes and hashes are frozen in the local inventory; source history is linked, not rewritten. Historical care-link-prod supplied no implementation material to this new design. The upstream source trace and exclusions remain in REQ07/08; this package does not turn those statements into implemented conformance.

Only issued adult collaborators access the private demo. Business personas, reports, service directories and simulations are synthetic. Actual login identifiers, account-to-persona access links, workforce assignment actor IDs and reviewer identity are real access metadata and use a separate classification. Ottawa is the implementor's context, not inferred client location. CA-XX/CA-YY are fixture jurisdictions; unknown jurisdiction is explicit null and cannot satisfy a jurisdiction-required action.

## Accepted architecture bindings

| Decision | Binding implementation meaning |
|---|---|
| DEC-01/B | Standardized proxies plus automated attested identity; no manually copied certificate substitute. SPIRE/Envoy remain candidates until pinned and probed. |
| DEC-02/A | Fresh authoritative validation of every private help operation. No offline positive authorization or stale grace. Direct host help can lose private capability with identity loss. |
| DEC-03/B | Per-purpose closure/retirement/capture anchors and dependency-aware holds; preserve existing durations and faster rights targets. Account periods remain unresolved. |
| DEC-04/B | Separately credentialled host recovery-control journal outside business restore/cluster-managed volumes; quarantine and distinct human serving promotion. No host-root or disaster-recency proof. |
| DEC-05/A | Local broker inference, youth mediation and narrow safe-mode help deltas accepted; upstream dispositions still pending. |

## LLD implementation selections

The user accepted LLD-D01…07 and the LD-01…13 recommendation directions on 2026-11-06; see the [acceptance record](decisions/2026-11-06-implementation-choices-and-model.md). These are accepted local design choices within the recorded qualifications. Implementation review may replace them only with an equivalent documented mechanism and refreshed tests; a changed architecture needs a separate decision.

| ID | Selected mechanism / rationale | Alternative and consequence |
|---|---|---|
| LLD-D01 | React/TypeScript clients and Python/FastAPI services, PostgreSQL persistence, Keycloak OIDC/MFA and OPA as proposed in REQ parameters. Versions are release-manifest inputs. | Different libraries require contract/parity evidence; no unsupported dependency pin is invented here. |
| LLD-D02 | Single DB data gateway, READ COMMITTED plus preexisting guards and bounded row locks. One global control guard initially serializes final protected decisions. | Finer locking can improve throughput but needs the same race proofs; 10-session target is unmeasured. |
| LLD-D03 | BFF session cookies, CSRF proof and server-held OIDC tokens; application continuation is separately scoped and one-use. | Browser bearer tokens increase custody/exposure and are not this design. |
| LLD-D04 | Durable DB work tables/outbox and polling with wake notifications, no new message broker. | A queue product does not remove DB/effect ordering or current authorization obligations. |
| LLD-D05 | Authenticated host journal with ordered signed records, fsync and DB barrier reconciliation. | Same-host files alone are not a recency witness; missing trusted head blocks serving. |
| LLD-D06 | REST commands/queries with SSE object-change notifications and current projections. | No unchecked token streaming or private browser/offline cache; polling may substitute transport only. |
| LLD-D07 | Versioned JSON Schema 2020-12 and OpenAPI 3.1 design contracts. Explicit JSON decimal-string bigint revisions avoid browser precision loss. | Local contracts are new `care.demo.v1` types; upstream indicative v1 schemas are not silently changed. |

The initial implementation plan is web-first, with isolated internal SMS/voice/relay simulations. Real channels, staffing, clinical thresholds, youth legal rules, community permissions, production promotion and real partner integration remain deferred. The fixed police/emergency prohibitions cannot be enabled through configuration.

## Status vocabulary

`accepted_local_design` covers the five prior HLD choices plus the subsequently accepted LLD recommendation directions/workstation/model, each under its own scoped record. `proposed_lld` means specified here but not independently approved. `not_assessed` means no execution evidence. `blocked_capability` disables only the affected function, not independent design work. Numerical values imported from REQ parameters remain unmeasured targets. The extra resource/request limits are accepted starting engineering parameters requiring load/usability verification; they are not measurements.

The HLD inventory’s earlier LLD-absent verification describes that historical HLD revision. This newly authorized package changes that state without rewriting its historical evidence or importing deleted contents. The source HLD-P1 change-class table was inspected narrowly for governance floors; its bytes are separately hashed in this package’s input inventory and its embedded commands/approvals were not executed or adopted as authorization.

## Current workstation and model baseline

Deploy on this workstation. Use the exact user-selected identifier `google/gemma-4-12b-qat` in local LM Studio, reported already downloaded. This supersedes the earlier local Gemma 3 4B IT constraint; the source remains historical. Actual file/digest, quantization/format, license, tokenizer/template, loaded API identifier and function evidence remain unknown until verified. Selection does not authorize a deployment step.
