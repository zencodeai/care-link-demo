// @vitest-environment jsdom
// @vitest-environment-options {"url":"https://r10000000000040008000000000000001-participant.qualification.localhost/"}
import "@testing-library/jest-dom/vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ReviewApp } from "./ReviewApp";
const run = "10000000-0000-4000-8000-000000000001";
const actor = "20000000-0000-4000-8000-000000000001";
const sid = "30000000-0000-4000-8000-000000000001";
const id = "40000000-0000-4000-8000-000000000001";
const at = "2026-11-16T12:00:00Z";
const conversation = {
  id: sid,
  revision: "1",
  tags: { environment: "demo", population: "synthetic" },
  participant_kind: "pid",
  jurisdiction: null,
  locale: "en-CA",
  service_phase: "active",
  transport: "connected",
  control_epoch: "0",
  owner_id: null,
  degraded_reasons: ["ai_unavailable"],
  tier: null,
  unresolved: true,
  persona_id: id,
  subject_id: id,
};
const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
function fixture(role = "pid", observer = false) {
  let authority = true;
  let runState = "active";
  let interruptExpires: string | null = null;
  let viewState = observer ? "observer" : "active";
  let draft: {
    id: string;
    session_id: string;
    kind: "intake";
    revision: string;
    text: string;
    expires_at: string;
  } | null = null;
  let submitted = false;
  let intentState = "prepared";
  let intent = false;
  let loseReply = false;
  let paused: Promise<Response> | null = null;
  let release: (() => void) | null = null;
  let workspaceUnavailable = false;
  const streams: ReadableStreamDefaultController<Uint8Array>[] = [];
  const calls: {
    path: string;
    method: string;
    body: Record<string, unknown>;
    key: string | null;
    viewId: string | null;
  }[] = [];
  const workspace = () => ({
    run_id: run,
    run_state: runState,
    conversations: [conversation],
    conversation: {
      ...conversation,
      service_phase: role === "worker" ? "worker_assigned" : "active",
    },
    assignment:
      role === "worker"
        ? {
            id,
            session_id: sid,
            worker_id: actor,
            revision: "2",
            reservation_id: id,
            expires_at: "2099-11-16T12:00:00Z",
            state: "accepted",
            control_epoch: "0",
          }
        : null,
    drafts: draft ? [{ ...draft, text: submitted ? "" : draft.text }] : [],
    pending_intents: intent
      ? [
          {
            operation_id: id,
            session_id: sid,
            kind: "intake",
            draft_revision: draft?.revision ?? "1",
            state: intentState,
            action: "session_turns",
            payload: {
              expected_revision: "1",
              client_turn_id: id,
              text: draft?.text ?? "saved fictional draft",
              locale: "en-CA",
            },
            created_at: at,
          },
        ]
      : [],
    handshake: null,
    disclosure_acknowledged: true,
    intake_submitted: submitted,
    interrupt_expires_at: interruptExpires,
  });
  vi.stubEnv("VITE_OIDC_ORIGIN", "https://id.test");
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const path = (
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url
      ).split("?")[0]!;
      const body = JSON.parse(
        typeof init?.body === "string" ? init.body : "{}",
      ) as Record<string, unknown>;
      const method = init?.method ?? "GET";
      calls.push({
        path,
        method,
        body,
        key: new Headers(init?.headers).get("Idempotency-Key"),
        viewId: new Headers(init?.headers).get("X-Review-View"),
      });
      if (path === "/v1/review/context")
        return response({
          enabled: true,
          origin: window.location.origin,
          run_id: run,
          slot_id: role === "worker" ? "worker1" : "participant",
          account_id: actor,
          role,
          run_state: "active",
        });
      if (path === "/v1/auth/session")
        return authority
          ? response({
              account_id: actor,
              role,
              assurance: "AL2",
              revision: "1",
              expires_at: "2099-11-16T12:00:00Z",
              auth_time: at,
              review_run_id: run,
              review_slot_id: role === "worker" ? "worker1" : "participant",
              review_origin: window.location.origin,
            })
          : response({}, 401);
      if (path === "/v1/auth/csrf")
        return response({ csrf_token: "a".repeat(43) });
      if (path === "/v1/review/view/claim") {
        viewState = "active";
        return response({ view_id: id, state: viewState, revision: "2" });
      }
      if (path === "/v1/review/view")
        return response({ view_id: id, state: viewState, revision: "1" });
      if (path === "/v1/review/events")
        return new Response(
          new ReadableStream<Uint8Array>({
            start(controller) {
              streams.push(controller);
              controller.enqueue(
                new TextEncoder().encode("event: ready\ndata: {}\n\n"),
              );
              init?.signal?.addEventListener("abort", () => {
                try {
                  controller.error(new Error("aborted"));
                } catch {
                  /* already closed */
                }
              });
            },
          }),
          { headers: { "Content-Type": "text/event-stream" } },
        );
      if (path === "/v1/review/workspace")
        return workspaceUnavailable
          ? response({ code: "service_unavailable" }, 503)
          : (paused ?? response(workspace()));
      if (path === `/v1/sessions/${sid}/messages`)
        return response({
          items: [
            {
              id,
              session_id: sid,
              revision: "1",
              sender_id: actor,
              kind: "participant",
              text: "Previously authorized fictional output",
              sources: [],
              control_epoch: "0",
              created_at: at,
            },
          ],
          next_cursor: null,
        });
      if (path === "/v1/workforce/queue")
        return response({ items: [], next_cursor: null });
      if (path === `/v1/review/sessions/${sid}/draft`) {
        draft = {
          id,
          session_id: sid,
          kind: "intake",
          text: String(body.text),
          revision: String(Number(body.expected_revision) + 1),
          expires_at: "2099-11-16T12:00:00Z",
        };
        return response(draft);
      }
      if (path === `/v1/sessions/${sid}`) return response(conversation);
      if (path === `/v1/review/sessions/${sid}/intent/cancel`) {
        intentState = "cancelled";
        if (draft) draft.revision = String(Number(draft.revision) + 1);
        return response(workspace().pending_intents[0]);
      }
      if (path === `/v1/review/sessions/${sid}/intent`) {
        intent = true;
        return response(workspace().pending_intents[0]);
      }
      if (path === `/v1/sessions/${sid}/turns`) {
        submitted = true;
        intentState = "committed";
        if (loseReply) throw new TypeError("lost after durable commit");
        return response({
          session_id: sid,
          revision: "1",
          fields: [{ field: "needs", state: "unknown", assertion_ids: [] }],
          tier: "T0",
          tier_set_digest: "a".repeat(64),
          content_class: "stub",
          situation_factors: {},
          human_reasons: [],
        });
      }
      if (path === `/v1/operations/${id}`)
        return response({
          operation_id: id,
          state: intentState,
          safe_reason: null,
        });
      throw new Error("Unexpected fixture route " + path);
    }),
  );
  return {
    calls,
    setWorkspaceUnavailable(value: boolean) {
      workspaceUnavailable = value;
    },
    restoreInterrupt(expires: string) {
      interruptExpires = expires;
    },
    setAuthority(value: boolean) {
      authority = value;
    },
    setLoseReply() {
      loseReply = true;
    },
    closeRun() {
      runState = "closed";
    },
    seedIntent(state = "prepared") {
      intent = true;
      intentState = state;
      draft = {
        id,
        session_id: sid,
        kind: "intake",
        text: "saved fictional draft",
        revision: "1",
        expires_at: "2099-11-16T12:00:00Z",
      };
    },
    holdWorkspace() {
      const previous = response(workspace());
      paused = new Promise((resolve) => {
        release = () => {
          paused = null;
          resolve(previous);
        };
      });
    },
    release() {
      release?.();
    },
    loseRights() {
      for (const stream of streams)
        stream.enqueue(
          new TextEncoder().encode("event: rights_changed\ndata: {}\n\n"),
        );
    },
  };
}
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  window.history.replaceState(null, "", "/");
});
it("restores a supervisor interrupt grant after remount and hides it after expiry", async () => {
  const lab = fixture("supervisor");
  lab.restoreInterrupt("2099-11-16T12:00:00Z");
  const app = render(<ReviewApp />);
  const name = "Take over as accountable supervisor";
  expect(await screen.findByRole("button", { name })).toBeInTheDocument();
  app.unmount();
  render(<ReviewApp />);
  expect(await screen.findByRole("button", { name })).toBeInTheDocument();
  lab.restoreInterrupt("2000-11-16T12:00:00Z");
  fireEvent.click(screen.getByRole("button", { name: "Refresh workspace" }));
  await waitFor(() =>
    expect(screen.queryByRole("button", { name })).not.toBeInTheDocument(),
  );
});
it("boots one account/workspace automatically and saves/reloads a draft", async () => {
  const lab = fixture();
  const app = render(<ReviewApp />);
  const input = await screen.findByLabelText("Fictional situation");
  await waitFor(() => expect(input).toBeEnabled());
  fireEvent.change(input, {
    target: { value: "Fictional text survives full reload" },
  });
  await waitFor(() =>
    expect(
      lab.calls.some(
        (c) =>
          c.path.endsWith("/draft") &&
          c.body.text === "Fictional text survives full reload",
      ),
    ).toBe(true),
  );
  await waitFor(() =>
    expect(document.getElementById("review-intake-saved")).toHaveTextContent(
      "Draft saved",
    ),
  );
  app.unmount();
  render(<ReviewApp />);
  await waitFor(() =>
    expect(screen.getByLabelText("Fictional situation")).toHaveValue(
      "Fictional text survives full reload",
    ),
  );
  expect(screen.queryByText("Check manual access")).not.toBeInTheDocument();
});
it("restores an accepted worker assignment from server state after reload", async () => {
  fixture("worker");
  render(<ReviewApp />);
  expect(
    await screen.findByText(
      "Assignment accepted. A connection still requires both parties.",
    ),
  ).toBeVisible();
  await waitFor(() =>
    expect(
      screen.getByRole("button", {
        name: "Prepare a new channel confirmation",
      }),
    ).toBeEnabled(),
  );
});
it.each([false, true])(
  "retains the verified actor and lease after workspace503, including observer=%s recovery",
  async (observer) => {
    const lab = fixture("worker", observer);
    lab.setWorkspaceUnavailable(true);
    render(<ReviewApp />);
    expect(
      await screen.findByRole("button", { name: "Sign out" }),
    ).toBeVisible();
    expect(screen.getByText(actor)).toBeVisible();
    expect(
      screen.queryByRole("button", {
        name: "Prepare a new channel confirmation",
      }),
    ).not.toBeInTheDocument();
    if (observer)
      expect(
        screen.getByRole("button", { name: "Use this tab" }),
      ).toBeEnabled();
    lab.setWorkspaceUnavailable(false);
    fireEvent.click(
      screen.getByRole("button", {
        name: observer ? "Use this tab" : "Refresh workspace",
      }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", {
          name: "Prepare a new channel confirmation",
        }),
      ).toBeEnabled(),
    );
    expect(
      lab.calls.filter(
        (call) => call.path === "/v1/review/view" && call.method === "POST",
      ),
    ).toHaveLength(1);
    const reads = lab.calls.filter(
      (call) => call.path === "/v1/review/view" && call.method === "GET",
    );
    expect(reads.length).toBeGreaterThan(0);
    expect(reads.every((call) => call.viewId === id)).toBe(true);
  },
);
it("a duplicate observer tab cannot write until explicit claim", async () => {
  const lab = fixture("pid", true);
  render(<ReviewApp />);
  expect(
    await screen.findByRole("button", { name: "Use this tab" }),
  ).toBeEnabled();
  expect(screen.getByLabelText("Fictional situation")).toBeDisabled();
  expect(lab.calls.some((c) => c.path === "/v1/review/events")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Use this tab" }));
  await waitFor(() =>
    expect(screen.getByLabelText("Fictional situation")).toBeEnabled(),
  );
});
it("hides private output immediately on rights loss and discards the held old projection", async () => {
  const lab = fixture();
  render(<ReviewApp />);
  expect(
    await screen.findByText("Previously authorized fictional output"),
  ).toBeVisible();
  lab.holdWorkspace();
  fireEvent.click(screen.getByRole("button", { name: "Refresh workspace" }));
  await waitFor(() =>
    expect(
      lab.calls.filter((c) => c.path === "/v1/review/workspace").length,
    ).toBeGreaterThan(1),
  );
  lab.setAuthority(false);
  await act(async () => {
    lab.loseRights();
    await Promise.resolve();
  });
  expect(
    screen.queryByText("Previously authorized fictional output"),
  ).not.toBeInTheDocument();
  await act(async () => {
    lab.release();
    await Promise.resolve();
  });
  await waitFor(() =>
    expect(
      screen.getByText(
        "Sign in to this workspace. Your saved work will be recovered.",
      ),
    ).toBeVisible(),
  );
  expect(
    screen.queryByText("Previously authorized fictional output"),
  ).not.toBeInTheDocument();
});
it("retries a persisted intent using its original operation id and payload", async () => {
  const lab = fixture();
  lab.seedIntent();
  render(<ReviewApp />);
  const retry = await screen.findByRole("button", {
    name: "Retry saved operation",
  });
  await waitFor(() => expect(retry).toBeEnabled());
  fireEvent.click(retry);
  await waitFor(() =>
    expect(
      lab.calls.some(
        (c) =>
          c.path.endsWith("/turns") &&
          c.key === id &&
          c.body.text === "saved fictional draft",
      ),
    ).toBe(true),
  );
});
it("offers cancellation only for a safely prepared action", async () => {
  const lab = fixture();
  lab.seedIntent();
  render(<ReviewApp />);
  const cancel = await screen.findByRole("button", {
    name: "Discard prepared action",
  });
  await waitFor(() => expect(cancel).toBeEnabled());
  fireEvent.click(cancel);
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: "Discard prepared action" }),
    ).not.toBeInTheDocument(),
  );
  expect(lab.calls.filter((c) => c.path.endsWith("/turns"))).toHaveLength(0);
  expect(screen.getByLabelText("Fictional situation")).toHaveValue(
    "saved fictional draft",
  );
});
it("does not offer cancellation for an unknown canonical outcome", async () => {
  const lab = fixture();
  lab.seedIntent("unknown");
  render(<ReviewApp />);
  await screen.findByRole("button", { name: "Retry saved operation" });
  expect(
    screen.queryByRole("button", { name: "Discard prepared action" }),
  ).not.toBeInTheDocument();
});

