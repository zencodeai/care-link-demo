// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import {
  cleanup,
  fireEvent,
  act,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ManualService } from "./ManualService";

const account = "10000000-0000-4000-8000-000000000001";
const sessionId = "20000000-0000-4000-8000-000000000001";
const assignmentId = "30000000-0000-4000-8000-000000000001";
const id = "40000000-0000-4000-8000-000000000001";
const at = "2026-11-09T10:00:00Z";
const csrf = "a".repeat(43);
const view = {
  id: sessionId,
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
const message = {
  id,
  session_id: sessionId,
  revision: "1",
  sender_id: account,
  kind: "participant",
  text: "Fictional message",
  sources: [],
  control_epoch: "0",
  created_at: at,
};
const assignment = {
  id: assignmentId,
  session_id: sessionId,
  worker_id: account,
  revision: "1",
  reservation_id: id,
  expires_at: "2099-11-09T10:01:00Z",
  state: "reserved",
  control_epoch: "0",
};
function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
function fixture(role = "pid", enforceSupervisorScopes = false) {
  let authority = true;
  let csrfAvailable = true;
  let currentRole = role;
  let currentAccount = account;
  let blockedRead = false;
  let heldSession: Promise<Response> | null = null;
  let releaseSession: (() => void) | null = null;
  let heldOperation: Promise<Response> | null = null;
  let releaseOperation: (() => void) | null = null;
  let operationState = "committed";
  let supervisorScope = "none";
  let scopeExpiresAt = 0;
  let current: Omit<typeof view, "owner_id"> & { owner_id: string | null } = {
    ...view,
  };
  let otherPartyAck = false;
  let failMessage = false;
  let rejectMessage = false;
  const commands: { path: string; key: string | null; body: unknown }[] = [];
  const fetcher = vi.fn(
    async (input: string | URL | Request, init?: RequestInit) => {
      await Promise.resolve();
      const path = (
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url
      ).split("?")[0];
      if (path === "/v1/auth/session")
        return authority
          ? response({
              account_id: currentAccount,
              role: currentRole,
              assurance: "AL1",
              revision: "1",
              auth_time: at,
              expires_at: "2099-11-09T11:00:00Z",
            })
          : response({}, 401);
      if (path === "/v1/auth/csrf")
        return csrfAvailable
          ? response({ csrf_token: csrf })
          : response({}, 503);
      if (init?.method === "POST") {
        const raw = typeof init.body === "string" ? init.body : "{}";
        const body: unknown = JSON.parse(raw);
        const key = new Headers(init.headers).get("Idempotency-Key");
        commands.push({ path: path ?? "", key, body });
        if (path === "/v1/sessions") return response(current);
        if (path?.endsWith("/messages")) {
          if (rejectMessage) return response({}, 403);
          if (failMessage) {
            failMessage = false;
            throw new TypeError("lost acknowledgement");
          }
          return response(message);
        }
        if (path?.endsWith("/channel-acks"))
          return response({
            ack_id: id,
            challenge_id: id,
            evidence_id: otherPartyAck ? assignmentId : null,
            state: otherPartyAck
              ? "two_party_confirmed"
              : "one_party_acknowledged",
            expires_at: "2099-11-09T10:01:00Z",
          });
        if (path?.endsWith("/confirm-transfer")) {
          current = {
            ...current,
            service_phase: "human_controlled",
            control_epoch: "1",
            owner_id: account,
          };
          return response(current);
        }
        if (path?.endsWith("/observe") && enforceSupervisorScopes) {
          if (
            typeof body !== "object" ||
            body === null ||
            !("scope" in body) ||
            !("expected_revision" in body) ||
            !("expires_at" in body) ||
            typeof body.expires_at !== "string" ||
            body.expected_revision !== "7" ||
            (body.scope !== "observe" && body.scope !== "interrupt")
          )
            return response({}, 422);
          supervisorScope = body.scope;
          scopeExpiresAt = Date.parse(body.expires_at);
          current = {
            ...current,
            revision: String(BigInt(current.revision) + 1n),
          };
        }
        if (path?.endsWith("/takeover") && enforceSupervisorScopes) {
          if (supervisorScope !== "interrupt" || scopeExpiresAt <= Date.now())
            return response({}, 403);
          current = {
            ...current,
            service_phase: "worker_assigned",
            owner_id: account,
            revision: String(BigInt(current.revision) + 1n),
            control_epoch: "1",
          };
          return response(current);
        }
        if (path?.endsWith("/reserve")) return response(assignment);
        if (path?.endsWith("/accept")) {
          current = {
            ...current,
            service_phase: "worker_assigned",
            owner_id: account,
          };
          return response({ ...assignment, revision: "2", state: "accepted" });
        }
        return response({
          operation_id: key,
          state: "committed",
          resource_id: sessionId,
          revision: "2",
          audit_ref: id,
        });
      }
      if (path === `/v1/sessions/${sessionId}/workforce/challenge`)
        return response({
          challenge_id: id,
          assignment_id: assignmentId,
          session_id: sessionId,
          party: "worker",
          nonce: "A".repeat(43),
          transport_generation: "1",
          control_epoch: "0",
          expires_at: "2099-11-09T10:01:00Z",
        });
      if (path === `/v1/sessions/${sessionId}`) {
        if (heldSession) {
          const held = heldSession;
          heldSession = null;
          return held;
        }
        if (blockedRead) return response({}, 403);
        if (
          enforceSupervisorScopes &&
          (supervisorScope === "none" || scopeExpiresAt <= Date.now())
        )
          return response({}, 404);
        return response(current);
      }
      if (path === `/v1/sessions/${sessionId}/messages`)
        return response({ items: [message], next_cursor: null });
      if (path === "/v1/workforce/queue")
        return response({
          items: [
            {
              session_id: sessionId,
              ticket_id: id,
              revision: enforceSupervisorScopes ? "7" : "1",
              mode: "normal",
              state: "pending",
              requested_at: at,
              next_review_at: at,
              wait_estimate_seconds: null,
              connection_confirmed: false,
            },
          ],
          next_cursor: null,
        });
      if (path?.startsWith("/v1/operations/")) {
        if (heldOperation) {
          const held = heldOperation;
          heldOperation = null;
          return held;
        }
        return response({
          operation_id: path.split("/").at(-1),
          state: operationState,
          safe_reason: null,
        });
      }
      return response({}, 404);
    },
  );
  vi.stubGlobal("fetch", fetcher);
  return {
    commands,
    fetcher,
    failCsrf: () => {
      csrfAvailable = false;
    },
    denyMessage: () => {
      rejectMessage = true;
    },
    rejectOperation: () => {
      operationState = "rejected";
    },
    holdOperation: (operationId: string) => {
      heldOperation = new Promise<Response>((resolve) => {
        releaseOperation = () =>
          resolve(
            response({
              operation_id: operationId,
              state: "rejected",
              safe_reason: null,
            }),
          );
      });
    },
    releaseOperation: () => {
      releaseOperation?.();
    },
    denyRead: () => {
      blockedRead = true;
    },
    allowRead: () => {
      blockedRead = false;
    },
    holdSession: () => {
      const saved = { ...current };
      heldSession = new Promise<Response>((resolve) => {
        releaseSession = () => resolve(response(saved));
      });
    },
    releaseSession: () => {
      releaseSession?.();
    },
    switchActor: (nextRole: string, nextAccount: string) => {
      authority = true;
      currentRole = nextRole;
      currentAccount = nextAccount;
    },
    handoff: () => {
      current = {
        ...current,
        service_phase: "handoff_pending",
        owner_id: account,
      };
    },
    otherPartyAck: () => {
      otherPartyAck = true;
    },
    revoke: () => {
      authority = false;
    },
    restore: () => {
      authority = true;
    },
    dropMessage: () => {
      failMessage = true;
    },
  };
}
function controlledStreams() {
  const sources: Stream[] = [];
  class Stream {
    onmessage: (() => void) | null = null;
    onopen: (() => void) | null = null;
    onerror: (() => void) | null = null;
    closed = false;
    handlers = new Map<string, () => void>();
    constructor() {
      sources.push(this);
    }
    addEventListener(name: string, handler: () => void) {
      this.handlers.set(name, handler);
    }
    close() {
      this.closed = true;
    }
  }
  vi.stubGlobal("EventSource", Stream);
  return sources;
}
async function check() {
  fireEvent.click(screen.getByRole("button", { name: "Check manual access" }));
  await screen.findByText(/Current signed-in role:/);
}
async function open() {
  fireEvent.change(await screen.findByLabelText("Conversation ID"), {
    target: { value: sessionId },
  });
  const form = screen.getByLabelText("Conversation ID").closest("form");
  if (!form) throw new Error("Conversation form missing");
  fireEvent.submit(form);
  await screen.findByText("Fictional message");
}
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
describe("manual actor workspaces", () => {
  it("clears an unsent command after failed access so same-account reauthentication can reopen the conversation", async () => {
    const api = fixture();
    render(<ManualService locale="en-CA" />);
    await check();
    await open();
    api.revoke();
    fireEvent.click(screen.getByRole("button", { name: "Ask for a human" }));
    await screen.findByText(/Sign in again. Private information is hidden/);
    expect(api.commands).toHaveLength(0);
    expect(
      screen.queryByRole("button", { name: "Retry the same operation" }),
    ).not.toBeInTheDocument();
    api.restore();
    await check();
    expect(
      screen.getByRole("button", { name: "Open current conversation" }),
    ).toBeEnabled();
    await open();
    expect(screen.getByText("Fictional message")).toBeVisible();
    expect(api.commands).toHaveLength(0);
  });
  it("does not create an unknown mutation when CSRF bootstrap fails before dispatch", async () => {
    const api = fixture();
    render(<ManualService locale="en-CA" />);
    await check();
    await open();
    api.failCsrf();
    fireEvent.click(screen.getByRole("button", { name: "Ask for a human" }));
    await screen.findByText(/Current access or service is unavailable/);
    expect(api.commands).toHaveLength(0);
    expect(
      screen.queryByRole("button", { name: "Retry the same operation" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Open current conversation" }),
    ).toBeEnabled();
  });
  it("retains a genuinely dispatched unknown operation and its original key across same-account reauthentication", async () => {
    const api = fixture();
    render(<ManualService locale="en-CA" />);
    await check();
    await open();
    api.dropMessage();
    fireEvent.change(screen.getByLabelText("Manual message"), {
      target: { value: "Uncertain fictional send" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Send manual message" }),
    );
    await screen.findByText(/The result is unknown/);
    const original = api.commands[0];
    api.revoke();
    fireEvent.click(
      screen.getByRole("button", { name: "Check manual access" }),
    );
    await screen.findByText(/Sign in again. Private information is hidden/);
    api.restore();
    await check();
    expect(
      screen.getByRole("button", { name: "Retry the same operation" }),
    ).toBeEnabled();
    fireEvent.click(
      screen.getByRole("button", { name: "Retry the same operation" }),
    );
    await screen.findByText("Fictional message");
    expect(api.commands).toHaveLength(2);
    expect(api.commands[1]).toEqual(original);
  });
  it("does not carry another actor's pending operation through a period with no current identity", async () => {
    const api = fixture();
    render(<ManualService locale="en-CA" />);
    await check();
    await open();
    api.dropMessage();
    fireEvent.change(screen.getByLabelText("Manual message"), {
      target: { value: "First actor's draft" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Send manual message" }),
    );
    await screen.findByText(/The result is unknown/);
    api.revoke();
    fireEvent.click(
      screen.getByRole("button", { name: "Check manual access" }),
    );
    await screen.findByText(/Sign in again. Private information is hidden/);
    api.switchActor("worker", "10000000-0000-4000-8000-000000000099");
    await check();
    await screen.findByRole("heading", { name: "Worker workspace" });
    expect(
      screen.queryByRole("button", { name: "Retry the same operation" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Check operation status" }),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("Conversation ID")).toHaveValue("");
    expect(api.commands).toHaveLength(1);
  });
  it("retains the original unknown operation when a later replay is denied", async () => {
    const api = fixture();
    render(<ManualService locale="en-CA" />);
    await check();
    await open();
    api.dropMessage();
    fireEvent.change(screen.getByLabelText("Manual message"), {
      target: { value: "Uncertain first effect" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Send manual message" }),
    );
    await screen.findByText(/The result is unknown/);
    const original = api.commands[0];
    await check();
    api.denyMessage();
    fireEvent.click(
      screen.getByRole("button", { name: "Retry the same operation" }),
    );
    await screen.findByText(/The action was rejected/);
    expect(api.commands).toHaveLength(2);
    expect(api.commands[1]).toEqual(original);
    expect(
      screen.getByRole("button", { name: "Check operation status" }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "Retry the same operation" }),
    ).toBeEnabled();
    api.rejectOperation();
    fireEvent.click(
      screen.getByRole("button", { name: "Check operation status" }),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Retry the same operation" }),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.getByRole("button", { name: "Open current conversation" }),
    ).toBeEnabled();
  });
  it("does not publish a held canonical operation status across stream loss", async () => {
    const sources = controlledStreams();
    const api = fixture();
    render(<ManualService locale="en-CA" />);
    await check();
    await open();
    api.dropMessage();
    fireEvent.change(screen.getByLabelText("Manual message"), {
      target: { value: "Pending before stream loss" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Send manual message" }),
    );
    await screen.findByText(/The result is unknown/);
    const operationId = api.commands[0]?.key;
    if (!operationId) throw new Error("Original command key missing");
    api.holdOperation(operationId);
    fireEvent.click(
      screen.getByRole("button", { name: "Check operation status" }),
    );
    await waitFor(() =>
      expect(
        api.fetcher.mock.calls.some(
          ([path]) => path === `/v1/operations/${operationId}`,
        ),
      ).toBe(true),
    );
    act(() => {
      sources[0]?.onerror?.();
    });
    await act(async () => {
      api.releaseOperation();
      await Promise.resolve();
    });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Check operation status" }),
      ).toBeEnabled(),
    );
    expect(
      screen.getByRole("button", { name: "Retry the same operation" }),
    ).toBeEnabled();
    expect(
      screen.queryByText("Current operation status: rejected"),
    ).not.toBeInTheDocument();
    expect(api.commands).toHaveLength(1);
  });
  it.each(["error", "rights_changed"] as const)(
    "invalidates a held SessionView on stream %s and keeps fresh reopen reachable",
    async (loss) => {
      const sources = controlledStreams();
      const api = fixture();
      render(<ManualService locale="en-CA" />);
      await check();
      await open();
      const source = sources[0];
      expect(source).toBeDefined();
      api.holdSession();
      const reads = () =>
        api.fetcher.mock.calls.filter(
          ([path]) => path === `/v1/sessions/${sessionId}`,
        ).length;
      const before = reads();
      fireEvent.click(
        screen.getByRole("button", { name: "Refresh current state" }),
      );
      await waitFor(() => expect(reads()).toBe(before + 1));
      api.denyRead();
      act(() => {
        if (loss === "error") source?.onerror?.();
        else source?.handlers.get(loss)?.();
      });
      expect(
        screen.queryByRole("heading", {
          name: "Current authorized conversation",
        }),
      ).not.toBeInTheDocument();
      const revealed: boolean[] = [];
      const observer = new MutationObserver(() => {
        revealed.push(
          document.body.textContent?.includes(
            "Current authorized conversation",
          ) ?? false,
        );
      });
      observer.observe(document.body, { childList: true, subtree: true });
      await act(async () => {
        api.releaseSession();
        await Promise.resolve();
      });
      await waitFor(() => expect(reads()).toBeGreaterThan(before + 1));
      await waitFor(() =>
        expect(
          screen.getByRole("button", { name: "Check manual access" }),
        ).toBeEnabled(),
      );
      observer.disconnect();
      expect(revealed).not.toContain(true);
      expect(screen.queryByText("Fictional message")).not.toBeInTheDocument();
      api.allowRead();
      act(() => {
        source?.onopen?.();
      });
      expect(await screen.findByText("Fictional message")).toBeVisible();
      expect(sources).toHaveLength(1);
      expect(api.commands).toHaveLength(0);
    },
  );
  it("selects the workspace from current server role and keeps assignment unconnected", async () => {
    fixture("worker");
    render(<ManualService locale="en-CA" />);
    await check();
    expect(
      screen.getByRole("heading", { name: "Worker workspace" }),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Start a fictional conversation" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh queue" }));
    await screen.findByRole("button", { name: "Reserve for myself" });
    expect(
      screen.getByText("Wait estimate is unknown.", { exact: false }),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Reserve for myself" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Accept reservation" }),
    );
    await screen.findByText(
      "Assignment accepted. A connection still requires both parties.",
    );
    expect(
      screen.queryByText(
        "Both parties confirmed the app channel. Human support is connected.",
      ),
    ).not.toBeInTheDocument();
  });
  it("retries a lost response with its exact operation key and preserves the unsent message", async () => {
    const api = fixture();
    render(<ManualService locale="en-CA" />);
    await check();
    await open();
    api.dropMessage();
    fireEvent.change(screen.getByLabelText("Manual message"), {
      target: { value: "My fictional unsent message" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Send manual message" }),
    );
    await screen.findByText(/The result is unknown/);
    expect(screen.queryByText("Fictional message")).not.toBeInTheDocument();
    const first = api.commands[0];
    expect(first?.key).toMatch(/^[a-f0-9-]{36}$/);
    fireEvent.click(
      screen.getByRole("button", { name: "Check operation status" }),
    );
    await screen.findByText("Current operation status: committed");
    fireEvent.click(
      screen.getByRole("button", { name: "Retry the same operation" }),
    );
    await screen.findByText("Fictional message");
    expect(api.commands[1]).toEqual(first);
    expect(screen.getByLabelText("Manual message")).toHaveValue("");
  });
  it("hides private projections after current authority is lost and preserves draft across reauthentication", async () => {
    const api = fixture();
    render(<ManualService locale="en-CA" />);
    await check();
    await open();
    fireEvent.change(screen.getByLabelText("Manual message"), {
      target: { value: "A preserved fictional draft" },
    });
    api.revoke();
    fireEvent.click(
      screen.getByRole("button", { name: "Refresh current state" }),
    );
    await screen.findByText(/Sign in again. Private information is hidden/);
    expect(screen.queryByText("Fictional message")).not.toBeInTheDocument();
    api.restore();
    await check();
    await open();
    expect(screen.getByLabelText("Manual message")).toHaveValue(
      "A preserved fictional draft",
    );
  });
  it("requires explicit end choice and permits human request before disclosure", async () => {
    const api = fixture();
    render(<ManualService locale="en-CA" />);
    await check();
    await open();
    expect(
      screen.getByRole("button", { name: "Submit fictional situation" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Ask for a human" }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "End my conversation" }),
    ).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/I choose to end this conversation/));
    fireEvent.click(
      screen.getByRole("button", { name: "End my conversation" }),
    );
    await waitFor(() => expect(api.commands).toHaveLength(1));
    expect(api.commands[0]?.body).toEqual({
      expected_revision: "1",
      reason: "user_choice",
    });
  });
  it("confirms a handoff only after current two-party evidence and refreshes a worker ACK with its original key", async () => {
    const api = fixture("worker");
    api.handoff();
    render(<ManualService locale="en-CA" />);
    await check();
    await open();
    fireEvent.click(
      screen.getByRole("button", { name: "Confirm my app channel" }),
    );
    await screen.findByText(
      "Your channel was acknowledged. The other party must confirm independently.",
    );
    expect(
      screen.queryByRole("button", { name: "Confirm handoff" }),
    ).not.toBeInTheDocument();
    api.otherPartyAck();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Check the other party’s channel confirmation",
      }),
    );
    await screen.findByRole("button", { name: "Confirm handoff" });
    expect(api.commands[1]?.key).toBe(api.commands[0]?.key);
    fireEvent.click(screen.getByRole("button", { name: "Confirm handoff" }));
    await screen.findByText(
      "Both parties confirmed the app channel. Human support is connected.",
    );
    expect(api.commands[2]?.body).toEqual({
      expected_revision: "1",
      assignment_id: assignmentId,
      channel_evidence_id: assignmentId,
      worker_ack_id: id,
      expected_control_epoch: "0",
    });
  });
  it("keeps both-party channel liveness during ACK and reauthorizes each stream update", async () => {
    const sources: { closed: boolean; onmessage: (() => void) | null }[] = [];
    class Stream {
      closed = false;
      onmessage: (() => void) | null = null;
      onopen: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor() {
        sources.push(this);
      }
      addEventListener() {
        /* Named events use the same current-projection handler. */
      }
      close() {
        this.closed = true;
      }
    }
    vi.stubGlobal("EventSource", Stream);
    const api = fixture("worker");
    api.handoff();
    render(<ManualService locale="en-CA" />);
    await check();
    await open();
    // The message projection can render before the passive subscription effect.
    // Wait for the resource this scenario exercises instead of assuming a flush.
    await waitFor(() => expect(sources).toHaveLength(1));
    fireEvent.click(
      screen.getByRole("button", { name: "Confirm my app channel" }),
    );
    await screen.findByText(
      "Your channel was acknowledged. The other party must confirm independently.",
    );
    expect(sources).toHaveLength(1);
    expect(sources[0]?.closed).toBe(false);
    api.revoke();
    act(() => {
      sources[0]?.onmessage?.();
    });
    await screen.findByText(/Sign in again. Private information is hidden/);
    expect(screen.queryByText("Fictional message")).not.toBeInTheDocument();
    await waitFor(() => expect(sources[0]?.closed).toBe(true));
  });
  it("keeps observing supervisors read-only when they do not own the conversation", async () => {
    fixture("supervisor");
    render(<ManualService locale="en-CA" />);
    await check();
    // This fixture represents a separately granted observation. The API must
    // enforce the grant; the UI never derives it from the role label.
    await open();
    fireEvent.change(screen.getByLabelText("Manual message"), {
      target: { value: "No writer authority" },
    });
    expect(
      screen.getByRole("button", { name: "Send manual message" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", {
        name: "Take over as accountable supervisor",
      }),
    ).toBeDisabled();
  });
  it("keeps observation read-only and requires explicit scoped interruption confirmation before takeover", async () => {
    const api = fixture("supervisor", true);
    render(<ManualService locale="en-CA" />);
    await check();
    fireEvent.click(screen.getByRole("button", { name: "Refresh queue" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Observe for five minutes" }),
    );
    await waitFor(() => expect(api.commands).toHaveLength(1));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Check manual access" }),
      ).toBeEnabled(),
    );
    await open();
    expect(api.commands[0]?.body).toMatchObject({
      expected_revision: "7",
      scope: "observe",
    });
    expect(
      screen.getByRole("button", {
        name: "Take over as accountable supervisor",
      }),
    ).toBeDisabled();
    fireEvent.click(
      screen.getByRole("button", { name: "Prepare interruption" }),
    );
    expect(
      screen.getByRole("button", {
        name: "Confirm interruption scope for five minutes",
      }),
    ).toBeDisabled();
    fireEvent.click(
      screen.getByLabelText(
        /I intend to interrupt this conversation as supervisor/,
      ),
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Confirm interruption scope for five minutes",
      }),
    );
    await screen.findByText(
      "Interruption scope was acknowledged. Refresh the conversation before takeover.",
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", {
          name: "Take over as accountable supervisor",
        }),
      ).toBeEnabled(),
    );
    const body = api.commands[1]?.body;
    expect(body).toMatchObject({ expected_revision: "7", scope: "interrupt" });
    if (
      typeof body !== "object" ||
      body === null ||
      !("expires_at" in body) ||
      typeof body.expires_at !== "string"
    )
      throw new Error("Missing scoped expiry");
    expect(Object.keys(body).sort()).toEqual([
      "expected_revision",
      "expires_at",
      "scope",
    ]);
    expect(Date.parse(body.expires_at)).toBeGreaterThan(Date.now());
    expect(Date.parse(body.expires_at)).toBeLessThanOrEqual(
      Date.now() + 300000,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Take over as accountable supervisor",
      }),
    );
    await screen.findByText("Worker assigned — connection unconfirmed");
    expect(api.commands[2]?.body).toEqual({
      expected_revision: "3",
      worker_id: account,
    });
    expect(
      screen.getByRole("button", {
        name: "Take over as accountable supervisor",
      }),
    ).toBeDisabled();
    expect(
      screen.queryByText(
        "Both parties confirmed the app channel. Human support is connected.",
      ),
    ).not.toBeInTheDocument();
  });
  it("offers the French workspace while preserving an unsent fictional situation", async () => {
    fixture();
    const rendered = render(<ManualService locale="en-CA" />);
    await check();
    await open();
    fireEvent.change(screen.getByLabelText("Fictional situation"), {
      target: { value: "A fictional draft" },
    });
    rendered.rerender(<ManualService locale="fr-CA" />);
    expect(
      screen.getByRole("heading", { name: "Soutien manuel" }),
    ).toBeVisible();
    expect(screen.getByLabelText("Situation fictive")).toHaveValue(
      "A fictional draft",
    );
    expect(
      screen.getByRole("button", { name: "Demander une personne" }),
    ).toBeEnabled();
  });
});
