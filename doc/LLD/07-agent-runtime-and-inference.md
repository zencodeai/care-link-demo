# Bounded agent coordinator, tools and local inference

> Current implementation direction · 2026-11-20: [LLD18](18-agentic-knowledge-workflows.md) amends this design for Qwen3.8-27B, bounded LangGraph and role-scoped knowledge. Current source/contracts/defaults target `qwen/qwen3.8-27b`; prior Gemma evidence is historical. Runtime admission remains independently qualified.

## Task ownership and profiles

TaskCoordinator is authoritative; runtime only proposes. A task stores initiating human/account and workload separately, responsible human, discriminated resource binding, purpose, goal enum, input references/revisions, allowed fields/tools, approval mode, pinned function/model/prompt/schema, policy/control/serving epochs, deadline, counters and completion predicate. `session` binding, `receiving_package`, `operations`, `artifact_review`, `audit_grant` and `training_scenario` are distinct. Null session never means all sessions. Operational/audit scopes carry exact authorized resource or grant IDs, not general business-store access.

| Function profile | Allowed useful tools / context | Completion and release |
|---|---|---|
| client_navigation / carer_context | own session fields, permitted plan, protocol_read, directory_search, draft_prepare | Options/source observations or unsent draft; automatic participant output only reviewed templates/source assembly |
| worker_summary / worker_wording / referral_preparation | assigned session/plan/source refs, directory/protocol, draft/review | Cited timeline/conflict checklist or editable draft; final professional communication separately accepted |
| handoff_tracking / follow_up_draft | authorized queue/receipt/contact scope | Observed factual state or unsent proposal; cannot promise connection/send reminder |
| receiver_completeness | own receiving package and approved protocol | Clarification/completeness draft; receiver alone decides capacity/acceptance |
| plan_draft | own permitted plan/assertions and approved protocol | PID-led draft; no grant or authored-wish overwrite |
| supervisor_queue | exact queue/aggregate scope | Bounded demand/reassignment proposal; no clinical priority or individual exposure ranking |
| incident_draft | approved health/security-event projection and runbook | Incident draft, no secrets/infrastructure changes |
| evidence_draft | exact artifact-review scope or time/purpose audit grant | Evidence-linked draft, no compliance certification/approval |
| training_debrief | isolated scenario evidence and instructor rubric | Debrief draft; no competence certification |

## State, leases and budget accounting

Machine transitions are listed in [state-machines.json](contracts/state-machines.json). requested→scoped only after deterministic role/resource/task admission; scoped→planning after lease+context admission; planning→awaiting_authorization/running/awaiting_human; running→awaiting_observation; observation is durably recorded before another step; completion requires exact predicate evidence. Cancellation/failure is terminal; a revised goal/scope creates a newly authorized task revision and stales leases/reviews. A model `completion_claim` is only a proposal.

Each originating-turn task slice has a single ledger: max 4 steps, max 3 total tool calls, max 2 total proposal attempts across all retries/specialized modules, context8192 and output1024. Reserve counters atomically before consumption. A parser repair/model retry consumes proposal attempt; lease retry never resets any counter. Delegation depth≤1, modules only, same-or-narrower scope and shared counters. No autonomous spawning. Longer task purpose cannot mint infinite turn budgets: a new slice requires an explicit actor/domain event and task revision with preserved lifetime accounting. Proposed task deadline120seconds; human waiting ends execution slice and requires fresh authorized resumption, not indefinite compute lease.

Step claim under task lock increments fence and records owner/expiry (proposed 10seconds, renew≤5seconds). Completion compares current task revision, step fence, lease expiry, source/control/policy epochs and cancellation. Old lease completion is denied even if valid output. Claim conflicts return RESOURCE_BUSY. Expired lease permits recovery of only unperformed/read-idempotent work; inspect observation/operation identity before redoing anything. Cancel increments task fence and suppresses output immediately; it does not prove backend compute stopped.

## Broker tools and observations

Typed tool union in contracts includes session_read, plan_read, protocol_read, directory_search, queue_status, receipt_read, draft_prepare and review_request plus strictly scoped package/health/evidence projections. Registry is a signed release artifact with exact argument/result schema, audience, maximum cost, effect class, applicable profiles and required purpose. No dynamic registration, URLs, SQL, shell, arbitrary browsing, clinical/consent/identity/priority mutation or emergency/police tool. Draft_prepare writes only an unsent proposal and consumes tool budget; review_request creates pending review, never approval. Business dispatch remains a human/domain command outside model tool authority.

Runtime submits task/step/invocation IDs, expected revision/fence and closed arguments. Broker looks up stored capability/actor/purpose/tool/fields/budgets, authenticates workload and reauthorizes current domain access. Capability token remains broker-side; runtime receives summary only. Invocation dedup key prevents duplicate logical tool effects. Observation stores typed result or safe failure, sources/revisions/digest and server-authored taint=`untrusted`. Failure is not a successful empty result. Tool and peer-agent text cannot promote provenance or establish consent. Observation availability is independent of whether the task is complete.

## Context and prompt assembly

ContextBuilder first obtains metadata authority, then scoped projections with audit. Construct ordered sections: approved immutable instructions, task goal/constraints, structured state and unknown/conflict markers, approved sourced facts, untrusted attributed reports/observations. Labels originate outside model. Preserve material source attribution, revisions, missingness and disagreements; optional old turns are dropped first. If critical content cannot fit, reduce scope or require human work. No shared session cache/vector memory, cross-actor scratchpad, online learning, prompt logging or hidden reasoning retention.

