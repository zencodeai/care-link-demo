# Agentic execution and scoped knowledge implementation

Date: 2026-11-20. Current amendment to LLD07 for the explicitly assigned IMP-06 continuation. [Architecture/decision](../decisions/2026-11-20-agentic-workflows-and-clinical-rag.md) defines authority and limits. This specifies new behavior; it does not restore historical deleted design or claim runtime admission.

## Ownership and dependency map

| Module | Responsibility / boundary |
|---|---|
| `care_link_knowledge` | Parse immutable closed catalog, derive integrity refs, filter by actual role/locale/period and bounded rank. No network or patient store |
| Data assistance service | Resolve current authorized session assertions, select knowledge in the configured synthetic-region binding, pin catalog and exact sources, recheck before inference/review |
| Core assistance gateway/broker | Authenticate actor/runtime separately, admit task, retain actor custody, queue metadata, validate exact inference result, return unsent review context |
| Runtime LangGraph runner | Execute existing lease→inference→proposal ports with bounded reference-only graph state; no direct model/Data route |
| Inference gateway | Rebuild current context, verify release and exact tokens, bound output/deadline, reject unsupported claims and native tool execution |
| Host loaded-model binder | Hash artifact metadata/weights, resolve already-loaded SDK instance with no autoload, check instance/config/template identity before/after tokenization |
| Actor UI | Explicit command or account/session-bound automatic opt-in, read-only bounded polling, separated source categories, exact review and manual fallback |

## Transport contracts

[Additive OpenAPI](contracts/agentic.openapi.json) is generated from the shared schemas for the two new transport endpoints. These supplement the canonical206 business-operation allocation; they do not silently change its historical count.

`KnowledgeQuery` is a closed object: query1..500 characters and locale en-CA/fr-CA. `KnowledgeResults` includes catalog SHA256, at most4 entries and synthetic-demo notice. Each entry carries SourceRef, title, text≤2000, HTTPS source URL, source title and locale. The current authenticated actor determines role; no caller-provided role or patient ID is accepted. POST `/v1/assistance/knowledge` performs authenticated lookup only and never dispatches an effect.

POST `/internal/v1/broker/work` accepts an empty closed object under the exact Runtime workload verifier. Its result is either three nulls or canonical task ID, positive decimal task revision and nonnegative decimal fence. Mixed null/present values, unknown fields and extra query arguments are invalid. `RuntimeWorkItem` aliases the common `RuntimeWork` shape. `AssistanceTaskContext.execution_fence` is an additive optional wire property for older readers; Data supplies it, and dispatch fails closed if it is absent. Fences are authoritative values, never inferred from revision.

`AssistanceDraftContext.sources` retains existing ref/text and adds optional title/source_url/source_title for protocol entries. Older assertion entries remain compatible. Runtime never supplies these metadata fields. Canonical shared JSON schemas and generated Python/TypeScript/browser validators remain the contract source.

## State, counters and recovery

Task creation and revision use existing authenticated, idempotent Data commands. Only a `scoped` task enters the bounded8 metadata queue. Duplicate publication for the same task updates references without creating another task. A full queue returns an explicit capacity outcome; an already committed task is recovered only with its original idempotency identity or explicit revision, not another task silently. Claim removes one bounded metadata entry, resolves current actor custody and reads current task availability/revision/fence. Revoked, inaccessible, stale or non-scoped entries cannot execute.

Runtime takes the existing fenced lease and uses the same task/step/revision through inference and proposal. Heartbeats renew only that current lease. The graph does not gain its own retry budget or checkpointer. Data remains owner of the four steps, three tools and two proposal attempts. No graph loop initiates referral sends, new actor tasks, policy changes or model-selected tools.

Core restart loses ephemeral queue/actor custody; Data records persist but cannot reconstruct authority from model/task content. A lost work-poll response can strand the task; UI/manual service stays available and explicit actor recovery is required. Reclaim and retry must pass existing lease/fence guards. Checkpoint persistence or replay is not exactly-once external delivery.

## Knowledge schema and retrieval

`care-link.knowledge.v1` has revision and at most128 entries in a ≤1MiB duplicate-free JSON document. Each entry has canonical UUID, decimal revision, section ID, title/text, locale, roles, synthetic population, CA-ON collection, content status, effective/review dates, publisher URL/title, license notice and bounded index terms. Entries are immutable serialized values. Duplicate identities/section-locales, malformed scope, URL credentials, unknown fields and invalid date ranges are rejected.

