# Actor-support agentic AI architecture

> Current direction · 2026-11-20: [Qwen3.8-27B with on-premises LM Studio](../decisions/2026-11-20-qwen-lm-studio-integration.md) replaces the earlier Gemma selection. [Bounded LangGraph execution and scoped clinical knowledge](../decisions/2026-11-20-agentic-workflows-and-clinical-rag.md) are now selected for the explicitly authorized implementation; the existing deterministic coordinator, broker, human authority and isolation boundaries remain. See the current decision and session evidence for implementation and qualification separately.

## Architectural role and value

AI supports actors through a bounded cycle of goal, permitted context, proposed next step, authorized tool observation and revised task progress. This is more than one chatbot answer but less than an autonomous care provider. Grounded navigation, context preparation, editable documentation and handoff follow-through reduce avoidable worker burden and help clients make informed choices. A fluent model response alone does not establish a useful or safe workflow.

The deterministic core owns task scope, durable progress, budgets and human-review state. The isolated runtime proposes plans/content, holds no store/partner credentials and communicates only through the broker. The broker mediates inference and every tool step; the inference gateway is the only host model path. Agent specializations are task/prompt/tool profiles in one bounded runtime initially. LangGraph coordinates explicit bounded steps through these ports. Framework state does not replace the deterministic coordinator or expand agent authority.

## Assistance functions and authority

| Assistant | Permitted context / useful result | Approval and boundary |
|---|---|---|
| Client/PID navigator | Own needs/preferences, reviewed knowledge, permitted plan and directory options | Client retains choice and sharing; only reviewed template/source content reaches clients automatically |
| Carer assistant | Own attributed reports and authorized shared facts, carer-directed services | Cannot create PID consent or disclose private youth content |
| Worker copilot | Assigned timeline, missing/conflicting facts, sourced protocols | Editable summary/response/referral drafts; worker verifies clinical facts and accepts final professional communication |
| Handoff coordinator | Authorized queue, referral and receipt observations | Tracks incomplete work and proposes recovery; acceptance/connection remains evidence from human/receiver |
| Receiver/navigator assistant | Only consented receiving package and own service status | Completeness/clarification/logistical drafts; receiver confirms capacity, receipt and acceptance |
| Planning/follow-up assistant | PID-authored wishes, scoped sharing and separate contact consent | Draft plan/follow-up proposals; no unilateral grant, reminder or transmission |
| Supervisor assistant | Scoped service demand and aggregate operational context | Suggests review/reassignment, not autonomous clinical queue priority or individual surveillance |
| Operations/security/governance/audit assistant | Authorized health/events/rules/evidence | Runbook/evidence/incident drafts; cannot approve, certify, access secrets or edit live policy |
| Training assistant | Fictional personas/scenario controls and instructor rubric | Role-play/debrief proposals, instructor oversight; no clinical competence credential |

Read-only draft preparation may run automatically within an authorized goal. Narrow low-risk searches/status checks may execute under deterministic preauthorization. Consequential disclosure/transmission and professional communication require exact scoped human approval as well as current deterministic authorization. Deterministic hazard/human-help protocols never wait for the model or optional draft review.

## Coordination, context and review

Tasks are durable service objects with an initiating actor, responsible human, purpose/session, allowed data/tools, approved model/prompt and bounded completion conditions. Runtime process state is disposable. Observations/checkpoints permit safe resumption without rerunning a possibly completed effect. Cancellation, takeover, revocation or changed source/policy state invalidates affected pending work and output. Budgets apply across retries/delegation, not per endlessly restarted step. No dynamic tools, arbitrary browsing/code, cross-session memory or online self-modification.

Context assembly labels instructions, approved sourced facts, structured state and untrusted reports/tool text. Facts are not instructions; model output cannot upgrade labels or supply authority. Critical unknown/conflict markers survive context selection, and an overlarge task is reduced/reviewed rather than silently dropping critical context. Directory recipients are resolved from authoritative stable IDs, not text-generated endpoints.

