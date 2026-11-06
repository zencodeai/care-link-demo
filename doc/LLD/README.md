# CARE-Link technical low-level design

Version 0.2 · 2026-11-06 · Recommended local design choices accepted; implementation/deployment evidence remains pending.

This is a new design derived from the current requirements and HLD, following the explicit LLD authoring request. No deleted LLD was recovered. It specifies the actor-led service, bounded AI assistance and deterministic controls needed to implement the closed synthetic demonstrator. The five accepted local HLD decisions remain binding within their recorded qualifications. The user subsequently accepted the recommended LLD choices, this workstation and the exact LM Studio model identifier; see the [scoped acceptance record](decisions/2026-11-06-implementation-choices-and-model.md). This does not establish independent implementation/release approval.

| Read | Implementation question |
|---|---|
| [00 — Baseline](00-baseline-and-design-decisions.md) | Which inputs, decisions and limits govern this design? |
| [01 — Modules](01-modules-and-build-boundaries.md) | What runs where, who owns state and which ports are exposed? |
| [02 — Contracts](02-contracts-and-protocols.md) | What are the exact operations, wire types, errors and compatibility rules? |
| [03 — Identity and trust](03-identity-and-workload-trust.md) | How are human, continuation and workload identities validated and revoked? |
| [04 — Data and transactions](04-data-model-and-transactions.md) | What is stored, constrained, locked and committed? |
| [05 — Actor workflows](05-actor-workflows-and-ui.md) | How do each actor's screens and state transitions behave? |
| [06 — Consent and referrals](06-consent-directory-and-referrals.md) | How do attributed plans, grants, sources and uncertain effects work? |
| [07 — Agent runtime](07-agent-runtime-and-inference.md) | How does useful bounded planning reach tools and the local model? |
| [08 — Runtime controls](08-runtime-security-and-governance.md) | How are policies, approvals, activation and containment enforced before effect? |
| [09 — Audit and rights](09-audit-rights-and-analytics.md) | How do audit, lifecycle, deletion, exports and aggregates behave? |
| [10 — Simulators](10-simulators-and-replay.md) | How are receivers, channels, feeds, training and replay isolated? |
| [11 — Deployment](11-deployment-and-configuration.md) | How are processes, connections, configuration and releases bound? |
| [12 — Continuity](12-continuity-and-operations.md) | What survives failure, and how does a restored target regain serving authority? |
| [13 — Verification](13-verification-and-traceability.md) | Which mechanisms and observable tests address each requirement? |
| [14 — Remaining decisions](14-decisions-and-admission-gates.md) | What still needs a product pin, evidence or a separate authority decision? |

Machine-readable design: [JSON types](contracts/definitions.schema.json), [OpenAPI](contracts/openapi.json), [operation ownership](contracts/operations.json), [state transitions](contracts/state-machines.json), [contract fixtures](contracts/fixtures.json), [trace matrix](traceability.json), [input inventory](design-inventory.json), [physical storage dictionary](storage-model.json) [implementation defaults](implementation-defaults.json) and [runtime control register](control-register.json). Run the [design validator](validate_design.py) with Python and `jsonschema` to check artifacts; its checks are documentation checks, not runtime tests.

The normative order within this package is: current user constraints and accepted local HLD decisions; current requirements with their later overlays; LLD mechanism prose and matching machine contracts. A contradiction is a design defect to reconcile, never permission to choose the less restrictive interpretation. Unknown products, facts, approvals or results remain unknown. The [remaining decisions](14-decisions-and-admission-gates.md) distinguish design completeness from deployment readiness.

This prototype demonstrates control and containment architecture using non-clinical stub logic and synthetic data. It provides no evidence of clinical safety, triage validity, or equity performance, and must not be cited as such. There is no police integration or autonomous emergency-contact capability.

Validation from repository root (prefer an isolated environment): `python -m pip install -r doc/LLD/validation-requirements.txt`, then `python doc/LLD/validate_design.py`. The direct tooling dependencies are pinned to the versions used for this review; they do not pin the application runtime.
