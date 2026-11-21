import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { messages } from "../../../apps/web/src/features/recovery/messages";
import { binding, ids, installFixture } from "./fixtures";
async function open(page: Page, locale: "en-CA" | "fr-CA") {
  const text = messages[locale];
  await page.goto("/recovery");
  await page.getByLabel("Language").selectOption(locale);
  await page.getByRole("button", { name: text.check }).click();
  await expect(page.getByText(text.ready, { exact: true })).toBeVisible();
  return text;
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
  for (const role of ["operator", "security", "governance"] as const) {
    test(`${locale} ${role} exact evidence, keyboard and accessibility at 1280/640px`, async ({
      page,
    }) => {
      const f = await installFixture(page, (f) => {
        f.role = role;
      });
      const text = await open(page, locale);
      if (role === "operator") {
        await page.getByLabel(text.targetId).fill(ids.target);
        await page.getByLabel(text.targetId).press("Enter");
        await expect(
          page.getByText(binding.artifact_digest, { exact: true }),
        ).toBeVisible();
        await page.getByRole("button", { name: text.propose }).focus();
        await page.keyboard.press("Enter");
        await expect(page.getByLabel(text.proposalId)).toHaveValue(
          ids.proposal,
        );
        expect(f.commands[0]?.body).toMatchObject({ binding });
      } else {
        await page.getByLabel(text.proposalId).fill(ids.proposal);
        await page.getByLabel(text.proposalId).press("Enter");
        await expect(
          page.getByText(binding.artifact_digest, { exact: true }),
        ).toBeVisible();
        await page.getByLabel(text.ceremony).fill(ids.ceremony);
        await expect(
          page.getByRole("button", { name: text.approve }),
        ).toBeEnabled();
        expect(f.commands).toHaveLength(0);
      }
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
  }
  test(`${locale} unknown execution reuses exact operation identity`, async ({
    page,
  }) => {
    const f = await installFixture(page, (f) => {
      f.proposalState = "approved";
      f.lost = true;
    });
    const text = await open(page, locale);
    await page.getByLabel(text.proposalId).fill(ids.proposal);
    await page.getByLabel(text.proposalId).press("Enter");
    await page.getByRole("button", { name: text.execute }).click();
    await expect(page.getByRole("button", { name: text.retry })).toBeVisible();
    await expect(
      page.getByText(binding.artifact_digest, { exact: true }),
    ).toHaveCount(0);
    await page.getByRole("button", { name: text.retry }).click();
    await expect(page.getByRole("button", { name: text.retry })).toHaveCount(0);
    expect(f.commands).toHaveLength(2);
    expect(f.commands[1]).toEqual(f.commands[0]);
  });
}
test("expired approval cannot execute", async ({ page }) => {
  const f = await installFixture(page, (f) => {
    f.proposalState = "approved";
    f.expired = true;
  });
  const text = await open(page, "en-CA");
  await page.getByLabel(text.proposalId).fill(ids.proposal);
  await page.getByLabel(text.proposalId).press("Enter");
  await expect(page.getByText(text.expired, { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: text.execute })).toBeDisabled();
  expect(f.commands).toHaveLength(0);
});
test("signed-out authority removes all exact evidence", async ({ page }) => {
  const f = await installFixture(page, (f) => {
    f.role = "security";
  });
  const text = await open(page, "en-CA");
  await page.getByLabel(text.proposalId).fill(ids.proposal);
  await page.getByLabel(text.proposalId).press("Enter");
  await expect(
    page.getByText(binding.artifact_digest, { exact: true }),
  ).toBeVisible();
  f.signedOut = true;
  await page.getByRole("button", { name: text.check }).click();
  await expect(page.getByText(text.signed_out, { exact: true })).toBeVisible();
  await expect(
    page.getByText(binding.artifact_digest, { exact: true }),
  ).toHaveCount(0);
  await expect(page.getByRole("button", { name: text.approve })).toHaveCount(0);
});
test("invalid sealed evidence is rejected before display", async ({ page }) => {
  await installFixture(page, (f) => {
    f.malformed = true;
  });
  const text = await open(page, "en-CA");
  await page.getByLabel(text.proposalId).fill(ids.proposal);
  await page.getByLabel(text.proposalId).press("Enter");
  await expect(page.getByText(text.invalid, { exact: true })).toBeVisible();
  await expect(
    page.getByText(binding.artifact_digest, { exact: true }),
  ).toHaveCount(0);
});
