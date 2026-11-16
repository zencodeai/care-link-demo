import { afterEach, expect, test, vi } from "vitest";
import { browserRequest, prepareBarrierMutation } from "../e2e/imp03/request";

// Mocked-fetch regression only: this proves harness behavior, not a live outage.
const path = "/v1/sessions/synthetic-session/human-request";
const body = { expected_revision: "1", reason: "user_requested" };
afterEach(() => {
  vi.unstubAllGlobals();
  delete (window as unknown as { g03BarrierProof?: unknown }).g03BarrierProof;
});

test("barrier mutation sends actual POST using proof obtained before identity loss", async () => {
  const fetch = vi
    .fn<typeof globalThis.fetch>()
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ csrf_token: "synthetic-proof" }), {
        status: 200,
      }),
    )
    .mockResolvedValue(new Response("{}", { status: 503 }));
  vi.stubGlobal("fetch", fetch);
  expect(await prepareBarrierMutation(path)).toBe(200);
  const result = await browserRequest({
    path,
    body,
    key: "synthetic-command",
    preparedMutation: true,
  });
  expect(result.status).toBe(503);
  expect(result.attempted).toEqual({ method: "POST", path });
  expect(fetch.mock.calls.map(([url]) => url)).toEqual(["/v1/auth/csrf", path]);
  expect(fetch.mock.calls[1]?.[1]).toMatchObject({
    method: "POST",
    body: JSON.stringify(body),
    headers: { "X-CSRF-Token": "synthetic-proof" },
  });
  await expect(
    browserRequest({ path, body, preparedMutation: true }),
  ).rejects.toThrow("Missing exact pre-barrier CSRF proof");
  expect(fetch).toHaveBeenCalledTimes(2);
});

test("failed bootstrap cannot be represented as an attempted mutation", async () => {
  const fetch = vi
    .fn<typeof globalThis.fetch>()
    .mockResolvedValue(new Response("{}", { status: 503 }));
  vi.stubGlobal("fetch", fetch);
  expect(await prepareBarrierMutation(path)).toBe(503);
  await expect(
    browserRequest({ path, body, preparedMutation: true }),
  ).rejects.toThrow("Missing exact pre-barrier CSRF proof");
  expect(fetch).toHaveBeenCalledTimes(1);
  const unprepared = await browserRequest({ path, body });
  expect(unprepared).toMatchObject({ status: 503, attempted: null });
  expect(fetch.mock.calls.map(([url]) => url)).toEqual([
    "/v1/auth/csrf",
    "/v1/auth/csrf",
  ]);
});

test("prepared proof cannot authorize a different target and is consumed on mismatch", async () => {
  const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValue(
    new Response(JSON.stringify({ csrf_token: "synthetic-proof" }), {
      status: 200,
    }),
  );
  vi.stubGlobal("fetch", fetch);
  expect(await prepareBarrierMutation(path)).toBe(200);
  await expect(
    browserRequest({
      path: "/v1/other-target",
      body,
      preparedMutation: true,
    }),
  ).rejects.toThrow("Missing exact pre-barrier CSRF proof");
  await expect(
    browserRequest({ path, body, preparedMutation: true }),
  ).rejects.toThrow("Missing exact pre-barrier CSRF proof");
  expect(fetch).toHaveBeenCalledTimes(1);
});
