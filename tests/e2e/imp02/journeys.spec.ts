import { randomUUID } from "node:crypto";
import { test, expect } from "@playwright/test";
import { parseContract } from "../../../packages/contracts/typescript/src/index.ts";
import {
  accountPanel,
  cancelOwned,
  csrfProof,
  helpResult,
  signIn,
} from "./browser";
import { readLabConfig } from "./lab";
const lab = readLabConfig();

test("real provider: separate role profiles, current private ownership and accepted-unconnected", async ({
  browser,
}, testInfo) => {
  testInfo.annotations.push({
    type: "actor-attribution",
    description:
      "Scoped role accounts are synthetic profiles role-played by the same project owner; no independent-human acceptance.",
  });
  testInfo.annotations.push({
    type: "browser",
    description: browser.version(),
  });
  const participant = await browser.newContext({
    ignoreHTTPSErrors: lab.ignoreHTTPSErrors,
  });
  const worker = await browser.newContext({
    ignoreHTTPSErrors: lab.ignoreHTTPSErrors,
  });
  const other = await browser.newContext({
    ignoreHTTPSErrors: lab.ignoreHTTPSErrors,
  });
  const anonymous = await browser.newContext({
    ignoreHTTPSErrors: lab.ignoreHTTPSErrors,
  });
  let helpId: string | null = null;
  let cleanupError: Error | null = null;
  try {
    const page = await participant.newPage();
    const panel = await signIn(page, lab, lab.participant, "pid");
    const cookies = await participant.cookies(lab.helpOrigin);
    const sessionCookie = cookies.find(
      (cookie) =>
        cookie.name.startsWith("__Host-") && !cookie.name.includes("binding"),
    );
    expect(
      (await participant.cookies(lab.staticOrigin)).filter((cookie) =>
        cookie.name.startsWith("__Host-"),
      ).length,
    ).toBe(0);
    expect(sessionCookie?.secure).toBe(true);
    expect(sessionCookie?.httpOnly).toBe(true);
    expect(sessionCookie?.sameSite).toBe("Lax");
    expect(sessionCookie?.path).toBe("/");
    expect(await page.evaluate(() => document.cookie)).not.toContain(
      sessionCookie?.name,
    );
    expect(
      await page.evaluate(
        () =>
          Object.keys(localStorage).length + Object.keys(sessionStorage).length,
      ),
    ).toBe(0);
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
    expect(helpId).toMatch(/^[0-9a-f-]{36}$/);
    // Knowing an opaque ID or supplying a role header does not supply authority.
    const denied = await anonymous.request.get(
      `${lab.helpOrigin}/help/v1/requests/${helpId}`,
      { headers: { "X-Role": "worker", "X-Account-Id": randomUUID() } },
    );
    expect([401, 403]).toContain(denied.status());
    const otherPage = await other.newPage();
    await signIn(otherPage, lab, lab.otherParticipant, "pid");
    const wrongOwner = await otherPage.request.get(
      `${lab.helpOrigin}/help/v1/requests/${helpId}`,
    );
    expect([403, 404]).toContain(wrongOwner.status());
    const token = await csrfProof(page, lab.helpOrigin);
    const selfAccept = await page.request.post(
      `${lab.helpOrigin}/help/v1/requests/${helpId}/accept`,
      {
        headers: {
          Origin: lab.helpOrigin,
          "X-CSRF-Token": token,
          "Idempotency-Key": randomUUID(),
        },
        data: { expected_revision: "1" },
      },
    );
    expect(selfAccept.status()).toBe(403);
    const forgedOrigin = await page.request.post(
      `${lab.helpOrigin}/help/v1/requests/${helpId}/cancel`,
      {
        headers: {
          Origin: "https://untrusted.invalid",
          "X-CSRF-Token": token,
          "Idempotency-Key": randomUUID(),
        },
        data: { expected_revision: "1" },
      },
    );
    expect(forgedOrigin.status()).toBe(403);
    const workerPage = await worker.newPage();
    const workerPanel = await signIn(workerPage, lab, lab.worker, "worker");
    await expect(workerPanel.getByText(/Assurance: AL2/)).toBeVisible();
    await workerPanel.getByLabel("Help request ID").fill(helpId);
    await workerPanel
      .getByRole("button", { name: "Check help status", exact: true })
      .click();
    await expect(
      workerPanel.getByText(
        "Request recorded. A staffed connection is not confirmed.",
        { exact: true },
      ),
    ).toBeVisible();
    await workerPanel
      .getByRole("button", { name: "Accept request", exact: true })
      .click();
    await expect(
      workerPanel.getByText(
        "A worker accepted this request. You are not connected.",
        { exact: true },
      ),
    ).toBeVisible();
    await panel
      .getByRole("button", { name: "Check help status", exact: true })
      .click();
    await expect(
      panel.getByText(
        "A worker accepted this request. You are not connected.",
        { exact: true },
      ),
    ).toBeVisible();
    const actual = await helpResult(
      await page.request.get(`${lab.helpOrigin}/help/v1/requests/${helpId}`),
    );
    expect(actual.state).toBe("accepted_unconnected");
    expect(actual.connection_confirmed).toBe(false);
    await cancelOwned(page, lab, helpId);
    helpId = null;
    const logoutResponse = page.waitForResponse(
      (response) =>
        response.url() === `${lab.helpOrigin}/v1/auth/logout` &&
        response.request().method() === "POST",
    );
    await panel.getByRole("button", { name: "Sign out", exact: true }).click();
    const completedLogout = await logoutResponse;
    expect(completedLogout.status()).toBe(200);
    const logoutCommand = parseContract(
      "CommandResult",
      await completedLogout.text(),
    ) as { state: string };
    expect(logoutCommand.state).toBe("committed");
    await expect(
      panel.getByRole("button", { name: "Sign out", exact: true }),
    ).toHaveCount(0);
    const afterLogout = await page.request.get(
      `${lab.helpOrigin}/v1/auth/session`,
    );
    expect([401, 403]).toContain(afterLogout.status());
  } finally {
    try {
      if (helpId) {
        const page = participant.pages()[0];
        if (page) await cancelOwned(page, lab, helpId);
      }
    } catch (error) {
      cleanupError =
        error instanceof Error ? error : new Error("Owned help cleanup failed");
    }
    const closed = await Promise.allSettled([
      participant.close(),
      worker.close(),
      other.close(),
      anonymous.close(),
    ]);
    if (cleanupError || closed.some((result) => result.status === "rejected")) {
      cleanupError ??= new Error("Browser context cleanup failed");
      testInfo.annotations.push({
        type: "cleanup-failed",
        description:
          "Owned help cancellation or context closure failed; no cleanup completion claimed.",
      });
      if (helpId)
        testInfo.annotations.push({
          type: "help-cleanup-needed",
          description:
            "1 owned request requires cancellation reconciliation; identifier retained only in private evidence.",
        });
    }
  }
  // An exception from the test body propagates through finally unchanged. This
  // runs only when the body succeeded, so cleanup cannot replace its failure.
  if (cleanupError) throw cleanupError;
});

