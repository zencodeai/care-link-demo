import { expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { resolve } from "node:path";
import { textFor } from "../../../apps/web/src/plans/messages";
import {
  type Actors,
  type Observations,
  type PlanState,
  loadVisiblePlan,
} from "./cases";
import { row, text, type Row } from "./config";

function journal(action: "pause" | "resume"): Row {
  try {
    return row(
      JSON.parse(
        execFileSync(
          resolve(".venv/bin/python"),
          [
            "-m",
            "tools.imp04_deployment.fault",
            "--role",
            "journal",
            "--action",
            action,
          ],
          {
            encoding: "utf8",
            timeout: 15_000,
            stdio: ["ignore", "pipe", "pipe"],
          },
        ),
      ) as unknown,
    );
  } catch {
    throw new Error(
      `Exact receipt-bound new-target journal ${action} failed; details suppressed`,
    );
  }
}
export async function pendingUi(
  actors: Actors,
  observations: Observations,
  state: PlanState,
): Promise<Row> {
  const actor = actors.pid;
  const identity = await actor.current();
  if (
    identity.assurance !== "AL2" ||
    Date.now() - Date.parse(text(identity, "auth_time")) >= 210_000
  )
    await actor.signIn(false);
  const current = await actor.ok(`/v1/plans/${state.plan}`);
  expect(current.subject_id).toBe(state.subject);
  expect(current.state).toBe("active");
  await loadVisiblePlan(actor, state);
  await actor.page.locator("#plan-field").selectOption("plan.strategies");
  const draft = `Fictional pending-operation plan words ${randomUUID()}.`;
  await actor.page.locator("#plan-words").fill(draft);
  const workspace = actor.page.locator(
    'section[aria-labelledby="plans-title"]',
  );
  const append = workspace.getByRole("button", {
    name: textFor("en-CA").append,
    exact: true,
  });
  await expect(append).toBeEnabled();
  const path = `/v1/plans/${state.plan}/fields`;
  let recoveryIntended = false;
  let paused: Row,
    resumed: Row = {},
    originalKey: string,
    originalBody: string;
  let failureStatus: number;
  try {
    recoveryIntended = true; // Covers a freezer transition whose acknowledgement is lost.
    paused = journal("pause");
    expect(paused.target).toBe("care-link-imp04-002");
    expect(paused.role).toBe("journal");
    expect(paused.container_identity_verified).toBe(true);
    expect(paused.paused_observed).toBe(true);
    expect(paused.maximum_pause_seconds).toBe(20);
    const dispatched = actor.page.waitForRequest(
      (request) =>
        request.url() === actor.config.mainOrigin + path &&
        request.method() === "POST",
    );
    const failedResponse = actor.page.waitForResponse(
      (response) =>
        response.url() === actor.config.mainOrigin + path &&
        response.request().method() === "POST",
    );
    await append.click();
    const sent = await dispatched;
    originalKey = sent.headers()["idempotency-key"] ?? "";
    if (
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
        originalKey,
      )
    )
      throw new Error(
        "Actual native append did not issue one canonical logical operation key",
      );
    originalBody = sent.postData() ?? "";
    failureStatus = (await failedResponse).status();
    expect(
      failureStatus,
      "Actual journal dependency loss returns uncertain mutation outcome",
    ).toBe(503);
    await expect(
      workspace
        .getByText(textFor("en-CA").operationUnknown, { exact: true })
        .first(),
    ).toBeVisible();
    await expect(
      workspace.getByText(originalKey, { exact: true }),
    ).toBeVisible();
    await expect(
      workspace.getByRole("button", {
        name: textFor("en-CA").retry,
        exact: true,
      }),
    ).toBeEnabled();
  } finally {
    if (recoveryIntended) {
      resumed = journal("resume");
      expect(resumed.target).toBe("care-link-imp04-002");
      expect(resumed.action).toBe("resume");
      expect(resumed.container_identity_verified).toBe(true);
      expect(resumed.paused_observed).toBe(false);
    }
  }
  const retriedRequest = actor.page.waitForRequest(
    (request) =>
      request.url() === actor.config.mainOrigin + path &&
      request.method() === "POST",
  );
  const retriedResponse = actor.page.waitForResponse(
    (response) =>
      response.url() === actor.config.mainOrigin + path &&
      response.request().method() === "POST",
  );
  await workspace
    .getByRole("button", { name: textFor("en-CA").retry, exact: true })
    .click();
  const actualRetry = await retriedRequest;
  expect(
    actualRetry.headers()["idempotency-key"],
    "Visible retry preserves the original logical key",
  ).toBe(originalKey);
  expect(
    actualRetry.postData() === originalBody,
    "Visible retry preserves exact original command bytes",
  ).toBe(true);
  const committed = await retriedResponse;
  expect(
    committed.status(),
    "Ordinary current controls permit the same logical command after dependency recovery",
  ).toBe(200);
  const projection = row((await committed.json()) as unknown);
  if (!Array.isArray(projection.fields))
    throw new Error("Missing actual retry PlanView");
  const effect = projection.fields.map(row).filter((field) => {
    const value = row(field.value);
    return (
      field.field === "plan.strategies" &&
      field.author_id === actor.issued.accountId &&
      value.kind === "text" &&
      value.text === draft
    );
  });
  expect(
    effect.length,
    "Actual current PlanView contains exactly one attributed command effect",
  ).toBe(1);
  await expect(workspace.getByText(originalKey, { exact: true })).toHaveCount(
    0,
  );
  await expect(
    workspace.getByRole("button", {
      name: textFor("en-CA").retry,
      exact: true,
    }),
  ).toHaveCount(0);
  expect(
    (await actor.page.locator("#plan-words").inputValue()) === draft,
    "Mounted-page input survives uncertain outcome and successful same-key reconciliation",
  ).toBe(true);
  const operation = await actor.ok(`/v1/operations/${originalKey}`);
  expect(operation.state).toBe("committed");
  const result = {
    case: "Q09-pending-ui",
    status: "passed",
    plan_id: state.plan,
    operation_id: originalKey,
    actual_failure_status: failureStatus,
    actual_retry_status: committed.status(),
    field_id: effect[0]?.id,
    native_unknown_result_displayed: true,
    same_logical_key_path_and_body: true,
    exactly_one_attributed_effect_in_actual_projection: true,
    pending_ui_cleared: true,
    mounted_input_retained_after_reconciliation: true,
    full_reload_persistence_claimed: false,
    journal_pause: paused,
    journal_resume: resumed,
    durable_effect_count:
      "coordinator_read_only_operation_and_field_count_required",
  };
  observations.push(result);
  return result;
}
