/** Synthetic API boundary values for tests only; never model admission evidence. */
export const sessionId = "10000000-0000-4000-8000-000000000001";
export const taskId = "20000000-0000-4000-8000-000000000001";
export const draftId = "30000000-0000-4000-8000-000000000001";
export const subjectId = "40000000-0000-4000-8000-000000000001";
export const sourceId = "50000000-0000-4000-8000-000000000001";
export const actorId = "60000000-0000-4000-8000-000000000001";
export const at = "2026-11-20T12:00:00Z";
export const source = {
  kind: "assertion",
  id: sourceId,
  revision: "1",
  digest: "b".repeat(64),
  observed_at: at,
  verification: "disputed",
};
export const vector = Object.fromEntries(
  [
    "identity",
    "roles",
    "subject",
    "session_access",
    "assignment",
    "resource",
    "directory",
    "policy_epoch",
    "control_epoch",
    "serving_generation",
    "restriction_barrier",
  ].map((key) => [key, "1"]),
);
export const scope = {
  session_id: sessionId,
  subject_id: subjectId,
  purpose: "support",
  fields: ["needs", "preferences", "observations"],
  recipient_id: null,
};
export function task(state = "awaiting_human", revision = "1") {
  return {
    id: taskId,
    revision,
    function: "worker_summary",
    scope,
    state,
    human_owner_id: actorId,
    deadline: new Date(Date.now() + 120000).toISOString(),
    budgets: {
      max_steps: 4,
      max_tools: 3,
      max_proposal_attempts: 2,
      context_tokens: 8192,
      output_tokens: 1024,
    },
    steps_used: 1,
    tools_used: 1,
    control_epoch: "1",
    completion: "draft_ready",
    safe_reason: null,
    binding: { kind: "session", session_id: sessionId },
  };
}
export function draft(
  text = "Synthetic draft: a request for navigation; capacity is unknown.",
  revision = "1",
  state = "review_pending",
) {
  return {
    id: draftId,
    revision,
    task_id: taskId,
    kind: "summary",
    text,
    sources: [source],
    payload_digest: (revision === "1" ? "a" : "c").repeat(64),
    source_vector: vector,
    state,
  };
}
export function draftContext(
  text?: string,
  revision = "1",
  state = "review_pending",
) {
  return {
    draft: draft(text, revision, state),
    original_text:
      "Synthetic original: navigation requested; capacity unknown.",
    sources: [
      {
        ref: source,
        text: "Synthetic report: navigation requested; service capacity is unknown.",
      },
    ],
    scope,
    expires_at: new Date(Date.now() + 240000).toISOString(),
    expected_effect: "unsent_draft",
    ai_provenance: true,
  };
}
export function session() {
  return {
    id: sessionId,
    revision: "1",
    subject_id: subjectId,
    persona_id: subjectId,
    tags: { environment: "demo", population: "synthetic" },
    participant_kind: "pid",
    jurisdiction: null,
    locale: "en-CA",
    service_phase: "human_controlled",
    transport: "connected",
    control_epoch: "1",
    owner_id: actorId,
    degraded_reasons: [],
    tier: null,
    unresolved: true,
  };
}
export function review(decision: string) {
  return {
    id: "70000000-0000-4000-8000-000000000001",
    draft_id: draftId,
    decision,
    reviewer_id: actorId,
    exact_digest: "a".repeat(64),
    expires_at: new Date(Date.now() + 240000).toISOString(),
    revision: "1",
  };
}
