# Implementation slice sessions

Read AGENTS.md, doc/IMP/README.md, doc/IMP/02-codex-agent-contracts.md and doc/IMP/03-repository-design-and-modularity.md before implementation. Preserve accepted REQ/HLD/LLD boundaries and current human gates.

## Session and handoff ownership

Each service slice implementation starts in its own Codex chat. Each follow-up starts in a separate chat, scoped to that same slice. A specialist thread is bounded assistance within a chat, not a replacement for this separation. Do not automatically launch another chat or advance to another slice.

Use one durable folder per slice: doc/IMP/slices/<IMP-NN>-<slice-slug>/. Bind it to the canonical stage and task IDs; several slices may belong to one stage. Keep the canonical plan in doc/IMP/implementation-plan.json rather than duplicating it. Create the folder only when the slice is actually assigned. Implementation code belongs in the source tree, not this documentation folder.

The slice README.md records scope, stage/task/operation IDs, source references, dependencies, owned code paths, current state, evidence and unresolved decisions. Keep each chat's work packet, results and handoff in sessions/<NNN>-<purpose>/ beneath the slice folder. Use the existing WorkPacket/AgentResult/DemoPacket contracts for applicable records; a handoff does not grant authorization.

At chat start read the slice README and most recent handoff, inspect current branch/commit and uncommitted changes, confirm prerequisite gates and scope against the current user instruction, and identify changed sources. Do not assume access to earlier chats or treat old packets as new authorization. At chat end update the slice README and session handoff with changed files, actual checks and evidence, failures/not-run reasons, remaining work, decisions and a concrete next-chat starting point. Record actual human decisions separately; never infer stage acceptance.

## Modular implementation and uncluttered root

Follow doc/IMP/03-repository-design-and-modularity.md: apps/ for clients; services/ for deployable services; host/ for host components; packages/ for cohesive shared contracts/domain/policy/rendering; config/ for configuration; deploy/ for deployment assets; tests/ for cross-component verification; tools/ for development automation; doc/ for documentation. Reuse established directories. Do not create a root folder for each slice or chat. Keep only necessary workspace manifests, lockfiles, top-level guidance and entry configuration at the repository root. Keep caches/build outputs ignored and temporary files outside the source tree. Do not create empty scaffolding for future stages.

Use cohesive capability modules, explicit public interfaces, typed contracts, thin transport handlers, application use cases, domain logic and adapters with dependency injection at composition roots. Keep domain code independent of frameworks/persistence, prohibit circular and private cross-service imports, and avoid catch-all utils or oversized modules. Extract shared code only for an actual shared responsibility. Co-locate service-specific tests/configuration/migrations with their owner where the accepted layout permits; use tests/ for cross-service checks. Verify meaningful behavior and import/dependency boundaries with checks appropriate to the slice. Preserve trust and credential isolation; directory structure alone is not enforcement.

## Agent coordination

The primary owns integration and handoffs. Use imp_scope for decomposition, imp_python/imp_web/imp_platform/imp_controls for exclusive scoped implementation, imp_verifier for behavioral evidence and imp_review for read-only integrated review. Delegate only useful bounded work, at most three concurrent specialists across all roles, with no nested delegation. All specialists read this workflow and the assigned slice/session records; exact authorized WorkPacket paths and resource leases control writes. Review includes session continuity, module boundaries and root clutter. When custom agents are unavailable, perform equivalent sequential passes and report that limitation. No commit, push, deployment or host/model change follows from configuration alone.
