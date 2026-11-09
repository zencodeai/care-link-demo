import { randomUUID } from "node:crypto";
import { test, expect, type Page } from "@playwright/test";
import {
  accountPanel,
  csrfProof,
  isRecord,
  providerLogin,
  signIn,
} from "./browser";
import { readLabConfig } from "./lab";
const lab = readLabConfig();
async function beginExportVerification(page: Page, resourceId: string) {
  const panel = accountPanel(page, "main");
  await panel.getByLabel("Verification purpose").selectOption("export");
  await panel.getByLabel("Resource ID").fill(resourceId);
  const navigation = page.waitForURL((url) => url.origin === lab.oidcOrigin, {
    waitUntil: "domcontentloaded",
  });
  await panel
    .getByRole("button", { name: "Start verification", exact: true })
    .click();
  await navigation;
  await providerLogin(page, lab, lab.worker, lab.mainOrigin);
  await accountPanel(page, "main")
    .getByRole("button", { name: "Check sign-in", exact: true })
    .click();
  await expect(
    accountPanel(page, "main").getByRole("button", {
      name: "Confirm verification",
      exact: true,
    }),
  ).toBeVisible();
}

test("real provider: mandatory five-minute cooling and a second fresh MFA proof", async ({
  browser,
}, testInfo) => {
  test.setTimeout(420_000);
  const context = await browser.newContext({
    ignoreHTTPSErrors: lab.ignoreHTTPSErrors,
  });
  try {
    const page = await context.newPage();
    await signIn(page, lab, lab.worker, "worker", "main");
    const resourceId = randomUUID();
    await beginExportVerification(page, resourceId);
    const sessionResponse = await page.request.get(
      lab.mainOrigin + "/v1/auth/session",
    );
    const ceremonyId = sessionResponse.headers()["x-ceremony-id"];
    const session: unknown = await sessionResponse.json();
    if (
      !ceremonyId ||
      !isRecord(session) ||
      typeof session.revision !== "string"
    )
      throw new Error(
        "Actual current session lacks its bound ceremony metadata",
      );
    const proofResponse = await page.request.get(
      `${lab.mainOrigin}/v1/auth/step-up/proof?ceremony_id=${ceremonyId}`,
    );
    const proof: unknown = await proofResponse.json();
    if (!isRecord(proof) || typeof proof.proof_intent_id !== "string")
      throw new Error("Actual current proof metadata is invalid");
    const first = page.waitForResponse(
      (response) =>
        response.url() === lab.mainOrigin + "/v1/auth/step-up/confirm" &&
        response.request().method() === "POST",
    );
    await accountPanel(page, "main")
      .getByRole("button", { name: "Confirm verification", exact: true })
      .click();
    const firstResponse = await first;
    expect(firstResponse.status()).toBe(200);
    const cooling: unknown = await firstResponse.json();
    if (
      !isRecord(cooling) ||
      cooling.state !== "cooling_off" ||
      typeof cooling.not_before !== "string"
    )
      throw new Error("First actual fresh proof did not establish cooling-off");
    const boundary = Date.parse(cooling.not_before);
    expect(boundary - Date.now()).toBeGreaterThanOrEqual(295_000);
    testInfo.annotations.push({
      type: "cooling-clock-boundary",
      description: JSON.stringify({
        first_response_received_at: new Date().toISOString(),
        signed_not_before: cooling.not_before,
      }),
    });
    const token = await csrfProof(page, lab.mainOrigin);
    const replay = await page.request.post(
      lab.mainOrigin + "/v1/auth/step-up/confirm",
      {
        headers: {
          Origin: lab.mainOrigin,
          "X-CSRF-Token": token,
          "Idempotency-Key": randomUUID(),
        },
        data: {
          ceremony_id: ceremonyId,
          proof_intent_id: proof.proof_intent_id,
          expected_revision: session.revision,
        },
      },
    );
    expect(replay.status()).toBe(403);
    let interval = 0;
    while (Date.now() < boundary) {
      interval += 1;
      const until = Math.min(boundary, Date.now() + 30_000);
      await test.step(`Mandatory cooling interval ${interval} (real clock, at most 30 seconds)`, async () => {
        await expect
          .poll(() => Date.now() >= until, {
            timeout: 31_000,
            intervals: [500, 1000],
          })
          .toBe(true);
      });
    }
    await beginExportVerification(page, resourceId);
    const second = page.waitForResponse(
      (response) =>
        response.url() === lab.mainOrigin + "/v1/auth/step-up/confirm" &&
        response.request().method() === "POST",
    );
    await accountPanel(page, "main")
      .getByRole("button", { name: "Confirm verification", exact: true })
      .click();
    const secondResponse = await second;
    expect(secondResponse.status()).toBe(200);
    const verified: unknown = await secondResponse.json();
    expect(
      isRecord(verified) &&
        verified.ceremony_id === ceremonyId &&
        verified.state === "verified",
    ).toBe(true);
    testInfo.annotations.push({
      type: "cooling-clock-completed",
      description: JSON.stringify({
        second_response_received_at: new Date().toISOString(),
        elapsed_after_not_before_ms: Date.now() - boundary,
      }),
    });
    const after: unknown = await (
      await page.request.get(lab.mainOrigin + "/v1/auth/session")
    ).json();
    expect(isRecord(after) && after.assurance === "AL2").toBe(true);
    testInfo.annotations.push({
      type: "assurance-scope",
      description:
        "Real-clock cooldown and second MFA verified the exact ceremony; no export executed and no ambient AL3 granted.",
    });
  } finally {
    await context.close();
  }
});
