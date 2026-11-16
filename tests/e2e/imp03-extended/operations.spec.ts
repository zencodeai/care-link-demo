import { expect, test, type Page, type Request } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { evidenceDirectory, privateFile } from "../imp03/config";
import { manualMessages } from "../../../apps/web/src/manual/messages";
import { object, readExtendedConfig, text } from "./config";
import { checkpoint, login, ok, request, type Row } from "./helpers";
import { intake } from "./intake";

const lab = readExtendedConfig();
const output = evidenceDirectory();
const labels = manualMessages["en-CA"];
type Signals = {
  opened: number;
  errors: number;
  authority: number;
  sources: EventSource[];
};
type Sample = {
  group: "sequential" | "concurrent";
  index: number;
  status: number;
  duration_ms: number;
};
function publish(file: string, value: unknown) {
  writeFileSync(resolve(output, file), JSON.stringify(value, null, 2), {
    mode: 0o600,
    flag: "wx",
  });
}
async function receipt(file: string, binding: Row) {
  const path = resolve(output, file);
  await expect
    .poll(
      () => {
        if (!existsSync(path)) return false;
        privateFile(path);
        const value = object(JSON.parse(readFileSync(path, "utf8")) as unknown);
        return (
          Object.keys(value).length === Object.keys(binding).length &&
          Object.entries(binding).every(
            ([key, expected]) => value[key] === expected,
          )
        );
      },
      {
        timeout: 90_000,
        message:
          "Waiting for the exact operator shutdown/restart receipt: " + file,
      },
    )
    .toBe(true);
}
async function measure(
  page: Page,
  path: string,
  group: Sample["group"],
  index: number,
): Promise<Sample> {
  const value = await page.evaluate(async (path) => {
    const start = performance.now();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    let status: number;
    try {
      const response = await fetch(path, {
        cache: "no-store",
        signal: controller.signal,
      });
      status = response.status;
      await response.arrayBuffer();
    } catch {
      status = 0;
      // Return only a transport status; suppress URLs, cookies and private bodies.
    } finally {
      clearTimeout(timeout);
    }
    return {
      status,
      duration_ms: Math.round((performance.now() - start) * 1000) / 1000,
    };
  }, path);
  return { group, index, ...value };
}
async function revoked(page: Page, id: string | undefined) {
  if (!id) return null;
  const response = await request(page, "/v1/sessions/" + id);
  expect(
    [403, 404].includes(response.status),
    "Previously revoked conversation remains denied under current rights",
  ).toBe(true);
  return response.status;
}
async function signalCounts(page: Page) {
  return page.evaluate(() => {
    const state = (window as unknown as { g03Operations: Signals })
      .g03Operations;
    return {
      opened: state.opened,
      errors: state.errors,
      authority: state.authority,
      active: state.sources.filter(
        (source) => source.readyState === EventSource.OPEN,
      ).length,
    };
  });
}

