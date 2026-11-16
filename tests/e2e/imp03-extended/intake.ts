import { expect, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { disclosures } from "../../../apps/web/src/manual/disclosures";
import { manualMessages } from "../../../apps/web/src/manual/messages";
import { object, text, type ExtendedConfig, type Locale } from "./config";
import { checkpoint, ok, request } from "./helpers";

export async function intake(
  page: Page,
  lab: ExtendedConfig,
  locale: Locale,
  output: string,
) {
  checkpoint(output, "ui_create_" + locale);
  await page.locator("#language").selectOption(locale);
  const labels = manualMessages[locale];
  await page.getByRole("button", { name: labels.check, exact: true }).click();
  const created = page.waitForResponse(
    (response) =>
      response.url() === lab.mainOrigin + "/v1/sessions" &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: labels.create, exact: true }).click();
  const reply = await created;
  expect(reply.status(), "Actual UI creates fictional conversation").toBe(200);
  const session = object((await reply.json()) as unknown);
  const path = `/v1/sessions/${text(session, "id")}`;
  const story = `Fictional qualification situation ${randomUUID()}. No real person is described.`;
  await page.getByLabel(labels.story, { exact: true }).fill(story);
  await expect(
    page.getByRole("button", { name: labels.check, exact: true }),
  ).toBeEnabled();
  await expect(
    page.getByRole("button", { name: labels.turn, exact: true }),
  ).toBeDisabled();
  // Direct API verifies that the server enforces the same pre-disclosure gate.
  const denied = await request(page, path + "/turns", {
    expected_revision: session.revision,
    client_turn_id: randomUUID(),
    text: story,
    locale,
  });
  expect(
    [403, 409].includes(denied.status),
    "Actual server gates undisclosed intake",
  ).toBe(true);
  await expect(
    page.getByText(disclosures[locale].text, { exact: true }),
  ).toBeVisible();
  const acknowledged = page.waitForResponse(
    (response) =>
      response.url() === lab.mainOrigin + path + "/disclosure" &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: labels.acknowledge, exact: true })
    .click();
  const ack = await acknowledged;
  expect(ack.status(), "Exact disclosure acknowledged by actual UI").toBe(200);
  const command = object(ack.request().postDataJSON() as unknown);
  expect(
    command.template_id === disclosures[locale].id &&
      command.template_digest === disclosures[locale].digest &&
      command.locale === locale &&
      command.acknowledged === true,
    "Actual UI sends the exact current disclosure identity/digest/locale",
  ).toBe(true);
  await expect(
    page.getByRole("button", { name: labels.turn, exact: true }),
  ).toBeEnabled();
  const submitted = page.waitForResponse(
    (response) =>
      response.url() === lab.mainOrigin + path + "/turns" &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: labels.turn, exact: true }).click();
  expect((await submitted).status(), "Actual UI submits fictional intake").toBe(
    200,
  );
  await expect(page.getByText(story, { exact: true })).toBeVisible();
  const messages = await ok(page, path + "/messages");
  expect(
    Array.isArray(messages.items) &&
      messages.items.some((item: unknown) => {
        const value = object(item);
        return (
          value.kind === "participant" &&
          value.sender_id === lab.accounts.pid &&
          value.text === story
        );
      }),
    "Actual stored/projection message attributes the turn to the issued participant",
  ).toBe(true);
  checkpoint(output, "ui_intake_complete_" + locale);
  return { path, session: await ok(page, path) };
}
