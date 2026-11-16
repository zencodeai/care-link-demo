import { expect } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { disclosures } from "../../../apps/web/src/manual/disclosures";
import { ActorPage, words } from "./browser";
import { text } from "./config";

export async function createConversation(participant: ActorPage) {
  await expect(
    participant.button(words.create),
    "Fresh run has no inherited conversation",
  ).toBeEnabled();
  const result = await participant.postUI("/v1/sessions", () =>
    participant.button(words.create).click(),
  );
  const id = text(result, "id");
  await expect(participant.conversation()).toBeVisible();
  await expect(participant.conversation().locator("code").first()).toHaveText(
    id,
  );
  return id;
}
export async function disclosureAndIntake(participant: ActorPage, id: string) {
  await expect(
    participant.page.getByText(disclosures["en-CA"].text, { exact: true }),
  ).toBeVisible();
  await expect(participant.button(words.turn)).toBeDisabled();
  await participant.postUI(`/v1/sessions/${id}/disclosure`, () =>
    participant.button(words.acknowledge).click(),
  );
  await expect(
    participant.page.getByText(words.acknowledged, { exact: true }),
  ).toBeVisible();
  // The current deterministic intake may itself queue an unknown fixture. Make
  // the participant's explicit visible request while the conversation is active.
  await participant.postUI(`/v1/sessions/${id}/human-request`, () =>
    participant.button(words.human).click(),
  );
  await expect(
    participant.conversation().getByText(words.unconnected, { exact: true }),
  ).toBeVisible();
  await participant.postUI(`/v1/sessions/${id}/turns`, () =>
    participant.button(words.turn).click(),
  );
  await expect(
    participant.page.getByText(words.submitted, { exact: true }),
  ).toBeVisible();
}
export async function reserveAndAccept(worker: ActorPage, id: string) {
  await worker.button(words.loadQueue).click();
  const queueItem = worker.page
    .locator(".manual-queue > li")
    .filter({ hasText: id });
  await expect(queueItem).toHaveCount(1);
  await worker.postUI(`/v1/sessions/${id}/workforce/reserve`, () =>
    queueItem.getByRole("button", { name: words.reserve, exact: true }).click(),
  );
  await expect(worker.button(words.accept)).toBeEnabled();
  await worker.postUI(`/v1/sessions/${id}/workforce/accept`, () =>
    worker.button(words.accept).click(),
  );
  await expect(
    worker.page.getByText(words.accepted, { exact: true }),
  ).toBeVisible();
  await worker.reloadAndClaim();
  await expect(
    worker.page.getByText(words.accepted, { exact: true }),
  ).toBeVisible();
  await expect(worker.conversation()).toBeVisible();
  await expect(
    worker.conversation().getByText(words.unconnected, { exact: true }),
  ).toBeVisible();
}
export async function handshake(
  participant: ActorPage,
  worker: ActorPage,
  id: string,
  expireFirst: boolean,
) {
  const path = `/v1/sessions/${id}/workforce/prepare-transfer`;
  const first = await worker.postUI(path, () =>
    worker.button(words.prepare).click(),
  );
  if (expireFirst) {
    await expect(
      worker.page.getByText(words.expired, { exact: true }),
      "Actual 30-second challenge expires without a synthetic clock",
    ).toBeVisible({ timeout: 38_000 });
    await expect(worker.button(words.challenge)).toBeDisabled();
    const replacement = await worker.postUI(path, () =>
      worker.button(words.prepare).click(),
    );
    expect(
      replacement.challenge_id !== first.challenge_id,
      "Explicit fresh preparation replaces the expired challenge",
    ).toBe(true);
  }
  await expect(participant.button(words.challenge)).toBeEnabled();
  await participant.postUI(`/v1/sessions/${id}/workforce/channel-acks`, () =>
    participant.button(words.challenge).click(),
  );
  await expect(
    participant.page.getByText(words.waitOther, { exact: false }),
  ).toBeVisible();
  await expect(worker.button(words.challenge)).toBeEnabled();
  await worker.postUI(`/v1/sessions/${id}/workforce/channel-acks`, () =>
    worker.button(words.challenge).click(),
  );
  await expect(worker.button(words.confirm)).toBeEnabled();
  await worker.postUI(`/v1/sessions/${id}/workforce/confirm-transfer`, () =>
    worker.button(words.confirm).click(),
  );
  await expect(
    worker.conversation().getByText(words.connected, { exact: true }),
  ).toBeVisible();
  await expect(
    participant.conversation().getByText(words.connected, { exact: true }),
  ).toBeVisible();
}
export async function sendMessage(
  sender: ActorPage,
  receiver: ActorPage,
  id: string,
  description: string,
) {
  const marker = `Fictional ${description} ${randomUUID()}.`;
  await sender.page.getByLabel(words.message, { exact: true }).fill(marker);
  await expect(sender.page.locator("#review-message-saved")).toHaveText(
    words.saved,
  );
  const value = await sender.postUI(`/v1/sessions/${id}/messages`, () =>
    sender.button(words.send).click(),
  );
  await expect(
    sender.page.locator(".manual-message-text").filter({ hasText: marker }),
  ).toHaveCount(1);
  await expect(
    receiver.page.locator(".manual-message-text").filter({ hasText: marker }),
  ).toHaveCount(1);
  expect(
    value.sender_id === sender.actor.account &&
      value.kind ===
        (sender.actor.role === "pid" ? "participant" : "human_authored"),
    "Visible message retains exact human attribution",
  ).toBe(true);
  return { marker, messageId: text(value, "id") };
}
export async function supervisorTakeover(
  supervisor: ActorPage,
  oldWorker: ActorPage,
  participant: ActorPage,
  id: string,
) {
  await supervisor.button(words.loadQueue).click();
  let item = supervisor.page
    .locator(".manual-queue > li")
    .filter({ hasText: id });
  await supervisor.postUI(`/v1/sessions/${id}/workforce/observe`, () =>
    item.getByRole("button", { name: words.observe, exact: true }).click(),
  );
  await expect(
    supervisor.page.getByText(words.observed, { exact: true }),
  ).toBeVisible();
  await expect(supervisor.button(words.takeover)).toHaveCount(0);
  item = supervisor.page.locator(".manual-queue > li").filter({ hasText: id });
  await item
    .getByRole("button", { name: words.prepareInterrupt, exact: true })
    .click();
  await item
    .getByRole("checkbox", { name: words.interrupt, exact: true })
    .check();
  await supervisor.postUI(`/v1/sessions/${id}/workforce/observe`, () =>
    item
      .getByRole("button", { name: words.confirmInterrupt, exact: true })
      .click(),
  );
  await supervisor.reloadAndClaim();
  await expect(
    supervisor.button(words.takeover),
    "Current interrupt grant is recovered after reload",
  ).toBeEnabled();
  const result = await supervisor.postUI(
    `/v1/sessions/${id}/workforce/takeover`,
    () => supervisor.button(words.takeover).click(),
  );
  expect(
    result.owner_id === supervisor.actor.account &&
      result.service_phase === "worker_assigned",
    "Takeover changes the actual owner and requires new channel confirmation",
  ).toBe(true);
  await expect(
    supervisor.conversation().getByText(words.unconnected, { exact: true }),
  ).toBeVisible();
  await expect(
    participant.conversation().getByText(words.unconnected, { exact: true }),
  ).toBeVisible();
  await expect(
    oldWorker.page.getByLabel(words.message, { exact: true }),
  ).toBeDisabled();
  const denied = await oldWorker.api(`/v1/sessions/${id}/messages`, {
    expected_revision: result.revision,
    expected_control_epoch: result.control_epoch,
    text: "Fictional forbidden old-owner response.",
    accepted_draft_id: null,
  });
  expect(
    [403, 404, 409].includes(denied.status),
    "Old owner cannot write through a direct API after takeover",
  ).toBe(true);
  return result;
}
