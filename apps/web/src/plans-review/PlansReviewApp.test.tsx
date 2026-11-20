// @vitest-environment jsdom
// @vitest-environment-options {"url":"https://review.qualification.localhost/plans-review"}
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
import { PlansReviewApp } from "./PlansReviewApp";
import { emptyPlanForm } from "../plans/review";
import type { PlanDraft } from "./types";

const run = "10000000-0000-4000-8000-000000000001",
  actor = "20000000-0000-4000-8000-000000000001";
const sid = "30000000-0000-4000-8000-000000000001",
  subject = "40000000-0000-4000-8000-000000000001";
const planId = "50000000-0000-4000-8000-000000000001",
  recipient = "60000000-0000-4000-8000-000000000001";
const viewId = "70000000-0000-4000-8000-000000000001",
  secondView = "70000000-0000-4000-8000-000000000002";
const at = "2026-11-16T12:00:00Z",
  future = "2099-11-16T12:00:00Z";
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
  persona_id: subject,
  subject_id: subject,
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
function fixture(
  options: {
    signedIn?: boolean;
    enabled?: boolean;
    observer?: boolean;
    streamReady?: boolean;
  } = {},
) {
  let signedIn = options.signedIn ?? false,
    enabled = options.enabled ?? true;
  let authAt = Date.now();
  let observer = options.observer ?? false,
    currentView = viewId,
    currentActor = actor;
  let sessionDenial = 0,
    workspaceDenial = 0,
    mutationDenial = 0,
    directoryDenial = 0;
  let directoryName = "Previously disclosed review option";
  const directory = () => ({
    id: recipient,
    revision: "1",
    facts: {
      name: directoryName,
      jurisdictions: ["CA-XX"],
      languages: ["en-CA", "fr-CA"],
      age_scope: "all_fixture",
      availability: "unknown",
      police_involvement: "unknown",
      qualifications: [],
      alternative_service_id: null,
      hours_description: "Current hours unknown",
      operating_state: "normal_operations",
    },
    sources: [
      {
        kind: "directory",
        id: subject,
        revision: "1",
        digest: "a".repeat(64),
        observed_at: at,
        verification: "verified",
      },
    ],
    state: "stale",
    verified_at: at,
    expires_at: at,
  });
  let workspacePause: Promise<Response> | null = null,
    sessionPause: Promise<Response> | null = null;
  let draft: PlanDraft | undefined;
  const holds = new Map<string, Promise<void>>();
  let viewUnknown = false;
  const calls: {
    path: string;
    method: string;
    body: Record<string, unknown>;
    view: string | null;
  }[] = [];
  const streams: ReadableStreamDefaultController<Uint8Array>[] = [];
  const context = () => ({
    enabled: true,
    mode: "plans",
    authentication_mode: "automatic_review",
    environment: "synthetic-review",
    origin: window.location.origin,
    run_state: "active",
    run_id: run,
    slot_id: "pid",
    account_id: currentActor,
    role: "pid",
    started_at: at,
    expires_at: future,
  });
  const account = () => ({
    account_id: currentActor,
    role: "pid",
    assurance: Date.now() - authAt > 300000 ? "AL1" : "AL2",
    revision: "1",
    expires_at: future,
    auth_time: new Date(authAt).toISOString(),
    review_run_id: run,
    review_slot_id: "pid",
    review_origin: window.location.origin,
  });
  const workspace = () => ({
    workspace: {
      run_id: run,
      run_state: "active",
      conversations: [conversation],
      conversation,
      assignment: null,
      drafts: draft ? [draft] : [],
      pending_intents: [],
      handshake: null,
      disclosure_acknowledged: true,
      intake_submitted: true,
      interrupt_expires_at: null,
    },
    selection: { session_id: sid, plan_id: planId, recipient_id: recipient },
    expires_at: future,
  });
  const fetcher = vi.fn(
    async (input: string | URL | Request, init?: RequestInit) => {
      const path =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url;
      const method = init?.method ?? "GET",
        body = JSON.parse(
          typeof init?.body === "string" ? init.body : "{}",
        ) as Record<string, unknown>;
      calls.push({
        path,
        method,
        body,
        view: new Headers(init?.headers).get("X-Review-View"),
      });
      const hold = holds.get(path);
      if (hold) await hold;
      if (path === "/v1/plans-review/context")
        return json(enabled ? context() : { enabled: false });
      if (path === "/v1/auth/csrf") return json({ csrf_token: "a".repeat(43) });
      if (path === "/v1/auth/session")
        return signedIn ? json(account()) : json({}, 401);
      if (path === "/v1/auth/review/login") {
        signedIn = true;
        observer = false;
        authAt = Date.now();
        currentView =
          calls.filter((item) => item.path === path).length > 1
            ? secondView
            : viewId;
        return json(account());
      }
      if (path === "/v1/review/view/claim") {
        observer = false;
        return json({ view_id: currentView, state: "active", revision: "2" });
      }
      if (path === "/v1/review/view" && method === "GET" && viewUnknown)
        return json(
          {
            code: "REVISION_CONFLICT",
            request_id: subject,
            retryable: false,
            message_key: "manual.review_view_unknown",
            operation_id: null,
            retry_after_ms: null,
          },
          409,
        );
      if (path === "/v1/review/view" && method === "POST") viewUnknown = false;
      if (path === "/v1/review/view")
        return json({
          view_id: currentView,
          state: observer ? "observer" : "active",
          revision: "1",
        });
      if (path === "/v1/review/events")
        return new Response(
          new ReadableStream<Uint8Array>({
            start(controller) {
              streams.push(controller);
              if (options.streamReady !== false)
                controller.enqueue(
                  new TextEncoder().encode("event: ready\ndata: {}\n\n"),
                );
              init?.signal?.addEventListener("abort", () => {
                try {
                  controller.error(new Error("aborted"));
                } catch {
                  /* closed */
                }
              });
            },
          }),
          { headers: { "Content-Type": "text/event-stream" } },
        );
      if (path === "/v1/plans-review/workspace")
        return workspaceDenial
          ? json({}, workspaceDenial)
          : (workspacePause ?? json(workspace()));
      if (path === "/v1/directory/search")
        return json({ items: [directory()], next_cursor: null });
      if (path === `/v1/directory/${recipient}`)
        return directoryDenial ? json({}, directoryDenial) : json(directory());
      if (path === `/v1/sessions/${sid}`)
        return sessionDenial
          ? json({}, sessionDenial)
          : (sessionPause ?? json(conversation));
      if (path === `/v1/plans/${planId}`)
        return json({
          id: planId,
          subject_id: subject,
          revision: "1",
          state: "active",
          fields: [
            {
              id: subject,
              subject_id: subject,
              revision: "1",
              field: "plan.strategies",
              value: { kind: "text", text: "Current authorized plan words" },
              author_id: actor,
              source: null,
              verification: "unverified",
              supersedes_id: null,
              effective_at: at,
            },
          ],
          retired_at: null,
        });
      if (path === `/v1/review/sessions/${sid}/draft`) {
        if (mutationDenial) return json({}, mutationDenial);
        draft = {
          id: subject,
          session_id: sid,
          kind: "plan",
          revision: String(Number(draft?.revision ?? 0) + 1),
          text: body.text as string,
          expires_at: future,
        };
        return json(draft);
      }
      if (path === "/v1/auth/review/verify") {
        authAt = Date.now();
        currentView = secondView;
        return json({
          ceremony_id: subject,
          state: "verified",
          not_before: at,
          expires_at: future,
          authorization_url: null,
        });
      }
      if (path === `/v1/plans/${planId}/fields`)
        return json({}, mutationDenial || 403);
      throw new Error(`Unexpected ${method} ${path}`);
    },
  );
  vi.stubGlobal("fetch", fetcher);
  return {
    calls,
    streams,
    unknownView() {
      viewUnknown = true;
      observer = true;
    },
    hold(path: string) {
      let release!: () => void;
      holds.set(
        path,
        new Promise<void>((resolve) => {
          release = resolve;
        }),
      );
      return () => {
        holds.delete(path);
        release();
      };
    },
    workspace,
    setDraft(value: PlanDraft) {
      draft = value;
    },
    getDraft: () => draft,
    authTime: () => authAt,
    ageAssurance() {
      authAt = Date.now() - 301000;
    },
    signedOut() {
      signedIn = false;
    },
    disable() {
      enabled = false;
    },
    actor(value: string) {
      currentActor = value;
    },
    denySession(value: number) {
      sessionDenial = value;
    },
    denyWorkspace(value: number) {
      workspaceDenial = value;
    },
    denyMutation(value: number) {
      mutationDenial = value;
    },
    directoryFailure(status: number, nextName = directoryName) {
      directoryDenial = status;
      directoryName = nextName;
    },
    pauseWorkspace(value: Promise<Response> | null) {
      workspacePause = value;
    },
    pauseSession(value: Promise<Response> | null) {
      sessionPause = value;
    },
    emit(event: string) {
      streams
        .at(-1)
        ?.enqueue(new TextEncoder().encode(`event: ${event}\ndata: {}\n\n`));
    },
  };
}
// The actor-facing form labels remain localized by the existing plans package.
const words = () => document.querySelector<HTMLTextAreaElement>("#plan-words")!;
function reviewTick() {
  let tick: () => void = () => {
    throw new Error("No review refresh registered");
  };
  vi.spyOn(window, "setInterval").mockImplementation((handler, interval) => {
    if (interval === 5000) tick = handler;
    return 1 as unknown as ReturnType<typeof window.setInterval>;
  });
  return () => tick();
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/plans-review");
});

