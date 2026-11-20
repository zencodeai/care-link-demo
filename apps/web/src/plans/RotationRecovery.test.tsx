// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PlansWorkspace } from "./PlansWorkspace";

const account = "10000000-0000-4000-8000-000000000001";
const otherAccount = "10000000-0000-4000-8000-000000000002";
const sessionId = "20000000-0000-4000-8000-000000000001";
const subject = "30000000-0000-4000-8000-000000000001";
const planId = "40000000-0000-4000-8000-000000000001";
const grantId = "80000000-0000-4000-8000-000000000001";
const directoryId = "90000000-0000-4000-8000-000000000001";
const at = "2026-11-16T10:00:00Z";
const future = "2099-11-16T10:00:00Z";
const paths = {
  identity: "/v1/auth/session",
  session: `/v1/sessions/${sessionId}`,
  plan: `/v1/plans/${planId}`,
  grant: `/v1/consents/${grantId}`,
  directory: `/v1/directory/${directoryId}`,
};
const draft = "Unsent same-actor words";
const initialWords = "Previously disclosed strategy";
function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
interface Call {
  path: string;
  signal: AbortSignal | null | undefined;
  method: string;
}
function fixture() {
  let currentAccount = account,
    currentRole = "pid",
    fresh = false;
  const ceremony = {
    ceremony_id: "60000000-0000-4000-8000-000000000001",
    state: "pending",
    not_before: at,
    expires_at: new Date(Date.now() + 60_000).toISOString(),
    authorization_url:
      "https://issuer.example/authorize?state=server-issued-state",
  };
  const conversation = {
    id: sessionId,
    revision: "4",
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
  const identity = () => ({
    account_id: currentAccount,
    role: currentRole,
    assurance: "AL2",
    revision: "7",
    auth_time: at,
    expires_at: future,
  });
  const plan = () => ({
    id: planId,
    subject_id: subject,
    revision: fresh ? "2" : "1",
    state: "active",
    retired_at: null,
    fields: [
      {
        id: "50000000-0000-4000-8000-000000000001",
        revision: "1",
        subject_id: subject,
        field: "plan.strategies",
        value: {
          kind: "text",
          text: fresh ? "Fresh current strategy" : initialWords,
        },
        author_id: account,
        source: null,
        verification: "unverified",
        supersedes_id: null,
        effective_at: at,
      },
    ],
  });
  const grant = {
    id: grantId,
    revision: "1",
    scope: {
      session_id: sessionId,
      subject_id: subject,
      purpose: "plan",
      fields: ["plan.strategies"],
      recipient_id: otherAccount,
    },
    recipient: { kind: "account", account_id: otherAccount },
    grantor_id: account,
    scope_digest: "b".repeat(64),
    effective_at: at,
    expires_at: future,
    revoked_at: null,
  };
  const directory = {
    id: directoryId,
    revision: "1",
    facts: {
      name: "Previously disclosed option",
      jurisdictions: ["CA-XX"],
      languages: ["en-CA", "fr-CA"],
      age_scope: "all_fixture",
      availability: "available_fixture",
      police_involvement: "unknown",
      qualifications: [],
      alternative_service_id: null,
      hours_description: "Fictional hours",
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
    state: "verified",
    verified_at: at,
    expires_at: future,
  };
  const calls: Call[] = [];
  const queued = new Map<string, (() => Promise<Response>)[]>();
  const fetcher = vi.fn((input: string | URL | Request, init?: RequestInit) => {
    const path =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    calls.push({ path, signal: init?.signal, method: init?.method ?? "GET" });
    const special = queued.get(path)?.shift();
    if (special) return special();
    let body: unknown;
    if (path === paths.identity) body = identity();
    else if (path === "/v1/auth/csrf") body = { csrf_token: "a".repeat(43) };
    else if (path === paths.session) body = conversation;
    else if (path === paths.plan) body = plan();
    else if (path === paths.grant) body = grant;
    else if (path === paths.directory) body = directory;
    else if (path === "/v1/directory/search")
      body = { items: [directory], next_cursor: null };
    else if (path === "/v1/auth/step-up") body = ceremony;
    else return Promise.resolve(json({}, 503));
    return Promise.resolve(json(body));
  });
  vi.stubGlobal("fetch", fetcher);
  vi.stubEnv("VITE_OIDC_ORIGIN", "https://issuer.example");
  const popup = {
    opener: window as Window | null,
    location: { href: "about:blank" },
    close: vi.fn(),
  };
  const open = vi
    .spyOn(window, "open")
    .mockReturnValue(popup as unknown as Window);
  const queue = (path: string, ...replies: (() => Promise<Response>)[]) =>
    queued.set(path, replies);
  return {
    calls,
    ceremony,
    conversation,
    directory,
    identity,
    plan,
    open,
    queue,
    fresh: () => {
      fresh = true;
    },
    switchActor: () => {
      currentAccount = otherAccount;
      currentRole = "worker";
    },
    switchRole: () => {
      currentRole = "worker";
    },
    block: (path: string) => {
      let release: ((value: Response) => void) | undefined;
      queue(
        path,
        () =>
          new Promise<Response>((resolve) => {
            release = resolve;
          }),
      );
      return (body: unknown) => {
        if (!release) throw new Error("Expected current read to be pending");
        release(json(body));
      };
    },
  };
}
async function load(label: string, value: string, button: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
  fireEvent.click(screen.getByRole("button", { name: button }));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Check current access" }),
    ).toBeEnabled(),
  );
}
async function pendingWorkspace(f: ReturnType<typeof fixture>) {
  render(<PlansWorkspace locale="en-CA" />);
  await load("Conversation ID", sessionId, "Load conversation");
  await load("Plan ID", planId, "Open current plan");
  await screen.findByText(initialWords);
  await load("Permission ID", grantId, "Read current permission");
  fireEvent.click(
    screen.getByRole("button", { name: "Refresh sourced options" }),
  );
  await screen.findByRole("heading", { name: "Previously disclosed option" });
  fireEvent.change(screen.getByLabelText("Your words"), {
    target: { value: draft },
  });
  fireEvent.click(screen.getByRole("button", { name: "Verify my authority" }));
  await screen.findByRole("button", { name: "Confirm verification" });
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Check current access" }),
    ).toBeEnabled(),
  );
  f.calls.length = 0;
}
function check() {
  fireEvent.click(screen.getByRole("button", { name: "Check current access" }));
}
function inaccessibleOldViews() {
  expect(screen.queryByText(initialWords)).not.toBeInTheDocument();
  expect(
    screen.queryByRole("heading", { name: "Previously disclosed option" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Confirm verification" }),
  ).not.toBeInTheDocument();
}
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});
describe("bounded same-principal step-up read recovery", () => {
  it("does not retry an ordinary401 without a decoded pending ceremony", async () => {
    const f = fixture();
    render(<PlansWorkspace locale="en-CA" />);
    await load("Plan ID", planId, "Open current plan");
    await screen.findByText(initialWords);
    f.calls.length = 0;
    f.queue(paths.plan, () => Promise.resolve(json({}, 401)));
    check();
    await screen.findByText(/Sign in again to continue/);
    expect(f.calls.map((call) => call.path)).toEqual([
      paths.identity,
      paths.plan,
    ]);
    expect(screen.queryByText(initialWords)).not.toBeInTheDocument();
  });
  it("never retries a mutation401 during a pending ceremony", async () => {
    const f = fixture();
    await pendingWorkspace(f);
    f.queue(paths.plan + "/fields", () => Promise.resolve(json({}, 401)));
    fireEvent.click(
      screen.getByRole("button", { name: "Append my field version" }),
    );
    await screen.findByText(/Sign in again to continue/);
    expect(f.calls.map((call) => [call.path, call.method])).toEqual([
      ["/v1/auth/csrf", "GET"],
      [paths.plan + "/fields", "POST"],
    ]);
    inaccessibleOldViews();
  });
  it("hides projections, re-reads every selected resource and retains the mounted draft/ceremony", async () => {
    const f = fixture();
    await pendingWorkspace(f);
    const words = screen.getByLabelText("Your words");
    const confirmation = screen.getByRole("button", {
      name: "Confirm verification",
    });
    f.fresh();
    f.queue(
      paths.session,
      () => Promise.resolve(json({}, 401)),
      () => Promise.resolve(json(f.conversation)),
    );
    const release = f.block(paths.directory);
    check();
    await waitFor(() =>
      expect(document.querySelector("[inert]")).not.toBeNull(),
    );
    await waitFor(() =>
      expect(f.calls.some((call) => call.path === paths.directory)).toBe(true),
    );
    expect(screen.getByText(initialWords)).not.toBeVisible();
    expect(words).not.toBeVisible();
    expect(confirmation).not.toBeVisible();
    expect(words).toHaveValue(draft);
    expect(words.isConnected).toBe(true);
    expect(
      screen.queryByText("Fresh current strategy"),
    ).not.toBeInTheDocument();
    await act(async () => {
      release(f.directory);
      await Promise.resolve();
    });
    await screen.findByText("Fresh current strategy");
    expect(document.querySelector("[inert]")).toBeNull();
    expect(screen.getByLabelText("Your words")).toBe(words);
    expect(words).toHaveValue(draft);
    expect(screen.getByRole("button", { name: "Confirm verification" })).toBe(
      confirmation,
    );
    expect(confirmation).toBeVisible();
    expect(f.calls.map((call) => call.path)).toEqual([
      paths.identity,
      paths.session,
      paths.identity,
      paths.session,
      paths.plan,
      paths.grant,
      paths.directory,
    ]);
    expect(f.calls.every((call) => call.method === "GET")).toBe(true);
    expect(new Set(f.calls.map((call) => call.signal)).size).toBe(1);
    expect(f.open).toHaveBeenCalledOnce();
    // A second401 for the same admitted ceremony cannot create a third pass.
    f.calls.length = 0;
    f.queue(paths.session, () => Promise.resolve(json({}, 401)));
    check();
    await screen.findByText(/Sign in again to continue/);
    expect(f.calls.map((call) => call.path)).toEqual([
      paths.identity,
      paths.session,
    ]);
    inaccessibleOldViews();
  });
  it("clears normally if the one recovery also receives401", async () => {
    const f = fixture();
    await pendingWorkspace(f);
    f.queue(
      paths.session,
      () => Promise.resolve(json({}, 401)),
      () => Promise.resolve(json({}, 401)),
    );
    check();
    await screen.findByText(/Sign in again to continue/);
    expect(f.calls.map((call) => call.path)).toEqual([
      paths.identity,
      paths.session,
      paths.identity,
      paths.session,
    ]);
    inaccessibleOldViews();
  });
  it.each([403, 503])(
    "clears normally when a current recovery resource returns%s",
    async (status) => {
      const f = fixture();
      await pendingWorkspace(f);
      f.queue(
        paths.session,
        () => Promise.resolve(json({}, 401)),
        () => Promise.resolve(json(f.conversation)),
      );
      f.queue(paths.plan, () => Promise.resolve(json({}, status)));
      check();
      await waitFor(() =>
        expect(screen.queryByText(initialWords)).not.toBeInTheDocument(),
      );
      expect(f.calls.map((call) => call.path)).toEqual([
        paths.identity,
        paths.session,
        paths.identity,
        paths.session,
        paths.plan,
      ]);
      inaccessibleOldViews();
      expect(document.querySelector("[inert]")).toBeNull();
    },
  );
  it("clears old actor inputs if fresh identity has changed", async () => {
    const f = fixture();
    await pendingWorkspace(f);
    const prior = f.identity();
    f.queue(
      paths.identity,
      () => Promise.resolve(json(prior)),
      () => {
        f.switchActor();
        return Promise.resolve(json(f.identity()));
      },
    );
    f.queue(paths.session, () => Promise.resolve(json({}, 401)));
    check();
    await screen.findByRole("alert");
    inaccessibleOldViews();
    expect(f.calls.map((call) => call.path)).toEqual([
      paths.identity,
      paths.session,
      paths.identity,
    ]);
    await load("Plan ID", planId, "Open current plan");
    await screen.findByText(initialWords);
    expect(screen.getByLabelText("Your words")).toHaveValue("");
  });
  it("clears old-role inputs when the same account changes role and reopens the same plan", async () => {
    const f = fixture();
    await pendingWorkspace(f);
    const prior = f.identity();
    f.queue(
      paths.identity,
      () => Promise.resolve(json(prior)),
      () => {
        f.switchRole();
        return Promise.resolve(json(f.identity()));
      },
    );
    f.queue(paths.session, () => Promise.resolve(json({}, 401)));
    check();
    await screen.findByRole("alert");
    inaccessibleOldViews();
    expect(f.identity().account_id).toBe(account);
    expect(f.identity().role).toBe("worker");
    expect(f.calls.map((call) => call.path)).toEqual([
      paths.identity,
      paths.session,
      paths.identity,
    ]);
    await load("Plan ID", planId, "Open current plan");
    await screen.findByText(initialWords);
    expect(screen.getByLabelText("Your words")).toHaveValue("");
  });
  it("rejects a changed subject before restoring any selected projection", async () => {
    const f = fixture();
    await pendingWorkspace(f);
    f.queue(
      paths.session,
      () => Promise.resolve(json({}, 401)),
      () =>
        Promise.resolve(
          json({
            ...f.conversation,
            subject_id: otherAccount,
            persona_id: otherAccount,
          }),
        ),
    );
    check();
    await screen.findByRole("alert");
    inaccessibleOldViews();
    expect(f.calls.map((call) => call.path)).toEqual([
      paths.identity,
      paths.session,
      paths.identity,
      paths.session,
    ]);
  });
  it("does not recover from401 when the server-issued marker has expired", async () => {
    const f = fixture();
    await pendingWorkspace(f);
    vi.spyOn(Date, "now").mockReturnValue(
      Date.parse(f.ceremony.expires_at) + 1,
    );
    f.queue(paths.session, () => Promise.resolve(json({}, 401)));
    check();
    await screen.findByText(/Sign in again to continue/);
    expect(f.calls.map((call) => call.path)).toEqual([
      paths.identity,
      paths.session,
    ]);
    inaccessibleOldViews();
  });
  it("cannot publish a late response after the original five-second abort", async () => {
    const f = fixture();
    await pendingWorkspace(f);
    f.queue(
      paths.session,
      () => Promise.resolve(json({}, 401)),
      () => Promise.resolve(json(f.conversation)),
    );
    const release = f.block(paths.plan);
    check();
    await waitFor(() =>
      expect(document.querySelector("[inert]")).not.toBeNull(),
    );
    await waitFor(() =>
      expect(f.calls.some((call) => call.path === paths.plan)).toBe(true),
    );
    const signal = f.calls[0]?.signal;
    await waitFor(() => expect(signal?.aborted).toBe(true), { timeout: 5500 });
    expect(screen.getByText(initialWords)).not.toBeVisible();
    await act(async () => {
      release(f.plan());
      await Promise.resolve();
    });
    await waitFor(() =>
      expect(screen.queryByText(initialWords)).not.toBeInTheDocument(),
    );
    inaccessibleOldViews();
    expect(document.querySelector("[inert]")).toBeNull();
    expect(f.calls.filter((call) => call.path === paths.identity)).toHaveLength(
      2,
    );
  }, 10_000);
});
