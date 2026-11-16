import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { browserRequest, prepareBarrierMutation } from "../imp03/request";
import { evidenceDirectory, privateFile } from "../imp03/config";
import { object, readExtendedConfig } from "./config";
import { checkpoint, login, ok, park, request } from "./helpers";
import { intake } from "./intake";

const lab = readExtendedConfig();
const output = evidenceDirectory();
test("G-03 actual committed database acknowledgement loss", async ({
  browser,
}) => {
  const context = await browser.newContext({ ignoreHTTPSErrors: false });
  try {
    const page = await context.newPage();
    await login(page, lab, "pid", output);
    const { path } = await intake(page, lab, "en-CA", output);
    await park(page, lab.mainOrigin);
    const current = await ok(page, path);
    const target = path + "/human-request";
    expect(await page.evaluate(prepareBarrierMutation, target)).toBe(200);
    const key = randomUUID();
    const ready = {
      session: "imp03-002",
      phase: "database-ack-loss",
      nonce: randomUUID(),
      session_id: path.split("/").at(-1)!,
      principal_id: lab.accounts.pid,
      operation_id: key,
    };
    writeFileSync(resolve(output, "commit-ready.json"), JSON.stringify(ready), {
      mode: 0o600,
      flag: "wx",
    });
    checkpoint(output, "await_real_database_ack_fault");
    const applied = resolve(output, "commit-applied.json");
    await expect
      .poll(
        () => {
          if (!existsSync(applied)) return false;
          privateFile(applied);
          const value = object(
            JSON.parse(readFileSync(applied, "utf8")) as unknown,
          );
          return (
            Object.keys(value).length === Object.keys(ready).length &&
            Object.entries(ready).every(
              ([name, field]) => value[name] === field,
            )
          );
        },
        { timeout: 120_000 },
      )
      .toBe(true);
    const body = {
      expected_revision: current.revision,
      reason: "user_requested",
    };
    const sent = page.waitForRequest(
      (r) =>
        r.method() === "POST" &&
        r.url() === lab.mainOrigin + target &&
        r.headers()["idempotency-key"] === key,
    );
    const [lost] = await Promise.all([
      page.evaluate(browserRequest, {
        path: target,
        body,
        key,
        preparedMutation: true,
      }),
      sent,
    ]);
    expect(
      lost.status,
      "Actual committed driver acknowledgement loss returns unknown",
    ).toBe(503);
    expect(object(lost.value).code).toBe("COMMIT_UNKNOWN");
    const status = await ok(page, "/v1/operations/" + key);
    expect(status.state).toBe("committed");
    const replay = await request(page, target, body, key);
    expect(
      replay.status,
      "Original key reconciles the one real committed queue effect",
    ).toBe(200);
    const queue = object(replay.value);
    writeFileSync(
      resolve(output, "commit-binding.json"),
      JSON.stringify({
        ...ready,
        queue_id: queue.ticket_id,
      }),
      { mode: 0o600, flag: "wx" },
    );
    writeFileSync(
      resolve(output, "observations.json"),
      JSON.stringify(
        {
          session: "imp03-002",
          suite: "database-ack-loss",
          status: "passed",
          actual_post_status: lost.status,
          original_key_state: status.state,
          replay_status: replay.status,
          browser_tls_verification: true,
          observations: [
            "actual_driver_error_after_real_database_commit",
            "original_key_reconciliation",
          ],
          human_acceptance: false,
          limits: [
            "Exact one-shot queue commit boundary; durable counts are separately verified by operator.",
          ],
        },
        null,
        2,
      ),
      { mode: 0o600, flag: "wx" },
    );
    checkpoint(output, "passed");
  } finally {
    await context.close();
  }
});