Hard context check uses pinned tokenizer or verified server count and loaded prompt template: `input_tokens + verified_template_overhead + output_reserve <= min(8192, verified_model_window)`. Character estimates cannot prove fit. If tokenizer/template identity cannot be established, function stays disabled rather than silently truncating critical facts. Include no secrets, access/continuation/capability tokens or arbitrary uploaded binary content. Retrieved claims must resolve to currently admitted sources; generated unsupported service/legal claims reject proposal as a whole.

## Model adapter and compute slots

RuntimeInferenceRequest contains only task/step/fence/revision; the broker builds context, trust labels, pins and budgets from current stored state. Runtime-supplied approved labels/instructions/artifact IDs are never authoritative. Fixed flow: runtime requests broker inference→gateway→authenticated host bridge→pinned LM Studio `/v1/chat/completions`. Request uses exact loaded model ID, admitted schema, `stream:false`, temperature0, output≤1024, context cap and absolute deadline≤30seconds. Bridge strips caller destinations/headers and disables redirects; only fixed loopback model port is reachable. No remote fallback, download/load API or native model tool execution. Response parser bounds bytes/depth, rejects duplicate/unknown keys, truncation, invalid sources/action claims and schema mismatch; reject entire proposal before tool effects. Reasoning fields are excluded from retained application data.

The selected model identifier is `qwen/qwen3.8-27b`, accepted by the user and reported already downloaded in local LM Studio. The [LM Studio structured-output documentation](https://lmstudio.ai/docs/developer/openai-compat/structured-output) is an interface reference, not proof of this selected artifact’s capability. No inference is made from the identifier about architecture, file format or quantization. Exact artifact origin/digest/quantization/license, server/engine version, tokenizer/template, loaded identity, output-schema support and per-function EN/FR/adversarial evidence are required. A model-list name alone is insufficient artifact proof. Failed functions remain manual/template-only; no silent alternate model.

Persist inference_job(id,task,step,fence,model/prompt digests,state,deadline,slot_id,request_digest,result_ref) and compute_slot(id,state,job_id,bridge_generation). Admission max 2 concurrent, queue≤8. Human/urgent work never waits on this queue. Timeout/cancel fences output and changes job to compute_unknown if provider stop is unverified; slot is NOT freed on HTTP timeout. It returns only on observed completion, verified cancel or controlled bridge recovery that establishes no old compute remains. Late results are ignored for delivery and recorded minimally. Exhausted unknown slots disable AI while manual service continues. Broker cancellation and slot cleanup are different operations.

## Review, completion and hazards

Review shows original facts and timestamps, sources, proposed diff, uncertainty, recipient/fields/purpose, expected effect and expiry≤300seconds. Accept/edit/reject are separate. Edits create new digest/revision; changed payload/source/ownership/policy stales review and requires current recheck. Acceptance preserves AI provenance and does not assert accuracy/consent. Critical seeded error detection/automation bias is tested separately from a clickthrough.

Per-function hazard register includes harmful commission/omission, hallucination, stale facts, conflicting reports, automation bias/fatigue, translation error, leakage, injected instructions, duplicates and outage. Preventive controls are current projections/source validation, approved templates, human review and structural absence of dangerous tools; recovery is manual service/human routing. Completion predicates are draft_ready/options_observed/receipt_observed/evidence_ready, never client_safe or care_success. Test every actor flow with all AI suggestions rejected. No throughput gain offsets unauthorized effects or seeded critical failures.

## Broker capability and taint invariants

The BrokerCapability record binds exact task/binding/session-purpose scope, allowed tools/fields, shared counters, jurisdiction, committed fixture-tier ceiling, expiry, policy/control epochs and token digest. Proposed lifetime is at most 60 seconds and never beyond task deadline; renewal reevaluates current scope without resetting budgets. The raw broker token is never sent to runtime, model or observations; summary grants no executable authority. Exceeding current tier ceiling, source/ownership change or revocation blocks optional tool use until newly authorized scope; mandatory human request is independent. Each tool still requires fresh full authorization—capability validity is an upper bound, not a positive permission cache.

Local taint invariants: only server assembly establishes trust labels; untrusted text cannot raise role/assurance/jurisdiction/tier/consent; retrieved/model content never executes code/policy/recipient destinations; every sourced claim resolves an admitted current source and returned observations remain untrusted; any invalid envelope/provenance rejects the whole proposal before partial action. These implement the local containment obligations without asserting unverified upstream schema conformance.

Model choice and workstation target are accepted in the [decision record](decisions/2026-11-06-implementation-choices-and-model.md). `model_identifier` is exactly `qwen/qwen3.8-27b`; `loaded_model_id` is independently observed and pinned at integration. Existing 8192-context/1024-output, 30-second timeout, two-compute-slot/eight-queued limits remain unchanged and unmeasured. No automatic budget increase or model substitution follows from the new identifier.

## Current workflow and knowledge amendment

[LLD18](18-agentic-knowledge-workflows.md) specifies the authorized LangGraph execution, metadata dispatch, role-scoped knowledge catalog, current Qwen migration, source freshness and verification obligations. It preserves the exact-excerpt first-profile guard and all current authority/compute controls. Historical Gemma acceptance and session receipts retain their original meaning.
