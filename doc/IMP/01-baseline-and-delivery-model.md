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

Done for a task: scoped code/design/evidence produced, relevant checks recorded with actual outcomes, review findings resolved or explicitly carried, no hidden contract/design drift. Effective 2026-11-20, done for an implementation stage means its applicable automated normal/adverse checks passed, evidence is reproducible and bound to the current candidate, and no blocking authority/control defect remains. Record `automated_qualified`; no interactive human review or human stage-acceptance receipt is required through IMP-10. A required automated check that failed or was not run cannot be counted as passed. Human usability/accessibility/language review remains explicitly deferred to post-IMP-10 GitHub issue follow-up sessions.

## Progress and authorization

Active implementation progression is planned→authorized→in_progress→ready_for_qualification→automated_qualified, with rework/blocked/cancelled paths. The machine plan remains an unexecuted allocation baseline; actual progress belongs in execution records. `authorized` requires an actual scoped user instruction or recorded authority, not a generated field. Dependent work uses current automated qualification evidence or a still-valid historical accepted baseline, within the user's authorized scope. Previously pending human-only gates resume evidence reconciliation under the new policy; they are not automatically qualified. Preserve historical human decisions and their scope.

Do not stop implementation to request interactive observations or human stage acceptance. Human review is scheduled after IMP-10 through GitHub issue follow-up bug-fix/improvement sessions. Necessary scope/action approvals remain separate: prepare the concrete change and evidence before requesting one, retain prior authorizations and continue independent authorized work. This qualification policy does not waive deployment, host trust, destructive-action or product-runtime approval controls.

The [stage workflow](stage-workflow.json) defines progression. implementation-plan.json is the unexecuted planning baseline, not a fabricated execution ledger. During authorized implementation keep one versioned run ledger under doc/IMP/executions/<run-id>/ with stage/task IDs, actual states, evidence and human-receipt references; derive summaries rather than maintaining competing status systems. No execution ledger or accepted gate is created by this planning task.