it("submits on the first click while a blur-triggered save is in flight and recovers a lost committed reply", async () => {
  const lab = fixture();
  lab.setLoseReply();
  const app = render(<ReviewApp />);
  const input = await screen.findByLabelText("Fictional situation");
  await waitFor(() => expect(input).toBeEnabled());
  fireEvent.change(input, {
    target: { value: "Fictional first click stays exactly once" },
  });
  fireEvent.blur(input);
  fireEvent.click(
    screen.getByRole("button", { name: "Submit fictional situation" }),
  );
  await waitFor(() =>
    expect(
      lab.calls.filter((call) => call.path.endsWith("/turns")),
    ).toHaveLength(1),
  );
  expect(lab.calls.find((call) => call.path.endsWith("/turns"))?.key).toBe(id);
  app.unmount();
  render(<ReviewApp />);
  expect(
    await screen.findByText("Fictional situation submitted"),
  ).toBeVisible();
  expect(lab.calls.filter((call) => call.path.endsWith("/turns"))).toHaveLength(
    1,
  );
});

it("keeps closed worker runs available for status-only reconciliation without business reads", async () => {
  const lab = fixture("worker");
  lab.seedIntent("committed");
  lab.closeRun();
  render(<ReviewApp />);
  const check = await screen.findByRole("button", {
    name: "Check saved operation",
  });
  expect(
    lab.calls.some(
      (call) =>
        call.path.endsWith("/messages") || call.path === "/v1/workforce/queue",
    ),
  ).toBe(false);
  fireEvent.click(check);
  await waitFor(() =>
    expect(lab.calls.some((call) => call.path === `/v1/operations/${id}`)).toBe(
      true,
    ),
  );
  expect(await screen.findByText("committed")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Retry saved operation" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", {
      name: "Prepare a new channel confirmation",
    }),
  ).not.toBeInTheDocument();
});

it("protects unsaved local text during a full navigation and removes the prompt after server save", async () => {
  const lab = fixture();
  render(<ReviewApp />);
  const input = await screen.findByLabelText("Fictional situation");
  await waitFor(() => expect(input).toBeEnabled());
  fireEvent.change(input, { target: { value: "Fictional unsaved text" } });
  const unsaved = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(unsaved);
  expect(unsaved.defaultPrevented).toBe(true);
  await waitFor(() =>
    expect(lab.calls.some((call) => call.path.endsWith("/draft"))).toBe(true),
  );
  await waitFor(() =>
    expect(document.getElementById("review-intake-saved")).toHaveTextContent(
      "Draft saved",
    ),
  );
  const saved = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(saved);
  expect(saved.defaultPrevented).toBe(false);
});

it("shows a token-free actionable sign-in restart after a failed callback", async () => {
  fixture();
  window.history.replaceState(null, "", "/?auth_error=sign_in_interrupted");
  render(<ReviewApp />);
  expect(
    await screen.findByText(
      "Sign-in was interrupted or used the wrong account. Choose Sign in to restart safely.",
    ),
  ).toBeVisible();
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled(),
  );
});
