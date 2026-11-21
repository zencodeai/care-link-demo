import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { messages } from "../../../apps/web/src/governance/messages";
import { installFixture, ids, digest, evidence, type Role } from "./fixtures";
async function open(page: Page, locale: "en-CA" | "fr-CA") {
  const text = messages[locale];
  await page.goto("/governance");
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
  for (const role of [
    "operator",
    "security",
    "governance",
    "auditor",
  ] as const satisfies readonly Role[]) {
    test(`${locale} ${role} current role workspace, keyboard and axe at 1280/640px`, async ({
      page,
    }) => {
      await installFixture(page, { role });
      const text = await open(page, locale);
      if (role === "operator") {
        const region = page.getByRole("region", { name: text.activation });
        await region.getByLabel(text.knownActivation).fill(ids.activation);
        await region.getByLabel(text.knownActivation).press("Enter");
        await expect(region.getByText(digest, { exact: true })).toBeVisible();
        await region.getByRole("button", { name: text.health }).focus();
        await page.keyboard.press("Enter");
        await expect(region.getByText("7", { exact: true })).toBeVisible();
        await expect(region.getByText("8", { exact: true })).toBeVisible();
        await expect(
          page.getByRole("heading", { name: text.audit }),
        ).toHaveCount(0);
      } else if (role === "security" || role === "governance") {
        const region = page.getByRole("region", { name: text.review });
        await expect(
          region.getByRole("button", { name: text.submitReview }),
        ).toBeDisabled();
        await region.getByLabel(text.digest).fill(digest);
        await region.getByLabel(text.digest).press("Enter");
        await expect(
          region.getByText("config/demo/imp08/policy.json", { exact: true }),
        ).toBeVisible();
        await expect(
          region.getByRole("heading", { name: text.missingReviews }),
        ).toBeVisible();
        await region.getByLabel(text.evidence).fill(evidence);
        await region.getByLabel(text.reviewExpiry).fill("2099-11-21T13:00");
        await expect(
          region.getByRole("button", { name: text.submitReview }),
        ).toBeEnabled();
      } else {
        const region = page.getByRole("region", {
          name: text.metrics,
          exact: true,
        });
        await region.getByLabel(text.definition).fill("v1");
        await region.getByLabel(text.periodStart).fill("2026-11-01T00:00");
        await region.getByLabel(text.periodEnd).fill("2026-11-02T00:00");
        await region.getByRole("button", { name: text.queryMetrics }).focus();
        await page.keyboard.press("Enter");
        for (const name of [
          "safety",
          "access",
          "equity",
          "police_avoidance",
          "exposure_aggregate",
        ] as const)
          await expect(
            page.getByRole("heading", { name: text[name] }),
          ).toBeVisible();
        await expect(
          page.getByRole("heading", { name: text.artifact }),
        ).toHaveCount(0);
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
  test(`${locale} unknown commit retains exact retry identity`, async ({
    page,
  }) => {
    const fixture = await installFixture(page, { lostCommit: true });
    const text = await open(page, locale);
    await page.getByLabel(text.knownActivation).fill(ids.activation);
    await page.getByLabel(text.knownActivation).press("Enter");
    await page.getByRole("button", { name: text.commit }).click();
    await expect(page.getByRole("button", { name: text.retry })).toBeVisible();
    await expect(page.getByRole("button", { name: text.commit })).toHaveCount(
      0,
    );
    await page.getByRole("button", { name: text.retry }).click();
    await expect(page.getByRole("button", { name: text.retry })).toHaveCount(0);
    const commits = fixture.commands.filter((v) => v.path.endsWith("/commit"));
    expect(commits).toHaveLength(2);
    expect(commits[1]).toEqual(commits[0]);
  });
}
test("expired authority removes disclosed audit metadata and stale role cannot issue a query", async ({
  page,
}) => {
  const fixture = await installFixture(page, { role: "auditor" });
  const text = await open(page, "en-CA");
  await page.getByLabel(text.grantId).fill(ids.grant);
  await page.getByLabel(text.from).fill("2026-11-21T00:00");
  await page.getByLabel(text.to).fill("2026-11-22T00:00");
  await page.getByRole("button", { name: text.queryAudit }).click();
  await expect(
    page.getByText("artifact_register", { exact: true }),
  ).toBeVisible();
  fixture.signOut();
  await page.getByRole("button", { name: text.check }).click();
  await expect(page.getByText(text.signed_out, { exact: true })).toBeVisible();
  await expect(
    page.getByText("artifact_register", { exact: true }),
  ).toHaveCount(0);
});
test("an isolated police-avoidance response is rejected before disclosure", async ({
  page,
}) => {
  await installFixture(page, { role: "auditor", malformedMetrics: true });
  const text = await open(page, "en-CA");
  await page.getByLabel(text.definition).fill("v1");
  await page.getByLabel(text.periodStart).fill("2026-11-01T00:00");
  await page.getByLabel(text.periodEnd).fill("2026-11-02T00:00");
  await page.getByRole("button", { name: text.queryMetrics }).click();
  await expect(page.getByText(text.invalid, { exact: true })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: text.police_avoidance }),
  ).toHaveCount(0);
});

test("export pagination stays on the original scoped export", async ({
  page,
}) => {
  const fixture = await installFixture(page, {
    role: "auditor",
    exportPages: true,
  });
  const text = await open(page, "en-CA");
  await page.getByLabel(text.grantId).fill(ids.grant);
  await page.getByLabel(text.from).fill("2026-11-21T00:00");
  await page.getByLabel(text.to).fill("2026-11-22T00:00");
  await page.getByLabel(text.exportId).fill(ids.export);
  await page.getByRole("button", { name: text.readExport }).click();
  await expect(
    page.getByText("artifact_register", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: text.next }).click();
  await expect(
    page.getByText("artifact_review", { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: text.next })).toHaveCount(0);
  expect(fixture.commands).toHaveLength(0);
});
