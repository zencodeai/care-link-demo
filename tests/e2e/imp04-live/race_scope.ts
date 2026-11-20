import { expect } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { type Actor } from "./browser";
import { type Observations, type PlanState } from "./cases";
import { evidenceDirectory, text } from "./config";

/** Each race owns a new subject: retained grants from old attempts cannot mask it. */
export async function createRaceScope(
  pid: Actor,
  observations: Observations,
  operation: "A03" | "A04" | "A03-authority-loss",
): Promise<PlanState> {
  const current = await pid.current();
  const age = Date.now() - Date.parse(text(current, "auth_time"));
  if (current.assurance !== "AL2" || !Number.isFinite(age) || age >= 210_000)
    await pid.signIn(false);
  const own = await pid.ok("/v1/sessions", {
    tags: { environment: "demo", population: "synthetic" },
    participant_kind: "pid",
    jurisdiction: null,
    locale: "en-CA",
    channel: "web",
    persona_id: null,
    fixture_id: null,
  });
  let plan = await pid.ok("/v1/plans", {
    subject_id: own.subject_id,
    expected_revision: own.revision,
  });
  for (const field of ["plan.strategies", "plan.medication_report"])
    plan = await pid.ok(`/v1/plans/${text(plan, "id")}/fields`, {
      expected_revision: plan.revision,
      field,
      value: { kind: "text", text: `Fictional isolated race ${randomUUID()}` },
      source: null,
      safety_relevant: false,
    });
  const state = {
    session: text(own, "id"),
    subject: text(own, "subject_id"),
    plan: text(plan, "id"),
    proof: await pid.verifySubject(text(own, "subject_id")),
    grant: "",
  };
  // Unload the real ceremony callback UI after completion. The same genuine
  // cookie jar remains; API-only race actors need no background React polls.
  await pid.page.goto("about:blank", { waitUntil: "domcontentloaded" });
  await pid.ensureMain();
  expect(plan.subject_id).toBe(state.subject);
  writeFileSync(
    resolve(evidenceDirectory(), "live-state.json"),
    JSON.stringify(state, null, 2),
    { mode: 0o600 },
  );
  observations.push({
    case: operation + "-scope",
    status: "passed",
    session_id: state.session,
    subject_id: state.subject,
    plan_id: state.plan,
    fresh_subject_and_plan: true,
    prior_grants_restrictions_and_subjects_untouched: true,
    actual_subject_bound_mfa: true,
  });
  return state;
}
