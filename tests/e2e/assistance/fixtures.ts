import type { Page } from "@playwright/test";
import {
  actorId,
  at,
  draftContext,
  draftId,
  review,
  session,
  sessionId,
  source,
  task,
  taskId,
} from "../../../apps/web/src/assistance/fixtures";
export interface Mutation {
  path: string;
  body: Record<string, unknown>;
  key: string | undefined;
}
/** Browser boundary fixtures: this never proves deployed authorization or model quality. */
export async function installFixture(
  page: Page,
  options: {
    unavailable?: boolean;
    stale?: boolean;
    unknown?: boolean;
    pending?: boolean;
    statusAuthFailure?: 401 | 403;
  } = {},
) {
  let text: string | undefined,
    revision = "1",
    unknownOnce = options.unknown,
    privateWasRead = false;
  // This suite exercises UI commands; deployed SSE authority is checked separately.
  await page.addInitScript(() => {
    class QuietEventSource {
      close() {
        /* fixture has no open transport */
      }
      addEventListener() {
        /* no fixture events */
      }
    }
    Object.defineProperty(window, "EventSource", { value: QuietEventSource });
  });
  await page.route("**/dev/health", (route) =>
    route.fulfill({ status: 503, body: "synthetic API boundary" }),
  );
  const mutations: Mutation[] = [];
  const manualMessages: Record<string, unknown>[] = [];
  await page.route("**/v1/**", async (route) => {
    const request = route.request(),
      url = new URL(request.url()),
      path = url.pathname;
    if (url.origin !== "http://127.0.0.1:5176")
      throw new Error("Fixture rejects external origin");
    const body =
      request.method() === "POST"
        ? (JSON.parse(request.postData() ?? "null") as Record<string, unknown>)
        : {};
    if (request.method() === "POST")
      mutations.push({ path, body, key: request.headers()["idempotency-key"] });
    const respond = async (value: unknown, status = 200) =>
      route.fulfill({
        status,
        contentType: "application/json",
        headers: { "Cache-Control": "no-store" },
        body: JSON.stringify(value),
      });
    if (path === `/v1/sessions/${sessionId}`) return respond(session());
    if (path === "/v1/auth/session")
      return respond({
        account_id: actorId,
        role: "worker",
        assurance: "AL2",
        revision: "1",
        expires_at: "2099-01-01T00:00:00Z",
        auth_time: at,
      });
    if (path === `/v1/sessions/${sessionId}/messages`) {
      if (request.method() === "POST") {
        const message = {
          id: "80000000-0000-4000-8000-000000000001",
          session_id: sessionId,
          revision: "1",
          sender_id: actorId,
          kind: "human_authored",
          text: body.text,
          sources: [],
          control_epoch: "1",
          created_at: at,
        };
        manualMessages.push(message);
        return respond(message);
      }
      return respond({ items: manualMessages, next_cursor: null });
    }

    if (path === "/v1/auth/csrf")
      return respond({ csrf_token: "x".repeat(40) });
    if (path === "/v1/assistance/knowledge")
      return respond({
        catalog_digest: "d".repeat(64),
        entries: [
          {
            source: { ...source, kind: "protocol", verification: "verified" },
            title: "Synthetic handoff guidance",
            text: "Check the receiving service requirements before preparing a package.",
            source_url:
              "https://www.ontariohealth.ca/clinical/quality-standards/major-depression",
            source_title: "Ontario Health background standard",
            locale: body.locale,
          },
        ],
        notice: "synthetic_demo_information",
      });
    if (path === "/v1/assistance") {
      if (options.statusAuthFailure && privateWasRead)
        return respond({}, options.statusAuthFailure);
      return respond({
        available: !options.unavailable,
        reason: options.unavailable ? "assistance.function_disabled" : null,
        functions: options.unavailable ? [] : ["worker_summary"],
      });
    }
    if (path === "/v1/tasks")
      return respond(task(options.pending ? "planning" : "awaiting_human"));
    if (path === `/v1/tasks/${taskId}/context`)
      return respond({
        task: task(options.pending ? "planning" : "awaiting_human"),
        draft_id: options.pending ? null : draftId,
        available: true,
        reason: null,
      });
    if (path === `/v1/drafts/${draftId}/context`) {
      privateWasRead = true;
      return respond(
        draftContext(
          text,
          revision,
          options.stale ? "stale" : "review_pending",
        ),
      );
    }
    if (path === `/v1/tasks/${taskId}/cancel`)
      return respond(task("cancelled", "2"));
    if (path === `/v1/drafts/${draftId}/review`) {
      if (unknownOnce) {
        unknownOnce = false;
        return respond({}, 503);
      }
      if (body.decision === "edit") {
        text = String(body.edited_text);
        revision = "2";
      }
      return respond(review(String(body.decision)));
    }
    throw new Error("Unexpected synthetic API route " + path);
  });
  return mutations;
}
