import { expect, type Locator, type Page } from "@playwright/test";
import { labels } from "../../../apps/web/src/review/labels";
import { row, text, type Row } from "./config";
import type { ActorBinding } from "./toolkit";
export const words = labels("en-CA");
export interface Result {
  status: number;
  value: unknown;
}
export class ActorPage {
  view: string | null = null;
  constructor(
    readonly page: Page,
    readonly actor: ActorBinding,
    readonly runId: string,
  ) {
    page.on("request", (sent) => {
      if (new URL(sent.url()).origin === actor.origin) {
        const view = sent.headers()["x-review-view"];
        if (view) this.view = view;
      }
    });
  }
  button(name: string): Locator {
    return this.page.getByRole("button", { name, exact: true });
  }
  conversation(): Locator {
    return this.page.locator(
      'section[aria-labelledby="review-conversation-title"]',
    );
  }
  async api(path: string, body?: Row, key?: string): Promise<Result> {
    return this.page.evaluate(
      async ({ path, body, key, view, origin }) => {
        if (location.origin !== origin)
          throw new Error("Actual actor origin differs");
        const headers: Record<string, string> = view
          ? { "X-Review-View": view }
          : {};
        try {
          if (body !== undefined) {
            const bootstrap = await fetch("/v1/auth/csrf", {
              cache: "no-store",
            });
            if (!bootstrap.ok) return { status: bootstrap.status, value: {} };
            const proof = (await bootstrap.json()) as { csrf_token: string };
            headers["X-CSRF-Token"] = proof.csrf_token;
            headers["Content-Type"] = "application/json";
            headers["Idempotency-Key"] = key ?? crypto.randomUUID();
          }
          const reply = await fetch(path, {
            cache: "no-store",
            headers,
            method: body === undefined ? "GET" : "POST",
            signal: AbortSignal.timeout(15000),
            ...(body === undefined ? {} : { body: JSON.stringify(body) }),
          });
          return {
            status: reply.status,
            value: (await reply.json().catch(() => null)) as unknown,
          };
        } catch {
          return { status: 0, value: null };
        }
      },
      { path, body, key, view: this.view, origin: this.actor.origin },
    );
  }
  async current() {
    const response = await this.api("/v1/auth/session");
    expect(response.status, "Actual actor session is current").toBe(200);
    const value = row(response.value);
    expect(
      value.account_id === this.actor.account &&
        value.role === this.actor.role &&
        value.review_run_id === this.runId &&
        value.review_slot_id === this.actor.slot &&
        value.review_origin === this.actor.origin,
      "Actual session matches exact toolkit actor/role/run/slot/origin",
    ).toBe(true);
    return value;
  }
  async workspace() {
    const result = await this.api(
      "/v1/review/workspace" +
        (this.page.url().split("#")[1]
          ? "?session_id=" + this.page.url().split("#")[1]
          : ""),
    );
    expect(result.status, "Actual workspace can be reconstructed").toBe(200);
    const value = row(result.value);
    expect(value.run_id === this.runId, "Workspace stays in its run").toBe(
      true,
    );
    return value;
  }
  async postUI(path: string, action: () => Promise<unknown>) {
    const pending = this.page.waitForResponse(
      (reply) =>
        reply.url() === this.actor.origin + path &&
        reply.request().method() === "POST",
    );
    await action();
    const reply = await pending;
    expect(reply.status(), "Actual visible action succeeds: " + path).toBe(200);
    try {
      return row((await reply.json()) as unknown);
    } catch {
      throw new Error("Invalid action projection; private body suppressed");
    }
  }
  async selected(id: string) {
    await this.page.getByLabel(words.choose, { exact: true }).selectOption(id);
    await expect(this.conversation()).toBeVisible();
    await expect(this.conversation().locator("code").first()).toHaveText(id);
  }
  async reloadAndClaim() {
    this.view = null;
    await this.page.reload({ waitUntil: "domcontentloaded" });
    await expect(
      this.button(words.claim),
      "Reload offers explicit control recovery",
    ).toBeVisible();
    await this.button(words.claim).click();
    await expect(this.button(words.claim)).toHaveCount(0);
    await this.current();
  }
  async assertVisibleIdentity() {
    await expect(
      this.page
        .locator("header")
        .getByText(this.actor.account, { exact: true }),
    ).toBeVisible();
    await expect(this.button(words.signOut)).toBeVisible();
    await this.current();
  }
  async sessionId() {
    const value = await this.workspace();
    return text(row(value.conversation), "id");
  }
}
