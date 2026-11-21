# Documentation handoff — Qwen / LM Studio

The user's current model direction is Qwen3.8-27B on this laptop through LM Studio. The documented installed candidate is lmstudio-community/Qwen3.8-27B-MLX-4bit. The serving API identifier and loaded artifact/tokenizer/template remain unknown. This documentation supersedes the prior model-selection direction, while preserving its historical evidence.

The [decision and integration plan](../../../../../decisions/2026-11-20-qwen-lm-studio-integration.md) records:

- Prior read-only observations: M4 Max / 36 GiB, LM Studio0.4.28+2, three MLX4-bit shards about14.95 GiB; public API1234 refused connections, internal application port41343 responded404 to inference API routes. No inference request or server/model change occurred.
- Conditional adequacy for the private synthetic demo; one initial active generation, existing ceilings, short outputs and function-specific EN/FR/usefulness/adversarial/performance evidence.
- Proposed bounded LangGraph orchestration beneath existing coordinator/broker authority, eight associated capability profiles and human review/effect boundaries. Adoption/version selection and implementation remain pending.
- Fixed authenticated discovery/generation/host tokenization interfaces, coordinated model/schema/fixture/source migration, grounded synthesis/tool expansion and staged admission.
- Identity/capability, data/memory, injection containment, network, supply-chain, resource and audit controls; versioned OWASP/ATLAS threat/test mapping recommendations.

Project/REQ/HLD/LLD/IMP indexes and the directly affected AI documents link the current direction. Their intentional input/artifact hash changes are recorded in inventories with previous/new hashes. Canonical machine model-pin/default fields and source retain the earlier Gemma baseline pending coordinated implementation; no schema regeneration or source edit was performed. Historical decisions, session001 results/candidate/handoff and their receipts remain unchanged.

The primary authored the documentation; configured hld_review supplied a bounded read-only consistency review. See [validation](validation.json) for actual checks and limits; [baseline](baseline.json) records pre-edit documentation and preserved non-documentation hashes. Missing openapi_spec_validator in the application environment prevented the unchanged full LLD validator from starting; documentation-specific integrity/link/JSON checks and the IMP plan check are used for this scope. No missing dependency was installed or validator weakened.

Next implementation should start as its own scoped chat/session, read this record and the IMP-06 source handoff, reconcile actual state, migrate the model pins and preserve historical evidence, then verify the exact local runtime and useful functions. G-06 stays blocked/unqualified; human usability/screen-reader/visual/language review remains deferred_until_after_IMP10. There was no model load, framework/SDK installation, service/host configuration, deployment, commit, push or publication in this documentation follow-through.

## Subsequent server-enabled verification — 2026-11-20

The user enabled the server and loaded Qwen. Direct host discovery reports `qwen/qwen3.8-27b`, an 8192-token context and server parallel setting 4; a short synthetic completion returned `READY` in about 5.26 seconds. This supersedes the earlier reachability/unknown serving-ID observations above. Exact artifact binding and application qualification remain pending. Requests succeeded without authentication; the response had a reasoning field, whose text was not retained. See [sanitized evidence and current checks](connectivity-verification.json). Earlier validation receipts remain historical. Application/model configuration was not changed by the agent; AI remains disabled.
