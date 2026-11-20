import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import {
  messages,
  type Locale,
} from "../../../apps/web/src/referrals/messages";
import {
  installFixture,
  sid,
  service,
  rid,
  consentId,
  did,
  ceremonyId,
  sourceId,
  digest,
  reviewId,
  versions,
} from "./fixtures";
async function activate(page: Page, name: string) {
  const button = page.getByRole("button", { name, exact: true });
  await button.focus();
  await expect(button).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("button", {
      name: /^(Check account|Vérifier le compte)$/,
      exact: true,
    }),
  ).toBeEnabled();
}
async function initialize(page: Page, locale: Locale, path = "/referrals") {
  await page.goto(path);
  const language = page.getByRole("combobox", {
    name: "Language",
    exact: true,
  });
  await language.selectOption(locale);
  await page
    .getByRole("combobox", { name: messages[locale].language, exact: true })
    .focus();
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("button", { name: messages[locale].check, exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(
    page.getByText(messages[locale].done, { exact: true }),
  ).toBeVisible();
}
async function accessibilityAndReflow(
  page: Page,
  actor: string,
  locale: Locale,
) {
  const rows: {
    width: number;
    scrollWidth: number;
    violations: string[];
    incomplete: string[];
  }[] = [];
  for (const width of [1280, 640]) {
    await page.setViewportSize({ width, height: 900 });
    const scrollWidth = await page.evaluate(
      () => document.documentElement.scrollWidth,
    );
    expect(scrollWidth).toBeLessThanOrEqual(width);
    const result = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();
    rows.push({
      width,
      scrollWidth,
      violations: result.violations.map((value) => value.id),
      incomplete: result.incomplete.map((value) => value.id),
    });
    expect(result.violations).toEqual([]);
  }
  await test.info().attach(`${actor}-${locale}-automated-accessibility.json`, {
    contentType: "application/json",
    body: JSON.stringify(
      {
        environment:
          "isolated Chromium with mocked synthetic API and provider; HTTP loopback only",
        browser: "Chromium",
        native_200_percent_zoom: "not_tested",
        human_review: "deferred_until_after_IMP10",
        rows,
      },
      null,
      2,
    ),
  });
}
for (const locale of ["en-CA", "fr-CA"] as const) {
  test(`worker exact review, uncertain delivery and partial reconciliation ${locale}`, async ({
    page,
  }) => {
    const fixture = await installFixture(page, "worker"),
      text = messages[locale];
    await initialize(page, locale);
    await page
      .getByRole("textbox", { name: text.session, exact: true })
      .fill(sid);
    await activate(page, text.load);
    await activate(page, text.findOptions);
    await page
      .getByRole("combobox", { name: text.chooseOption, exact: true })
      .selectOption(service);
    const source = page.getByRole("checkbox", {
      name: new RegExp(`${text.labels.needs} · Synthetic`),
    });
    await source.focus();
    await page.keyboard.press("Space");
    await expect(source).toBeChecked();
    await activate(page, text.draft);
    await expect(
      page.getByText(`${text.digest}: ${digest}`, { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("Fictional option; capacity is unknown", { exact: true }),
    ).toBeVisible();
    await page
      .getByRole("textbox", { name: text.consent, exact: true })
      .fill(consentId);
    await activate(page, text.loadConsent);
    await activate(page, text.approve);
    await activate(page, text.enqueue);
    await expect(page.getByText(text.pending, { exact: true })).toBeVisible();
    expect(
      fixture.mutations.some((value) => value.path.endsWith("/send")),
    ).toBe(false);
    await activate(page, text.send);
    await expect(
      page.getByText(text.unresolved, { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: text.send, exact: true }),
    ).toHaveCount(0);
    await activate(page, text.reconcile);
    await activate(page, text.receipt);
    await expect(
      page.getByText(text.partialState, { exact: true }),
    ).toBeVisible();
    await expect(page.getByText(text.support, { exact: true })).toBeVisible();
    expect(
      fixture.mutations.filter((value) => value.path.endsWith("/send")),
    ).toHaveLength(1);
    expect(
      fixture.mutations.find((value) => value.path.endsWith("/review"))?.body,
    ).toMatchObject({
      exact_digest: digest,
      source_vector: versions,
      decision: "accept",
    });
    expect(
      fixture.mutations.find((value) => value.path.endsWith("/dispatch"))?.body,
    ).toMatchObject({
      consent_id: consentId,
      review_id: reviewId,
      exact_payload_digest: digest,
    });
    await accessibilityAndReflow(page, "worker", locale);
  });
  test(`receiver field-specific decision ${locale}`, async ({ page }) => {
    const fixture = await installFixture(page, "receiver"),
      text = messages[locale];
    await initialize(page, locale, "/referrals/receiver");
    await activate(page, text.loadInbox);
    await activate(page, did);
    await page
      .getByRole("combobox", { name: text.decision, exact: true })
      .selectOption("partial");
    const field = page.getByRole("checkbox", {
      name: text.labels.needs,
      exact: true,
    });
    await field.focus();
    await page.keyboard.press("Space");
    await activate(page, text.submitDecision);
    await expect(
      page.getByText(text.partialState, { exact: true }),
    ).toBeVisible();
    expect(
      fixture.mutations.find((value) => value.path.endsWith("/decision"))?.body,
    ).toEqual({
      expected_revision: "1",
      dispatch_id: did,
      payload_digest: digest,
      decision: "partial",
      accepted_fields: ["needs"],
      reason: "scope",
    });
    await accessibilityAndReflow(page, "receiver", locale);
  });
  test(`client exact consent preview and provider-proof binding ${locale}`, async ({
    page,
  }) => {
    const fixture = await installFixture(page, "pid"),
      text = messages[locale];
    await initialize(page, locale, "/referrals/client");
    await page.getByRole("textbox", { name: text.open, exact: true }).fill(rid);
    await activate(page, text.openReferral);
    const field = page.getByRole("checkbox", {
      name: text.labels.needs,
      exact: true,
    });
    await field.focus();
    await page.keyboard.press("Space");
    await expect(
      page.getByRole("button", { name: text.previewConsent, exact: true }),
    ).toBeDisabled();
    await activate(page, text.beginVerification);
    await activate(page, text.confirmVerification);
    await activate(page, text.previewConsent);
    expect(
      fixture.mutations.some((value) => value.path === "/v1/consents"),
    ).toBe(false);
    await accessibilityAndReflow(page, "client-preview", locale);
    await activate(page, text.grantConsent);
    await expect(
      page.getByText(text.grantRecorded, { exact: true }),
    ).toBeVisible();
    expect(
      fixture.mutations.find((value) => value.path === "/v1/consents")?.body,
    ).toMatchObject({
      purpose: "referral",
      fields: ["needs"],
      authority_proof_id: ceremonyId,
      recipient: {
        kind: "service",
        service_id: service,
        directory_revision: "1",
      },
    });
    expect(
      fixture.mutations.find(
        (value) => value.path === "/v1/auth/step-up/confirm",
      )?.body,
    ).toMatchObject({ ceremony_id: ceremonyId, proof_intent_id: sourceId });
  });
}
