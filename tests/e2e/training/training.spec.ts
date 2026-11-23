import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import {
  messages,
  type Text,
} from "../../../apps/web/src/features/training/messages";
import { fixture, installFixture } from "./fixtures";

async function open(page: Page, locale: keyof typeof messages) {
  const text = messages[locale];
  await page.goto("/training");
  await page.getByLabel("Language").selectOption(locale);
  await page.getByRole("button", { name: text.check }).press("Enter");
  await expect(page.getByText(text.ready, { exact: true })).toBeVisible();
  return text;
}

async function createScenario(page: Page, text: Text) {
  await page.getByLabel(text.scenarioArtifact).fill(fixture.artifact);
  await page.getByLabel(text.fixture).selectOption("channel_drop");
  await page.getByLabel(text.clock).fill(fixture.clock);
  await page.getByLabel(text.clock).press("Tab");
  const submit = page.getByRole("button", {
    name: text.createScenario,
    exact: true,
  });
  await expect(submit).toBeFocused();
  await page.keyboard.press("Enter");
}

async function requestReplay(page: Page, text: Text) {
  await page.getByLabel(text.replayScenario).fill(fixture.scenario);
  await page.getByLabel(text.manifest).fill(fixture.manifest);
  await page.getByLabel(text.recorded).fill(fixture.recorded);
  await page.getByLabel(text.bundle).fill(fixture.bundle);
  await page.getByLabel(text.bundle).press("Enter");
}

async function scan(page: Page) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations).toEqual([]);
  expect(result.incomplete).toEqual([]);
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(page.viewportSize()?.width ?? 0);
}

