import { expect, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { privateFile } from "../imp03/config";
import { browserRequest, prepareBarrierMutation } from "../imp03/request";
import { object, type ExtendedConfig } from "./config";
import { ok, park, request, stream, type Row } from "./helpers";

export async function revokeAcl(
  page: Page,
  lab: ExtendedConfig,
  path: string,
  output: string,
) {
  const current = await ok(page, path);
  await stream(page, path.split("/").at(-1)!);
  const mutationPath = path + "/human-request";
  expect(
    await page.evaluate(prepareBarrierMutation, mutationPath),
    "Current CSRF is acquired before the operator's actual ACL restriction",
  ).toBe(200);
  const baseline = await page.evaluate(
    () =>
      (window as unknown as { g03AuthoritySignals: number })
        .g03AuthoritySignals,
  );
  const ready: Row = {
    session: "imp03-002",
    phase: "acl-revocation",
    nonce: randomUUID(),
    session_id: path.split("/").at(-1)!,
    principal_id: lab.accounts.pid,
  };
  writeFileSync(
    resolve(output, "extended-revocation-ready.json"),
    JSON.stringify(ready),
    { mode: 0o600, flag: "wx" },
  );
  const applied = resolve(output, "extended-revocation-applied.json");
  await expect
    .poll(
      () => {
        if (!existsSync(applied)) return false;
        privateFile(applied);
        const receipt = object(
          JSON.parse(readFileSync(applied, "utf8")) as unknown,
        );
        return (
          Object.keys(receipt).length === Object.keys(ready).length &&
          Object.entries(ready).every(([key, value]) => receipt[key] === value)
        );
      },
      {
        timeout: 120_000,
        message: "Waiting for exact operator-applied current ACL restriction",
      },
    )
    .toBe(true);
  const denied = await request(page, path);
  expect(
    [403, 404].includes(denied.status),
    "Existing participant session loses current disclosure scope",
  ).toBe(true);
  const key = randomUUID();
  const observed = page.waitForRequest(
    (sent) =>
      sent.method() === "POST" &&
      sent.url() === lab.mainOrigin + mutationPath &&
      sent.headers()["idempotency-key"] === key,
  );
  const [mutation] = await Promise.all([
    page.evaluate(browserRequest, {
      path: mutationPath,
      body: { expected_revision: current.revision, reason: "user_requested" },
      key,
      preparedMutation: true,
    }),
    observed,
  ]);
  expect(
    mutation.attempted?.method === "POST" &&
      mutation.attempted.path === mutationPath,
    "Revocation denial belongs to the actual intended POST",
  ).toBe(true);
  expect(
    [403, 404].includes(mutation.status),
    "Current ACL restriction denies the actual mutation",
  ).toBe(true);
  await expect
    .poll(
      () =>
        page.evaluate(
          () =>
            (window as unknown as { g03AuthoritySignals: number })
              .g03AuthoritySignals,
        ),
      { message: "Already open stream observes scope loss", timeout: 15_000 },
    )
    .toBeGreaterThan(baseline);
  const fresh = await page.context().newPage();
  try {
    await park(fresh, lab.mainOrigin);
    const next = await request(fresh, path + "/messages");
    expect(
      [403, 404].includes(next.status),
      "Fresh page cannot reuse earlier disclosure authority",
    ).toBe(true);
  } finally {
    await fresh.close();
  }
  return {
    method: "POST",
    path: mutationPath,
    read_status: denied.status,
    mutation_status: mutation.status,
    scope:
      "Operator-applied exact participant/session support ACL revocation; existing cookie/channel and fresh-page reads revalidate. No broader identity-account revocation claim.",
  };
}