Review presents original attributed facts, source timestamps, suggested changes, uncertainty, recipient/purpose/fields and intended effect. Human can accept/edit/reject without pressure; material changes invalidate old review. Human acceptance does not replace consent, legal basis, current policy or model validity evaluation. Raw unchecked model tokens are never streamed as authoritative client guidance. Protected manual work remains possible when all AI suggestions are rejected or AI is disabled.

## Local inference boundary

Use requested host LM Studio and `qwen/qwen3.8-27b` through a constrained authenticated inference gateway/host bridge. No runtime-to-host exception or remote fallback is permitted. Pin exact artifact origin/license/digest, loaded identifier, quantization, prompt/decoding and server capability before task admission. Supported structured output/tool behaviour and cancellation depend on the actual model/runtime, not an SDK label.

Inference is asynchronous bounded work separated from human messaging/help and deterministic urgent processing. Shared parameter budgets constrain context/output, concurrency, queue and retries; they are unmeasured targets. A timeout does not prove GPU work stopped, so pending results are fenced and capacity recovery is verified. Temperature zero is not deterministic generation or clinical confidence.

Malformed/unsourced/tainted proposals reject the whole affected proposal before partial tool effects. Model unavailable, overload, unsupported task, context overflow or uncertain output routes to reviewed template/manual assistance, not invented facts or replacement model. Each assistant function needs task-specific grounding, critical-fact, EN/FR, latency, multi-turn/adversarial and actor-usefulness evidence. Recorded model output supports deterministic service replay; regenerating identical text is not required.

## Decision and limitation

Selected approach favours a small explicit coordinator with isolated model proposals over autonomous multi-agent services. It preserves useful planning/tool observation while reducing authority laundering and recovery complexity. Model task capability and source-owner approval of broker-mediated inference remain unresolved before affected integration. Refer to [requirements service research](../REQ/10-agentic-ai-and-service-model.md) for comparator evidence and its limits; it does not validate local Qwen for clinical use.

> This prototype demonstrates control and containment architecture using non-clinical stub logic and synthetic data. It provides no evidence of clinical safety, triage validity, or equity performance, and must not be cited as such.

The [2026-11-06 LLD/workstation/model acceptance](../LLD/decisions/2026-11-06-implementation-choices-and-model.md) is historical evidence for the earlier workstation/Gemma choice. The user subsequently selected Qwen and authorized the current workflow/RAG implementation. [Session003](../IMP/slices/IMP-06-bounded-ai-assistance/sessions/003-agentic-workflows-rag/) records actual source, model observations and verification; no clinical or deployed qualification follows from model availability. Broker/host boundaries and existing budgets remain.

## Workflow preparation and clinical knowledge

An authorized actor command or account/session-bound opt-in starts worker preparation. Core publishes bounded metadata; an independently identified Runtime claims it and executes the lease/inference/proposal graph through the broker. Data supplies current permitted reports plus applicable catalog references. Human review receives an unsent result, separated patient/reference evidence and publisher/version metadata. Automatic read-only work reduces repeated prompting while current domain commands retain every consequential effect. Lost dispatch metadata requires explicit actor recovery rather than reconstructed authority.

Knowledge retrieval uses one immutable, network-free catalog library in Core for patient-independent role lookup and in Data for patient-scoped context. Role, language, period and configured synthetic-region applicability are enforced before ranking. The first retrieval baseline is lexical; no vector or clinical applicability score is claimed. Clinical references remain professional-only and distinct from authored fictional demo guidance. Catalog changes/expiry stale pending work. Research snapshots are evidence inputs, not executable instructions or automatically admitted content.

The [current decision](../decisions/2026-11-20-agentic-workflows-and-clinical-rag.md) records alternatives, clinical-source boundaries and failure behavior. Worker preparation and six-role knowledge lookup are the initial delivery; other task profiles remain independently admitted extensions.
