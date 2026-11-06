# CARE-Link Demo working instructions

## HLD authoring and review

For creating, refining or reviewing doc/HLD, read `.codex/HLD_WORKFLOW.md`. A technical HLD explains how major system parts satisfy requirements: boundaries, responsibilities and authority, interactions, data ownership, deployment, security/governance, failure handling and architectural decisions/trade-offs. It guides implementation planning; it is not a low-level implementation specification.

The primary agent is the coordinating architect and sole HLD writer. For substantial HLD work, delegate focused analysis to the configured hld_sources, hld_service, hld_platform and hld_assurance roles as useful, then use hld_review on the integrated result. Run at most three specialist threads concurrently, queue remaining tasks, and avoid redundant work. Specialists return findings; the primary reconciles them. If custom subagents are unavailable, perform the same passes sequentially and report that limitation. Model/permissions inherit from the active session; do not change them as part of HLD work.

## LLD authoring and review

For an explicit request to create, refine or review a technical LLD, read `.codex/LLD_WORKFLOW.md`. An LLD translates current HLD responsibilities into implementation-ready modules, exact contracts/data, state/algorithms/concurrency, security/governance mechanisms, deployment behaviour and testable outcomes. The primary agent coordinates and is sole writer; use the relevant lld_contracts, lld_data, lld_behaviour, lld_ai, lld_security and lld_operations passes, then lld_review. The shared limit is three concurrent specialist threads, not three per workflow. Specialists return proposals/findings and do not edit or delegate further. Fall back to equivalent sequential review if unavailable and state what actually ran.

Configuring LLD assistance does not authorize creating doc/LLD. The deleted LLD must not be restored. Only a separate explicit authoring request may create a new design from current requirements/HLD. LLD requests allow design-level schemas, algorithms and specification artifacts as needed; they do not authorize implementation, host/database changes or deployment. Preserve the HLD abstraction boundary and explicitly reconcile rather than silently alter architectural decisions.

## Project boundaries

- Useful, actor-led client service is the design objective; agentic AI assists actors under human authority and deterministic runtime controls.
- Respect Ottawa/Ontario context, no police affiliation/integration, absent autonomous emergency contact, private synthetic demo and explicit production/clinical evidence limits.
- Use current user instructions and doc/REQ as requirements; existing HLD is a draft to evaluate, not unquestionable truth. Identify conflicts instead of silently inventing approval.
- `../care-link` is a source reference and `backup/care-link-prod` is historical evidence, not a template or transferred authorization. Do not modify sibling repositories for this task.
- The user deleted doc/LLD. Do not recreate it, restore its contents, or generate implementation schemas/code unless explicitly requested.
- Do not turn missing clinical/legal approvals into an inability to design a synthetic system. Record genuine unresolved authority and deployment decisions without invented gates.
- No deployment, global Codex settings change, GitHub mutation, commit or push follows from an authoring request alone. Follow explicit user authorization for those actions.

For other work, apply relevant project constraints without forcing the HLD workflow on unrelated tasks.
