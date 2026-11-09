/** Unsigned rendered-card QA only: intercepted fixture transport, no publication/provider. */
import { readFileSync, writeFileSync, lstatSync } from "node:fs";
import { resolve } from "node:path";
import { createHash } from "node:crypto";
import { parseArgs } from "node:util";
import { chromium } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
const { values } = parseArgs({
  options: {
    directory: { type: "string" },
    channel: { type: "string", default: "chromium" },
  },
});
if (!values.directory || !["chrome", "chromium"].includes(values.channel))
  throw new Error(
    "Supply the explicitly prepared private fixture directory and browser channel",
  );
const directory = resolve(values.directory);
if ((lstatSync(directory).mode & 0o077) !== 0)
  throw new Error("Fixture evidence directory must be owner-only");
const metadata: unknown = JSON.parse(
  readFileSync(resolve(directory, "fixture.json"), "utf8"),
);
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function stringRecord(value: unknown): value is Record<string, string> {
  return (
    record(value) &&
    Object.values(value).every((item) => typeof item === "string")
  );
}
if (
  !record(metadata) ||
  typeof metadata.artifact_digest !== "string" ||
  !stringRecord(metadata.headers)
)
  throw new Error("Invalid unsigned fixture metadata");
const fixtureHeaders = metadata.headers;
interface PageResult {
  locale: string;
  html_sha256: string;
  desktop_violations: { id: string; impact: string | null | undefined }[];
  mobile_violations: { id: string; impact: string | null | undefined }[];
  incomplete_checks: string[];
  keyboard_focus_outline_px: number;
  reflow_320px: boolean;
  text_font_px: number;
  reflow_320px_200percent: boolean;
  console_errors: string[];
}
const browser = await chromium.launch({
  ...(process.env.CARE_LINK_IMP02_BROWSER_PATH
    ? { executablePath: process.env.CARE_LINK_IMP02_BROWSER_PATH }
    : { channel: values.channel }),
  headless: true,
});
const report = {
  fixture_only: true,
  transport_mocked: true,
  signed_publication: false,
  provider_exercised: false,
  human_accessibility_review: false,
  browser_version: browser.version(),
  artifact_digest: metadata.artifact_digest,
  pages: [] as PageResult[],
};
try {
  const context = await browser.newContext({
    viewport: { width: 1280, height: 960 },
  });
  await context.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (
      url.origin !== "https://static-fixture.localhost" ||
      url.pathname !== "/fallback"
    ) {
      await route.abort();
      return;
    }
    const locale = url.searchParams.get("locale");
    if (locale === null || !["en-CA", "fr-CA"].includes(locale)) {
      await route.abort();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "text/html; charset=utf-8",
      headers: fixtureHeaders,
      body: readFileSync(resolve(directory, `${locale}.html`), "utf8"),
    });
  });
  for (const locale of ["en-CA", "fr-CA"]) {
    const page = await context.newPage();
    const consoleErrors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    await page.goto(
      `https://static-fixture.localhost/fallback?locale=${locale}`,
    );
    const desktop = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
      .analyze();
    await page.screenshot({
      path: resolve(directory, `${locale}-desktop.png`),
      fullPage: true,
    });
    await page.keyboard.press("Tab");
    const focusWidth = await page
      .locator(":focus")
      .evaluate((node) =>
        Number.parseFloat(getComputedStyle(node).outlineWidth),
      );
    await page.setViewportSize({ width: 320, height: 800 });
    const reflow = await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    );
    await page.evaluate(() => {
      document.documentElement.style.fontSize = "200%";
    });
    const textSize = await page.evaluate(() =>
      Number.parseFloat(getComputedStyle(document.documentElement).fontSize),
    );
    const zoomReflow = await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    );
    const mobile = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
      .analyze();
    await page.screenshot({
      path: resolve(directory, `${locale}-mobile-200percent.png`),
      fullPage: true,
    });
    report.pages.push({
      locale,
      html_sha256: createHash("sha256")
        .update(readFileSync(resolve(directory, `${locale}.html`)))
        .digest("hex"),
      desktop_violations: desktop.violations.map((rule) => ({
        id: rule.id,
        impact: rule.impact,
      })),
      mobile_violations: mobile.violations.map((rule) => ({
        id: rule.id,
        impact: rule.impact,
      })),
      incomplete_checks: [
        ...new Set(
          [...desktop.incomplete, ...mobile.incomplete].map((rule) => rule.id),
        ),
      ],
      keyboard_focus_outline_px: focusWidth,
      reflow_320px: reflow,
      text_font_px: textSize,
      reflow_320px_200percent: zoomReflow,
      console_errors: consoleErrors,
    });
    await page.close();
  }
  await context.close();
} finally {
  await browser.close();
}
writeFileSync(
  resolve(directory, "qa-results.json"),
  JSON.stringify(report, null, 2),
  { mode: 0o600 },
);
const failed = report.pages.some(
  (page) =>
    page.desktop_violations.length ||
    page.mobile_violations.length ||
    page.keyboard_focus_outline_px < 2 ||
    !page.reflow_320px ||
    page.text_font_px < 32 ||
    !page.reflow_320px_200percent ||
    page.console_errors.length,
);
process.stdout.write(
  JSON.stringify({
    fixture_only: true,
    browser: report.browser_version,
    locales: report.pages.length,
    result: failed ? "failed" : "passed",
    evidence: resolve(directory, "qa-results.json"),
  }) + "\n",
);
if (failed) process.exitCode = 1;
