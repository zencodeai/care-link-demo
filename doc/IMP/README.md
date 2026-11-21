# CARE-Link implementation planning

> Current authorized implementation · 2026-11-20: [Agentic workflows and role-scoped clinical knowledge](../decisions/2026-11-20-agentic-workflows-and-clinical-rag.md) records the bounded LangGraph architecture, Qwen migration, resource provenance and implementation limits. See session003 evidence for actual qualification; no clinical or deployed-readiness pass is implied.

> Current model direction · 2026-11-21: [Authorized Qwen workflow/RAG implementation](../decisions/2026-11-20-agentic-workflows-and-clinical-rag.md) defines the bounded LangGraph and host SDK integration. The worker-summary profile passed automated qualification in the isolated synthetic demo. Existing demo serving remains disabled pending independent release approval.

Version 0.1 · 2026-11-06 · Proposed plan for human review. No application implementation, tool installation, host change or deployment is performed by this package.

**Execution status.** [G-08 is automated-qualified for isolated synthetic governance source/build](executions/2026-11-21-IMP-08/ledger.json). See the [IMP-08 handoff](slices/IMP-08-operational-governance/sessions/001-implementation/handoff.md). G-07 follow-up/rights and G-06 worker-summary qualification remain separately bound to their prior candidates. Human review is deferred until after IMP-10. IMP-08 live activation admits Rego policy artifacts; audit access is metadata-only. Backup recovery/erasure remains pending IMP-09; no deployment or publication follows from this implementation.

Implement the accepted LLD as small, demonstrable service slices. Use Codex specialists for bounded analysis and scoped work and preserve one accountable integration owner. Security/governance controls are built into the earliest relevant behavior, not deferred to a final audit.

**Current workflow policy · 2026-11-20:** the user directed automated qualification only through completion of IMP-10. Per-step interactive human review and per-stage human acceptance are no longer implementation prerequisites, including the pending G-04 review. Human usability, screen-reader, visual and language review is deferred to bug-fix/improvement sessions using GitHub issue follow-up after IMP-10. Preserve prior results as history; record unperformed human review as deferred, never passed. This policy supersedes older human-gate wording in this planning package and slice handoffs. See the [active workflow](../../.codex/IMP_WORKFLOW.md), [qualification procedure](06-demonstrations-and-human-decisions.md) and [machine workflow](stage-workflow.json). Actual deployment/action approvals and product-runtime human authority remain separate. This update does not itself qualify a stage or authorize the next slice.

| Read | Purpose |
|---|---|
| [01 — Baseline and delivery](01-baseline-and-delivery-model.md) | Authority, current state, scope and stage completion rules |
| [02 — Codex agent contracts](02-codex-agent-contracts.md) | Roles, dispatch, inputs/results, ownership, concurrency and escalation |
| [03 — Repository and modularity](03-repository-design-and-modularity.md) | Python/TypeScript boundaries and implementation design practices |
| [04 — Tooling and quality](04-technology-tooling-and-quality.md) | Recommended tools, pinned setup and mandatory checks by technology |
| [05 — Implementation stages](05-staged-implementation-roadmap.md) | Stage scope, automated scenarios, adverse outcomes and qualification checkpoints |
| [06 — Qualification and deferred human review](06-demonstrations-and-human-decisions.md) | Candidate-bound automated evidence and post-IMP-10 GitHub issue follow-up |
| [07 — Work packages](07-work-packages-and-sequencing.md) | Ready-to-start rules, task slicing and parallel ownership |
| [08 — Verification and CI](08-verification-ci-and-evidence.md) | Test strategy, CI lanes, risk-based checks and truthful evidence |
| [09 — Decisions and first stage](09-risks-decisions-and-first-stage.md) | Remaining implementation choices and the first concrete work packet |
| [10 — Sources and validation](10-sources-and-validation.md) | Official documentation, provenance and checks actually run |

The [implementation plan](implementation-plan.json) is the canonical stage/task/dependency/operation allocation. [Agent roles](agent-contracts.json) and [planning contracts](contracts/planning.schema.json) define development-agent work, not CARE-Link's product agents. [Tool catalog](tooling.json) records recommendation and pin status. [Examples](examples/) are unexecuted planning packets, not approvals. [Codex templates](codex/README.md) are ready to adapt but are not installed into `.codex/` by this task.

Start at IMP-00. This workstation and the accepted LLD authority boundaries are retained; the current user-selected model is `qwen/qwen3.8-27b` in LM Studio. Download is user-reported; unknown metadata/capacity remains unknown. Read the [scoped acceptance](../LLD/decisions/2026-11-06-implementation-choices-and-model.md). Local engineering acceptance does not establish independent release, clinical, real-partner or production authority.

Validation: install [validation dependencies](validation-requirements.txt) into an isolated environment, then run `python doc/IMP/validate_plan.py` from the repository root. This checks the planning artifacts; it does not run proposed tools, application tests or demos. All implementation stages begin `planned`, evidence empty and human decisions absent. No PR, commit or activation follows automatically from this planning request.

Configuration update · 2026-11-07: the user authorized installing the seven IMP roles in the demo and workspace configuration. The [active implementation workflow](../../.codex/IMP_WORKFLOW.md) now requires separate slice/follow-up chats, durable slice/session handoffs, modular source ownership and an uncluttered root. This supersedes the earlier dormant-only configuration statements above; the planning templates remain unchanged. No implementation stage is activated.
