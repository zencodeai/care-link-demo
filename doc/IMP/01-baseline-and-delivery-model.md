# Baseline and delivery model

## Current authority and state

Current user instructions and accepted local decisions govern; [REQ](../REQ/README.md), [HLD](../HLD/README.md) and [LLD](../LLD/README.md) provide the technical baseline. The planning inventory freezes their input bytes. A later change is reconciled explicitly with previous/new hashes and affected work, never hidden by refreshing an inventory. The root commit and branch identify a local planning input, not proof that a PR merged or a release ran.

Application implementation is not established. The source checkout contains a detailed design/validator, not running actor services. Existing local Codex HLD/LLD configuration is unrelated work preserved in place. All new planning files stay in doc/IMP. No previous LLD is recovered and no historical implementation/credentials/approvals are imported.

The deployment target is this workstation. Runtime inference is host LM Studio with exact selected identifier `google/gemma-4-12b-qat`, broker mediated, no remote fallback. Codex development-agent models inherit the active session; the application model selection does not reconfigure Codex. Keep all existing budgets unchanged until reviewed measurement justifies a change.

## Deliver useful slices with complete boundaries

Each stage is a bounded vertical capability: real UI/CLI entry, typed operation, deterministic policy, durable state where needed, observable result and error/recovery path. Self-contained means complete and reviewable within that declared scope, not a new microservice or a claim of whole-system completion. A developer-only shell can be useful before participant admission but must visibly identify missing capabilities. Unsupported operations fail explicitly; no success stubs are passed off as delivered workflows.

Manual client→worker service precedes optional AI. Inline access, audit, consent/revocation and current journal/generation checks appear before the first corresponding protected effect. IMP-08 completes operational change/review consoles; it does not introduce enforcement for the first time. IMP-09 completes integrated recovery proof; journal foundations and restriction ordering begin in IMP-03. Rights completion accurately remains backup-pending until backup/restore obligations are tested.

One stage may contain several small implementation PRs. A PR can merge after its required human review without authorizing deployment, accepting the full stage or closing source obligations. Conversely, a demonstration is not permission to merge or deploy a changed candidate. Human decisions name the exact action/scope being accepted.

## Definition of ready and done

Ready: accepted baseline references; named stage/task owner; complete work packet; bounded paths and resource leases; current contracts; relevant decision prerequisites; explicit test/demo outcomes; recoverable rollback; necessary user authorization for implementation/setup actions. Unknown clinical/production authority does not stop unrelated synthetic engineering, but absent trust/account/content evidence blocks the affected admission.

Done for a task: scoped code/design/evidence produced, relevant checks recorded with actual outcomes, review findings resolved or explicitly carried, no hidden contract/design drift. Done for a stage: integrated self-contained demonstration and adverse cases, reproducible evidence, current candidate/manifest binding, no unresolved critical authority/control defect, and an explicit human stage decision. An AI summary, screenshot, schema pass or elapsed wait cannot accept a stage.

## Progress and authorization

Stages use planned→authorized→in_progress→ready_for_demo→awaiting_human→accepted, with rework/blocked/cancelled paths. All current statuses are planned. `authorized` requires an actual scoped user instruction or recorded authority, not a generated field. Independent work may continue while a stage awaits review only within existing authorization and without depending on its unaccepted behavior or activating protected capability.

No automatic stop is imposed at every routine edit. Human checkpoints occur at the meaningful stage boundaries and at actual scope/authority changes. When requesting a decision, first prepare a working, reviewable candidate and its evidence. Do not repeatedly ask about already accepted workstation/model/architecture choices. If a new decision is essential, ask precisely and continue work that does not depend on it.

The [stage workflow](stage-workflow.json) defines progression. implementation-plan.json is the unexecuted planning baseline, not a fabricated execution ledger. During authorized implementation keep one versioned run ledger under doc/IMP/executions/<run-id>/ with stage/task IDs, actual states, evidence and human-receipt references; derive summaries rather than maintaining competing status systems. No execution ledger or accepted gate is created by this planning task.
