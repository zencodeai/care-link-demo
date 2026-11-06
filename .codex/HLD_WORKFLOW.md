# HLD authoring workflow

Configuration date: 2026-11-06. This configures Codex development assistance, not the runtime agent framework of CARE-Link.

## Definition and output boundary

Requirements state what must happen. The HLD explains how major parts work together and why the architecture is appropriate. A later LLD defines precise implementation. Write for a technical reviewer who has not read the chat. Prefer connected explanations, responsibility/authority tables and a few purposeful diagrams. Document count, word count and mechanical trace coverage are not substitutes for architectural quality.

Include: system context and exclusions; actors and meaningful service workflows; agentic-AI place and authority limits; component responsibilities and logical interfaces; major data entities/ownership/lifecycle; human/workload authentication and trust boundaries; realtime security/governance enforcement; deployment topology; availability/performance assumptions; major failure/degraded/recovery behaviour; observability; alternatives/decisions/trade-offs; open issues and requirement trace.

Exclude by default: full API schemas, physical table/column dictionaries, source code, function signatures, detailed lock/retry algorithms, exact manifest YAML and unsupported fine-grained implementation defaults. An architectural guarantee that depends on these mechanisms may be explained semantically; leave detailed specification for an explicitly requested implementation-design task. Never recreate the deleted LLD automatically.

## Execution sequence

1. Read current user request, repo AGENTS.md, doc/REQ index, relevant requirements/decisions and existing HLD. Inspect repository status; preserve unrelated changes. Identify acceptance objectives and scope before writing. Do not ask the user to reconfirm established constraints.
2. Primary author produces a short architecture brief: service goal, major actors, constraints, candidate boundaries, known conflicts and design questions. This is working material, not a required new approval artifact.
3. Delegate independent focused analysis: hld_sources for evidence/trace; hld_service for actor/AI workflows; hld_platform for topology/data/operations; hld_assurance for trust/runtime controls. Use only relevant roles on narrow tasks; no more than three concurrent specialist threads and no nested delegation. Do not give several agents the same files to edit. If tooling is unavailable, conduct these passes sequentially.
4. Primary selects/coheres the architecture and writes the authorized HLD changes. Resolve conflicting findings with evidence and explicit alternatives/trade-offs. Technology choices require a reason and verification limits. Do not invent actual installation, performance, legal status or approvals.
5. Run hld_review on the integrated draft. Review at least one normal actor journey, human takeover, model failure, policy/audit failure, revocation and restore scenario across document boundaries. Keep significant unresolved findings visible; correct genuine defects within scope without repeatedly requesting permission.
6. Verify local links, consistent component/actor names and authority, requirement trace, parameters versus measured targets, and diagram syntax/rendering if a renderer is available. State visual verification limits honestly. Refresh a design-input inventory only when inputs intentionally changed; do not mask source drift.
7. Report changed files, resolved design issues, meaningful remaining decisions and checks performed. No auto-merge or agent self-approval. Human review is distinct from AI specialist review.

## Specialist return format

Return a compact table: finding ID; severity (major/minor/question); requirement/source evidence; affected component/workflow; recommended architectural resolution; residual decision if any. Include useful alternatives and benefits, not only hazards. No claims of review or tool execution that did not occur.

## HLD quality checklist

- A reviewer can explain the service goal, system boundaries and each actor's service journey.
- Agentic AI has concrete useful tasks and bounded coordination, with explicit human and deterministic authority.
- Each major component has responsibility, data ownership, input/output relationships and dependency/failure behaviour.
- Major workflows agree with diagrams, component interfaces, identity scopes and deployment topology.
- Inline security/governance enforcement is distinguishable from monitoring, PR review and human approvals.
- Human/workload/mesh identity, credential lifecycle and compromise/outage handling have architectural ownership; a specific mesh product is not assumed without justification.
- Failures preserve only capabilities that actually survive; no false human connection, exactly-once delivery, instantaneous revocation, immutable local root, or whole-host redundancy claim.
- Backup restore distinguishes current authority, quarantine and serving readiness; lifecycle/continuation recovery gaps are identified at architecture level.
- Decisions explain alternatives/trade-offs; material unknowns remain explicit without blocking unrelated design work.
- Synthetic-demo limitations do not replace useful service design or imply clinical production approval.
- HLD remains high level; no accidental LLD, duplicated compliance framework or implementation backlog disguised as architecture.

## Example request

“Review and refine doc/HLD against the HLD definition. Use the configured specialist roles, keep the primary author as sole writer, preserve current requirements and exclusions, remove implementation-level drift, and report architectural decisions and remaining gaps. Do not create an LLD.”
