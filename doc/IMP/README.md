# CARE-Link implementation planning

Version 0.1 · 2026-11-06 · Proposed plan for human review. No application implementation, tool installation, host change or deployment is performed by this package.

Implement the accepted LLD as small, demonstrable service slices. Use Codex specialists for bounded analysis and scoped work, preserve one accountable integration owner, and require explicit human decisions on exact stage candidates. Security/governance controls are built into the earliest relevant behavior, not deferred to a final audit.

| Read | Purpose |
|---|---|
| [01 — Baseline and delivery](01-baseline-and-delivery-model.md) | Authority, current state, scope and stage completion rules |
| [02 — Codex agent contracts](02-codex-agent-contracts.md) | Roles, dispatch, inputs/results, ownership, concurrency and escalation |
| [03 — Repository and modularity](03-repository-design-and-modularity.md) | Python/TypeScript boundaries and implementation design practices |
| [04 — Tooling and quality](04-technology-tooling-and-quality.md) | Recommended tools, pinned setup and mandatory checks by technology |
| [05 — Implementation stages](05-staged-implementation-roadmap.md) | Stage scope, demonstrations, adverse outcomes and human gates |
| [06 — Human demonstrations](06-demonstrations-and-human-decisions.md) | Demo packets, decisions, evidence binding and progression |
| [07 — Work packages](07-work-packages-and-sequencing.md) | Ready-to-start rules, task slicing and parallel ownership |
| [08 — Verification and CI](08-verification-ci-and-evidence.md) | Test strategy, CI lanes, risk-based checks and truthful evidence |
| [09 — Decisions and first stage](09-risks-decisions-and-first-stage.md) | Remaining implementation choices and the first concrete work packet |
| [10 — Sources and validation](10-sources-and-validation.md) | Official documentation, provenance and checks actually run |

The [implementation plan](implementation-plan.json) is the canonical stage/task/dependency/operation allocation. [Agent roles](agent-contracts.json) and [planning contracts](contracts/planning.schema.json) define development-agent work, not CARE-Link's product agents. [Tool catalog](tooling.json) records recommendation and pin status. [Examples](examples/) are unexecuted planning packets, not approvals. [Codex templates](codex/README.md) are ready to adapt but are not installed into `.codex/` by this task.

Start at IMP-00. Existing choices—this workstation, `google/gemma-4-12b-qat` in LM Studio and the accepted LLD directions—are retained. Download is user-reported; unknown metadata/capacity remains unknown. Read the [scoped acceptance](../LLD/decisions/2026-11-06-implementation-choices-and-model.md). Local engineering acceptance does not establish independent release, clinical, real-partner or production authority.

Validation: install [validation dependencies](validation-requirements.txt) into an isolated environment, then run `python doc/IMP/validate_plan.py` from the repository root. This checks the planning artifacts; it does not run proposed tools, application tests or demos. All implementation stages begin `planned`, evidence empty and human decisions absent. No PR, commit or activation follows automatically from this planning request.
