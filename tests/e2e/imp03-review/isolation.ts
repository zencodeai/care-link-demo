import { expect } from "@playwright/test";
import { ActorPage, words } from "./browser";
import { signIn } from "./auth";
import { row } from "./config";
import type { Toolkit } from "./toolkit";
export interface PreviousRun {
  runId: string;
  sessionId: string;
  operationId: string;
}
export async function crossRun(actor: ActorPage, previous: PreviousRun) {
  const workspace = await actor.workspace();
  expect(
    Array.isArray(workspace.conversations) &&
      workspace.conversations.length === 0,
    "Fresh run has no prior-run conversations",
  ).toBe(true);
  for (const path of [
    `/v1/sessions/${previous.sessionId}`,
    `/v1/sessions/${previous.sessionId}/messages`,
    `/v1/operations/${previous.operationId}`,
  ]) {
    const result = await actor.api(path);
    expect(
      [403, 404].includes(result.status),
      "New run cannot disclose a previous run's record or operation",
    ).toBe(true);
  }
  expect(
    actor.runId !== previous.runId,
    "New run has a distinct durable identity",
  ).toBe(true);
}
export async function closedRun(
  actor: ActorPage,
  toolkit: Toolkit,
  operationId: string,
) {
  // Closure invalidates business admission. Reauthenticate the same real actor
  // through the closed origin for its explicit status-recovery scope.
  actor.view = null;
  await actor.page.reload({ waitUntil: "domcontentloaded" });
  await signIn(actor, toolkit, false);
  await expect(
    actor.page.getByText(words.closed, { exact: true }).first(),
  ).toBeVisible();
  const workspace = await actor.workspace();
  expect(
    workspace.run_state,
    "Closed run remains closed after reauthentication",
  ).toBe("closed");
  await expect(actor.button(words.create)).toBeHidden();
  await expect(actor.button(words.send)).toBeHidden();
  const section = actor.page
    .locator(".manual-reconciliation")
    .filter({ hasText: operationId });
  await expect(section).toHaveCount(1);
  await section
    .getByRole("button", { name: words.reconcile, exact: true })
    .click();
  await expect(section.getByRole("status")).toHaveText("committed");
  const status = await actor.api("/v1/operations/" + operationId);
  expect(
    status.status,
    "Closed same-principal status recovery remains available",
  ).toBe(200);
  expect(row(status.value).state).toBe("committed");
  const denied = await actor.api("/v1/sessions", {
    tags: { environment: "demo", population: "synthetic" },
    participant_kind: "pid",
    jurisdiction: null,
    locale: "en-CA",
    channel: "web",
    persona_id: null,
    fixture_id: null,
  });
  expect(
    [401, 403, 409].includes(denied.status),
    "Closed status session cannot create new business state",
  ).toBe(true);
}
