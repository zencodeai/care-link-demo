# Qwen on this laptop: model direction and integration plan

> Subsequent explicit implementation authority: [current workflow/RAG decision](2026-11-20-agentic-workflows-and-clinical-rag.md). Statements below about recommendations and pre-migration source describe the earlier planning baseline; current source/checks are in session003.

Date: 2026-11-20. Documentation authority: the user selected `qwen3.8-27b`, stated that it is installed in local LM Studio, requested a reachability/adequacy/integration assessment without changes, then instructed “Update documentation with this information.”

The model selection is the user's current direction. LangGraph adoption, additional agent functions, tuning and admission criteria below are recommendations for a later scoped implementation. This document performs no source/configuration migration, package installation, server startup, model load, deployment, activation or publication. G-06 remains unqualified and all AI functions remain disabled.

## Decision and precedence

Use on-premises LM Studio on this laptop with the user-selected **Qwen3.8-27B** as the integration target. This supersedes the **model-selection direction only** of the [2026-11-06 Gemma decision](../LLD/decisions/2026-11-06-implementation-choices-and-model.md). The earlier decision and its evidence retain their historical meaning.

Distinguish three identities:

| Identity | Current information |
|---|---|
| User-selected model | `qwen3.8-27b` / Qwen3.8-27B |
| Installed artifact candidate | `lmstudio-community/Qwen3.8-27B-MLX-4bit` |
| Actual serving instance/API identifier | `qwen/qwen3.8-27b`, observed in the enabled server; exact binding to inspected artifact bytes remains pending |

The source, canonical machine contracts/defaults and current disabled runtime manifest still pin `google/gemma-4-12b-qat`. They describe the pre-migration implementation baseline, not the new desired model. Their migration is explicit remaining work; this documentation does not regenerate schemas, change application constants or make an old evidence packet prove Qwen compatibility. The [implementation plan](../IMP/implementation-plan.json) retains its existing stage/operation allocations and pre-migration model field until coordinated migration. Current user direction takes precedence over the legacy model-selection field, while admission continues to deny an incompatible runtime.

Workstation hosting, synthetic-only access, Ottawa/Ontario/EN-FR context, no police integration or autonomous emergency contact, broker mediation, current deterministic authority, human accountability and absence of remote inference fallback remain unchanged. Selecting a model or documenting a framework is not function admission or clinical/production approval.

## Initial read-only observations

These were observed during the immediately preceding assessment in this chat on 2026-11-20. No exact observation timestamp was captured. They are a point-in-time record, not an assertion of subsequent server state.

| Check | Observed result | Limit |
|---|---|---|
| Laptop | Apple M4 Max; 38,654,705,664 bytes / 36 GiB unified memory | Free capacity and inference performance were not measured |
| LM Studio application | Installed version `0.4.28+2`; process running | Application availability does not establish public inference availability |
| Configured public server | Port `1234`; configured CORS false | Configuration is not a listening-service proof |
| `GET http://127.0.0.1:1234/v1/models` | Connection refused / HTTP status 000, including outside the sandbox | No model listing or generation was obtained |
| `GET http://127.0.0.1:1234/api/v1/models` | Connection refused / HTTP status 000, including outside the sandbox | No loaded model or capability was verified |
| Internal application port | `127.0.0.1:41343` listened; both preceding API paths returned 404 | This internal service is not the public inference endpoint and must not replace it |
| Local artifact directory | `~/.lmstudio/models/lmstudio-community/Qwen3.8-27B-MLX-4bit` present | Directory/name alone does not prove weight provenance or serving identity |
| Weight files | Three Safetensors shards, about 14.95 GiB combined | Full weight-shard digests and loaded-instance mapping were not verified |
| Local configuration | MLX affine 4-bit quantization, group size 64; tool-use/thinking markers in template | Template markers do not prove runtime tool parsing or reliable behavior |
| Architecture label | `Qwen3_5ForConditionalGeneration` / `qwen3_5`; configured text position maximum 262144 | Publisher describes Qwen3.8's Qwen3.5 foundation; this label alone is not evidence of a wrong download. The position maximum is not the loaded or admitted context limit |

At that initial assessment, the public REST inference endpoint was therefore **not reachable**. No inference request was submitted. Loaded model identity, schema/tool support, throughput, latency, cancellation and function quality remain unverified. No application settings, services or model state were changed by the assessment.

Metadata bytes were hashed read-only; these identify configuration files, not verified model weights:

