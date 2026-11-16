import {
  expect,
  type APIResponse,
  type Page,
  type Request,
} from "@playwright/test";
import { object, type ExtendedConfig } from "./config";
import { closeStream, ok, request, type Row } from "./helpers";
import { takeover, type Worker } from "./ownership";

export async function bufferedReply(
  winner: Worker,
  supervisor: Page,
  lab: ExtendedConfig,
  path: string,
  message: Row,
  marker: string,
) {
  await closeStream(winner.page);
  const page = winner.page;
  let held: APIResponse | undefined;
  let intercepted: Request | undefined;
  let released = false;
  let fulfilled = false;
  let ready: (() => void) | undefined;
  let release: (() => void) | undefined;
  let done: (() => void) | undefined;
  const readyPromise = new Promise<void>((resolve) => {
    ready = resolve;
  });
  const releasePromise = new Promise<void>((resolve) => {
    release = resolve;
  });
  const donePromise = new Promise<void>((resolve) => {
    done = resolve;
  });
  const matches = (url: URL) =>
    url.origin === lab.mainOrigin &&
    url.pathname === path + "/messages" &&
    url.searchParams.get("limit") === "50";
  await page.route(matches, async (route) => {
    if (intercepted || route.request().method() !== "GET") {
      await route.continue();
      return;
    }
    intercepted = route.request();
    try {
      try {
        held = await route.fetch();
      } catch {
        throw new Error(
          "Actual buffered read failed; private call details suppressed",
        );
      }
      expect(
        held.status(),
        "Actual old-owner message read was authorized before takeover",
      ).toBe(200);
      const body = object((await held.json()) as unknown);
      expect(
        Array.isArray(body.items) &&
          body.items.some((item: unknown) => object(item).id === message.id),
        "Held response contains the real previously undisplayed message",
      ).toBe(true);
      ready?.();
      await releasePromise;
      released = true;
      try {
        await route.fulfill({ response: held });
        fulfilled = true;
      } catch {
        /* A correctly aborted browser request is checked separately below. */
      }
    } finally {
      done?.();
    }
  });
  await page.evaluate((marker) => {
    const state = window as unknown as {
      g03BufferedSeen: boolean;
      g03BufferedObserver?: MutationObserver;
    };
    state.g03BufferedSeen = false;
    state.g03BufferedObserver = new MutationObserver(() => {
      if (
        document
          .querySelector(".manual-messages")
          ?.textContent?.includes(marker)
      )
        state.g03BufferedSeen = true;
    });
    state.g03BufferedObserver.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
    });
  }, marker);
  try {
    await page
      .getByLabel("Conversation ID", { exact: true })
      .fill(path.split("/").at(-1)!);
    await page
      .getByRole("button", { name: "Open current conversation", exact: true })
      .click();
    await Promise.race([
      readyPromise,
      new Promise<never>((_, reject) =>
        setTimeout(
          () => reject(new Error("Actual buffered response was not held")),
          15_000,
        ),
      ),
    ]);
    const signalsBefore = await page.evaluate(
      () =>
        (window as unknown as { g03AuthoritySignals: number })
          .g03AuthoritySignals,
    );
    const taken = await takeover(supervisor, lab, path);
    const oldRead = await request(page, path);
    expect(
      [403, 404].includes(oldRead.status),
      "Old owner loses current read authority after takeover",
    ).toBe(true);
    await expect
      .poll(
        () =>
          page.evaluate(
            () =>
              (window as unknown as { g03AuthoritySignals: number })
                .g03AuthoritySignals,
          ),
        {
          message: "Actual old-owner stream reports authority loss",
          timeout: 15_000,
        },
      )
      .toBeGreaterThan(signalsBefore);
    release?.();
    await donePromise;
    await expect(
      page.getByRole("button", { name: "Check manual access", exact: true }),
    ).toBeEnabled();
    const cancelled =
      intercepted?.failure() !== null && intercepted?.failure() !== undefined;
    expect(
      released && (fulfilled || cancelled),
      "Held actual reply was released or the browser independently cancelled it",
    ).toBe(true);
    expect(
      await page.evaluate(
        () =>
          (window as unknown as { g03BufferedSeen: boolean }).g03BufferedSeen,
      ),
      "No previously buffered old-owner content becomes visible after observed authority loss",
    ).toBe(false);
    await expect(page.getByText(marker, { exact: true })).toHaveCount(0);
    const current = await ok(supervisor, path);
    expect(
      current.owner_id === lab.accounts.supervisor &&
        current.control_epoch === taken.control_epoch,
      "Buffered reply does not rewind actual server ownership",
    ).toBe(true);
    return {
      response_fulfilled: fulfilled,
      client_cancelled: cancelled,
      scope:
        "Real pre-takeover GET response held in browser transport; UI visibility after observed SSE authority loss. Not every server/OS-buffer race.",
    };
  } finally {
    release?.();
    await page.unroute(matches);
    await page.evaluate(() =>
      (
        window as unknown as { g03BufferedObserver?: MutationObserver }
      ).g03BufferedObserver?.disconnect(),
    );
  }
}
