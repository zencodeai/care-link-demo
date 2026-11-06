# Codex technical-design configuration

Project guidance: [AGENTS.md](../AGENTS.md). Workflows: [HLD](HLD_WORKFLOW.md) and [LLD](LLD_WORKFLOW.md).

Five hld_* and seven lld_* specialist definitions live in agents/. The primary session coordinates and writes; specialists return focused findings/proposals. The shared cap is three concurrently spawned specialist threads, excluding the primary, regardless of workflow. Model, approval, sandbox, provider and MCP settings inherit from the session; no global settings are changed. Read-only specialist behaviour is an instruction, not a separate enforced sandbox or independent human approval.

Choose HLD for architectural boundaries/responsibilities/interactions/trade-offs. Choose LLD only for an explicit implementation-design authoring/review request. Configuration does not create design content. The previous LLD remains deleted and must not be restored; a new requested design uses current requirements/HLD.

Start a new Codex session in care-link-demo to load project guidance and custom agents. The care-link-workspace startup root mirrors the role definitions and routes to the canonical workflows here. Existing sessions may not reload configuration. Confirm custom roles are discoverable before relying on them; otherwise use sequential equivalent passes and report it. TOML validation does not establish runtime discovery or specialist execution.

Official configuration references: [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents), [AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md). Standalone roles define name, description and developer_instructions; project config controls availability and shared concurrency.