The catalog digest identifies exact file bytes; each protocol SourceRef digest binds all entry metadata and text. Filter current actual actor role, exact locale and active review period before scoring token/concept overlap, then return at most4 positive matches with deterministic tie order. There is no vector model, cross-patient similarity search, remote retrieval or LLM-generated search authorization. Data uses only permitted assertion text, with a bounded fallback query if no assertions exist. It pins catalog identity in private task state and rechecks entry identity/expiry at generation, proposal and review. `protocol_read` accepts the existing exact artifact digest, section ID and locale and consumes the durable tool budget.

`synthetic_demo` entries are fictional administrative guidance. `reference_only` entries are allowed only for worker/professional-participant roles and stay labelled as clinical references, with applicability and translation limitations. Integrity verification is not independent clinical approval. Knowledge never supplies a diagnosis, consent, assignment, recipient or policy fact. Actual CA-XX→CA-ON scenario binding is trusted composition configuration; no mapping defaults from unknown jurisdictions.

## Local model and resource configuration

The current model identifier becomes `qwen/qwen3.8-27b` consistently in current machine pins, fixtures, bridge and inference source. Historical Gemma evidence retains its identity. No downloaded/loaded model substitution is allowed. Host SDK binding inspects already-loaded handles; `.model(key)` and model load/unload/download operations are absent from application tools. Tokens come from the actual loaded template and tokenizer, bounded by the admitted8192 window.

Observed `reasoning_effort=none` capability must not enter the admitted path unless the token counter renders the exact corresponding prompt. SDK1.5.0 template options may not reproduce this prediction setting. Record empirical results separately, preserve actual template proof, and never replace it with character estimates. Reasoning text is not retained in normal traces or review records.

Runtime alone depends on pinned LangGraph1.2.24. Host bridge alone depends on LM Studio SDK1.5.0. Root lockfile binds transitive versions/hashes. Neither installed LangSmith libraries nor framework availability authorizes cloud tracing; runtime must reject external tracing configuration. Minimal Core packaging includes the knowledge package but excludes Runtime/SDK source and credentials. Source package separation is checked independently of deployed network isolation.

## Verification obligations

Positive cases: real graph calls fixed broker ports, worker task produces an exact source-linked unsent draft, role/locale lookup returns only applicable entries, reference metadata is visible, review uses current refs, and manual UI remains operable. Negative cases: invalid role/locale/catalog, expired or mutated source, clinical reference to nonprofessional role, unknown jurisdiction, changed actor/runtime fence, wrong task identity, forged tool/approval, duplicate/replayed command, full queue, lost response/restart, context overflow, provider truncation, timeout with unknown compute and unauthorized network route.

Run real PostgreSQL for durable source/lease/review behavior; mock transport tests are not deployed TLS/isolation proof. Run real Chromium EN/FR/axe/keyboard/reflow against synthetic fixtures and separately run loaded-model/tokenizer tests. Keep raw prompts/reasoning/secrets out of receipts. G-06 remains unqualified for any failed/unrun mandatory test. Human usability, clinical/language review and production assurances are not inferred from automated passes.

## Provider evidence-selection amendment

The local model-facing DTO is `ModelEvidenceSelection`: closed object containing1..12 unique integer indices0..63. The context builder assigns indices to ordered scoped data items; instructions and task-state entries are never selectable evidence. The gateway rejects duplicates, invalid/out-of-range references and omitted patient assertion entries before constructing `Proposal` from current request task/step/fence/revision, exact selected texts/SourceRefs, `next=null` and no effect-completion claim. Canonical Proposal validation and Core exact-excerpt custody remain mandatory. More than12 mandatory assertion entries fail preflight before tokenization/provider work and require reduced scope, not silent omission. The full reconstructed draft remains bounded by the canonical Proposal text limit, separately from the model-token budget.

The generic proposal/tool schema is not sent to the MLX grammar compiler. Its unsupported `uniqueItems` generation keyword may be omitted from the narrow wire grammar only because full local uniqueness validation still denies duplicate outputs. No `oneOf` approximation or tool widening is permitted. Canonical proposal, selection schema, actual wire grammar, prompt and implementation hashes belong in qualification evidence.

Non-thinking generation uses per-request settings only. The host invokes the SDK's public `remote_call` method with pinned internal/generated `applyPromptTemplate` RPC types and vendor configuration keys with the matching prediction configuration, then tokenize the actual server-rendered string. This must match the REST provider's reported prompt count; mismatch rejects the entire result. It is not permission to estimate tokens, mutate model settings, autoload an instance or retain hidden reasoning.
