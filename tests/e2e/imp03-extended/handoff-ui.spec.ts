import { expect, test } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { evidenceDirectory } from "../imp03/config";
import { readExtendedConfig } from "./config";
import { checkpoint, login } from "./helpers";
import { intake } from "./intake";

const lab = readExtendedConfig();
const output = evidenceDirectory();

test("actual accepted worker opens and prepares a conversation through UI", async ({
  browser,
}) => {
  const participantContext = await browser.newContext({
    ignoreHTTPSErrors: false,
  });
  const workerContext = await browser.newContext({ ignoreHTTPSErrors: false });
  const responses: { method: string; path: string; status: number }[] = [];
  try {
    const participant = await participantContext.newPage();
    const worker = await workerContext.newPage();
    await login(participant, lab, "pid", output);
    await login(worker, lab, "worker", output);
    const { path } = await intake(participant, lab, "en-CA", output);
    const sid = path.split("/").at(-1)!;
    worker.on("response", (response) => {
      const pathname = new URL(response.url()).pathname;
      if (pathname.startsWith("/v1/"))
        responses.push({
          method: response.request().method(),
          path: pathname.replace(/[0-9a-f]{8}-[0-9a-f-]{27}/g, "{id}"),
          status: response.status(),
        });
    });
    checkpoint(output, "participant_requests_human_ui");
    await participant
      .getByRole("button", { name: "Ask for a human", exact: true })
      .click();
    await expect(
      participant.getByRole("button", {
        name: "Check manual access",
        exact: true,
      }),
    ).toBeEnabled();
    const workspace = worker.getByRole("region", {
      name: "Worker workspace",
      exact: true,
    });
    await workspace
      .getByRole("button", { name: "Refresh queue", exact: true })
      .click();
    const row = workspace
      .locator(".manual-queue > li")
      .filter({ hasText: sid });
    await expect(row).toHaveCount(1);
    checkpoint(output, "worker_reserve_accept_ui");
    await row
      .getByRole("button", { name: "Reserve for myself", exact: true })
      .click();
    await workspace
      .getByRole("button", { name: "Accept reservation", exact: true })
      .click();
    await expect(
      workspace.getByText(
        "Assignment accepted. A connection still requires both parties.",
        { exact: true },
      ),
    ).toBeVisible();
    checkpoint(output, "worker_opens_before_prepare_ui");
    const form = worker
      .locator("form")
      .filter({ has: worker.getByLabel("Conversation ID", { exact: true }) });
    await form.getByLabel("Conversation ID", { exact: true }).fill(sid);
    await form
      .getByRole("button", { name: "Open current conversation", exact: true })
      .click();
    await expect(
      worker.getByRole("heading", {
        name: "Current authorized conversation",
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      worker.getByRole("button", {
        name: "Refresh current state",
        exact: true,
      }),
    ).toBeVisible();
    checkpoint(output, "worker_prepares_ui");
    await workspace
      .getByRole("button", {
        name: "Prepare a new channel confirmation",
        exact: true,
      })
      .click();
    await expect(
      worker.getByText("Two-party connection confirmation pending", {
        exact: true,
      }),
    ).toBeVisible();
    await participant
      .getByRole("button", { name: "Refresh current state", exact: true })
      .click();
    await expect(
      participant.getByRole("button", {
        name: "Confirm my app channel",
        exact: true,
      }),
    ).toBeVisible();
    writeFileSync(
      resolve(output, "handoff-ui-observations.json"),
      JSON.stringify({
        status: "passed",
        browser_tls_verification: true,
        separate_actual_actors: true,
        accepted_worker_opened_before_preparation: true,
        worker_refresh_visible: true,
        preparation_reached_handoff_pending: true,
        participant_confirmation_visible: true,
        responses,
        human_acceptance: false,
      }),
      { mode: 0o600, flag: "wx" },
    );
  } finally {
    writeFileSync(
      resolve(output, "handoff-ui-responses.json"),
      JSON.stringify(responses),
      { mode: 0o600, flag: "wx" },
    );
    await participantContext.close();
    await workerContext.close();
  }
});
