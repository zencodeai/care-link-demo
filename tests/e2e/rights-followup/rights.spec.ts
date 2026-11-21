import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { messages } from "../../../apps/web/src/lifecycle/messages";
import { ids, installFixture } from "./fixtures";
async function open(page: Page, locale: "en-CA" | "fr-CA") {
  const text = messages[locale];
  await page.goto("/follow-up");
  await page.getByLabel("Language").selectOption(locale);
  await page.getByRole("button", { name: text.check }).click();
  await expect(page.getByRole("heading", { name: text.inbox })).toBeVisible();
  return text;
}
async function loadSession(page: Page, text: (typeof messages)["en-CA"]) {
  await page.getByLabel(text.session, { exact: true }).fill(ids.session);
  await page.getByRole("button", { name: text.load, exact: true }).click();
  await expect(
    page.getByRole("heading", { name: text.followup, exact: true }),
  ).toBeVisible();
}
async function scan(page: Page) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations).toEqual([]);
  expect(result.incomplete).toEqual([]);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth,
    ),
  ).toBe(false);
}
for (const locale of ["en-CA", "fr-CA"] as const) {
  test(`${locale} pending anchor, keyboard and backup exceptions at 1280/640px`, async ({
    page,
  }) => {
    const fixture = await installFixture(page);
    const text = await open(page, locale);
    await loadSession(page, text);
    const rightsRegion = page.getByRole("region", { name: text.rights });
    await expect(
      rightsRegion.getByText(ids.subject, { exact: true }),
    ).toBeVisible();
    await expect(
      rightsRegion.getByRole("textbox", { name: text.rightsRevision }),
    ).toHaveCount(0);
    await page.getByLabel(text.grant, { exact: true }).fill(ids.grant);
    await page
      .getByRole("button", { name: text.schedule, exact: true })
      .focus();
    await page.keyboard.press("Enter");
    await expect(
      page.getByText(`${text.state}: ${text.states.anchor_pending}`, {
        exact: true,
      }),
    ).toBeVisible();
    expect(fixture.commands[0]?.body).toEqual({
      kind: "pending_anchor",
      expected_revision: "1",
      subject_id: ids.subject,
      recipient_account_id: ids.account,
      contact_grant_id: ids.grant,
    });
    await expect(page.getByRole("button", { name: text.bind })).toBeDisabled();
    await page.getByLabel(text.knownRights).fill(ids.rights);
    await page.getByLabel(text.knownRights).press("Enter");
    await expect(
      page.getByText(`${text.state}: ${text.states.backup_pending}`, {
        exact: true,
      }),
    ).toBeVisible();
    await expect(page.getByText(text.backup, { exact: true })).toBeVisible();
    await expect(page.getByText(text.exceptionReasons.held)).toBeVisible();
    await scan(page);
    await page.setViewportSize({ width: 640, height: 800 });
    await scan(page);
    await expect(page.locator("html")).toHaveAttribute("lang", locale);
    expect(
      await page.evaluate(() => ({
        local: localStorage.length,
        session: sessionStorage.length,
      })),
    ).toEqual({ local: 0, session: 0 });
  });
  test(`${locale} lost cancellation is retried with its exact original key`, async ({
    page,
  }) => {
    const fixture = await installFixture(page, { lostCancel: true });
    const text = await open(page, locale);
    await loadSession(page, text);
    await page.getByLabel(text.knownFollowup).fill(ids.followup);
    await page.getByLabel(text.knownFollowup).press("Enter");
    await page.getByRole("button", { name: text.cancel, exact: true }).click();
    await expect(page.getByRole("button", { name: text.retry })).toBeVisible();
    await expect(
      page.getByText(`${text.state}: ${text.states.cancelled}`, {
        exact: true,
      }),
    ).toHaveCount(0);
    await page.getByRole("button", { name: text.retry }).click();
    await expect(
      page.getByText(`${text.state}: ${text.states.cancelled}`, {
        exact: true,
      }),
    ).toBeVisible();
    const requests = fixture.commands.filter((command) =>
      command.path.endsWith("/cancel"),
    );
    expect(requests).toHaveLength(2);
    expect(requests[1]).toEqual(requests[0]);
  });
}
test("authorized delivery displays cancellation may be too late", async ({
  page,
}) => {
  await installFixture(page, { authorized: true });
  const text = await open(page, "en-CA");
  await loadSession(page, text);
  await page.getByLabel(text.knownFollowup).fill(ids.followup);
  await page.getByLabel(text.knownFollowup).press("Enter");
  await expect(
    page.getByText(`${text.state}: ${text.states.authorized}`, { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: text.cancel, exact: true }).click();
  await expect(
    page.getByText(`${text.state}: ${text.states.authorized}`, { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(`${text.state}: ${text.states.cancelled}`, { exact: true }),
  ).toHaveCount(0);
});
test("private inbox clears on expired authority", async ({ page }) => {
  const fixture = await installFixture(page);
  const text = await open(page, "en-CA");
  await page.getByRole("button", { name: text.openInbox }).click();
  await page.getByRole("button", { name: text.openMessage }).click();
  await expect(page.getByText("Synthetic private inbox content")).toBeVisible();
  fixture.signOut();
  await page.getByRole("button", { name: text.check }).click();
  await expect(page.getByText(text.signed_out, { exact: true })).toBeVisible();
  await expect(page.getByText("Synthetic private inbox content")).toHaveCount(
    0,
  );
});