for (const locale of ["en-CA", "fr-CA"] as const) {
  test(`${locale} trainer creates, reads and stops a scenario and inspects a replay`, async ({
    page,
  }) => {
    const state = await installFixture(page);
    const text = await open(page, locale);
    await expect(page.locator("html")).toHaveAttribute("lang", locale);
    await createScenario(page, text);
    await expect(page.getByText(text.committed)).toBeVisible();
    await expect(
      page.getByLabel(text.scenarioReference, { exact: true }),
    ).toHaveValue(fixture.scenario);
    await page
      .getByLabel(text.scenarioReference, { exact: true })
      .press("Enter");
    await expect(
      page.getByText(text.scenarioStates.created, { exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: text.stopScenario }).press("Enter");
    await expect(page.getByText(text.committed)).toBeVisible();
    await page
      .getByLabel(text.scenarioReference, { exact: true })
      .press("Enter");
    await expect(
      page.getByText(text.scenarioStates.stopped, { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: text.stopScenario }),
    ).toHaveCount(0);
    await requestReplay(page, text);
    await expect(
      page.getByText(fixture.evidence, { exact: true }),
    ).toBeVisible();
    await expect(page.getByLabel(text.evaluationReference)).toHaveValue(
      fixture.evaluation,
    );
    state.evaluation = "failed";
    await page.getByLabel(text.evaluationReference).press("Enter");
    await expect(
      page.getByText(text.evaluationStates.failed, { exact: true }),
    ).toBeVisible();
    await expect(page.getByText(fixture.evidence, { exact: true })).toHaveCount(
      0,
    );
    expect(state.mutations.map(({ path, body }) => ({ path, body }))).toEqual([
      {
        path: "/v1/training/scenarios",
        body: {
          artifact_digest: fixture.artifact,
          business_clock_at: fixture.clock,
          fixture_mode: "channel_drop",
          locale,
        },
      },
      {
        path: `/v1/training/scenarios/${fixture.scenario}/stop`,
        body: { expected_revision: "1" },
      },
      {
        path: "/v1/evaluation/replays",
        body: {
          scenario_id: fixture.scenario,
          input_manifest_digest: fixture.manifest,
          recorded_outputs_digest: fixture.recorded,
          bundle_digest: fixture.bundle,
        },
      },
    ]);
    expect(new Set(state.mutations.map(({ key }) => key)).size).toBe(3);
    expect(
      state.mutations.every(
        ({ key, csrf }) => key.length === 36 && csrf.length === 48,
      ),
    ).toBe(true);
    expect(state.reads).toEqual([
      `/v1/training/scenarios/${fixture.scenario}`,
      `/v1/training/scenarios/${fixture.scenario}`,
      `/v1/evaluation/replays/${fixture.evaluation}`,
    ]);
    await scan(page);
    await page.setViewportSize({ width: 320, height: 800 });
    await scan(page);
    expect(
      await page.evaluate(() => ({
        local: localStorage.length,
        session: sessionStorage.length,
      })),
    ).toEqual({
      local: 0,
      session: 0,
    });
  });
}

test("unknown outcome locks new commands and a retry uses the same request", async ({
  page,
}) => {
  const state = await installFixture(page);
  const text = await open(page, "en-CA");
  state.lostMutation = true;
  await createScenario(page, text);
  await expect(page.getByRole("alert")).toHaveText(text.unknown);
  await expect(
    page.getByRole("button", { name: text.createScenario, exact: true }),
  ).toBeDisabled();
  await expect(page.getByText(text.committed)).toHaveCount(0);
  await page.getByRole("button", { name: text.retry }).press("Enter");
  await expect(page.getByText(text.committed)).toBeVisible();
  expect(state.mutations).toHaveLength(2);
  expect(state.mutations[1]).toEqual(state.mutations[0]);
});

test("a changed account clears pending authority and does not redispatch", async ({
  page,
}) => {
  const state = await installFixture(page);
  const text = await open(page, "en-CA");
  state.lostMutation = true;
  await createScenario(page, text);
  await expect(page.getByRole("alert")).toHaveText(text.unknown);
  state.account = fixture.trainerReplacement;
  await page.getByRole("button", { name: text.retry }).press("Enter");
  await expect(page.getByRole("alert")).toHaveText(text.rejected);
  await expect(page.getByRole("button", { name: text.retry })).toHaveCount(0);
  expect(state.mutations).toHaveLength(1);
});

test("a governance reviewer can request replay and sees no scenario controls", async ({
  page,
}) => {
  await installFixture(page, "governance");
  const text = await open(page, "fr-CA");
  await expect(page.getByRole("heading", { name: text.scenarios })).toHaveCount(
    0,
  );
  await requestReplay(page, text);
  await expect(page.getByText(fixture.evidence, { exact: true })).toBeVisible();
  await scan(page);
});

test("wrong target and sign-out clear previously loaded scenario evidence", async ({
  page,
}) => {
  const state = await installFixture(page);
  const text = await open(page, "en-CA");
  await page
    .getByLabel(text.scenarioReference, { exact: true })
    .fill(fixture.scenario);
  await page.getByLabel(text.scenarioReference, { exact: true }).press("Enter");
  await expect(page.getByText(fixture.artifact)).toBeVisible();
  state.malformedRead = true;
  await page.getByRole("button", { name: text.readScenario }).press("Enter");
  await expect(page.getByRole("alert")).toHaveText(text.invalid);
  await expect(page.getByText(fixture.artifact)).toHaveCount(0);
  state.signedOut = true;
  await page.getByRole("button", { name: text.check }).press("Enter");
  await expect(page.getByRole("alert")).toHaveText(text.signed_out);
  await expect(page.getByRole("heading", { name: text.scenarios })).toHaveCount(
    0,
  );
  expect(state.mutations).toHaveLength(0);
});

test("fresh verification for the same trainer preserves unsent input", async ({
  page,
}) => {
  const state = await installFixture(page);
  const text = await open(page, "en-CA");
  await page.getByLabel(text.scenarioArtifact).fill(fixture.artifact);
  state.signedOut = true;
  await page.getByRole("button", { name: text.check }).press("Enter");
  await expect(page.getByRole("alert")).toHaveText(text.signed_out);
  await expect(page.getByLabel(text.scenarioArtifact)).toHaveCount(0);
  state.signedOut = false;
  await page.getByRole("button", { name: text.check }).press("Enter");
  await expect(page.getByLabel(text.scenarioArtifact)).toHaveValue(
    fixture.artifact,
  );
  expect(state.mutations).toHaveLength(0);
});

test("training sign-in requests the selected role and exact return route", async ({
  page,
}) => {
  await installFixture(page);
  await page.route("**/v1/auth/login", async (route) => {
    await route.fulfill({ status: 403, json: {} });
  });
  await page.goto("/training");
  const account = page.locator("#training-sign-in-role");
  for (const [role, returnRoute] of [
    ["trainer", "training"],
    ["governance", "governance"],
  ] as const) {
    await account.selectOption(role);
    const requested = page.waitForRequest("**/v1/auth/login");
    await page
      .locator("#training-sign-in-title")
      .locator("..")
      .getByRole("button", {
        name: "Sign in",
        exact: true,
      })
      .click();
    expect((await requested).postDataJSON()).toEqual({
      role,
      return_route: returnRoute,
      locale: "en-CA",
    });
    await expect(account).toBeEnabled();
  }
});
