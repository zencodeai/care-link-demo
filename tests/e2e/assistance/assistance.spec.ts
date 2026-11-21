import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { manualMessages } from "../../../apps/web/src/manual/messages";
import { messages } from "../../../apps/web/src/assistance/messages";
import { sessionId } from "../../../apps/web/src/assistance/fixtures";
import { installFixture } from "./fixtures";
async function open(page: Page, locale: "en-CA" | "fr-CA") {
  const text = messages[locale];
  await page.goto("/assistance");
  await page.getByLabel("Language").selectOption(locale);
  await page.getByRole("textbox", { name: text.session }).fill(sessionId);
  await page.getByRole("button", { name: text.load }).click();
  return text;
}
async function completeManual(page: Page, locale: "en-CA" | "fr-CA") {
  await page.getByRole("link", { name: messages[locale].manual }).click();
  await page.locator("#language").selectOption(locale);
  const text = manualMessages[locale];
  const manual = page.getByRole("region", { name: text.title, exact: true });
  await manual.getByRole("button", { name: text.check }).click();
  await manual
    .getByRole("textbox", { name: text.session, exact: true })
    .fill(sessionId);
  await manual.getByRole("button", { name: text.open, exact: true }).click();
  await manual
    .getByRole("textbox", { name: text.message, exact: true })
    .fill("Human authored synthetic support after optional assistance.");
  await manual.getByRole("button", { name: text.send, exact: true }).click();
  await expect(manual.locator(".manual-message-text")).toHaveText(
    "Human authored synthetic support after optional assistance.",
  );
}
async function scan(page: Page) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations).toEqual([]);
  expect(result.incomplete).toEqual([]);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(overflow).toBe(false);
}
for (const locale of ["en-CA", "fr-CA"] as const) {
  test(`${locale} exact review, edit, reject and keyboard with clean axe at1280/640`, async ({
    page,
  }) => {
    const mutations = await installFixture(page);
    const text = await open(page, locale);
    await expect(page.getByRole("button", { name: text.start })).toBeEnabled();
    await page.getByRole("button", { name: text.start }).focus();
    await page.keyboard.press("Enter");
    const editor = page.getByRole("textbox", { name: text.edit });
    await expect(editor).toBeVisible();
    await expect(
      page.getByRole("heading", { name: text.proposed, level: 3 }),
    ).toBeFocused();
    await expect(page.getByText(text.effect)).toBeVisible();
    await expect(page.getByText(text.noRecipient)).toBeVisible();
    await expect(page.getByText(text.disputed, { exact: false })).toBeVisible();
    await scan(page);
    await page.setViewportSize({ width: 640, height: 800 });
    await scan(page);
    await editor.focus();
    await page.keyboard.press("ControlOrMeta+A");
    await page.keyboard.type(
      "Human corrected synthetic draft; capacity unknown.",
    );
    await expect(
      page.getByRole("button", { name: text.accept }),
    ).toBeDisabled();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("button", { name: text.save })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByText(text.edited)).toBeVisible();
    await expect(editor).toHaveValue(
      "Human corrected synthetic draft; capacity unknown.",
    );
    await page.getByRole("button", { name: text.reject }).click();
    await expect(page.getByText(text.rejected)).toBeVisible();
    expect(
      mutations
        .filter((item) => item.path.endsWith("/review"))
        .map((item) => item.body.decision),
    ).toEqual(["edit", "reject"]);
    expect(
      mutations.some((item) => /dispatch|consent|messages/.test(item.path)),
    ).toBe(false);
    await expect(page.getByRole("link", { name: text.manual })).toHaveAttribute(
      "href",
      "/",
    );
    await completeManual(page, locale);
    expect(
      mutations.filter((item) => item.path.endsWith("/messages")).at(-1)?.body
        .accepted_draft_id,
    ).toBe(null);
  });
  test(`${locale} outage and unknown compute leave manual service available`, async ({
    page,
  }) => {
    await installFixture(page, { unavailable: true });
    const text = await open(page, locale);
    await expect(page.getByText(text.unavailable)).toBeVisible();
    await expect(page.getByRole("button", { name: text.start })).toBeDisabled();
    await expect(page.getByRole("link", { name: text.manual })).toBeVisible();
    await scan(page);
    await completeManual(page, locale);
  });
}
test("stale source review is fenced", async ({ page }) => {
  const mutations = await installFixture(page, { stale: true });
  const text = await open(page, "en-CA");
  await page.getByRole("button", { name: text.start }).click();
  await expect(page.getByText(text.stale)).toBeVisible();
  await expect(page.getByRole("button", { name: text.accept })).toBeDisabled();
  expect(
    mutations.filter((item) => item.path.endsWith("/review")),
  ).toHaveLength(0);
});
test("uncertain review retries the same exact operation", async ({ page }) => {
  const mutations = await installFixture(page, { unknown: true });
  const text = await open(page, "en-CA");
  await page.getByRole("button", { name: text.start }).click();
  await page.getByRole("button", { name: text.accept }).click();
  await expect(page.getByText(text.unknown)).toBeVisible();
  await page.getByRole("button", { name: text.retry }).click();
  await expect(page.getByText(text.accepted)).toBeVisible();
  const attempts = mutations.filter((item) => item.path.endsWith("/review"));
  expect(attempts).toHaveLength(2);
  expect(attempts[0]).toEqual(attempts[1]);
});
test("cancelled output never claims model compute stopped", async ({
  page,
}) => {
  await installFixture(page, { pending: true });
  const text = await open(page, "en-CA");
  await page.getByRole("button", { name: text.start }).click();
  await expect(page.getByText(text.working)).toBeVisible();
  await page.getByRole("button", { name: text.cancel }).click();
  await expect(page.getByText(text.cancelled)).toBeVisible();
  await expect(page.getByRole("link", { name: text.manual })).toBeVisible();
});

