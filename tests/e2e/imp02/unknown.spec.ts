import { test, expect } from "@playwright/test";
import { accountPanel, cancelOwned, signIn } from "./browser";
import { readLabConfig } from "./lab";
const lab = readLabConfig();

for (const lost of ["create-intent", "requests"] as const) {
  test(`real provider: lost ${lost} reply survives full page navigation with one help identity`, async ({
    browser,
  }) => {
    const context = await browser.newContext({
      ignoreHTTPSErrors: lab.ignoreHTTPSErrors,
    });
    let helpId: string | null = null;
    try {
      const page = await context.newPage();
      await signIn(page, lab, lab.participant, "pid");
      const keys: string[] = [];
      let preparedKey: string | null = null;
      let aborted = false;
      await page.route(
        `${lab.helpOrigin}/help/v1/create-intent`,
        async (route) => {
          const response = await route.fetch();
          expect(response.status()).toBe(200);
          const body: unknown = await response.json();
          if (
            typeof body !== "object" ||
            body === null ||
            !("operation_id" in body) ||
            typeof body.operation_id !== "string"
          )
            throw new Error("Actual durable intent response is invalid");
          if (preparedKey !== null) expect(body.operation_id).toBe(preparedKey);
          preparedKey = body.operation_id;
          if (lost === "create-intent" && !aborted) {
            aborted = true;
            await route.abort("failed");
          } else await route.fulfill({ response });
        },
      );
      await page.route(`${lab.helpOrigin}/help/v1/requests`, async (route) => {
        const response = await route.fetch();
        expect(response.status()).toBe(200);
        const body: unknown = await response.json();
        if (
          typeof body !== "object" ||
          body === null ||
          !("id" in body) ||
          typeof body.id !== "string"
        )
          throw new Error("Actual create response is invalid");
        if (helpId !== null) expect(body.id).toBe(helpId);
        helpId = body.id;
        keys.push(route.request().headers()["idempotency-key"] ?? "");
        if (lost === "requests" && !aborted) {
          aborted = true;
          await route.abort("failed");
        } else await route.fulfill({ response });
      });
      await accountPanel(page, "help")
        .getByRole("button", { name: "Request human help", exact: true })
        .click();
      await expect(
        accountPanel(page, "help").getByText(
          /No confirmed result was received/,
        ),
      ).toBeVisible();
      // A real navigation destroys every React ref and private retry map. Fresh
      // same-principal sign-in is checked against the real provider again.
      await page.goto("about:blank");
      await signIn(page, lab, lab.participant, "pid");
      await accountPanel(page, "help")
        .getByRole("button", { name: "Request human help", exact: true })
        .click();
      await expect(
        accountPanel(page, "help").getByText(
          "Request recorded. A staffed connection is not confirmed.",
          { exact: true },
        ),
      ).toBeVisible();
      expect(aborted).toBe(true);
      expect(keys).toHaveLength(lost === "requests" ? 2 : 1);
      expect(new Set(keys).size).toBe(1);
      expect(keys[0]).toBe(preparedKey);
      expect(
        await accountPanel(page, "help")
          .getByLabel("Help request ID")
          .inputValue(),
      ).toBe(helpId);
    } finally {
      const page = context.pages()[0];
      if (helpId && page) await cancelOwned(page, lab, helpId);
      await context.close();
    }
  });
}
