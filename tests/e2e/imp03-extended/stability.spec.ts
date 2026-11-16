import { expect, test } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { evidenceDirectory } from "../imp03/config";
import { readExtendedConfig } from "./config";
import { checkpoint, login } from "./helpers";
import { intake } from "./intake";

const lab = readExtendedConfig();
const output = evidenceDirectory();

test("unsent action failure permits same-account conversation reopening", async ({
  browser,
}) => {
  const context = await browser.newContext({ ignoreHTTPSErrors: false });
  try {
    const page = await context.newPage();
    await login(page, lab, "pid", output);
    const { path } = await intake(page, lab, "en-CA", output);
    const draft = "Unsent fictional stability draft";
    await page.getByLabel("Manual message", { exact: true }).fill(draft);
    let sent = 0;
    page.on("request", (request) => {
      if (
        new URL(request.url()).pathname === path + "/human-request" &&
        request.method() === "POST"
      )
        sent += 1;
    });
    // Abort actual access reads until the intended command has failed. No
    // successful response, identity claim or mutation is fabricated.
    await page.route("**/v1/auth/session", (route) =>
      route.abort("connectionfailed"),
    );
    await page
      .getByRole("button", { name: "Ask for a human", exact: true })
      .click();
    await expect(
      page.getByText(
        "Current access or service is unavailable. Private information is hidden; unsent text is preserved.",
        { exact: true },
      ),
    ).toBeVisible();
    expect(sent, "No human-request POST was dispatched").toBe(0);
    await page.unroute("**/v1/auth/session");
    await page
      .getByRole("button", { name: "Check manual access", exact: true })
      .click();
    await expect(
      page.getByText("Current signed-in role: pid", { exact: true }),
    ).toBeVisible();
    await page
      .getByLabel("Conversation ID", { exact: true })
      .fill(path.split("/").at(-1)!);
    await expect(
      page.getByRole("button", {
        name: "Open current conversation",
        exact: true,
      }),
      "A never-dispatched action does not lock conversation reopening",
    ).toBeEnabled();
    await page
      .getByRole("button", { name: "Open current conversation", exact: true })
      .click();
    await expect(
      page.getByRole("heading", {
        name: "Current authorized conversation",
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      page.getByLabel("Manual message", { exact: true }),
    ).toHaveValue(draft);
    expect(sent).toBe(0);
    writeFileSync(
      resolve(output, "unsent-observations.json"),
      JSON.stringify({
        status: "passed",
        human_acceptance: false,
        browser_tls_verification: true,
        intended_post_count: sent,
        existing_conversation_reopened: true,
        draft_preserved_in_mounted_page: true,
      }),
      { mode: 0o600, flag: "wx" },
    );
  } finally {
    await context.close();
  }
});

test("active participant remains reopenable across repeated stream reconnects", async ({
  browser,
}) => {
  test.setTimeout(480_000);
  const context = await browser.newContext({ ignoreHTTPSErrors: false });
  const samples: (Record<string, unknown> & {
    status: number;
    recovered: boolean;
  })[] = [];
  const duration = Number(
    process.env.CARE_LINK_IMP03_STABILITY_SECONDS ?? "360",
  );
  if (![90, 360].includes(duration))
    throw new Error("Exact bounded observation duration required");
  const failures: unknown[] = [];
  let observing = false;
  try {
    const page = await context.newPage();
    await page.addInitScript(() => {
      const Original = window.EventSource;
      const state = { opened: 0, errors: 0, authority: 0 };
      (window as unknown as { g03Stability: typeof state }).g03Stability =
        state;
      window.EventSource = class extends Original {
        constructor(url: string | URL, options?: EventSourceInit) {
          super(url, options);
          this.addEventListener("open", () => (state.opened += 1));
          this.addEventListener("error", () => (state.errors += 1));
          this.addEventListener(
            "resync_required",
            () => (state.authority += 1),
          );
          this.addEventListener("rights_changed", () => (state.authority += 1));
        }
      };
    });
    page.on("response", async (response) => {
      const path = new URL(response.url()).pathname;
      if (!observing || !path.startsWith("/v1/") || response.status() < 400)
        return;
      let reason: string | null = null;
      try {
        const body = (await response.json()) as { message_key?: unknown };
        if (
          typeof body.message_key === "string" &&
          /^(manual|identity)\.[a-z_]+$/.test(body.message_key)
        )
          reason = body.message_key;
      } catch {
        /* Suppress raw bodies, headers and URLs. */
      }
      failures.push({
        path: path.replace(/[0-9a-f]{8}-[0-9a-f-]{27}/g, "{id}"),
        status: response.status(),
        reason,
      });
    });
    await login(page, lab, "pid", output);
    const { path } = await intake(page, lab, "en-CA", output);
    const draft = "Fictional stability draft retained without sending";
    await page.getByLabel("Manual message", { exact: true }).fill(draft);
    // Intake deliberately verifies a pre-disclosure403/409 denial. The normal
    // stability observation starts only after that separate positive gate.
    observing = true;
    checkpoint(output, "observe_active_participant_" + duration + "_seconds");
    const started = Date.now();
    for (let index = 0; index < duration / 15; index += 1) {
      await page.waitForTimeout(15_000);
      const data = await page.evaluate(async () => {
        const response = await fetch("/v1/auth/session", { cache: "no-store" });
        const body = (await response.json().catch(() => ({}))) as {
          role?: unknown;
          expires_at?: unknown;
          message_key?: unknown;
        };
        return {
          status: response.status,
          role: typeof body.role === "string" ? body.role : null,
          expires_in_seconds:
            typeof body.expires_at === "string"
              ? Math.round((Date.parse(body.expires_at) - Date.now()) / 1000)
              : null,
          reason:
            typeof body.message_key === "string" &&
            /^(manual|identity)\.[a-z_]+$/.test(body.message_key)
              ? body.message_key
              : null,
          signals: (window as unknown as { g03Stability: unknown })
            .g03Stability,
        };
      });
      let recovered = true;
      if (data.status === 200) {
        try {
          await expect(
            page.getByRole("heading", {
              name: "Current authorized conversation",
              exact: true,
            }),
            "Fresh authorized projection recovers within the existing five-second request bound",
          ).toBeVisible({ timeout: 5_000 });
        } catch {
          recovered = false;
        }
      }
      samples.push({
        elapsed_ms: Date.now() - started,
        ...data,
        recovered,
        conversation_visible: await page
          .getByRole("heading", {
            name: "Current authorized conversation",
            exact: true,
          })
          .isVisible(),
        open_enabled: await page
          .getByRole("button", {
            name: "Open current conversation",
            exact: true,
          })
          .isEnabled(),
      });
      writeFileSync(
        resolve(output, "stability-progress.json"),
        JSON.stringify({ samples, failures }),
        { mode: 0o600 },
      );
    }
    await page
      .getByRole("button", { name: "Check manual access", exact: true })
      .click();
    await expect(
      page.getByText("Current signed-in role: pid", { exact: true }),
    ).toBeVisible();
    await page
      .getByLabel("Conversation ID", { exact: true })
      .fill(path.split("/").at(-1)!);
    await expect(
      page.getByRole("button", {
        name: "Open current conversation",
        exact: true,
      }),
    ).toBeEnabled();
    await page
      .getByRole("button", { name: "Open current conversation", exact: true })
      .click();
    await expect(
      page.getByRole("heading", {
        name: "Current authorized conversation",
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      page.getByLabel("Manual message", { exact: true }),
    ).toHaveValue(draft);
    expect(
      samples.every((sample) => sample.status === 200 && sample.recovered),
      "Every observed current authorization succeeds and the projection is recoverable",
    ).toBe(true);
    expect(
      failures,
      "No protected HTTP denial during the bounded normal observation",
    ).toHaveLength(0);
    writeFileSync(
      resolve(output, "stability-observations.json"),
      JSON.stringify({
        status: "passed",
        human_acceptance: false,
        browser_tls_verification: true,
        samples,
        failures,
        existing_conversation_reopened: true,
        draft_preserved_in_mounted_page: true,
        scope: `Bounded ${duration}-second observation, not capacity or arbitrary-crash recovery`,
      }),
      { mode: 0o600, flag: "wx" },
    );
  } finally {
    writeFileSync(
      resolve(output, "stability-final.json"),
      JSON.stringify({ samples, failures }),
      { mode: 0o600, flag: "wx" },
    );
    await context.close();
  }
});
