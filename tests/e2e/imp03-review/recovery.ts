import { expect, type APIResponse } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { ActorPage, words } from "./browser";
import { row, text } from "./config";
import { signOutIsolated } from "./auth";
import type { Toolkit } from "./toolkit";

export async function draftRecovery(
  participant: ActorPage,
  others: ActorPage[],
  toolkit: Toolkit,
) {
  const marker = `Fictional saved intake ${randomUUID()}.`;
  await participant.page.getByLabel(words.story, { exact: true }).fill(marker);
  await expect(participant.page.locator("#review-intake-saved")).toHaveText(
    words.saved,
  );
  await participant.reloadAndClaim();
  await expect(
    participant.page.getByLabel(words.story, { exact: true }),
  ).toHaveValue(marker);
  await signOutIsolated(participant, others, toolkit);
  await expect(
    participant.page.getByLabel(words.story, { exact: true }),
  ).toHaveValue(marker);
  return marker;
}
export async function duplicateTab(actor: ActorPage) {
  const duplicate = new ActorPage(
    await actor.page.context().newPage(),
    actor.actor,
    actor.runId,
  );
  try {
    await duplicate.page.goto(actor.page.url(), {
      waitUntil: "domcontentloaded",
    });
    await duplicate.assertVisibleIdentity();
    await expect(
      duplicate.page.getByText(words.observer, { exact: true }),
    ).toBeVisible();
    await expect(
      duplicate.page.getByLabel(words.story, { exact: true }),
    ).toBeDisabled();
    await duplicate.button(words.claim).click();
    await expect(
      duplicate.page.getByLabel(words.story, { exact: true }),
    ).toBeEnabled();
    await expect(
      actor.page.getByText(words.observer, { exact: true }),
    ).toBeVisible();
    await expect(
      actor.page.getByLabel(words.story, { exact: true }),
    ).toBeDisabled();
    await actor.button(words.claim).click();
    await expect(
      actor.page.getByLabel(words.story, { exact: true }),
    ).toBeEnabled();
    await expect(
      duplicate.page.getByText(words.observer, { exact: true }),
    ).toBeVisible();
    const denied = await duplicate.api(
      "/v1/review/sessions/" + (await actor.sessionId()) + "/draft",
      {
        kind: "intake",
        text: "Fictional observer must not overwrite this draft.",
        expected_revision: "0",
      },
    );
    expect(denied.status, "Observer cannot mutate through a direct API").toBe(
      409,
    );
  } finally {
    await duplicate.page.close();
  }
}
export async function unknownReply(
  sender: ActorPage,
  receiver: ActorPage,
  id: string,
) {
  const marker = `Fictional committed acknowledgement loss ${randomUUID()}.`;
  const path = `/v1/sessions/${id}/messages`;
  await sender.page.getByLabel(words.message, { exact: true }).fill(marker);
  await expect(sender.page.locator("#review-message-saved")).toHaveText(
    words.saved,
  );
  let key = "",
    messageId = "",
    committed: APIResponse | undefined;
  const matches = (url: URL) =>
    url.origin === sender.actor.origin && url.pathname === path;
  let resolveCommit: (() => void) | undefined;
  const commit = new Promise<void>((resolve) => {
    resolveCommit = resolve;
  });
  await sender.page.route(matches, async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    key = route.request().headers()["idempotency-key"] ?? "";
    try {
      committed = await route.fetch();
    } catch {
      throw new Error(
        "Actual commit request failed; private request details suppressed",
      );
    }
    expect(
      committed.status(),
      "Server commits before the real HTTP reply is dropped",
    ).toBe(200);
    const value = row((await committed.json()) as unknown);
    messageId = text(value, "id");
    expect(
      value.sender_id === sender.actor.account,
      "Dropped reply belongs to the actual actor",
    ).toBe(true);
    await route.abort("failed");
    resolveCommit?.();
  });
  try {
    await sender.button(words.send).click();
    await Promise.race([
      commit,
      new Promise<never>((_, reject) =>
        setTimeout(
          () => reject(new Error("Actual commit reply was not observed")),
          20_000,
        ),
      ),
    ]);
  } finally {
    await sender.page.unroute(matches);
  }
  expect(
    /^[0-9a-f-]{36}$/.test(key),
    "Actual UI used a stable operation UUID",
  ).toBe(true);
  await sender.reloadAndClaim();
  const result = await sender.api("/v1/operations/" + key);
  expect(
    result.status,
    "Original operation is recoverable after full reload",
  ).toBe(200);
  expect(row(result.value).state, "Original operation committed once").toBe(
    "committed",
  );
  const messages = await sender.api(path + "?limit=50");
  expect(messages.status).toBe(200);
  const items = row(messages.value).items;
  expect(
    Array.isArray(items) &&
      items.filter((item: unknown) => row(item).id === messageId).length === 1,
    "The actual projection contains exactly one logical message effect",
  ).toBe(true);
  await expect(
    sender.page.locator(".manual-message-text").filter({ hasText: marker }),
  ).toHaveCount(1);
  await expect(
    receiver.page.locator(".manual-message-text").filter({ hasText: marker }),
  ).toHaveCount(1);
  await expect(
    sender.page.getByLabel(words.message, { exact: true }),
  ).toHaveValue("");
  return {
    operation_id: key,
    message_id: messageId,
    state: "committed",
    projected_effect_count: 1,
  };
}
