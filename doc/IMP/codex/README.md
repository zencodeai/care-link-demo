# Dormant Codex role templates

The seven [agent TOMLs](agents/) and [project fragment](project-config.fragment.toml) use the official standalone agent format reviewed on 2026-11-06. They are not installed into .codex/ by this planning task. Existing HLD/LLD roles remain untouched.

After explicit configuration authorization, reconcile the project AGENTS guidance with [AGENTS.fragment.md](AGENTS.fragment.md), merge the two project agent settings without replacing unrelated config, copy the imp_* files into the project .codex/agents directory, and start a fresh applicable client/session. Verify actual role discovery and a bounded read-only task before relying on delegation. Workspace-root users must route to the canonical demo guidance without claiming that mirrored templates are already active.

No model, reasoning effort, provider, MCP, approval or sandbox override is included. The parent session controls those settings. Read-only instructions do not establish a new sandbox. At most three spawned specialist threads; no nested delegation. The application Gemma identifier must never become a Codex `model` setting by substitution.

Native TOML syntax checks establish only parseability/expected fields, not client discovery or execution. See [official custom-agent documentation](https://learn.chatgpt.com/docs/agent-configuration/subagents).