for (const code of [401, 403] as const) {
  test(`status ${code} hides previously visible private facts and preserves unsent correction`, async ({
    page,
  }) => {
    await installFixture(page, { statusAuthFailure: code });
    const text = await open(page, "en-CA");
    await page.getByRole("button", { name: text.start }).click();
    await expect(
      page.getByText(
        "Synthetic report: navigation requested; service capacity is unknown.",
      ),
    ).toBeVisible();
    const editor = page.getByRole("textbox", { name: text.edit });
    await editor.fill("Unsent human correction after expired access");
    await page.getByRole("button", { name: text.check }).click();
    await expect(
      page.getByText(code === 401 ? text.signedOut : text.failed),
    ).toBeVisible();
    await expect(editor).toHaveValue(
      "Unsent human correction after expired access",
    );
    await expect(
      page.getByText(
        "Synthetic report: navigation requested; service capacity is unknown.",
      ),
    ).toHaveCount(0);
    await expect(
      page.getByText(
        "Synthetic original: navigation requested; capacity unknown.",
      ),
    ).toHaveCount(0);
    await expect(page.getByRole("button", { name: text.accept })).toHaveCount(
      0,
    );
  });
}

for (const locale of ["en-CA", "fr-CA"] as const) {
  test(`${locale} scoped preparation opt-in and attributed knowledge preserve manual service`, async ({
    page,
  }) => {
    const mutations = await installFixture(page);
    const text = await open(page, locale);
    await expect(
      page.getByRole("checkbox", { name: text.automatic }),
    ).toHaveCount(0);
    await completeManual(page, locale);
    const automatic = page.getByRole("checkbox", { name: text.automatic });
    await expect(page.getByRole("button", { name: text.start })).toBeEnabled();
    await expect(automatic).not.toBeChecked();
    expect(mutations.filter(({ path }) => path === "/v1/tasks")).toHaveLength(
      0,
    );
    await automatic.check();
    await expect(page.getByRole("textbox", { name: text.edit })).toBeVisible();
    await automatic.uncheck();
    await automatic.check();
    expect(mutations.filter(({ path }) => path === "/v1/tasks")).toHaveLength(
      1,
    );
    await page
      .getByRole("textbox", { name: text.knowledgeQuery })
      .fill("handoff");
    await page.getByRole("button", { name: text.knowledgeSearch }).click();
    await expect(
      page.getByRole("heading", { name: "Synthetic handoff guidance" }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Ontario Health background standard" }),
    ).toHaveAttribute(
      "href",
      "https://www.ontariohealth.ca/clinical/quality-standards/major-depression",
    );
    await expect(page.getByText(text.clinicalSourceHint)).toBeVisible();
    await scan(page);
    await page.setViewportSize({ width: 640, height: 800 });
    await scan(page);
    expect(mutations.some(({ path }) => /dispatch|consent/.test(path))).toBe(
      false,
    );
    await expect(
      page.getByRole("textbox", {
        name: manualMessages[locale].message,
        exact: true,
      }),
    ).toBeEnabled();
  });
}
