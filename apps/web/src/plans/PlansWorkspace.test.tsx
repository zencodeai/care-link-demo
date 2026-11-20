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
import { operatingStates, type DirectoryEntry } from "./api";
import { optionAvailability } from "./DirectoryOptions";

const account = "10000000-0000-4000-8000-000000000001";
const sessionId = "20000000-0000-4000-8000-000000000001";
const subject = "30000000-0000-4000-8000-000000000001";
const planId = "40000000-0000-4000-8000-000000000001";
const assertionId = "50000000-0000-4000-8000-000000000001";
const ceremonyId = "60000000-0000-4000-8000-000000000001";
const recipient = "70000000-0000-4000-8000-000000000001";
const grantId = "80000000-0000-4000-8000-000000000001";
const at = "2026-11-16T10:00:00Z";
const future = "2099-11-16T10:00:00Z";
const assertion = {
  id: assertionId,
  revision: "1",
  subject_id: subject,
  field: "plan.strategies",
  value: { kind: "text", text: "Fictional private strategy" },
  author_id: account,
  source: null,
  verification: "unverified",
  supersedes_id: null,
  effective_at: at,
};
const plan = {
  id: planId,
  subject_id: subject,
  revision: "1",
  state: "active",
  fields: [assertion],
  retired_at: null,
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
function entry(
  state: DirectoryEntry["facts"]["operating_state"],
  index = 0,
): DirectoryEntry {
  return {
    id: `90000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
    revision: "1",
    facts: {
      name: `Fictional ${state}`,
      jurisdictions: ["CA-XX"],
      languages: ["en-CA", "fr-CA"],
      age_scope: "all_fixture",
      availability: "available_fixture",
      police_involvement: "unknown",
      qualifications: [],
      alternative_service_id: null,
      hours_description: "Fictional hours require current confirmation",
      operating_state: state,
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
}
function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
function fixture(role = "pid") {
  let denied = false,
    lost = false;
  let signedIn = true;
  let differentSubject = false;
  let currentAccount = account;
  let reportsDenied = false;
  let reportLost = false;
  let directoryReader: ((id: string) => Promise<Response>) | null = null;
  const reportOutcomes = new Map<string, object>();
  let reports: unknown[] = [];
  const commands: {
    path: string;
    key: string | null;
    body: Record<string, unknown>;
  }[] = [];
  const fetcher = vi.fn(
    async (input: string | URL | Request, init?: RequestInit) => {
      await Promise.resolve();
      const path =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url;
      if (path === "/v1/auth/session")
        return signedIn
          ? response({
              account_id: currentAccount,
              role,
              assurance: "AL2",
              revision: "2",
              auth_time: at,
              expires_at: future,
            })
          : response({}, 401);
      if (path === "/v1/auth/csrf")
        return response({ csrf_token: "a".repeat(43) });
      if (path.startsWith("/v1/directory/") && init?.method !== "POST")
        return directoryReader
          ? directoryReader(path.slice("/v1/directory/".length))
          : response({}, 503);
      if (path === `/v1/sessions/${sessionId}`)
        return response({
          ...conversation,
          participant_kind: role === "pid" ? "pid" : "carer",
        });
      if (path === `/v1/sessions/${sessionId}/own-reports`)
        return reportsDenied
          ? response({}, 403)
          : response({ items: reports, next_cursor: null });
      if (path === `/v1/plans/${planId}`)
        return denied
          ? response({}, 403)
          : response(
              differentSubject
                ? {
                    ...plan,
                    subject_id: recipient,
                    fields: [{ ...assertion, subject_id: recipient }],
                  }
                : plan,
            );
      if (path.startsWith("/v1/operations/"))
        return response({
          operation_id: path.split("/").at(-1),
          state: "committed",
          safe_reason: null,
        });
      if (path.startsWith("/v1/auth/step-up/proof"))
        return response({ proof_intent_id: assertionId });
      if (path === `/v1/consents/${grantId}`)
        return response({
          id: grantId,
          revision: "1",
          scope: {
            session_id: sessionId,
            subject_id: subject,
            purpose: "plan",
            fields: ["plan.strategies"],
            recipient_id: recipient,
          },
          recipient: { kind: "account", account_id: recipient },
          grantor_id: account,
          scope_digest: "b".repeat(64),
          effective_at: at,
          expires_at: future,
          revoked_at: null,
        });
      if (init?.method === "POST") {
        const body: Record<string, unknown> =
          typeof init.body === "string"
            ? (JSON.parse(init.body) as Record<string, unknown>)
            : {};
        commands.push({
          path,
          key: new Headers(init.headers).get("Idempotency-Key"),
          body,
        });
        if (path === "/v1/plans") {
          if (lost) {
            lost = false;
            throw new TypeError("lost acknowledgement");
          }
          return response(plan);
        }
        if (path === `/v1/plans/${planId}/fields`)
          return response({
            ...plan,
            revision: "2",
            fields: [
              ...plan.fields,
              { ...assertion, id: recipient, value: body.value },
            ],
          });
        if (path === `/v1/sessions/${sessionId}/assertions`) {
          const key = new Headers(init.headers).get("Idempotency-Key") ?? "";
          const previous = reportOutcomes.get(key);
          if (previous) return response(previous);
          const report = {
            ...assertion,
            author_id: currentAccount,
            field: "observations",
            value: body.value,
          };
          reportOutcomes.set(key, report);
          reports = [...reports, report];
          if (reportLost) {
            reportLost = false;
            throw new TypeError("lost report acknowledgement");
          }
          return response(report);
        }
        if (path === "/v1/directory/search")
          return response({
            items: operatingStates.map((state, index) => entry(state, index)),
            next_cursor: null,
          });
        if (path === "/v1/auth/step-up" || path === "/v1/auth/step-up/confirm")
          return response({
            ceremony_id: ceremonyId,
            state: path.endsWith("confirm") ? "verified" : "pending",
            not_before: at,
            expires_at: future,
            authorization_url: null,
          });
        if (path === "/v1/consents")
          return response({
            id: grantId,
            revision: "1",
            scope: {
              session_id: sessionId,
              subject_id: subject,
              purpose: "plan",
              fields: body.fields,
              recipient_id: recipient,
            },
            recipient: { kind: "account", account_id: recipient },
            grantor_id: account,
            scope_digest: "b".repeat(64),
            effective_at: body.effective_at,
            expires_at: body.expires_at,
            revoked_at: null,
          });
      }
      return response({}, 503);
    },
  );
  vi.stubGlobal("fetch", fetcher);
  return {
    commands,
    readDirectory: (reader: (id: string) => Promise<Response>) => {
      directoryReader = reader;
    },
    loseReport: () => {
      reportLost = true;
    },
    switchAccount: () => {
      currentAccount = recipient;
    },
    denyReports: () => {
      reportsDenied = true;
    },
    seedReport: (author = account) => {
      reports = [{ ...assertion, field: "observations", author_id: author }];
    },
    otherSubject: () => {
      differentSubject = true;
    },
    deny: () => {
      denied = true;
    },
    signOut: () => {
      signedIn = false;
    },
    signIn: () => {
      signedIn = true;
    },
    lose: () => {
      lost = true;
    },
  };
}
async function loadConversation() {
  fireEvent.change(screen.getByLabelText("Conversation ID"), {
    target: { value: sessionId },
  });
  fireEvent.click(screen.getByRole("button", { name: "Load conversation" }));
  await screen.findByRole("button", { name: "Create my plan" });
}
async function loadPlan() {
  fireEvent.change(screen.getByLabelText("Plan ID"), {
    target: { value: planId },
  });
  fireEvent.click(screen.getByRole("button", { name: "Open current plan" }));
  await screen.findByText("Fictional private strategy");
}
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.useRealTimers();
});
describe("plans and sharing", () => {
  it("clears disclosed fields when a current read loses permission", async () => {
    const f = fixture("carer");
    render(<PlansWorkspace locale="en-CA" />);
    await loadPlan();
    expect(
      screen.queryByRole("button", { name: "Append my field version" }),
    ).not.toBeInTheDocument();
    f.deny();
    fireEvent.click(
      screen.getByRole("button", { name: "Check current access" }),
    );
    await waitFor(() =>
      expect(
        screen.queryByText("Fictional private strategy"),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("alert")).toHaveTextContent("rejected");
  });
  it("reconciles lost creation acknowledgement using the same logical operation", async () => {
    const f = fixture();
    render(<PlansWorkspace locale="en-CA" />);
    await loadConversation();
    f.lose();
    fireEvent.click(screen.getByRole("button", { name: "Create my plan" }));
    await waitFor(() =>
      expect(
        screen.getAllByText(/The outcome is unknown/).length,
      ).toBeGreaterThan(0),
    );
    expect(
      screen.getByRole("button", { name: "Load conversation" }),
    ).toBeDisabled();
    fireEvent.click(
      screen.getByRole("button", { name: "Reconcile operation" }),
    );
    await screen.findByText("Fictional private strategy");
    const creates = f.commands.filter(
      (command) => command.path === "/v1/plans",
    );
    expect(creates).toHaveLength(2);
    expect(creates[0]?.key).toBe(creates[1]?.key);
    expect(creates[0]?.body).toEqual({
      subject_id: subject,
      expected_revision: "4",
    });
  });
  it("previews exact recipient, selected values and expiry before a verified grant", async () => {
    const f = fixture();
    vi.stubEnv("VITE_OIDC_ORIGIN", "https://issuer.example");
    vi.spyOn(window, "open").mockReturnValue(window);
    vi.spyOn(window, "close").mockImplementation(() => {});
    render(<PlansWorkspace locale="en-CA" />);
    await loadConversation();
    await loadPlan();
    fireEvent.click(
      screen.getByRole("button", { name: "Verify my authority" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Confirm verification" }),
    );
    await screen.findByText("Authority verified for this subject.");
    fireEvent.change(screen.getByLabelText("Recipient account ID"), {
      target: { value: recipient },
    });
    fireEvent.click(screen.getByLabelText("Strategies"));
    fireEvent.click(
      screen.getByRole("button", { name: "Review exact sharing" }),
    );
    expect(screen.getByText(`Recipient account ID:`)).toBeInTheDocument();
    expect(
      f.commands.filter((command) => command.path === "/v1/consents"),
    ).toHaveLength(0);
    fireEvent.click(
      screen.getByRole("button", { name: "Confirm this exact permission" }),
    );
    await waitFor(() =>
      expect(
        f.commands.filter((command) => command.path === "/v1/consents"),
      ).toHaveLength(1),
    );
    const grant = f.commands.find((command) => command.path === "/v1/consents");
    expect(grant?.body).toMatchObject({
      subject_id: subject,
      session_id: sessionId,
      purpose: "plan",
      fields: ["plan.strategies"],
      recipient: { kind: "account", account_id: recipient },
      authority_proof_id: ceremonyId,
      basis: "self",
    });
  });
  it("does not preview another subject’s plan as consent for the loaded conversation", async () => {
    const f = fixture();
    f.otherSubject();
    vi.stubEnv("VITE_OIDC_ORIGIN", "https://issuer.example");
    vi.spyOn(window, "open").mockReturnValue(window);
    vi.spyOn(window, "close").mockImplementation(() => {});
    render(<PlansWorkspace locale="en-CA" />);
    await loadConversation();
    await loadPlan();
    fireEvent.click(
      screen.getByRole("button", { name: "Verify my authority" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Confirm verification" }),
    );
    await screen.findByText("Authority verified for this subject.");
    fireEvent.change(screen.getByLabelText("Recipient account ID"), {
      target: { value: recipient },
    });
    fireEvent.click(screen.getByLabelText("Strategies"));
    expect(
      screen.getByRole("button", { name: "Review exact sharing" }),
    ).toBeDisabled();
    expect(
      f.commands.filter((command) => command.path === "/v1/consents"),
    ).toHaveLength(0);
  });
  it("keeps a carer report in their own attributed conversation", async () => {
    const f = fixture("carer");
    render(<PlansWorkspace locale="en-CA" initialSessionId={sessionId} />);
    const report = await screen.findByLabelText("Your words");
    fireEvent.change(report, {
      target: { value: "Fictional carer observation" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Append my report" }));
    await waitFor(() => expect(f.commands).toHaveLength(1));
    expect(f.commands[0]).toMatchObject({
      path: `/v1/sessions/${sessionId}/assertions`,
      body: {
        subject_id: subject,
        field: "observations",
        value: { kind: "text", text: "Fictional carer observation" },
      },
    });
    expect(
      screen.queryByRole("button", { name: "Create my plan" }),
    ).not.toBeInTheDocument();
    await screen.findByText("Fictional carer observation", {
      selector: "li p",
    });
    cleanup();
    render(<PlansWorkspace locale="en-CA" initialSessionId={sessionId} />);
    await screen.findByText("Fictional carer observation", {
      selector: "li p",
    });
    expect(
      screen.getByRole("heading", { name: "My saved reports" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("No independently verified source"),
    ).toBeInTheDocument();
  });
  it("recovers a saved own report after losing its acknowledgement without a new effect", async () => {
    const f = fixture("carer");
    render(<PlansWorkspace locale="en-CA" initialSessionId={sessionId} />);
    const input = await screen.findByLabelText("Your words");
    fireEvent.change(input, {
      target: { value: "Fictional uncertain report" },
    });
    f.loseReport();
    fireEvent.click(screen.getByRole("button", { name: "Append my report" }));
    await waitFor(() =>
      expect(
        screen.getAllByText(/The outcome is unknown/).length,
      ).toBeGreaterThan(0),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Reconcile operation" }),
    );
    await screen.findByText("Fictional uncertain report", { selector: "li p" });
    await waitFor(() =>
      expect(
        f.commands.filter((command) => command.path.endsWith("/assertions")),
      ).toHaveLength(2),
    );
    const attempts = f.commands.filter((command) =>
      command.path.endsWith("/assertions"),
    );
    expect(attempts[0]?.key).toBe(attempts[1]?.key);
    expect(
      screen.getAllByText("Fictional uncertain report", { selector: "li p" }),
    ).toHaveLength(1);
  });
  it("clears saved own reports when current access is denied", async () => {
    const f = fixture("carer");
    f.seedReport();
    render(<PlansWorkspace locale="en-CA" initialSessionId={sessionId} />);
    await screen.findByText("Fictional private strategy");
    f.denyReports();
    fireEvent.click(
      screen.getByRole("button", { name: "Check current access" }),
    );
    await waitFor(() =>
      expect(
        screen.queryByText("Fictional private strategy"),
      ).not.toBeInTheDocument(),
    );
  });
  it("clears saved reports and unsent words on an actual account switch", async () => {
    const f = fixture("carer");
    f.seedReport();
    render(<PlansWorkspace locale="en-CA" initialSessionId={sessionId} />);
    await screen.findByText("Fictional private strategy");
    fireEvent.change(screen.getByLabelText("Your words"), {
      target: { value: "Unsent former-account report" },
    });
    f.switchAccount();
    fireEvent.click(
      screen.getByRole("button", { name: "Check current access" }),
    );
    await waitFor(() =>
      expect(
        screen.queryByText("Fictional private strategy"),
      ).not.toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Load conversation" }));
    // Server response for the old author's report is rejected even if the fixture session read remains permissive.
    await screen.findByRole("alert");
    expect(
      screen.queryByText("Fictional private strategy"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByDisplayValue("Unsent former-account report"),
    ).not.toBeInTheDocument();
  });
  it("rejects a report projection attributed to a different account", async () => {
    const f = fixture("professional_participant");
    f.seedReport(recipient);
    render(<PlansWorkspace locale="en-CA" initialSessionId={sessionId} />);
    await screen.findByRole("alert");
    expect(
      screen.queryByText("Fictional private strategy"),
    ).not.toBeInTheDocument();
  });
  it("preserves unsent words across sign-out while clearing private views", async () => {
    const f = fixture();
    render(<PlansWorkspace locale="en-CA" />);
    await loadPlan();
    fireEvent.change(screen.getByLabelText("Your words"), {
      target: { value: "Unsent fictional words" },
    });
    f.signOut();
    fireEvent.click(
      screen.getByRole("button", { name: "Check current access" }),
    );
    await screen.findByText(/Sign in again to continue/);
    expect(
      screen.queryByText("Fictional private strategy"),
    ).not.toBeInTheDocument();
    f.signIn();
    fireEvent.click(
      screen.getByRole("button", { name: "Check current access" }),
    );
    await screen.findByText("Fictional private strategy");
    expect(screen.getByLabelText("Your words")).toHaveValue(
      "Unsent fictional words",
    );
    expect(f.commands).toHaveLength(0);
  });
});
describe("truthful sourced options", () => {
  it("refreshes seven current entries with one outstanding read and publishes them together", async () => {
    const f = fixture();
    const options = operatingStates.map((state, index) => entry(state, index));
    const reads: string[] = [],
      releases: (() => void)[] = [];
    let outstanding = 0,
      maximumOutstanding = 0;
    f.readDirectory((id) => {
      reads.push(id);
      outstanding += 1;
      maximumOutstanding = Math.max(maximumOutstanding, outstanding);
      const option = options.find((item) => item.id === id);
      if (!option) throw new Error("Unknown fixture entry");
      return new Promise<Response>((resolve) => {
        releases.push(() => {
          outstanding -= 1;
          resolve(
            response({
              ...option,
              revision: "2",
              facts: {
                ...option.facts,
                name: `Refreshed ${option.facts.operating_state}`,
              },
            }),
          );
        });
      });
    });
    render(<PlansWorkspace locale="en-CA" />);
    fireEvent.click(
      screen.getByRole("button", { name: "Check current access" }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Refresh sourced options" }),
      ).toBeEnabled(),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Refresh sourced options" }),
    );
    await screen.findByRole("heading", { name: "Fictional normal_operations" });
    fireEvent.click(
      screen.getByRole("button", { name: "Check current access" }),
    );
    await waitFor(() => expect(reads.length).toBeGreaterThan(0));
    expect(outstanding).toBe(1);
    for (let index = 0; index < options.length; index += 1) {
      await waitFor(() => expect(reads).toHaveLength(index + 1));
      expect(outstanding).toBe(1);
      expect(
        screen.queryByRole("heading", { name: /^Refreshed / }),
      ).not.toBeInTheDocument();
      const release = releases[index];
      if (!release) throw new Error("Missing pending current read");
      await act(async () => {
        release();
        await Promise.resolve();
      });
    }
    await screen.findByRole("heading", { name: "Refreshed normal_operations" });
    expect(reads).toEqual(options.map((option) => option.id));
    expect(maximumOutstanding).toBe(1);
    expect(outstanding).toBe(0);
    expect(
      screen.getAllByRole("heading", { name: /^Refreshed / }),
    ).toHaveLength(7);
    expect(
      screen.queryByRole("heading", { name: /^Fictional / }),
    ).not.toBeInTheDocument();
  });
  it("clears all previous directory entries when a later current read is denied", async () => {
    const f = fixture();
    const options = operatingStates.map((state, index) => entry(state, index));
    const reads: string[] = [];
    f.readDirectory(async (id) => {
      reads.push(id);
      const option = options.find((item) => item.id === id);
      if (!option) throw new Error("Unknown fixture entry");
      return Promise.resolve(
        reads.length === 2
          ? response({}, 403)
          : response({
              ...option,
              revision: "2",
              facts: { ...option.facts, name: "Refreshed first entry" },
            }),
      );
    });
    render(<PlansWorkspace locale="en-CA" />);
    fireEvent.click(
      screen.getByRole("button", { name: "Check current access" }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Refresh sourced options" }),
      ).toBeEnabled(),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Refresh sourced options" }),
    );
    await screen.findByRole("heading", { name: "Fictional normal_operations" });
    fireEvent.click(
      screen.getByRole("button", { name: "Check current access" }),
    );
    await screen.findByRole("alert");
    expect(reads).toEqual(options.slice(0, 2).map((option) => option.id));
    expect(
      screen.queryByRole("heading", { name: /^Fictional / }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Refreshed first entry" }),
    ).not.toBeInTheDocument();
  });
  it.each(operatingStates)("does not infer availability for %s", (state) => {
    const option = entry(state);
    expect(optionAvailability(option)).toBe(
      state === "normal_operations"
        ? "available"
        : state === "temporary_closure" || state === "regional_outage"
          ? "unavailableOption"
          : "unknownOption",
    );
    expect(optionAvailability({ ...option, state: "stale" })).not.toBe(
      "available",
    );
    expect(optionAvailability({ ...option, expires_at: at })).not.toBe(
      "available",
    );
    expect(optionAvailability({ ...option, state: "suspended" })).toBe(
      "unavailableOption",
    );
  });
  it("shows all seven states, police unknown and explicit absence of alternatives in French", async () => {
    fixture();
    render(<PlansWorkspace locale="fr-CA" />);
    fireEvent.click(
      screen.getByRole("button", { name: "Vérifier l’accès actuel" }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Actualiser les options sourcées" }),
      ).toBeEnabled(),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Actualiser les options sourcées" }),
    );
    await screen.findByRole("heading", {
      name: "Fictional conflicting_source",
    });
    expect(
      screen.getAllByText(/Aucune solution de rechange examinée/),
    ).toHaveLength(7);
    expect(screen.getAllByText(/Intervention policière inconnue/)).toHaveLength(
      7,
    );
    expect(
      screen.getByText("Sources contradictoires — disponibilité inconnue"),
    ).toBeInTheDocument();
  });
  it("removes options when their current source read fails", async () => {
    fixture();
    render(<PlansWorkspace locale="en-CA" />);
    fireEvent.click(
      screen.getByRole("button", { name: "Check current access" }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Refresh sourced options" }),
      ).toBeEnabled(),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Refresh sourced options" }),
    );
    await screen.findByRole("heading", { name: "Fictional normal_operations" });
    fireEvent.click(
      screen.getByRole("button", { name: "Check current access" }),
    );
    await act(async () => {
      await Promise.resolve();
    });
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: "Fictional normal_operations" }),
      ).not.toBeInTheDocument(),
    );
  });
});
