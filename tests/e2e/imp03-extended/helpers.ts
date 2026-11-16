import { expect, type Page } from "@playwright/test";
import { resolve } from "node:path";
import { writeFileSync } from "node:fs";
import { providerLogin } from "../imp02/browser";
import { browserRequest } from "../imp03/request";
import { object, type ActorName, type ExtendedConfig } from "./config";

export type Row = Record<string, unknown>;
export function checkpoint(output: string, stage: string) {
  writeFileSync(resolve(output, "progress.json"), JSON.stringify({ stage }), {
    mode: 0o600,
  });
}
export async function request(
  page: Page,
  path: string,
  body?: Row,
  key?: string,
) {
  return page.evaluate(browserRequest, { path, body, key });
}
export async function ok(page: Page, path: string, body?: Row, key?: string) {
  const response = await request(page, path, body, key);
  const value = object(response.value ?? {});
  const reason =
    typeof value.message_key === "string" &&
    /^manual\.[a-z_]+$/.test(value.message_key)
      ? value.message_key
      : "private_body_suppressed";
  expect(
    response.status,
    `Actual protected request succeeds: ${path.split("?")[0]} (${reason})`,
  ).toBe(200);
  return value;
}
export async function login(
  page: Page,
  lab: ExtendedConfig,
  who: ActorName,
  output: string,
) {
  const role = who === "worker2" ? "worker" : who;
  checkpoint(output, who + "_shell");
  await page.goto(lab.mainOrigin, { waitUntil: "domcontentloaded" });
  const account = page.getByRole("region", {
    name: "Main account",
    exact: true,
  });
  await account
    .getByLabel("Requested sign-in role", { exact: true })
    .selectOption(role);
  const signIn = account.getByRole("button", { name: "Sign in", exact: true });
  await expect(
    signIn,
    "Deployed UI has its approved provider origin",
  ).toBeEnabled();
  checkpoint(output, who + "_provider");
  const diagnostic: Row[] = [];
  page.on("response", async (response) => {
    const path = new URL(response.url()).pathname;
    if (!["/v1/auth/csrf", "/v1/auth/login"].includes(path)) return;
    const value: Row = { path, status: response.status() };
    try {
      const body = object((await response.json()) as unknown);
      value.fields = Object.keys(body).sort();
      value.error_key =
        typeof body.message_key === "string" ? body.message_key : null;
      value.csrf_length =
        typeof body.csrf_token === "string" ? body.csrf_token.length : null;
      value.expires_in_future =
        typeof body.expires_at === "string"
          ? Date.parse(body.expires_at) > Date.now()
          : null;
    } catch {
      value.body = "suppressed";
    }
    diagnostic.push(value);
  });
  await signIn.click();
  try {
    await expect
      .poll(() => new URL(page.url()).origin, {
        message: "Visible UI sign-in navigates only to the approved provider",
      })
      .toBe(lab.oidcOrigin);
  } catch (error) {
    writeFileSync(
      resolve(output, who + "-signin-diagnostic.json"),
      JSON.stringify(diagnostic),
      { mode: 0o600, flag: "wx" },
    );
    throw error;
  }
  await providerLogin(
    page,
    lab,
    who === "pid" ? lab.participant : lab[who],
    lab.mainOrigin,
  );
  const actor = await ok(page, "/v1/auth/session");
  expect(
    actor.role === role && actor.account_id === lab.accounts[who],
    "Actual provider resolves the exact separately issued account/role",
  ).toBe(true);
  await page
    .getByRole("button", { name: "Check manual access", exact: true })
    .click();
  await expect(
    page.getByText(`Current signed-in role: ${role}`, { exact: true }),
  ).toBeVisible();
  checkpoint(output, who + "_signed_in");
}
export async function park(page: Page, origin: string) {
  await page.route("**/assets/*.js", (route) => route.abort("blockedbyclient"));
  await page.goto(origin, { waitUntil: "domcontentloaded" });
}
export async function stream(page: Page, session: string) {
  await page.evaluate(async (session) => {
    const state = window as unknown as { g03Stream?: EventSource };
    state.g03Stream?.close();
    await new Promise<void>((resolve, reject) => {
      const source = new EventSource(`/v1/sessions/${session}/events`);
      state.g03Stream = source;
      const deadline = setTimeout(() => {
        source.close();
        reject(new Error("Actual SSE did not open"));
      }, 15_000);
      source.onopen = () => {
        clearTimeout(deadline);
        resolve();
      };
      source.onerror = () => {
        clearTimeout(deadline);
        source.close();
        reject(new Error("Actual SSE denied"));
      };
    });
  }, session);
}
export async function closeStream(page: Page) {
  await page.evaluate(() =>
    (window as unknown as { g03Stream?: EventSource }).g03Stream?.close(),
  );
}
// Observe real EventSource authority/error signals; no event is synthesized.
export async function observeSignals(page: Page) {
  await page.addInitScript(() => {
    const Original = window.EventSource;
    const state = window as unknown as { g03AuthoritySignals: number };
    state.g03AuthoritySignals = 0;
    window.EventSource = class extends Original {
      constructor(url: string | URL, options?: EventSourceInit) {
        super(url, options);
        for (const event of ["resync_required", "rights_changed", "error"])
          this.addEventListener(event, () => {
            state.g03AuthoritySignals += 1;
          });
      }
    };
  });
}
