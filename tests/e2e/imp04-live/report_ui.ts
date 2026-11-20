import { expect, type Request, type Response } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { textFor } from "../../../apps/web/src/plans/messages";
import { type Actor } from "./browser";
import { type Actors, type Observations } from "./cases";
import { evidenceDirectory, privateFile, row, text, type Row } from "./config";

interface SavedReport {
  slot: "carer" | "professional";
  session: string;
  report: string;
}
function uuid(raw: string): string {
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(raw)
  )
    throw new Error("Exact issued report/session UUID required");
  return raw;
}
function reportsFrom(directory: string): SavedReport[] {
  const file = resolve(directory, "sanitized-summary.json");
  privateFile(file);
  const source = row(JSON.parse(readFileSync(file, "utf8")) as unknown);
  if (!Array.isArray(source.observations))
    throw new Error("Actual prior report observations required");
  const records = source.observations.map(row);
  return (["carer", "professional"] as const).map((slot) => {
    const matches = records.filter(
      (record) =>
        record.case === "Q05/A01" &&
        record.slot === slot &&
        record.status === "passed",
    );
    if (matches.length !== 1)
      throw new Error(
        "One actual prior saved report per separately issued actor required",
      );
    const record = matches[0];
    if (!record) throw new Error("Missing actual report observation");
    return {
      slot,
      session: uuid(text(record, "session_id")),
      report: uuid(text(record, "report_id")),
    };
  });
}
async function requireOk(response: Response): Promise<void> {
  if (response.status() === 200) return;
  let key = "none";
  try {
    const error = row((await response.json()) as unknown);
    if (
      typeof error.message_key === "string" &&
      /^(manual|identity)\.[a-z_]+$/.test(error.message_key)
    )
      key = error.message_key;
  } catch {
    /* No error body or narrative is retained. */
  }
  throw new Error(
    `Actual report UI load denied; status=${response.status()}; message_key=${key}`,
  );
}
async function loadReport(actor: Actor, saved: SavedReport): Promise<Row[]> {
  await actor.ensureMain(true);
  const workspace = actor.page.locator(
    'section[aria-labelledby="plans-title"]',
  );
  const check = workspace.getByRole("button", {
    name: textFor("en-CA").check,
    exact: true,
  });
  const load = workspace.getByRole("button", {
    name: textFor("en-CA").loadSession,
    exact: true,
  });
  const path = `/v1/sessions/${saved.session}`;
  const network: Row[] = [];
  const paths = ["/v1/auth/session", path, path + "/own-reports"];
  const pathOf = (raw: string): string | null => {
    try {
      const url = new URL(raw);
      return url.origin === actor.config.mainOrigin &&
        paths.includes(url.pathname)
        ? url.pathname
        : null;
    } catch {
      return null;
    }
  };
  const requested = (request: Request): void => {
    const path = pathOf(request.url());
    if (path) network.push({ event: "request", path, at_ms: Date.now() });
  };
  const failed = (request: Request): void => {
    const path = pathOf(request.url());
    if (!path) return;
    const error = request.failure()?.errorText ?? "unknown";
    const allowed = [
      "net::ERR_ABORTED",
      "net::ERR_BLOCKED_BY_CLIENT",
      "net::ERR_BLOCKED_BY_CSP",
      "net::ERR_CONNECTION_CLOSED",
      "net::ERR_CONNECTION_RESET",
      "net::ERR_TIMED_OUT",
      "net::ERR_FAILED",
      "net::ERR_INSUFFICIENT_RESOURCES",
    ];
    network.push({
      event: "requestfailed",
      path,
      at_ms: Date.now(),
      category: allowed.includes(error) ? error : "other_network_failure",
    });
  };
  const record = (response: Response): void => {
    const url = new URL(response.url());
    if (
      url.origin === actor.config.mainOrigin &&
      ["/v1/auth/session", path, path + "/own-reports"].includes(url.pathname)
    )
      network.push({
        event: "response",
        path: url.pathname,
        status: response.status(),
        at_ms: Date.now(),
      });
  };
  const reply = (target: string) =>
    actor.page.waitForResponse(
      (response) =>
        response.url() === actor.config.mainOrigin + target &&
        response.request().method() === "GET",
    );
  const idle = async (): Promise<void> => {
    await expect(check).toBeEnabled();
    await expect(
      workspace
        .locator(':scope > [role="status"], :scope > [role="alert"]')
        .first(),
    ).toHaveText(textFor("en-CA").ready);
  };
  actor.page.on("response", record);
  actor.page.on("request", requested);
  actor.page.on("requestfailed", failed);
  try {
    const identity = reply("/v1/auth/session");
    await check.click();
    await requireOk(await identity);
    await idle();
    await actor.page.locator("#plans-session").fill(saved.session);
    await expect(load).toBeEnabled();
    const conversation = reply(path),
      ownReports = reply(path + "/own-reports");
    await load.click();
    await requireOk(await conversation);
    const response = await ownReports;
    await requireOk(response);
    await idle();
    await expect(
      workspace.getByText(saved.session, { exact: true }),
    ).toBeVisible();
    const page = row((await response.json()) as unknown);
    if (!Array.isArray(page.items))
      throw new Error("Missing actual saved report projection");
    return page.items.map(row);
  } catch {
    const actual = await workspace
      .locator(':scope > [role="status"], :scope > [role="alert"]')
      .first()
      .textContent()
      .catch(() => null);
    const known = [
      "ready",
      "pending",
      "committed",
      "rejected",
      "unavailable",
      "signed_out",
      "invalid",
      "operationUnknown",
    ] as const;
    const diagnostic = {
      slot: actor.slot,
      network: network.slice(-20),
      notice:
        known.find((name) => actual === textFor("en-CA")[name]) ??
        "other_or_unavailable",
      check_disabled: await check.isDisabled().catch(() => null),
      load_disabled: await load.isDisabled().catch(() => null),
      document_policy: actor.documentPolicy,
      document_and_timing: await actor.page
        .evaluate(() => ({
          origin: location.origin,
          path: location.pathname,
          meta_policy_count: document.querySelectorAll(
            'meta[http-equiv="Content-Security-Policy"]',
          ).length,
          requests: performance
            .getEntriesByType("resource")
            .filter((entry) => {
              try {
                return ["/v1/auth/session", "/v1/auth/csrf"].includes(
                  new URL(entry.name).pathname,
                );
              } catch {
                return false;
              }
            })
            .slice(-12)
            .map((entry) => ({
              path: new URL(entry.name).pathname,
              duration_ms: Math.round(entry.duration),
              initiator: (entry as PerformanceResourceTiming).initiatorType,
            })),
        }))
        .catch(() => null),
    };
    writeFileSync(
      resolve(evidenceDirectory(), `report-ui-${actor.slot}-diagnostic.json`),
      JSON.stringify(diagnostic, null, 2),
      { mode: 0o600 },
    );
    throw new Error(
      `Actual report UI loading failed; safe diagnostic=${JSON.stringify(diagnostic)}`,
    );
  } finally {
    actor.page.off("response", record);
    actor.page.off("request", requested);
    actor.page.off("requestfailed", failed);
  }
}
function words(report: Row): string {
  const value = row(report.value);
  if (value.kind !== "text")
    throw new Error("Expected actual fictional saved text report");
  return text(value, "text");
}
export async function reportUi(
  actors: Actors,
  observations: Observations,
  stateRoot: string,
): Promise<void> {
  const saved = reportsFrom(
    process.env.CARE_LINK_IMP04_E2E_REPORT_STATE ?? stateRoot,
  );
  if (
    new Set(saved.map((item) => item.report)).size !== 2 ||
    new Set(saved.map((item) => item.session)).size !== 2
  )
    throw new Error("Separate prior report/session bindings required");
  const returned = new Map<string, Row[]>();
  for (const item of saved)
    returned.set(
      item.slot,
      await actors[item.slot]
        .ok(`/v1/sessions/${item.session}/own-reports`)
        .then((page) => {
          if (!Array.isArray(page.items))
            throw new Error("Missing actual saved own reports");
          return page.items.map(row);
        }),
    );
  for (const item of saved) {
    const actor = actors[item.slot],
      other = saved.find((candidate) => candidate.slot !== item.slot);
    if (!other) throw new Error("Other actor report binding missing");
    const otherReport = returned
      .get(other.slot)
      ?.find((report) => report.id === other.report);
    if (!otherReport)
      throw new Error(
        "Other actual saved report missing from its owner-scoped response",
      );
    for (const afterReload of [false, true]) {
      if (afterReload)
        await actor.page.reload({ waitUntil: "domcontentloaded" });
      const reports = await loadReport(actor, item);
      expect(
        reports.every((report) => report.author_id === actor.issued.accountId),
      ).toBe(true);
      expect(reports.some((report) => report.id === other.report)).toBe(false);
      const own = reports.find((report) => report.id === item.report);
      if (!own)
        throw new Error(
          "Exact prior saved report absent from actual authorized response",
        );
      const form = actor.page
        .locator('section[aria-labelledby="plans-title"] form')
        .filter({
          has: actor.page.getByRole("heading", {
            name: textFor("en-CA").report,
            exact: true,
          }),
        });
      await expect(
        form.getByRole("heading", {
          name: textFor("en-CA").ownReports,
          exact: true,
        }),
      ).toBeVisible();
      const ownRow = form
        .locator("li")
        .filter({ has: actor.page.getByText(words(own), { exact: true }) });
      await expect(ownRow).toHaveCount(1);
      await expect(
        ownRow.getByText(actor.issued.accountId, { exact: true }),
      ).toBeVisible();
      await expect(
        form.getByText(actors[other.slot].issued.accountId, { exact: true }),
      ).toHaveCount(0);
      await expect(
        form.getByText(words(otherReport), { exact: true }),
      ).toHaveCount(0);
      observations.push({
        case: "Q05-report-ui",
        slot: item.slot,
        status: "passed",
        session_id: item.session,
        report_id: item.report,
        author_id: actor.issued.accountId,
        after_native_reload: afterReload,
        manually_reselected_session: true,
        exact_response_id_to_visible_row_mapping: true,
        report_id_visible: false,
        report_id_display_limit:
          "Current product uses report ID as React key, not rendered text",
        other_actor_response_id_and_visible_report_absent: true,
        no_new_report_or_grant_command: true,
      });
    }
  }
}
