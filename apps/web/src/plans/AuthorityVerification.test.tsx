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
import { RequestFailure } from "../trust/api";
import { AuthorityVerification } from "./AuthorityVerification";
import type { PlansChannel } from "./usePlans";

const account = "10000000-0000-4000-8000-000000000001";
const subject = "30000000-0000-4000-8000-000000000001";
const provider = "https://issuer.example";
const authorization = provider + "/authorize?state=server-issued-state";
const ceremony = {
  ceremony_id: "60000000-0000-4000-8000-000000000001",
  state: "pending",
  not_before: "2026-11-16T10:00:00Z",
  expires_at: "2099-11-16T10:00:00Z",
  authorization_url: authorization,
};
function json(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    headers: { "Content-Type": "application/json" },
  });
}
function fixture(refuseRun = false) {
  const errors: unknown[] = [],
    events: string[] = [];
  const controller = new AbortController();
  const run: PlansChannel["run"] = async (work) => {
    if (refuseRun) return;
    try {
      await work(controller.signal);
    } catch (error) {
      errors.push(error);
    }
  };
  const channel: PlansChannel = {
    account: {
      account_id: account,
      role: "pid",
      assurance: "AL2",
      revision: "7",
      auth_time: "2026-11-16T10:00:00Z",
      expires_at: ceremony.expires_at,
    },
    session: {
      id: "20000000-0000-4000-8000-000000000001",
      revision: "4",
      subject_id: subject,
      participant_kind: "pid",
    },
    currentPlan: null,
    ownReports: [],
    grant: null,
    directory: null,
    notice: "ready",
    busy: false,
    recovering: false,
    pending: null,
    check: async () => {},
    loadSession: async () => {},
    loadPlan: async () => {},
    loadGrant: async () => {},
    command: () => {},
    retry: () => {},
    reconcile: () => {},
    run,
    trackPendingVerification: () => {},
    loadSelection: async () => {},
    review: undefined,
    reviewWork: () => undefined,
    refreshCurrent: async () => {},
    adoptReviewView: () => {},
  };
  const opened = {
    opener: window as Window | null,
    location: { href: "about:blank" },
    close: vi.fn(),
  };
  const open = vi.spyOn(window, "open").mockImplementation(() => {
    events.push("open");
    return opened as unknown as Window;
  });
  const verified = vi.fn();
  vi.stubEnv("VITE_OIDC_ORIGIN", provider);
  render(
    <AuthorityVerification
      channel={channel}
      locale="en-CA"
      onVerified={verified}
    />,
  );
  return { channel, controller, errors, events, open, opened, verified };
}
function start(): void {
  fireEvent.click(screen.getByRole("button", { name: "Verify my authority" }));
}
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});
describe("authority verification popup lifecycle", () => {
  it("opens no popup and sends no step-up when the channel refuses stale enabled work", () => {
    const f = fixture(true);
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    start();
    expect(f.open).not.toHaveBeenCalled();
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("closes its own blank popup when the real step-up request fails", async () => {
    const f = fixture();
    const fetcher = vi.fn((path: string) =>
      path === "/v1/auth/csrf"
        ? Promise.resolve(json({ csrf_token: "a".repeat(43) }))
        : Promise.reject(new TypeError("Unavailable")),
    );
    vi.stubGlobal("fetch", fetcher);
    start();
    await waitFor(() => expect(f.opened.close).toHaveBeenCalledOnce());
    expect(f.opened.location.href).toBe("about:blank");
    expect(f.errors).toHaveLength(1);
    expect(f.errors[0]).toBeInstanceOf(RequestFailure);
  });
  it("opens synchronously before asynchronous CSRF and navigates only to the validated provider", async () => {
    const f = fixture();
    let releaseCsrf: ((value: Response) => void) | undefined;
    const fetcher = vi.fn((path: string, init?: RequestInit) => {
      f.events.push(path);
      if (path === "/v1/auth/csrf")
        return new Promise<Response>((resolve) => {
          releaseCsrf = resolve;
        });
      expect(path).toBe("/v1/auth/step-up");
      if (typeof init?.body !== "string")
        throw new Error("Expected step-up JSON body");
      expect(JSON.parse(init.body)).toEqual({
        purpose: "plan_edit",
        resource_id: subject,
        expected_revision: "7",
      });
      expect(new Headers(init?.headers).get("X-CSRF-Token")).toBe(
        "a".repeat(43),
      );
      return Promise.resolve(json(ceremony));
    });
    vi.stubGlobal("fetch", fetcher);
    start();
    expect(f.events).toEqual(["open", "/v1/auth/csrf"]);
    expect(f.opened.location.href).toBe("about:blank");
    await act(async () => {
      if (!releaseCsrf) throw new Error("Missing pending actual CSRF request");
      releaseCsrf(json({ csrf_token: "a".repeat(43) }));
      await Promise.resolve();
    });
    await waitFor(() => expect(f.opened.location.href).toBe(authorization));
    expect(f.opened.opener).toBeNull();
    expect(f.opened.close).not.toHaveBeenCalled();
    expect(f.errors).toEqual([]);
    expect(f.verified).not.toHaveBeenCalledWith(ceremony.ceremony_id);
    expect(
      screen.getByRole("button", { name: "Confirm verification" }),
    ).toBeVisible();
  });
  it("closes the popup and rejects an authorization URL outside the configured provider", async () => {
    const f = fixture();
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string) =>
        Promise.resolve(
          json(
            path === "/v1/auth/csrf"
              ? { csrf_token: "a".repeat(43) }
              : {
                  ...ceremony,
                  authorization_url: "https://other.example/authorize",
                },
          ),
        ),
      ),
    );
    start();
    await waitFor(() => expect(f.opened.close).toHaveBeenCalledOnce());
    expect(f.opened.location.href).toBe("about:blank");
    expect(f.errors).toHaveLength(1);
    expect(f.errors[0]).toBeInstanceOf(RequestFailure);
    expect(f.verified).not.toHaveBeenCalledWith(ceremony.ceremony_id);
  });
  it("closes a blank popup when a valid ceremony has no provider navigation", async () => {
    const f = fixture();
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string) =>
        Promise.resolve(
          json(
            path === "/v1/auth/csrf"
              ? { csrf_token: "a".repeat(43) }
              : { ...ceremony, authorization_url: null },
          ),
        ),
      ),
    );
    start();
    await waitFor(() => expect(f.opened.close).toHaveBeenCalledOnce());
    expect(f.errors).toEqual([]);
    expect(
      screen.getByRole("button", { name: "Confirm verification" }),
    ).toBeVisible();
  });
  it("closes the un-navigated popup when the active step-up is aborted", async () => {
    const f = fixture();
    const fetcher = vi.fn((path: string, init?: RequestInit) => {
      if (path === "/v1/auth/csrf")
        return Promise.resolve(json({ csrf_token: "a".repeat(43) }));
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener(
          "abort",
          () => reject(new DOMException("Aborted", "AbortError")),
          { once: true },
        );
      });
    });
    vi.stubGlobal("fetch", fetcher);
    start();
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    await act(async () => {
      f.controller.abort();
      await Promise.resolve();
    });
    await waitFor(() => expect(f.opened.close).toHaveBeenCalledOnce());
    expect(f.opened.location.href).toBe("about:blank");
    expect(f.errors).toHaveLength(1);
  });
});
