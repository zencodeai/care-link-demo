# Local HLD decision acceptance — 2026-11-06

Status: **accepted for local design**, subject to the qualifications in the approved recommendations. This is an attributable conversation decision record, not a cryptographic signature or implementation/release certificate.

## Approval evidence and scope

The user’s instruction in this conversation was:

> I approove secommended options

The immediately preceding [decision brief](../11-decision-requirements-and-options.md) contained five recommendations. The instruction is recorded as approval of all five, not just one option. The approving person is the user in this conversation; no legal name, source-owner role, independent specialist status or additional signature is inferred.

Approved brief before acceptance annotations: `doc/HLD/11-decision-requirements-and-options.md`, SHA-256 `86b501346871f29694d6e62332b951174850862e244ff8cd2659236a1b6f7c09`. The comparison text and its qualifications are retained in that document; acceptance annotations identify the changed status. The digest identifies the exact pre-annotation bytes, not a currently matching file or signed reviewed commit.

## Accepted local choices

| Decision | Chosen option | Effective local design meaning | Conditions retained |
|---|---|---|---|
| DEC-01 | B | Standardized service proxies with automated attested workload identity, rather than a mandatory full mesh initially | Family accepted as initial candidate. Product/version/host feasibility, cost comparison, rotation/revocation and bypass proof remain implementation work. A materially different full-mesh selection requires an explicit justified decision update. SPIRE/Envoy are candidates, not automatically approved products. |
| DEC-02 | A | Fresh authoritative validation for each private minimal-help operation, no stale-permission exception, unconditional public static information | Private help may stop during sole-authority/cluster loss even while host UI/spool survives. Separate offline help authority is not selected. |
| DEC-03 | B | Event-anchored per-purpose lifecycle, approved anchor proposal in the brief, existing demo durations, explicit dependencies/holds and truthful rights states | No legal retention approval or invented real-account schedule. Active plan versus retired copy and deletion-target exception are explicit. Actual account metadata periods and preserved minimal recovery/approval evidence still need a separate scoped schedule. |
| DEC-04 | B | Separate host recovery-control journal/checkpoints, quarantined restore and independently approved serving promotion | Same-host/root/disaster independence is not established; current head must be demonstrably trustworthy or serving remains blocked. No future restore/promotion is authorized by this design approval. |
| DEC-05 | A | Adopt explicit local inference/youth/safe-mode deltas and separately track targeted upstream disposition | Upstream documents/model/authority approvals remain unchanged. Local acceptance cannot be reported as upstream source conformance or live activation. |

Acceptance takes effect as the local design baseline on 2026-11-06. It does not authorize creating/restoring an LLD, changing runtime state, installing products, deploying, committing, pushing or merging a PR. Independent human/specialist review required for implementation/release remains distinct; this record does not fabricate a second reviewer.

## DEC-05 local delta register

| Delta | Local acceptance | Remaining upstream status |
|---|---|---|
| Inference mediation | Runtime remains broker-only; only admitted inference gateway reaches host LM Studio, with context/taint/provenance/audit retained | Source-owner disposition of conflicting inference-egress statements pending |
| Youth mediation | Broker/domain services enforce privacy, current disclosure basis and human routing without inventing a forbidden enforcer authority edge; clinical/legal youth rules remain stubbed/disabled | Formal source-graph/rule disposition pending |
| Safe-mode help | Healthy main human routing retains policy/audit; separate minimal host entry obeys DEC-02 current-authority rule and carries no private history/general tools; static information unconditional | Formal source safe-mode operation contract disposition pending |

No permission or approval from the historical care-link-prod checkout is imported. Clinical/production and no-police/autonomous-emergency exclusions remain in force.

## Follow-through

HLD 04/05/07/08/10 and the decision brief/index/inventory reflect these choices. The requirements decision overlay and parameter artifact identify accepted **design configuration meanings**, not deployed settings. Numerical targets are unchanged; new groups describe the selected mechanisms. Input-hash changes caused by those intentional edits are recorded in the inventory rather than masked.

Future changes record a superseding decision; do not silently rewrite this acceptance record or interpret absent evidence as passing implementation tests.

> This prototype demonstrates control and containment architecture using non-clinical stub logic and synthetic data. It provides no evidence of clinical safety, triage validity, or equity performance, and must not be cited as such.
