# Qwen integration documentation follow-through

Date: 2026-11-20. User instruction: “Update documentation with this information,” referring to the preceding Qwen3.8-27B / on-premises LM Studio assessment and detailed integration plan.

This is a documentation follow-through in the current chat. It creates no implementation task or runtime activation. [Current direction and integration plan](../../../../../decisions/2026-11-20-qwen-lm-studio-integration.md) is the authoritative documentation record; [handoff](handoff.md) distinguishes user selection, observations, recommendations and remaining implementation.

Existing IMP-06 source, historical session001 evidence, runtime model pins and machine contracts are preserved. LangGraph is recommended for bounded workflows; it is not installed, adopted or tested. G-06 remains unqualified and AI stays disabled. No server/model/host action or commit/push follows from this documentation request.

## Subsequent server-enabled verification — 2026-11-20

The user enabled the server and loaded Qwen. Direct host discovery reports `qwen/qwen3.8-27b`, an 8192-token context and server parallel setting 4; a short synthetic completion returned `READY` in about 5.26 seconds. This supersedes the earlier reachability/unknown serving-ID observations above. Exact artifact binding and application qualification remain pending. Requests succeeded without authentication; the response had a reasoning field, whose text was not retained. See [sanitized evidence and current checks](connectivity-verification.json). Earlier validation receipts remain historical. Application/model configuration was not changed by the agent; AI remains disabled.
