import type { Page } from "@playwright/test";
export const ids = {
  session: "10000000-0000-4000-8000-000000000001",
  subject: "20000000-0000-4000-8000-000000000001",
  account: "30000000-0000-4000-8000-000000000001",
  followup: "40000000-0000-4000-8000-000000000001",
  grant: "50000000-0000-4000-8000-000000000001",
  rights: "60000000-0000-4000-8000-000000000001",
  message: "70000000-0000-4000-8000-000000000001",
};
const at = "2026-11-20T12:00:00Z",
  future = "2099-11-20T12:00:00Z";
export async function installFixture(
  page: Page,
  options: { lostCancel?: boolean; authorized?: boolean } = {},
) {
  const commands: {
    path: string;
    body: Record<string, unknown>;
    key: string | undefined;
  }[] = [];
  let lostCancel = options.lostCancel ?? false;
  let signedOut = false;
  let state = options.authorized ? "authorized" : "scheduled";
  await page.route("**/v1/**", async (route) => {
    const request = route.request(),
      path = new URL(request.url()).pathname;
    const fulfill = (value: unknown, status = 200) =>
      route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(value),
      });
    if (path === "/v1/auth/session")
      return fulfill(
        signedOut
          ? {}
          : {
              account_id: ids.account,
              role: "pid",
              assurance: "AL2",
              revision: "1",
              expires_at: future,
              auth_time: at,
            },
        signedOut ? 401 : 200,
      );
    if (path === "/v1/auth/csrf")
      return fulfill({ csrf_token: "a".repeat(48) });
    if (request.method() === "POST")
      commands.push({
        path,
        body: request.postDataJSON() as Record<string, unknown>,
        key: request.headers()["idempotency-key"],
      });
    if (path === `/v1/sessions/${ids.session}`)
      return fulfill({
        id: ids.session,
        revision: "1",
        tags: { environment: "demo", population: "synthetic" },
        participant_kind: "pid",
        jurisdiction: null,
        locale: "en-CA",
        service_phase: "ended",
        transport: "disconnected",
        control_epoch: "1",
        owner_id: null,
        degraded_reasons: [],
        tier: null,
        unresolved: true,
        persona_id: ids.subject,
        subject_id: ids.subject,
        subject_revision: "7",
      });
    if (path === `/v1/sessions/${ids.session}/follow-ups`) {
      state = "anchor_pending";
      return fulfill({
        id: ids.followup,
        session_id: ids.session,
        revision: "1",
        state,
        due_at: null,
        inbox_message_id: null,
      });
    }
    if (path === `/v1/follow-ups/${ids.followup}/cancel`) {
      if (!options.authorized) state = "cancelled";
      if (lostCancel) {
        lostCancel = false;
        return route.abort("failed");
      }
      return fulfill({
        id: ids.followup,
        session_id: ids.session,
        revision: "2",
        state,
        due_at: at,
        inbox_message_id: null,
      });
    }
    if (path === `/v1/follow-ups/${ids.followup}`)
      return fulfill({
        id: ids.followup,
        session_id: ids.session,
        revision: "1",
        state,
        due_at: at,
        inbox_message_id: null,
      });
    const message = {
      id: ids.message,
      recipient_account_id: ids.account,
      followup_id: ids.followup,
      source_session_id: ids.session,
      text: "Synthetic private inbox content",
      sources: [],
      created_at: at,
      read_at: null,
      expires_at: future,
    };
    if (path === "/v1/inbox")
      return fulfill({ items: [message], next_cursor: null });
    if (path === `/v1/inbox/${ids.message}`) return fulfill(message);
    if (path === `/v1/rights/${ids.rights}`)
      return fulfill({
        id: ids.rights,
        revision: "2",
        kind: "delete",
        state: "backup_pending",
        exceptions: [
          "backup_erasure_pending_IMP09",
          "physical_erasure_not_proven",
          "active_hold",
        ],
        download_id: null,
        deadline: future,
      });
    return fulfill({}, 404);
  });
  return {
    commands,
    signOut: () => {
      signedOut = true;
    },
  };
}
