# Agentic assistance and inference

## Role-scoped bounded coordination

The task coordinator is deterministic and durable in the core. The runtime is an untrusted stateless proposer whose only network destination is the broker. Runtime polls leased tasks, receives minimal labelled context, requests inference through the broker, validates shape locally as an optimization and submits proposals; the broker validates again before any execution. This avoids a direct inference exception in Z2. It is a proposed resolution to upstream D-02, not a source-model amendment.

| Assistant function | Inputs and permitted tools | Output / acceptance boundary |
|---|---|---|
| Client/carer navigator | Own attributed needs, approved templates, permitted plan, directory query | Source-linked options/questions; client choice remains explicit |
| Worker copilot | Assigned timeline, uncertainty/conflict markers, sourced protocols | Editable context pack, summary and response/referral draft; professional content requires worker review |
| Handoff coordinator | Current task/queue/receipt state, allowed recipient IDs | Progress check, authorized receipt lookup, proposed alternative; cannot promise acceptance |
| Planning/follow-up assistant | PID preferences and scoped sharing, separate contact consent | Draft plan and proposed follow-up; no unilateral grant/send |
| Supervisor assistant | Scoped workload state and aggregated demand | Suggested reassignment/missing tasks; no autonomous clinical priority or exposure ranking |
| Operations/security/governance assistant | Scoped digests, health, rules and evidence | Runbook/evidence/incident drafts; cannot sign approvals, access secrets or change live policy |
| Training assistant | Fictional scenarios and rubric | Persona role-play and debrief proposal; instructor validates |

No multi-agent orchestration platform is necessary. Specializations are task types with prompt/tool profiles and separately approved capability admission. Delegation is at most one level with equal-or-narrower scope; parent budgets cover subtasks. No autonomous spawning or trusted inter-agent channel.

## Durable task record and state

Task holds ID, parent/correlation, initiating actor and workload, human owner, session/client, goal/purpose, input/source revisions, tool/field scope, approval mode, model/prompt digest, policy epoch, deadline/budgets, lease/fence and completion criteria. Step holds proposed operation, typed parameters/provenance, observation references and status. Neither stores hidden model reasoning. Drafts and human approvals are separate versioned records.

State machine: requested→scoped→planning→running/awaiting_authorization→awaiting_observation/awaiting_human→completed, failed or cancelled. A task resumes only from committed observations. Lost runtime lease causes a new lease generation, so an old runtime cannot publish a late step. Per-step idempotency prevents duplicate execution; total lifetime budgets prevent indefinite retry. Step/task completion does not mean successful client care.

Default modes are automatic scoped read-only draft preparation; bounded preauthorized directory/receipt reads; and human-reviewed consequential proposals. Approval binds exact payload digest, recipient, field set, source revisions and five-minute deadline. A one-second execution permit is separate from the longer human approval. Stale facts, edits, new consent revision, changed assignment or policy epoch force reauthorization; material payload change requires human review again.

## Inference path and admission

Broker routes an approved inference request to `inference-gateway`; only that workload can reach the pinned host endpoint. Gateway selects exact loaded Gemma artifact/quantization/digest, verifies availability, enforces queue/context/output/token limits and deadline, and returns tainted output. Start with LM Studio’s OpenAI-compatible chat-completions interface, not an assumption that all SDK functions/tool grammar work. Probe model listing/identity, JSON behavior, cancellation, Unicode EN/FR, context accounting and output limits before admission. Do not enable LM Studio MCP, dynamic tool discovery, remote model links or embeddings.

Requested baseline: 8192 total context budget, 1024 output cap, temperature zero, 30-second generation deadline, two proposal attempts, four agent steps and three tools per turn. Input plus reserved output must fit the verified model context. Two concurrent jobs/eight queued are benchmark targets only; urgent deterministic paths never share that queue. Temperature zero is not a deterministic replay guarantee. Prompt construction selects purpose-relevant source-linked items, preserves critical unknown/conflict markers, and refuses overflow rather than silently dropping safety facts. Raw tokens are never streamed to client UI; validated output can be delivered as a committed event.

Invalid/oversized output, tool not allowed, unsourced claim, taint violation, model mismatch, overflow, timeout and cancellation produce typed failures with no partial action. Bounded repair does not postpone human help. Every function is admitted independently on matched synthetic cases for factual fidelity, usefulness, EN/FR, latency and adversarial resilience. Unsupported model capability remains manual/template-only; no remote fallback or silent model substitution.

## Actor benefit and autonomy controls

Review panels show original attributed facts, timestamps, changes, uncertainty, intended recipient/purpose and accept/edit/reject. Optional AI can be disabled without losing authorized manual work. No auto-sending of clinical free text; approved template navigation remains distinct from worker-authored professional communication. Client agency, useful verified options, reduced editing/administration and meaningful human connection are measured against actor-only baselines, not inferred from fluency or engagement.

[Official LM Studio interface reference](https://lmstudio.ai/docs/developer/openai-compat) supports the proposed adapter choice; installed-version/model behavior still requires verification. No provider contact content or clinical data is sent outside the local approved boundary.

> This prototype demonstrates control and containment architecture using non-clinical stub logic and synthetic data. It provides no evidence of clinical safety, triage validity, or equity performance, and must not be cited as such.