it("uses only server-enabled automatic review sign-in and preselected resources", async () => {
  const f = fixture();
  render(<PlansReviewApp />);
  await waitFor(() => expect(words()).toBeVisible());
  expect(
    f.calls.filter((call) => call.path === "/v1/auth/review/login"),
  ).toHaveLength(1);
  expect(f.calls.find((call) => call.path === "/v1/review/events")?.view).toBe(
    viewId,
  );
  expect(
    screen.queryByRole("button", { name: "Load conversation" }),
  ).not.toBeInTheDocument();
  expect(screen.getByText("Current authorized plan words")).toBeVisible();
});
it("disabled server context never signs in or opens a review stream", async () => {
  const f = fixture({ enabled: false });
  render(<PlansReviewApp />);
  await screen.findByRole("alert");
  expect(f.calls.map((call) => call.path)).toEqual([
    "/v1/plans-review/context",
  ]);
  expect(words()).toBeNull();
});
it("waits for the real event stream before enabling or writing", async () => {
  const f = fixture({ signedIn: true, streamReady: false });
  render(<PlansReviewApp />);
  await waitFor(() => expect(f.streams).toHaveLength(1));
  expect(words()).toBeNull();
  expect(f.calls.some((call) => call.path.endsWith("/draft"))).toBe(false);
  act(() => f.emit("ready"));
  await waitFor(() => expect(words()).toBeVisible());
});
it("does not automatically claim a page owned elsewhere", async () => {
  const f = fixture({ signedIn: true, observer: true });
  render(<PlansReviewApp />);
  const button = await screen.findByRole("button", { name: "Continue here" });
  expect(f.calls.some((call) => call.path.endsWith("/claim"))).toBe(false);
  expect(f.streams).toHaveLength(0);
  fireEvent.click(button);
  await waitFor(() => expect(words()).toBeVisible());
  expect(f.calls.filter((call) => call.path.endsWith("/claim"))).toHaveLength(
    1,
  );
});
it("reload restores encrypted server draft words and sharing fields without browser storage", async () => {
  const f = fixture({ signedIn: true });
  const stored = {
    ...emptyPlanForm(recipient),
    planWords: "Unsent fictional words",
    fields: ["plan.strategies" as const],
    expires: "2098-01-01T10:00",
  };
  f.setDraft({
    id: subject,
    session_id: sid,
    kind: "plan",
    revision: "3",
    text: JSON.stringify(stored),
    expires_at: future,
  });
  const local = vi.spyOn(Storage.prototype, "setItem");
  const first = render(<PlansReviewApp />);
  await waitFor(() => expect(words()).toHaveValue(stored.planWords));
  fireEvent.change(words(), {
    target: { value: "New unsent fictional words" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  await waitFor(() =>
    expect(
      (JSON.parse(f.getDraft()!.text) as { planWords: string }).planWords,
    ).toBe("New unsent fictional words"),
  );
  first.unmount();
  render(<PlansReviewApp />);
  await waitFor(() =>
    expect(words()).toHaveValue("New unsent fictional words"),
  );
  expect(document.querySelector("#share-expiry")).toHaveValue(stored.expires);
  expect(document.querySelector("#share-recipient")).toHaveValue(recipient);
  expect(local).not.toHaveBeenCalled();
});
it("review verification rotates and reconnects before refreshing, never opens a provider popup", async () => {
  const f = fixture();
  const popup = vi.spyOn(window, "open");
  render(<PlansReviewApp />);
  await waitFor(() => expect(words()).toBeVisible());
  fireEvent.change(words(), { target: { value: "Keep these unsent words" } });
  fireEvent.click(screen.getByRole("button", { name: "Verify my authority" }));
  await waitFor(() =>
    expect(f.calls.some((call) => call.path === "/v1/auth/review/verify")).toBe(
      true,
    ),
  );
  await waitFor(() => expect(words()).toBeVisible());
  expect(words()).toHaveValue("Keep these unsent words");
  expect(popup).not.toHaveBeenCalled();
  const verifyIndex = f.calls.findIndex(
    (call) => call.path === "/v1/auth/review/verify",
  );
  expect(
    f.calls.slice(0, verifyIndex).some((call) => call.path.endsWith("/draft")),
  ).toBe(true);
  expect(
    f.calls
      .slice(verifyIndex + 1)
      .some(
        (call) => call.path === "/v1/review/events" && call.view === secondView,
      ),
  ).toBe(true);
  expect(f.calls.some((call) => call.path === "/v1/consents")).toBe(false);
});
it("stream ready alone cannot reveal projections while replacement workspace is blocked", async () => {
  const f = fixture();
  render(<PlansReviewApp />);
  await waitFor(() => expect(words()).toBeVisible());
  let release!: (value: Response) => void;
  f.pauseWorkspace(
    new Promise((resolve) => {
      release = resolve;
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Verify my authority" }));
  await waitFor(() => expect(f.streams.length).toBe(2));
  expect(words()).not.toBeVisible();
  act(() => f.emit("ready"));
  expect(words()).not.toBeVisible();
  await act(async () => {
    await Promise.resolve();
    release(json(f.workspace()));
  });
  await waitFor(() => expect(words()).toBeVisible());
});
it("workspace denial after cookie rotation keeps all protected projections hidden", async () => {
  const f = fixture();
  render(<PlansReviewApp />);
  await waitFor(() => expect(words()).toBeVisible());
  f.denyWorkspace(403);
  fireEvent.click(screen.getByRole("button", { name: "Verify my authority" }));
  await waitFor(() =>
    expect(
      screen.getByText(
        "Current access could not be confirmed. Protected information is hidden.",
      ),
    ).toBeVisible(),
  );
  expect(
    screen.queryByText("Current authorized plan words"),
  ).not.toBeInTheDocument();
});
it("a failed write is not automatically replayed after automatic renewal", async () => {
  const f = fixture();
  render(<PlansReviewApp />);
  await waitFor(() => expect(words()).toBeVisible());
  f.denyMutation(401);
  f.signedOut();
  fireEvent.change(words(), { target: { value: "Do not auto-submit me" } });
  fireEvent.click(
    screen.getByRole("button", { name: "Append my field version" }),
  );
  await waitFor(() =>
    expect(
      f.calls.filter((call) => call.path.endsWith("/fields")),
    ).toHaveLength(1),
  );
  await waitFor(() =>
    expect(
      f.calls.filter((call) => call.path === "/v1/auth/review/login"),
    ).toHaveLength(2),
  );
  expect(f.calls.filter((call) => call.path.endsWith("/fields"))).toHaveLength(
    1,
  );
});
it("renders French reconnect and ended-review guidance", async () => {
  fixture({ enabled: false });
  window.history.replaceState(null, "", "/plans-review?locale=fr-CA");
  render(<PlansReviewApp />);
  await screen.findByText(
    "Votre accès actuel n’a pas pu être confirmé. Les renseignements protégés sont masqués.",
  );
  expect(screen.getByRole("button", { name: "Reconnecter" })).toBeVisible();
});
it("background authorization reads preserve typing and focus; denial then removes projections", async () => {
  const tick = reviewTick();
  const f = fixture();
  render(<PlansReviewApp />);
  await waitFor(() => expect(words()).toBeVisible());

  let release!: (value: Response) => void;
  f.pauseSession(
    new Promise((resolve) => {
      release = resolve;
    }),
  );
  words().focus();
  await act(async () => {
    await Promise.resolve();
    tick();
  });
  expect(words()).toBeEnabled();
  expect(words()).toHaveFocus();
  fireEvent.change(words(), {
    target: { value: "I can keep typing while access refreshes" },
  });
  expect(words()).toHaveValue("I can keep typing while access refreshes");
  await act(async () => {
    await Promise.resolve();
    release(json({}, 403));
  });
  expect(
    screen.queryByText("Current authorized plan words"),
  ).not.toBeInTheDocument();
  expect(words()).toBeNull();
});
it.each([403, 503])(
  "revalidates directory references after transient failure, while a %s denial clears them",
  async (status) => {
    const tick = reviewTick();
    const f = fixture();
    render(<PlansReviewApp />);
    await waitFor(() => expect(words()).toBeVisible());
    fireEvent.change(words(), {
      target: { value: "My same-actor draft survives a read failure" },
    });
    await waitFor(() => expect(screen.getByText("Draft saved")).toBeVisible());
    fireEvent.click(
      screen.getByRole("button", { name: "Refresh sourced options" }),
    );
    await screen.findByRole("heading", {
      name: "Previously disclosed review option",
    });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Refresh sourced options" }),
      ).toBeEnabled(),
    );
    f.directoryFailure(status);
    await act(async () => {
      await Promise.resolve();
      tick();
    });
    await waitFor(() =>
      expect(
        screen.queryByText("Current authorized plan words"),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.queryByRole("heading", {
        name: "Previously disclosed review option",
      }),
    ).not.toBeInTheDocument();
    f.directoryFailure(0, "Freshly revalidated review option");
    const before = f.calls.length;
    await act(async () => {
      await Promise.resolve();
      tick();
    });
    await screen.findByText("Current authorized plan words");
    expect(words()).toHaveValue("My same-actor draft survives a read failure");
    if (status === 503) {
      await screen.findByRole("heading", {
        name: "Freshly revalidated review option",
      });
      expect(
        screen.queryByText(/Current access is unavailable/),
      ).not.toBeInTheDocument();
      expect(
        f.calls
          .slice(before)
          .filter((call) => call.path === `/v1/directory/${recipient}`),
      ).toHaveLength(1);
    } else {
      expect(
        screen.queryByRole("heading", {
          name: "Freshly revalidated review option",
        }),
      ).not.toBeInTheDocument();
      expect(
        f.calls
          .slice(before)
          .some((call) => call.path.startsWith("/v1/directory/")),
      ).toBe(false);
    }
    // Recovery rechecks resources with GET; it never replays a search or a business command.
    expect(f.calls.slice(before).some((call) => call.method === "POST")).toBe(
      false,
    );
  },
);
it("one read-only renewal restores the same actor and all selected resources without losing unsent words", async () => {
  const tick = reviewTick();
  const f = fixture();
  render(<PlansReviewApp />);
  await waitFor(() => expect(words()).toBeVisible());
  fireEvent.change(words(), {
    target: { value: "Survives a bounded read renewal" },
  });
  const before = f.calls.length;
  f.signedOut();
  await act(async () => {
    await Promise.resolve();
    tick();
  });
  await act(async () => {});
  expect(
    f.calls.filter((call) => call.path === "/v1/auth/review/login"),
  ).toHaveLength(2);
  expect(
    f.calls.slice(before).some((call) => call.path === `/v1/sessions/${sid}`),
  ).toBe(true);
  expect(
    f.calls.slice(before).some((call) => call.path === `/v1/plans/${planId}`),
  ).toBe(true);
  expect(words()).toHaveValue("Survives a bounded read renewal");
  expect(words()).toBeVisible();
});
it("a repeated resource401 consumes only one renewal attempt and clears old projections", async () => {
  const tick = reviewTick();
  const f = fixture();
  render(<PlansReviewApp />);
  await waitFor(() => expect(words()).toBeVisible());
  f.denySession(401);
  await act(async () => {
    await Promise.resolve();
    tick();
  });
  await act(async () => {});
  expect(
    f.calls.filter((call) => call.path === "/v1/auth/review/login"),
  ).toHaveLength(2);
  expect(
    screen.queryByText("Current authorized plan words"),
  ).not.toBeInTheDocument();
});
it("actor change remounts the form rather than showing the previous actor's unsent words", async () => {
  const f = fixture({ signedIn: true });
  render(<PlansReviewApp />);
  await waitFor(() => expect(words()).toBeVisible());
  fireEvent.change(words(), { target: { value: "Old actor unsent words" } });
  f.actor("20000000-0000-4000-8000-000000000002");
  act(() => {
    window.dispatchEvent(new Event("focus"));
  });
  await waitFor(() => expect(words()).toHaveValue(""));
  expect(words()).toBeVisible();
});
it("malformed server draft gives recoverable guidance without crashing or enabling effects", async () => {
  const f = fixture({ signedIn: true });
  f.setDraft({
    id: subject,
    session_id: sid,
    kind: "plan",
    revision: "1",
    text: "not JSON",
    expires_at: future,
  });
  render(<PlansReviewApp />);
  const recover = await screen.findByRole("button", {
    name: "Continue with the words on this page",
  });
  expect(words()).toBeNull();
  expect(screen.getByText(/Draft could not be saved/)).toBeVisible();
  await waitFor(() => expect(recover).toBeEnabled());
  fireEvent.click(recover);
  await waitFor(() => expect(words()).toBeVisible());
});
it("a malformed later draft preserves this page's own newer words while disabling effects", async () => {
  const f = fixture({ signedIn: true });
  render(<PlansReviewApp />);
  await waitFor(() => expect(words()).toBeVisible());
  fireEvent.change(words(), { target: { value: "Newer local unsent words" } });
  f.setDraft({
    id: subject,
    session_id: sid,
    kind: "plan",
    revision: "9",
    text: "",
    expires_at: future,
  });
  act(() => f.emit("changed"));
  await screen.findByRole("button", {
    name: "Continue with the words on this page",
  });
  expect(words()).toHaveValue("Newer local unsent words");
  expect(words()).not.toBeVisible();
});
it("renews synthetic assurance during a review beyond five minutes without performing a business action", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const f = fixture();
  render(<PlansReviewApp />);
  await waitFor(() => expect(words()).toBeVisible());
  const original = f.authTime();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(240000);
  });
  await waitFor(() => expect(words()).toBeVisible());
  await act(async () => {
    await vi.advanceTimersByTimeAsync(61000);
  });
  expect(f.authTime()).toBeGreaterThan(original + 230000);
  expect(
    f.calls.filter((call) => call.path === "/v1/auth/review/login"),
  ).toHaveLength(2);
  expect(
    f.calls.filter(
      (call) =>
        call.method === "POST" &&
        !["/v1/auth/review/login", "/v1/review/view"].includes(call.path),
    ),
  ).toEqual([]);
  expect(words()).toBeVisible();
});
it("an already aged AL1 review session renews before exposing the workspace", async () => {
  const f = fixture({ signedIn: true });
  f.ageAssurance();
  render(<PlansReviewApp />);
  await waitFor(() => expect(words()).toBeVisible());
  expect(
    f.calls.filter((call) => call.path === "/v1/auth/review/login"),
  ).toHaveLength(1);
  expect(Date.now() - f.authTime()).toBeLessThan(300000);
});
it.each([403, 503])(
  "a current resource%s denial clears projections without trying automatic login",
  async (status) => {
    const tick = reviewTick(),
      f = fixture();
    render(<PlansReviewApp />);
    await waitFor(() => expect(words()).toBeVisible());
    f.denySession(status);
    await act(async () => {
      await Promise.resolve();
      tick();
    });
    expect(
      screen.queryByText("Current authorized plan words"),
    ).not.toBeInTheDocument();
    expect(
      f.calls.filter((call) => call.path === "/v1/auth/review/login"),
    ).toHaveLength(1);
  },
);
it("losing the real stream hides the workspace and invalidates sharing verification and preview", async () => {
  const f = fixture();
  render(<PlansReviewApp />);
  await waitFor(() => expect(words()).toBeVisible());
  fireEvent.click(screen.getByRole("button", { name: "Verify my authority" }));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Review exact sharing" }),
    ).toBeEnabled(),
  );
  act(() => f.emit("lost"));
  await waitFor(() => expect(words()).not.toBeVisible());
  await waitFor(() => expect(f.streams.length).toBe(3), { timeout: 2500 });
  await waitFor(() => expect(words()).toBeVisible());
  expect(
    screen.getByRole("button", { name: "Review exact sharing" }),
  ).toBeDisabled();
  expect(f.calls.some((call) => call.path === "/v1/consents")).toBe(false);
});
it("an aged AL1 observer holds control until the person explicitly continues here", async () => {
  const f = fixture({ signedIn: true, observer: true });
  f.ageAssurance();
  render(<PlansReviewApp />);
  const claim = await screen.findByRole("button", { name: "Continue here" });
  expect(
    f.calls.filter((call) => call.path === "/v1/auth/review/login"),
  ).toHaveLength(0);
  expect(words()).toBeNull();
  fireEvent.click(claim);
  await waitFor(() => expect(words()).toBeVisible());
  expect(f.calls.filter((call) => call.path.endsWith("/claim"))).toHaveLength(
    1,
  );
  expect(
    f.calls.filter((call) => call.path === "/v1/auth/review/login"),
  ).toHaveLength(1);
});
it("the240-second assurance timer cannot automatically take control from an observer page", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const f = fixture({ signedIn: true, observer: true });
  render(<PlansReviewApp />);
  await screen.findByRole("button", { name: "Continue here" });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(241000);
  });
  expect(
    f.calls.filter((call) => call.path === "/v1/auth/review/login"),
  ).toHaveLength(0);
  expect(f.calls.filter((call) => call.path.endsWith("/claim"))).toHaveLength(
    0,
  );
  expect(screen.getByRole("button", { name: "Continue here" })).toBeVisible();
});
it("observer401 holds without login; an explicit Continue here can then renew", async () => {
  const f = fixture({ signedIn: true, observer: true });
  render(<PlansReviewApp />);
  await screen.findByRole("button", { name: "Continue here" });
  f.signedOut();
  await act(async () => {
    window.dispatchEvent(new Event("focus"));
    await Promise.resolve();
  });
  expect(
    f.calls.filter((call) => call.path === "/v1/auth/review/login"),
  ).toHaveLength(0);
  expect(words()).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Continue here" }));
  await waitFor(() => expect(words()).toBeVisible());
  expect(
    f.calls.filter((call) => call.path === "/v1/auth/review/login"),
  ).toHaveLength(1);
});
it("a validated unknown view holds for explicit Continue here without automatic register or login", async () => {
  const f = fixture({ signedIn: true });
  render(<PlansReviewApp />);
  await waitFor(() => expect(words()).toBeVisible());
  const registrations = f.calls.filter(
    (call) => call.path === "/v1/review/view" && call.method === "POST",
  ).length;
  f.unknownView();
  await act(async () => {
    window.dispatchEvent(new Event("focus"));
    await Promise.resolve();
  });
  const claim = await screen.findByRole("button", { name: "Continue here" });
  expect(words()).not.toBeVisible();
  expect(
    f.calls.filter(
      (call) => call.path === "/v1/review/view" && call.method === "POST",
    ),
  ).toHaveLength(registrations);
  expect(
    f.calls.filter((call) => call.path === "/v1/auth/review/login"),
  ).toHaveLength(0);
  fireEvent.click(claim);
  await waitFor(() => expect(words()).toBeVisible());
  expect(f.calls.filter((call) => call.path.endsWith("/claim"))).toHaveLength(
    1,
  );
});
it.each(["verify", "draft", "business"] as const)(
  "scheduled renewal waits for a held %s write and retains its own full auth budget",
  async (kind) => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const f = fixture({ signedIn: true });
    render(<PlansReviewApp />);
    await waitFor(() => expect(words()).toBeVisible());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(239000);
    });
    const path =
      kind === "verify"
        ? "/v1/auth/review/verify"
        : kind === "draft"
          ? `/v1/review/sessions/${sid}/draft`
          : `/v1/plans/${planId}/fields`;
    const release = f.hold(path);
    if (kind !== "verify")
      fireEvent.change(words(), {
        target: { value: "Keep this unsent draft" },
      });
    fireEvent.click(
      screen.getByRole("button", {
        name:
          kind === "verify"
            ? "Verify my authority"
            : kind === "draft"
              ? "Save draft"
              : "Append my field version",
      }),
    );
    await waitFor(() =>
      expect(f.calls.filter((call) => call.path === path)).toHaveLength(1),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3500);
    });
    expect(
      f.calls.filter((call) => call.path === "/v1/auth/review/login"),
    ).toHaveLength(0);
    await act(async () => {
      release();
      await Promise.resolve();
    });
    await waitFor(() => expect(words()).toBeVisible());
    expect(f.calls.filter((call) => call.path === path)).toHaveLength(1);
    expect(
      f.calls.filter((call) => call.path === "/v1/auth/review/login"),
    ).toHaveLength(kind === "verify" ? 0 : 1);
    expect(
      screen.queryByText(
        "The review connection is unavailable. Your unsent words remain here.",
      ),
    ).not.toBeInTheDocument();
  },
);
it("a timer and current401 share one cookie rotation without business replay", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const f = fixture({ signedIn: true });
  render(<PlansReviewApp />);
  await waitFor(() => expect(words()).toBeVisible());
  await act(async () => {
    await vi.advanceTimersByTimeAsync(239000);
  });
  const release = f.hold("/v1/auth/review/login");
  f.signedOut();
  await act(async () => {
    window.dispatchEvent(new Event("focus"));
    await Promise.resolve();
  });
  await waitFor(() =>
    expect(
      f.calls.filter((call) => call.path === "/v1/auth/review/login"),
    ).toHaveLength(1),
  );
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2000);
  });
  expect(
    f.calls.filter((call) => call.path === "/v1/auth/review/login"),
  ).toHaveLength(1);
  await act(async () => {
    release();
    await Promise.resolve();
  });
  await waitFor(() => expect(words()).toBeVisible());
  expect(
    f.calls.filter((call) => call.path === "/v1/auth/review/login"),
  ).toHaveLength(1);
});