| File in the observed artifact directory | SHA-256 |
|---|---|
| `config.json` | `14b65a0ee06517060a6bbd979bb1a8ff54e7b304b1a1f01d54344b88b8285e85` |
| `tokenizer_config.json` | `47a7a8371379b07650b22f3c8a78c32fed85c4e35ea88e3da0c4b7a7611e8082` |
| `chat_template.jinja` | `c3cf9e34abf4f9e36c2d72165aa9c132d3e2a725b6c2586aaa3a8af9d7a81041` |
| `model.safetensors.index.json` | `13b840162b4cb35c66fef7df072f7dbb4717908204364f5e5d9f9655a2758fa8` |

## Verification after the user enabled the server

On 2026-11-20, after the user reported enabling `http://127.0.0.1:1234` and loading the model, direct host checks succeeded. Sandbox-local curl initially failed; a host-network retry verified the service. This supersedes the earlier connectivity result without rewriting that historical observation.

| Check | Observed result / qualification |
|---|---|
| `GET /v1/models` | Successful JSON listing includes `qwen/qwen3.8-27b`; listing alone does not establish loaded state |
| `GET /api/v1/models` | Model key and loaded-instance ID both `qwen/qwen3.8-27b`; selected variant `qwen/qwen3.8-27b@4bit`; MLX, 4-bit, architecture `qwen3_5` |
| Loaded instance configuration | Context length 8192; server parallel setting 4. This does not admit four concurrent CARE-Link requests; retain one initial active prediction |
| API capability metadata | Reports vision, trained tool use, and reasoning `off/low/medium/xhigh/on`, default `xhigh`. These are advertised runtime metadata, not functional test passes |
| Synthetic generation | `POST /v1/chat/completions`, exact observed model ID, user prompt requesting only `READY`, temperature 0, max_tokens 128, non-streaming; returned `READY` with leading whitespace, finish_reason `stop` |
| Observed elapsed/usage | About 5.26 seconds for this single short request; 64 prompt / 34 completion / 98 total tokens, including 30 reasoning tokens. This is connectivity evidence, not a workload benchmark |
| Reasoning handling | Response contained a separate reasoning field. Its text is omitted from documentation/evidence; application integration must exclude it from retained application data |
| Authentication | These discovery and inference requests succeeded without an Authorization header. Authentication enforcement and listener/network isolation are still integration work, not verified controls |

No model load/unload, server settings or application configuration were changed by these checks. The user performed server activation. Exact full weight/tokenizer/template provenance, schema/tool behavior, reasoning-off behavior, cancellation, EN/FR quality, useful workflow performance and deployed isolation remain unqualified. The [sanitized connectivity receipt](../IMP/slices/IMP-06-bounded-ai-assistance/sessions/002-qwen-integration-documentation/connectivity-verification.json) retains only request metadata, final synthetic answer and bounded observations. CARE-Link remains Gemma-pinned and AI-disabled pending coordinated migration and qualification.

## Adequacy and operating envelope