test("real provider: main and help BFF cookies stay scoped to separate origins", async ({
  browser,
}) => {
  const context = await browser.newContext({
    ignoreHTTPSErrors: lab.ignoreHTTPSErrors,
  });
  try {
    const page = await context.newPage();
    await signIn(page, lab, lab.participant, "pid", "main");
    const mainSession = await page.request.get(
      lab.mainOrigin + "/v1/auth/session",
    );
    expect(mainSession.status()).toBe(200);
    // Ports are not cookie isolation. Main/help factories use distinct cookie
    // names and server records and must reject another BFF's session credential.
    const helpSession = await page.request.get(
      lab.helpOrigin + "/v1/auth/session",
    );
    expect([401, 403]).toContain(helpSession.status());
    await signIn(page, lab, lab.participant, "pid", "help");
    expect(
      (await page.request.get(lab.mainOrigin + "/v1/auth/session")).status(),
    ).toBe(200);
    const helpCookies = (await context.cookies(lab.helpOrigin)).filter(
      (cookie) => cookie.name.startsWith("__Host-"),
    );
    expect(
      new Set(helpCookies.map((cookie) => cookie.name)).size,
    ).toBeGreaterThanOrEqual(2);
    await expect(
      accountPanel(page, "help").getByRole("button", {
        name: "Request human help",
        exact: true,
      }),
    ).toBeEnabled();
  } finally {
    await context.close();
  }
});

test("real provider: forged callback cannot establish a browser session", async ({
  browser,
}) => {
  const context = await browser.newContext({
    ignoreHTTPSErrors: lab.ignoreHTTPSErrors,
  });
  try {
    const response = await context.request.get(
      `${lab.helpOrigin}/v1/auth/callback?state=${"x".repeat(43)}&code=forged&iss=${encodeURIComponent(lab.oidcOrigin)}`,
    );
    expect([400, 401, 403, 422]).toContain(response.status());
    expect([401, 403]).toContain(
      (await context.request.get(lab.helpOrigin + "/v1/auth/session")).status(),
    );
  } finally {
    await context.close();
  }
});