test("G-03 protected measurements and scoped active-channel shutdown", async ({
  browser,
}) => {
  test.setTimeout(360_000);
  const previous = process.env.CARE_LINK_IMP03_REVOKED_SESSION;
  if (
    previous &&
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
      previous,
    )
  )
    throw new Error("Prior revoked session must be an exact synthetic UUID");
  const context = await browser.newContext({ ignoreHTTPSErrors: false });
  try {
    const page = await context.newPage();
    await page.addInitScript(() => {
      const Original = window.EventSource;
      const state: Signals = {
        opened: 0,
        errors: 0,
        authority: 0,
        sources: [],
      };
      (window as unknown as { g03Operations: Signals }).g03Operations = state;
      window.EventSource = class extends Original {
        constructor(url: string | URL, options?: EventSourceInit) {
          super(url, options);
          state.sources.push(this);
          this.addEventListener("open", () => {
            state.opened += 1;
          });
          this.addEventListener("error", () => {
            state.errors += 1;
          });
          for (const event of ["rights_changed", "resync_required"])
            this.addEventListener(event, () => {
              state.authority += 1;
            });
        }
      };
    });
    await login(page, lab, "pid", output);
    const { path } = await intake(page, lab, "en-CA", output);
    const samples: Sample[] = [];
    checkpoint(output, "protected_measurements");
    for (let index = 0; index < 10; index += 1)
      samples.push(await measure(page, path, "sequential", index));
    expect(
      samples[0]!.status,
      "First actual protected read succeeds before any fault",
    ).toBe(200);
    samples.push(
      ...(await Promise.all(
        Array.from({ length: 4 }, (_, index) =>
          measure(page, path, "concurrent", index),
        ),
      )),
    );
    for (const sample of samples) {
      expect(
        [200, 503].includes(sample.status),
        "Every measurement records protected success or explicit service-unavailable response",
      ).toBe(true);
      expect(
        Number.isFinite(sample.duration_ms) && sample.duration_ms >= 0,
        "Measurement uses finite browser monotonic time",
      ).toBe(true);
    }
    const revokedBefore = await revoked(page, previous);
    // Keep the actual React workspace active. No parking document, synthetic
    // response or injected stream is used in this shutdown observation.
    const pending = new Set<Request>();
    const relevant = (sent: Request) => {
      const url = new URL(sent.url());
      return (
        url.origin === lab.mainOrigin &&
        url.pathname.startsWith("/v1/") &&
        !url.pathname.endsWith("/events")
      );
    };
    page.on("request", (sent) => {
      if (relevant(sent)) pending.add(sent);
    });
    page.on("requestfinished", (sent) => pending.delete(sent));
    page.on("requestfailed", (sent) => pending.delete(sent));
    await page
      .getByLabel(labels.session, { exact: true })
      .fill(path.split("/").at(-1)!);
    await page.getByRole("button", { name: labels.open, exact: true }).click();
    await expect(
      page.getByRole("heading", { name: labels.conversation, exact: true }),
    ).toBeVisible();
    await expect
      .poll(async () => (await signalCounts(page)).active, {
        timeout: 15_000,
        message: "Actual product EventSource is open before shutdown",
      })
      .toBeGreaterThan(0);
    await expect(
      page.getByRole("button", { name: labels.check, exact: true }),
    ).toBeEnabled();
    await expect(
      page.getByRole("button", { name: labels.reconcile, exact: true }),
    ).toHaveCount(0);
    await expect
      .poll(() => pending.size, {
        message: "UI read/command requests complete before shutdown readiness",
      })
      .toBe(0);
    const before = await ok(page, path);
    expect(
      before.owner_id === null && before.service_phase !== "human_controlled",
      "Participant intake has no fabricated human owner/connection",
    ).toBe(true);
    await expect(
      page.getByText(labels.unconnected, { exact: true }),
    ).toBeVisible();
    await expect
      .poll(() => pending.size, {
        message: "Baseline protected read completed",
      })
      .toBe(0);
    await expect(
      page.getByRole("button", { name: labels.check, exact: true }),
    ).toBeEnabled();
    const signalsBefore = await signalCounts(page);
    const binding: Row = {
      session: "imp03-002",
      phase: "core-shutdown",
      nonce: randomUUID(),
      session_id: path.split("/").at(-1)!,
      principal_id: lab.accounts.pid,
      revision: text(before, "revision"),
    };
    checkpoint(output, "await_core_stop");
    publish("operations-ready.json", binding);
    await receipt("operations-stopped.json", binding);
    await expect
      .poll(async () => (await signalCounts(page)).errors, {
        timeout: 15_000,
        message: "Existing product stream observes actual core outage",
      })
      .toBeGreaterThan(signalsBefore.errors);
    await expect(
      page.getByRole("heading", { name: labels.conversation, exact: true }),
    ).toHaveCount(0);
    await expect(page.locator(".manual-messages")).toHaveCount(0);
    await expect(
      page.getByText(labels.unavailable, { exact: true }),
    ).toBeVisible();
    const outage = await request(page, path);
    expect(
      [0, 503].includes(outage.status),
      "Protected access cannot succeed while the exact core is stopped",
    ).toBe(true);
    const surfaces: { surface: string; status: number }[] = [];
    for (const [surface, url] of [
      ["help_shell", lab.helpOrigin + "/private-help"],
      ["static", lab.staticOrigin + "/fallback"],
    ]) {
      const independent = await context.newPage();
      try {
        const response = await independent.goto(url!, {
          waitUntil: "domcontentloaded",
        });
        expect(
          response?.status(),
          "Independent " +
            surface +
            " remains available with normal browser TLS",
        ).toBe(200);
        surfaces.push({ surface: surface!, status: response!.status() });
      } finally {
        await independent.close();
      }
    }
    const signalsStopped = await signalCounts(page);
    publish("operations-outage-observed.json", binding);
    checkpoint(output, "await_core_resume");
    await receipt("operations-resumed.json", binding);
    // The primary has restored the exact container; current server state and
    // the real UI must now re-establish access without inventing business state.
    const after = await ok(page, path);
    const retained = [
      "id",
      "revision",
      "service_phase",
      "owner_id",
      "control_epoch",
      "unresolved",
    ].every((field) => before[field] === after[field]);
    expect(
      retained,
      "Same conversation, revisions, unresolved status and ownership survive restart",
    ).toBe(true);
    const revokedAfter = await revoked(page, previous);
    await page.getByRole("button", { name: labels.check, exact: true }).click();
    await expect(
      page.getByText("Current signed-in role: pid", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: labels.check, exact: true }),
    ).toBeEnabled();
    await page
      .getByLabel(labels.session, { exact: true })
      .fill(text(after, "id"));
    await page.getByRole("button", { name: labels.open, exact: true }).click();
    await expect(
      page.getByRole("heading", { name: labels.conversation, exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText(labels.unconnected, { exact: true }),
    ).toBeVisible();
    await expect(page.getByText(labels.connected, { exact: true })).toHaveCount(
      0,
    );
    await expect(
      page.getByRole("button", { name: labels.check, exact: true }),
    ).toBeEnabled();
    await expect
      .poll(() => pending.size, {
        message: "Re-established UI reads completed",
      })
      .toBe(0);
    checkpoint(output, "passed");
    publish("observations.json", {
      session: "imp03-002",
      suite: "operations",
      status: "passed",
      human_acceptance: false,
      browser_tls_verification: true,
      protected_samples: samples,
      conditions: {
        sequential_reads: 10,
        concurrent_reads: 4,
        active_product_stream: true,
        duration_source:
          "Browser performance.now through complete response body",
        acceptance_thresholds: "none introduced",
      },
      unavailable_samples: samples.filter((sample) => sample.status === 503)
        .length,
      core_outage_protected_status: outage.status,
      independent_surfaces: surfaces,
      stream_before: signalsBefore,
      stream_stopped: signalsStopped,
      same_conversation_and_authority_state_retained: retained,
      revoked_session_continuity: previous
        ? { status: "passed", before: revokedBefore, after: revokedAfter }
        : {
            status: "not_run",
            reason: "No prior revoked session UUID supplied",
          },
      observations: [
        "actual_product_channel_outage",
        "private_ui_hidden_with_unavailable_state",
        "help_and_static_browser_tls_available",
        "same_conversation_reopened_without_fake_human_connection",
      ],
      limits: [
        "One active-channel supervised core stop/start after UI quiescence; no in-flight database commit or arbitrary crash claim.",
        "Four concurrent requests and fourteen samples describe observed behavior, not capacity/latency acceptance or an invented threshold.",
        "Independent help observation is shell availability, not authenticated help acceptance.",
      ],
    });
  } finally {
    await context.close();
  }
});
