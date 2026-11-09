import AxeBuilder from "@axe-core/playwright";
import { createHash } from "node:crypto";
import { reviewManifest } from "./browser";
import { test, expect, type Page, type TestInfo } from "@playwright/test";
import { readLabConfig } from "./lab";
const lab = readLabConfig();
async function inspect(page: Page, testInfo: TestInfo, label: string) {
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  await testInfo.attach(label + "-axe-summary", {
    contentType: "application/json",
    body: JSON.stringify(
      {
        engine: result.testEngine,
        ruleTags: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"],
        violations: result.violations.map((rule) => ({
          id: rule.id,
          impact: rule.impact,
          targets: rule.nodes.map((node) => node.target),
        })),
        incomplete: result.incomplete.map((rule) => ({
          id: rule.id,
          impact: rule.impact,
          nodes: rule.nodes.length,
        })),
        passes: result.passes.length,
        scope:
          "automated only; does not establish human screen-reader or language review",
      },
      null,
      2,
    ),
  });
  expect(result.violations.map((rule) => rule.id)).toEqual([]);
}
for (const locale of ["en-CA", "fr-CA"] as const) {
  test(`actual static ${locale}: axe, readable language and 320px text reflow`, async ({
    page,
  }, testInfo) => {
    const response = await page.goto(
      `${lab.staticOrigin}/fallback?locale=${locale}`,
    );
    expect(response?.status()).toBe(200);
    const manifest = await reviewManifest(page, lab, locale);
    const responseBytes = await response?.body();
    if (!responseBytes)
      throw new Error("Actual public static body was unavailable");
    await testInfo.attach(`static-${locale}-artifact-binding`, {
      contentType: "application/json",
      body: JSON.stringify(
        {
          ...manifest,
          http_body_sha256: createHash("sha256")
            .update(responseBytes)
            .digest("hex"),
          browser: page.context().browser()?.version(),
        },
        null,
        2,
      ),
    });
    await testInfo.attach(`static-${locale}-desktop`, {
      contentType: "image/png",
      body: await page.screenshot({ fullPage: true }),
    });
    await expect(page.locator("html")).toHaveAttribute("lang", locale);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByRole("main")).toBeVisible();
    await inspect(page, testInfo, `static-${locale}`);
    await page.setViewportSize({ width: 320, height: 800 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth + 1,
      ),
    ).toBe(true);
    await page.evaluate(() => {
      document.documentElement.style.fontSize = "200%";
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth + 1,
      ),
    ).toBe(true);
    expect(
      await page.evaluate(() =>
        Number.parseFloat(getComputedStyle(document.documentElement).fontSize),
      ),
    ).toBeGreaterThanOrEqual(32);
    await inspect(page, testInfo, `static-${locale}-320px`);
    await testInfo.attach(`static-${locale}-320px-200percent-text`, {
      contentType: "image/png",
      body: await page.screenshot({ fullPage: true }),
    });
  });
  test(`actual help ${locale}: axe, keyboard focus and accessible language controls`, async ({
    page,
  }, testInfo) => {
    await page.goto(lab.helpOrigin + "/private-help");
    if (locale === "fr-CA")
      await page.getByLabel("Language", { exact: true }).selectOption(locale);
    await expect(page.locator("html")).toHaveAttribute("lang", locale);
    await inspect(page, testInfo, `help-${locale}`);
    await page.keyboard.press("Tab");
    await expect(page.locator(":focus")).toBeVisible();
    expect(
      await page
        .locator(":focus")
        .evaluate((node) =>
          Number.parseFloat(getComputedStyle(node).outlineWidth),
        ),
    ).toBeGreaterThanOrEqual(2);
    await page.setViewportSize({ width: 320, height: 800 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth + 1,
      ),
    ).toBe(true);
  });
}
