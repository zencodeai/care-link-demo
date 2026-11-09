// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TrustAndHelp } from "./TrustAndHelp";
import { HelpApp } from "./HelpApp";
import {
  authorizationUrl,
  configuredOrigin,
  decodeSession,
  decodeProof,
  csrf,
} from "./api";

const id = "11111111-1111-4111-8111-111111111111";
const session = {
  account_id: id,
  role: "pid",
  assurance: "AL1",
  revision: "1",
  auth_time: "2099-01-01T00:00:00Z",
  expires_at: "2099-01-01T01:00:00Z",
};
const help = {
  id,
  revision: "1",
  state: "recorded",
  created_at: "2026-11-08T00:00:00Z",
  connection_confirmed: false,
};
function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
function fixture(
  fetcher: (url: string, init?: RequestInit) => Response | Promise<Response>,
) {
  const spy = vi.fn((url: string, init?: RequestInit) =>
    Promise.resolve().then(() => fetcher(url, init)),
  );
  vi.stubGlobal("fetch", spy);
  return spy;
}
function panel() {
  return within(
    screen.getByRole("region", { name: "Separate private-help account" }),
  );
}
async function checkHelp() {
  fireEvent.click(panel().getByRole("button", { name: "Check sign-in" }));
  await panel().findByText(/Current server role/);
}
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("private identity and opaque help surfaces", () => {
  it("shows disabled unconfigured capabilities without private network calls or a false independent link", () => {
    const fetcher = fixture(() => json({}));
    render(<TrustAndHelp locale="en-CA" />);
    expect(fetcher).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeDisabled();
    expect(
      screen.getByText(/separate HTTPS private-help origin is not configured/),
    ).toBeVisible();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
  it("keeps server roles authoritative even when a worker sign-in role is selected", async () => {
    fixture(() => json(session));
    render(
      <TrustAndHelp
        locale="en-CA"
        helpOrigin="https://help.demo"
        surface="help"
      />,
    );
    await checkHelp();
    fireEvent.change(panel().getByLabelText("Requested sign-in role"), {
      target: { value: "worker" },
    });
    expect(panel().getByText(/Current server role: pid/)).toBeVisible();
    expect(
      panel().getByRole("button", { name: "Accept request" }),
    ).toBeDisabled();
    expect(
      panel().getByRole("button", { name: "Request human help" }),
    ).toBeEnabled();
  });
  it("creates an opaque request through CSRF and displays acceptance without claiming a connection", async () => {
    const fetcher = fixture((url, init) => {
      if (url.endsWith("/create-intent")) return json({ operation_id: id });
      if (url.endsWith("/session")) return json(session);
      if (url.endsWith("/csrf")) return json({ csrf_token: "x".repeat(43) });
      if (init?.method === "POST") return json(help);
      return json({ ...help, state: "accepted_unconnected", revision: "2" });
    });
    render(
      <TrustAndHelp
        locale="en-CA"
        helpOrigin="https://help.demo"
        surface="help"
      />,
    );
    await checkHelp();
    fireEvent.click(
      panel().getByRole("button", { name: "Request human help" }),
    );
    expect(
      await panel().findByText(
        "Request recorded. A staffed connection is not confirmed.",
      ),
    ).toBeVisible();
    const command = fetcher.mock.calls.find(
      ([url, init]) => url.endsWith("/requests") && init?.method === "POST",
    );
    expect(command?.[0]).toBe("/help/v1/requests");
    expect(
      JSON.parse(
        typeof command?.[1]?.body === "string" ? command[1].body : "null",
      ),
    ).toEqual({
      locale: "en-CA",
      jurisdiction: null,
    });
    expect(command?.[1]?.credentials).toBe("include");
    expect(command?.[1]?.headers).toMatchObject({
      "X-CSRF-Token": "x".repeat(43),
    });
    fireEvent.click(panel().getByRole("button", { name: "Check help status" }));
    expect(
      await panel().findByText(
        "A worker accepted this request. You are not connected.",
      ),
    ).toBeVisible();
  });
  it("clears stale private results on identity loss and retains the independent static destination", async () => {
    let unavailable = false;
    fixture((url) => {
      if (unavailable) return json({}, 503);
      if (url.endsWith("/create-intent")) return json({ operation_id: id });
      if (url.endsWith("/session")) return json(session);
      if (url.endsWith("/csrf")) return json({ csrf_token: "x".repeat(43) });
      return json(help);
    });
    render(
      <TrustAndHelp
        locale="en-CA"
        helpOrigin="https://help.demo"
        surface="help"
        staticOrigin="https://static.demo"
      />,
    );
    await checkHelp();
    fireEvent.click(
      panel().getByRole("button", { name: "Request human help" }),
    );
    await panel().findByText(/Request recorded/);
    unavailable = true;
    fireEvent.click(panel().getByRole("button", { name: "Check help status" }));
    await panel().findByText(/Current authority is unavailable/);
    expect(panel().queryByText(/Request recorded/)).not.toBeInTheDocument();
    expect(
      panel().getByRole("button", { name: "Request human help" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("link", { name: "Independent fallback information" }),
    ).toHaveAttribute("href", "https://static.demo/fallback?locale=en-CA");
  });
  it.each(["create", "prepare"] as const)(
    "recovers a lost %s reply after full remount with the server-held create key",
    async (lostResponse) => {
      let dropped = false;
      let prepared = false;
      let effects = 0;
      const storedRequests = new Set<string>();
      const keys: (string | null)[] = [];
      fixture((url, init) => {
        if (url.endsWith("/session")) return json(session);
        if (url.endsWith("/csrf")) return json({ csrf_token: "x".repeat(43) });
        if (url.endsWith("/create-intent")) {
          prepared = true;
          expect(new Headers(init?.headers).get("Idempotency-Key")).toBeNull();
          if (lostResponse === "prepare" && !dropped) {
            dropped = true;
            throw new TypeError("prepare reply lost");
          }
          return json({ operation_id: id });
        }
        if (url.endsWith("/requests") && init?.method === "POST") {
          const key = new Headers(init.headers).get("Idempotency-Key");
          keys.push(key);
          expect(key).toBe(id);
          if (key && !storedRequests.has(key)) {
            storedRequests.add(key);
            effects += 1;
          }
          if (lostResponse === "create" && !dropped) {
            dropped = true;
            throw new TypeError("committed create reply lost");
          }
          return json(help);
        }
        return json({}, 404);
      });
      const first = render(<TrustAndHelp locale="en-CA" surface="help" />);
      await checkHelp();
      fireEvent.click(
        panel().getByRole("button", { name: "Request human help" }),
      );
      await panel().findByText(/No confirmed result was received/);
      expect(prepared).toBe(true);
      first.unmount(); // Provider navigation destroys every component/ref and retry map.
      render(<TrustAndHelp locale="en-CA" surface="help" />);
      await checkHelp();
      fireEvent.click(
        panel().getByRole("button", { name: "Request human help" }),
      );
      await panel().findByText(/Request recorded/);
      expect(effects).toBe(1);
      expect(keys).toEqual(lostResponse === "create" ? [id, id] : [id]);
    },
  );
  it("denies forged connection results and expired sessions", async () => {
    fixture((url) =>
      url.endsWith("/session")
        ? json(session)
        : json({ ...help, connection_confirmed: true }),
    );
    render(
      <TrustAndHelp
        locale="en-CA"
        helpOrigin="https://help.demo"
        surface="help"
      />,
    );
    await checkHelp();
    fireEvent.change(panel().getByLabelText("Help request ID"), {
      target: { value: id },
    });
    fireEvent.click(panel().getByRole("button", { name: "Check help status" }));
    await panel().findByText(/incompatible result/);
    expect(
      panel().getByRole("button", { name: "Request human help" }),
    ).toBeDisabled();
    expect(() =>
      decodeSession(
        JSON.stringify({ ...session, expires_at: "2020-01-01T00:00:00Z" }),
      ),
    ).toThrow();
  });
  it("rejects an unexpected provider destination before navigating", async () => {
    const navigate = vi.fn();
    fixture((url) =>
      url.endsWith("/csrf")
        ? json({ csrf_token: "x".repeat(43) })
        : json({
            intent_id: id,
            authorization_url: "https://attacker.demo/auth",
            expires_at: "2099-01-01T00:00:00Z",
          }),
    );
    render(
      <TrustAndHelp
        locale="en-CA"
        oidcOrigin="https://id.demo"
        navigate={navigate}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByText(/incompatible result/);
    expect(navigate).not.toHaveBeenCalled();
    expect(configuredOrigin("https://id.demo/path")).toBeNull();
    expect(() =>
      authorizationUrl("https://id.demo@attacker.demo/auth", "https://id.demo"),
    ).toThrow();
  });
  it("retains an unsent request ID when switching EN/FR and reports pending support honestly", async () => {
    fixture(() => json(session));
    const { rerender } = render(
      <TrustAndHelp
        locale="en-CA"
        helpOrigin="https://help.demo"
        surface="help"
      />,
    );
    await checkHelp();
    fireEvent.change(panel().getByLabelText("Help request ID"), {
      target: { value: id },
    });
    rerender(
      <TrustAndHelp
        locale="fr-CA"
        helpOrigin="https://help.demo"
        surface="help"
      />,
    );
    expect(screen.getByLabelText("Identifiant de demande d’aide")).toHaveValue(
      id,
    );
    expect(
      screen.getByText(/L’admission des participants reste désactivée/),
    ).toBeVisible();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Demander une aide humaine" }),
      ).toBeEnabled(),
    );
  });
  it("restores a session-bound ceremony after redirect and confirms with fresh server proof", async () => {
    const fetcher = fixture((url, init) => {
      if (url.endsWith("/session")) {
        const response = json(session);
        response.headers.set("X-Ceremony-Id", id);
        return response;
      }
      if (url.endsWith("/csrf")) return json({ csrf_token: "x".repeat(43) });
      if (url.includes("/step-up/proof?")) return json({ proof_intent_id: id });
      if (init?.method === "POST")
        return json({
          ceremony_id: id,
          state: "cooling_off",
          not_before: "2099-01-01T00:05:00Z",
          expires_at: "2099-01-01T01:00:00Z",
          authorization_url: null,
        });
      return json({}, 404);
    });
    render(<TrustAndHelp locale="en-CA" oidcOrigin="https://id.demo" />);
    fireEvent.click(screen.getByRole("button", { name: "Check sign-in" }));
    const confirm = await screen.findByRole("button", {
      name: "Confirm verification",
    });
    fireEvent.click(confirm);
    await screen.findByText(/cooling_off/);
    const posted = fetcher.mock.calls.find(([url]) =>
      url.endsWith("/step-up/confirm"),
    );
    const body = posted?.[1]?.body;
    expect(typeof body === "string" ? JSON.parse(body) : null).toEqual({
      ceremony_id: id,
      proof_intent_id: id,
      expected_revision: "1",
    });
    expect(screen.queryByText(/AL3/)).not.toBeInTheDocument();
  });
  it("serves the help entry without contacting the core development API", () => {
    const fetcher = fixture(() => json({}));
    render(<HelpApp />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Separate private-help account",
    );
    expect(screen.queryByText("Main account")).not.toBeInTheDocument();
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("rejects duplicate and unknown BFF proof metadata instead of continuing a private mutation", async () => {
    fixture(
      () =>
        new Response(
          '{"csrf_token":"' +
            "x".repeat(43) +
            '","csrf_token":"' +
            "y".repeat(43) +
            '"}',
          { headers: { "Content-Type": "application/json" } },
        ),
    );
    await expect(csrf("", new AbortController().signal)).rejects.toThrow();
    expect(() =>
      decodeProof(JSON.stringify({ proof_intent_id: id, role: "worker" })),
    ).toThrow();
    expect(() =>
      decodeProof(
        '{"proof_intent_id":"' + id + '","proof_intent_id":"' + id + '"}',
      ),
    ).toThrow();
  });
  it("restores the original French request settings after English remount conflicts without creating a replacement", async () => {
    let dropped = false;
    let effects = 0;
    const keys: (string | null)[] = [];
    const preparedBodies: unknown[] = [];
    fixture((url, init) => {
      if (url.endsWith("/session")) return json(session);
      if (url.endsWith("/csrf")) return json({ csrf_token: "x".repeat(43) });
      if (url.endsWith("/create-intent")) {
        preparedBodies.push(init?.body);
        return init?.body ===
          JSON.stringify({ locale: "fr-CA", jurisdiction: null })
          ? json({ operation_id: id })
          : json({}, 409);
      }
      if (url.endsWith("/requests")) {
        const key = new Headers(init?.headers).get("Idempotency-Key");
        if (!keys.includes(key)) effects += 1;
        keys.push(key);
        if (!dropped) {
          dropped = true;
          throw new TypeError("committed French create reply lost");
        }
        return json(help);
      }
      return json({}, 404);
    });
    const first = render(<HelpApp />);
    fireEvent.change(screen.getByLabelText("Language"), {
      target: { value: "fr-CA" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Vérifier la connexion" }),
    );
    await screen.findByText(/Rôle actuel selon le serveur/);
    fireEvent.click(
      screen.getByRole("button", { name: "Demander une aide humaine" }),
    );
    await screen.findByText(/Aucun résultat confirmé/);
    first.unmount();
    render(<HelpApp />);
    await checkHelp();
    fireEvent.click(screen.getByRole("button", { name: "Request human help" }));
    await screen.findByText(
      /restore its original language and fictional jurisdiction/,
    );
    expect(keys).toEqual([id]);
    fireEvent.change(screen.getByLabelText("Language"), {
      target: { value: "fr-CA" },
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      /rétablissez sa langue et sa juridiction fictive d’origine/,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Demander une aide humaine" }),
    );
    await screen.findByText(/Demande enregistrée/);
    expect(effects).toBe(1);
    expect(keys).toEqual([id, id]);
    expect(preparedBodies).toEqual([
      JSON.stringify({ locale: "fr-CA", jurisdiction: null }),
      JSON.stringify({ locale: "en-CA", jurisdiction: null }),
      JSON.stringify({ locale: "fr-CA", jurisdiction: null }),
    ]);
  });
});
