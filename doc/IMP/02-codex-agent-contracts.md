# Codex development-agent contracts

## Roles and control

The primary Codex session is planning coordinator and integration owner. It owns the plan, baseline reconciliation, cross-module contracts, dispatch and final handoff. Specialists return focused analysis or implement only their explicitly assigned work. These are development agents; product-runtime task scope, Gemma tools and human service authority remain in LLD07/08.

| Role | Main responsibility | Boundary |
|---|---|---|
| imp_scope | Decompose a stage, map requirements/operations, identify unresolved decisions and critical path | Read-only planning proposals; no product scope substitution |
| imp_python | Python domain/application/adapters, persistence-facing code and Python checks | Only assigned module/test paths; no direct DB escape from gateway |
| imp_web | React/TypeScript role journeys, review UI, accessibility, client contract adapters | No browser permission authority, private token/cache storage or fake connection state |
| imp_platform | Reproducible builds, scoped persistence/migrations, network/proxy/host/journal and recovery work | No installation/deployment/destructive action merely from a coding packet |
| imp_controls | Identity/policy/consent/security/governance mechanisms and adverse review | Cannot approve its own policy, impersonate a human reviewer or waive fixed exclusions |
| imp_verifier | Independent test design/execution, race/crash evidence and reproducible demonstrations | May write assigned tests/evidence; cannot weaken production controls to make tests pass |
| imp_review | Integrated consistency/correctness/implementability review | Always read-only findings; never human acceptance or stage self-approval |

[agent-contracts.json](agent-contracts.json) is the role/permission specification; [TOML templates](codex/README.md) are the native Codex form. Native files define name, description and developer_instructions, with no model or permission overrides. Official Codex documentation describes project agent files and inherited permissions; instructions to be read-only are not a separate sandbox. [Official subagent configuration](https://learn.chatgpt.com/docs/agent-configuration/subagents).

## Dispatch contract

Every dispatch carries a validated WorkPacket: packet/task/stage IDs; mode; exact goal; baseline commit and file/digest references; read paths; exclusive write paths; dependencies and contract IDs; allowed action classes/commands; explicit prohibited actions; resource leases; expected outputs; positive/adverse acceptance; deadline/budget; reviewer; stopping/clarification conditions. No credentials, private transcripts or hidden model reasoning belong in packets. A prompt such as “implement security” without scope/tests is not ready work.

Modes: `planning` permits read-only analysis and returned proposals; `implementation` allows only assigned file edits and authorized local checks; `verification` allows assigned tests/evidence and declared checks; `review` is read-only. Tool/sandbox permissions still govern. Mode does not itself authorize installation, live DB mutation, model loading, deployment, resets, GitHub messaging, commits/pushes or merge. Those require actual session authorization recorded in the packet. Examples are never that authorization.

Scope expansion, missing current authority, incompatible contract, unclaimed shared file, unknown irreversible outcome, critical control defect or stale baseline triggers a finding to coordinator. The agent may continue independent in-scope work but cannot invent an approval or “repair” the HLD/LLD silently. A necessary design amendment becomes a concrete reviewed delta before affected behavior changes.

## Return and handoff contract

AgentResult names packet/task/baseline, status, changed paths, outputs, exact commands and actual results, evidence paths/digests, findings with severity/source/mechanism, unresolved risks, contract/version changes and recommended next step. `not_run`, `blocked` and `unknown` are valid truthful outcomes. Preserve operation/state vocabulary and original human/workload identities. No unsupported “all passed” summary without evidence. Findings must explain the failed behavior and concrete resolution; arbitrary counts are not quality evidence.

Coordinator verifies result identity and baseline, inspects the diff, runs relevant integration checks, reconciles findings and updates the stage evidence. A separate agent thread can review work without providing independent human approval. A read-only reviewer does not edit the result it reviews; fixes return to owner/coordinator and get rechecked.

Under the 2026-11-20 qualification policy, the coordinator records `automated_qualified` from applicable passing automated evidence through IMP-10. Specialists still cannot fabricate human acceptance. Missing interactive observations are recorded as deferred to post-IMP-10 GitHub issue follow-up, rather than blocking the implementation stage. Failed or unrun mandatory automated checks and blocking control defects still prevent qualification.

## Concurrency and file ownership

Use at most three concurrent specialist threads, excluding primary, matching the existing project cap. Delegate only independent bounded tasks when user/applicable project instructions authorize delegation. Do not spawn nested agents or recursive Codex CLI sessions. Use focused context/paths instead of copying the whole repository and repeating the same investigation. End completed tasks; retain meaningful handoff records, not long speculative chatter.

Planning has one writer: coordinator. Implementation can use independent writers only with disjoint claimed paths and compatible contracts. Shared roots—uv.lock, pnpm-lock.yaml, schemas/generation scripts, migrations, release/policy/role registries and stage evidence manifest—are coordinator-owned integration files unless explicitly assigned to one owner. Workers propose dependency changes; coordinator serializes lockfile resolution and compatibility checks. Do not independently regenerate common contracts or merge competing migrations.

If parallel implementation uses separate worktrees, they still share host compute, Docker daemon, ports, cluster and often Git administration. Resource leases name namespaces, volumes, ports, test DB/schema, model slots and side-effect owner. Only one operator mutates a shared demo/recovery gate at once. No worker tears down another's resources. Rebase/integration changes invalidate stale test/review binding and require appropriate rechecks.

## Loading templates and current execution status

Templates are not auto-discovered from doc/IMP. Install only after explicit project-configuration authorization, preserve existing HLD/LLD roles, then confirm discovery in a fresh client/session. If roles are not loaded, the primary can perform the same review passes sequentially and state what ran. Do not claim custom roles executed because TOML parsed. No IMP agents were launched while authoring this plan; planning consistency review was performed sequentially by the coordinator. [AGENTS.md discovery](https://learn.chatgpt.com/docs/agent-configuration/agents-md).