Assessment: **a credible candidate for the private synthetic demo, subject to local qualification**. The publisher describes instruction/agent capabilities, controllable thinking and vision-language input; the installed conversion targets Apple Silicon. These support evaluation, not an inference of CARE-Link quality from parameter count or general benchmarks. [Publisher model card](https://huggingface.co/Qwen/Qwen3.8-27B), [conversion release](https://huggingface.co/lmstudio-community/Qwen3.8-27B-MLX-4bit).

Start with one resident model and **one active generation**. Retain the existing two-slot hard ceiling while initially admitting only one active prediction; do not infer that two predictions fit. Approximately 15 GiB of weights leaves theoretical memory headroom, but macOS, running demo services, model buffers and context caches share memory. Measure with the existing workload running.

Retain the existing 8192-context/1024-output, 30-second generation,120-second task, four-step/three-tool/two-proposal limits as starting ceilings. Evaluate approximately 512-token outputs for short drafts. These are unchanged ceilings or narrower proposed operating settings, not measured performance. Large advertised model context must not silently enlarge the admitted context. Any ceiling change requires a documented measured delta.

Evaluate non-thinking generation first for interactive navigation, summaries and wording. Trial bounded reasoning only for functions whose quality gain fits their latency/token limits. Compare existing decoding with model-specific recommendations rather than assuming temperature0 is optimal. Confirm that the installed MLX runtime actually supports requested thinking/sampling parameters. Do not retain hidden reasoning or use model reasoning as authorization. Vision/document extraction can be a later isolated function; it is not initially admitted merely because the base model supports multimodal input.

## Orchestration and associated agents

**Recommendation: LangGraph for explicit workflow orchestration, retaining CARE-Link's existing TaskCoordinator, broker, durable ledgers and policy enforcement.** Introduce it for a demonstrated multi-step workflow, not as a replacement security authority. Its graph/persistence/interrupt features fit bounded service steps and human draft review. No LangGraph version has been selected, installed or tested here. [Overview](https://docs.langchain.com/oss/python/langgraph/overview), [persistence](https://docs.langchain.com/oss/python/langgraph/persistence), [interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts).

Agents are separately scoped function/prompt/tool profiles sharing one local model, not an unrestricted autonomous team. Each has actor/resource identity, a goal/completion predicate, approved context/tools, a release version and its own evaluated admission. Framework retries, graph resume and optional critique consume the same durable task counters; they cannot mint new budgets, restore expired approval or create new actor tasks autonomously.

| Agent profile | Workflow | Permitted result / human boundary |
|---|---|---|
| Navigation | Read permitted participant context → retrieve approved protocols/directory → explain options | Cited explanation/questions; no diagnosis or service eligibility promise |
| Worker summary | Retrieve current assertions → preserve facts, reports, missingness and conflicts → summarize | Editable source-linked summary |
| Plan drafting | Read permitted fields and participant wishes → propose an exact diff | Attributed proposed changes; no authored-wish overwrite or consent grant |
| Referral preparation | Compare needs with approved service facts → identify missing information → prepare package draft | Worker review; exact consent and dispatch remain separate commands |
| Handoff/follow-up | Read actual dispatch/receipt observations → explain status → draft follow-up | No inferred acceptance, human connection or automatic reminder send |
| Receiver completeness | Inspect only the receiver's package and approved requirements | Clarification/completeness draft; receiver decides acceptance/capacity |
| Supervisor queue | Inspect authorized queue/aggregate projections → identify operational gaps | Operational proposals; no autonomous clinical prioritization |
| Critique | Compare a candidate with its supplied sources and required fields | Flag unsupported claims/omissions; agreement is not correctness certification or permission |

A representative workflow is actor/task admission → scoped retrieval → structured candidate → factual/schema/source validation → optional critique within budget → human edit/reject/accept → separately authorized domain command if requested. Human waiting ends the execution slice; fresh review/resumption rechecks authority and revisions. Start with worker summary and navigation, then plan/referral drafting, followed by receipt/follow-up and role-specific functions.

LangGraph checkpoints should contain minimal references, revisions and execution state. Private content/checkpoint custody must use controlled Data ports, encryption and lifecycle rules; the framework must not gain an independent business DSN, cross-actor memory or cloud trace export. The existing coordinator remains the single owner of task progress, budgets, fences and effect authorization.

## LM Studio API integration sequence

1. **Serving identity and authentication.** The user has enabled the loopback API and loaded the model; discovery and a synthetic generation now pass as recorded above. In a separately scoped integration, enforce authentication and bind the observed stable serving ID `qwen/qwen3.8-27b` to the exact selected artifact and loaded configuration. Pin all weight shards, tokenizer/template, application and MLX engine versions. Give credentials only to the host bridge; keep model-management permissions/endpoints outside runtime tools. Prevent an unavailable admitted instance from silently auto-loading or substituting another artifact. [Model listing](https://lmstudio.ai/docs/developer/rest/list), [authentication](https://lmstudio.ai/docs/developer/core/authentication).
2. **Coordinated model migration.** Update source constants, admission bundles, disabled runtime manifest, canonical model-pin schemas/defaults/fixtures and generated adapters together. Preserve Gemma source/build/evaluation evidence as historical. Logical Qwen selection and observed serving ID must be separately pinned, rather than guessed from a display name.
3. **Narrow inference adapter.** Use native `GET /api/v1/models` for discovery and loaded-instance inspection; `GET /v1/models` for compatible identifier checks; `POST /v1/chat/completions` for explicit application-owned messages/schema requests. Keep load/unload/download APIs administrative. Reconstruct current context per request rather than trusting model/server conversation state. [LM Studio API](https://lmstudio.ai/docs/developer/rest).
4. **Exact token proof.** On the host bridge, apply the loaded model's actual prompt template and tokenize the rendered messages. Bind the resulting proof to the loaded artifact, tokenizer/template, window and request. Inference must reach this only through the authenticated bridge. No character estimate or SDK network bypass. [Tokenization API](https://lmstudio.ai/docs/python/tokenization).
5. **Runtime capability tests.** Exercise schema output, tool names/arguments and tool-result continuation, malformed/multiple calls, thinking controls, reasoning-field exclusion, truncation/stops, token usage, EN/FR, memory, timeout and cancellation against this exact MLX build. Documentation support is not runtime proof. [Structured output](https://lmstudio.ai/docs/developer/openai-compat/structured-output), [tool-use API](https://lmstudio.ai/docs/developer/openai-compat/tools).
6. **Useful workflow expansion.** Retain the extractive summary as a comparison baseline; qualify source-grounded synthesis/paraphrasing before changing its current literal-excerpt guard. Introduce scoped `plan_read`, `protocol_read`, `directory_search` and `receipt_read`, then unsent `draft_prepare`/`review_request`. Native tool-call requests are normalized into broker proposals, validated and authorized before any execution; framework/SDK tool loops must not bypass that path.
7. **Function admission.** Compare actor-only and assisted completion on identical fictional cases. Admit only passing functions; others stay manual/template-only with explicit reasons. A valid JSON response, available model name or accepted human draft alone does not establish accuracy or function usefulness.

LM Studio documents schema output for MLX using its engine integration; confirm actual schema behavior for this artifact. Qwen's default thinking behavior and vendor sampling controls require explicit runtime tests before they enter a release. No native MCP integration, SDK automatic tool executor, browser/shell access or model-selected destination is enabled by this plan.

## Security and governance architecture

| Control | Enforcement / adverse expectation |
|---|---|
| Human and workload identity | Preserve initiating actor and runtime separately; current scope and live workload fence/certificate checked before disclosure or effects |
| Scoped capability | Exact resource/fields/purpose/tools/expiry and current epochs; null binding never means all resources |
| Broker | Closed schemas, current policy, audit, idempotency and reserved budgets before tools; no model-granted authority |
| Network isolation | Runtime → broker; inference → approved Data/host bridge; host bridge → fixed loopback LM Studio. Deny direct runtime/model/DB/Internet paths |
| Injection containment | Reports, retrieved content, model output and observations stay untrusted; they cannot become policy, tool registration, recipient destinations or permission |
| Memory and checkpoints | Per-task isolation, minimized encrypted state, lifecycle controls and no unrestricted cross-actor retrieval |
| Review and effects | Source display, exact diff/digest/expiry; source/payload/ownership/epoch changes stale approval. Business action is a separate current domain command |
| Resource exhaustion | Bounded steps/tools/proposals/tokens/deadlines and one initial active prediction; uncertain compute remains occupied until completion/verified stop; manual capacity stays independent |
| Supply chain | Pin model/conversion/framework/engine/templates/schemas/tools, signatures and release evidence; verify compatibility before admission |
| Observability | Local metadata, decisions, references, versions and timings; no secrets, raw prompts or hidden reasoning in normal application traces; verify actual LM Studio log retention |

Map each function to version-pinned [OWASP Agentic Applications guidance](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/), [Securing Agentic Applications V2](https://genai.owasp.org/resource/securing-agentic-applications-v2/) and [MITRE ATLAS](https://github.com/mitre-atlas/atlas-data), with concrete denial tests and residual risks. Review edition changes explicitly; the existing pinned LLM 2025 mapping is not silently replaced. This is a proposed verification crosswalk, not a compliance/security certification or a guarantee that prompts prevent injection.

## Delivery, acceptance and current state

Deliver as a scoped IMP-06 follow-up: connectivity/identity → real summary baseline → one bounded graph workflow → separately evaluated synthesis/navigation/referral functions → adverse and performance qualification → release only passing functions. Benchmark with demo services running, one generation first and bounded output. If the existing 30-second ceiling cannot be met reliably, reduce scope/context/output and preserve manual service; do not silently enlarge deadlines or switch models.

Evaluate factual completeness, preserved conflicts/missingness, resolvable citations, numeric/identity fidelity, appropriate uncertainty, EN/FR fidelity, correct tool choice and completion time. Exercise cross-client leakage, injected sources, forged tool/approval claims, stale sources/consent/assignment, runtime revocation, duplicate/replayed effects, crash/restart, unknown compute and manual completion after all AI is rejected. The adversarial suite must observe no unauthorized effects; report failed/unrun cases honestly.

Actual clinical assessment, consent, eligibility/capacity acceptance and emergency decisions remain human/domain responsibilities. Automated implementation qualification through IMP-10 does not remove product-runtime human review; separate human usability/screen-reader/visual/language review remains `deferred_until_after_IMP10` under the [current policy](../IMP/06-demonstrations-and-human-decisions.md).

**Current source status:** the [IMP-06 implementation handoff](../IMP/slices/IMP-06-bounded-ai-assistance/sessions/001-implementation/handoff.md) remains the historical Gemma-pinned first-profile candidate. All AI admissions are disabled, G-06 is not automated-qualified, Qwen integration/framework adoption is planned, and no execution follows from this documentation update.
