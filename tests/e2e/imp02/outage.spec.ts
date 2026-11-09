import { randomUUID } from "node:crypto";
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { isAbsolute, join } from "node:path";
import { test, expect } from "@playwright/test";
import {
  accountPanel,
  cancelOwned,
  isRecord,
  signIn,
  reviewManifest,
} from "./browser";
import { readLabConfig } from "./lab";
const lab = readLabConfig();
type Phase = "main_down" | "identity_down" | "restored";
async function checkpoint(phase: Phase) {
  const directory = process.env.CARE_LINK_IMP02_OUTAGE_CONTROL;
  if (!directory || !isAbsolute(directory))
    throw new Error(
      "Outage qualification requires an explicit private supervisor handshake directory",
    );
  mkdirSync(directory, { recursive: true, mode: 0o700 });
  const nonce = randomUUID();
  const temporary = join(directory, `${nonce}.tmp`);
  writeFileSync(temporary, JSON.stringify({ nonce, phase }), { mode: 0o600 });
  renameSync(temporary, join(directory, "request.json"));
  await expect
    .poll(
      () => {
        try {
          const ack: unknown = JSON.parse(
            readFileSync(join(directory, "ack.json"), "utf8"),
          );
          return (
            isRecord(ack) &&
            ack.nonce === nonce &&
            ack.phase === phase &&
            ack.status === "applied" &&
            ack.mock_used === false
          );
        } catch {
          return false;
        }
      },
      {
        message: `Owner-operated actual ${phase} checkpoint`,
        timeout: phase === "restored" ? 150_000 : 45_000,
        intervals: [250, 500, 1000],
      },
    )
    .toBe(true);
}

test("actual main/identity outages retain honest host help and reviewed static boundaries", async ({
  browser,
}, testInfo) => {
  test.setTimeout(360_000);
  testInfo.annotations.push({
    type: "outage-coordination",
    description:
      "File protocol requests owner-operated leased service changes. Browser has no process/cluster authority. Checkpoints alone are not evidence; actual API/UI observations follow.",
  });
  const context = await browser.newContext({
    ignoreHTTPSErrors: lab.ignoreHTTPSErrors,
  });
  let helpId: string | null = null;
  let outageRequested = false;
  try {
    const page = await context.newPage();
    const panel = await signIn(page, lab, lab.participant, "pid");
    await panel
      .getByRole("button", { name: "Request human help", exact: true })
      .click();
    await expect(
      panel.getByText(
        "Request recorded. A staffed connection is not confirmed.",
        { exact: true },
      ),
    ).toBeVisible();
    helpId = await panel.getByLabel("Help request ID").inputValue();
    expect(
      (
        await page.request.get(lab.staticOrigin + "/fallback?locale=en-CA")
      ).status(),
    ).toBe(200);
    expect(
      (await page.request.get(lab.mainOrigin + "/dev/health")).status(),
    ).toBe(200);
    outageRequested = true;
    await checkpoint("main_down");
    const main = await page.request.get(lab.mainOrigin + "/dev/health").then(
      (response) => response.status(),
      () => 0,
    );
    expect(main === 0 || main >= 500).toBe(true);
    await panel
      .getByRole("button", { name: "Check help status", exact: true })
      .click();
    await expect(
      panel.getByText(
        "Request recorded. A staffed connection is not confirmed.",
        { exact: true },
      ),
    ).toBeVisible();
    expect(
      (
        await page.request.get(lab.helpOrigin + "/help/v1/requests/" + helpId)
      ).status(),
    ).toBe(200);
    expect(
      (
        await page.request.get(lab.staticOrigin + "/fallback?locale=fr-CA")
      ).status(),
    ).toBe(200);
    await checkpoint("identity_down");
    await panel
      .getByRole("button", { name: "Check help status", exact: true })
      .click();
    await expect(
      panel.getByText(/Current authority is unavailable|Sign in again/),
    ).toBeVisible();
    await expect(
      panel.getByRole("button", { name: "Request human help", exact: true }),
    ).toBeDisabled();
    await expect(
      panel.getByText(
        "Request recorded. A staffed connection is not confirmed.",
        { exact: true },
      ),
    ).toHaveCount(0);
    expect([401, 403, 502, 503, 504]).toContain(
      (
        await page.request.get(lab.helpOrigin + "/help/v1/requests/" + helpId)
      ).status(),
    );
    const fallback = page.getByRole("link", {
      name: "Independent fallback information",
      exact: true,
    });
    await expect(fallback).toHaveAttribute(
      "href",
      lab.staticOrigin + "/fallback?locale=en-CA",
    );
    await fallback.click();
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await reviewManifest(page, lab, "en-CA");
  } finally {
    if (outageRequested) await checkpoint("restored");
    if (helpId) {
      const page = context.pages()[0];
      if (page) {
        await page.goto(lab.helpOrigin + "/private-help");
        await accountPanel(page, "help")
          .getByRole("button", { name: "Check sign-in", exact: true })
          .click();
        await cancelOwned(page, lab, helpId);
      }
    }
    await context.close();
  }
});
