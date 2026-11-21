// @vitest-environment jsdom
// @vitest-environment-options {"url":"https://rights.qualification.localhost/follow-up"}
import "@testing-library/jest-dom/vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { LifecycleApp } from "./LifecycleApp";
import { messages } from "./messages";
const sid = "10000000-0000-4000-8000-000000000001",
  subject = "20000000-0000-4000-8000-000000000001",
  account = "30000000-0000-4000-8000-000000000001",
  followup = "40000000-0000-4000-8000-000000000001",
  grant = "50000000-0000-4000-8000-000000000001",
  rights = "60000000-0000-4000-8000-000000000001",
  message = "70000000-0000-4000-8000-000000000001",
  event = "80000000-0000-4000-8000-000000000001",
  ceremony = "90000000-0000-4000-8000-000000000001";
const future = "2099-11-20T12:00:00Z",
  at = "2026-11-20T12:00:00Z";
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
function fixture(
  options: {
    lostCancel?: boolean;
    malformedInbox?: boolean;
    initialFollowup?: string;
    subjectRevision?: string | null;
    rightsVerified?: boolean;
  } = {},
) {
  const commands: {
    path: string;
    body: Record<string, unknown>;
    key: string | undefined;
  }[] = [];
  let cancelLost = options.lostCancel ?? false;
  let denied = false;
  let actor = account;
  let revision = "1";
  let subjectRevision =
    options.subjectRevision === undefined ? "7" : options.subjectRevision;
  let verificationPurpose = "export";
  let deliveredState = options.initialFollowup ?? "scheduled";
  const inboxMessage = {
    id: message,
    recipient_account_id: account,
    followup_id: followup,
    source_session_id: sid,
    text: "Synthetic private inbox content",
    sources: [],
    created_at: at,
    read_at: null,
    expires_at: future,
  };
  const fetcher = vi.fn((raw: string | URL | Request, init?: RequestInit) => {
    const path =
      typeof raw === "string" ? raw : raw instanceof URL ? raw.href : raw.url;
    if (path === "/v1/auth/session")
      return denied
        ? json({}, 401)
        : json({
            account_id: actor,
            role: "pid",
            assurance: "AL2",
            revision: "1",
            expires_at: future,
            auth_time: at,
          });
    if (path === "/v1/auth/csrf") return json({ csrf_token: "a".repeat(48) });
    if (init?.method === "POST")
      commands.push({
        path,
        body: JSON.parse(
          typeof init.body === "string" ? init.body : "{}",
        ) as Record<string, unknown>,
        key: (init.headers as Record<string, string>)["Idempotency-Key"],
      });
    if (path === `/v1/sessions/${sid}`)
      return json({
        id: sid,
        revision,
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
        persona_id: subject,
        subject_id: subject,
        ...(subjectRevision === null
          ? {}
          : { subject_revision: subjectRevision }),
      });
    if (path === `/v1/sessions/${sid}/follow-ups`)
      return json({
        id: followup,
        session_id: sid,
        revision: "1",
        state:
          commands.at(-1)?.body.kind === "scheduled"
            ? "scheduled"
            : "anchor_pending",
        due_at:
          commands.at(-1)?.body.kind === "scheduled"
            ? commands.at(-1)?.body.due_at
            : null,
        inbox_message_id: null,
      });
    if (path === `/v1/follow-ups/${followup}/cancel`) {
      deliveredState = "cancelled";
      if (cancelLost) {
        cancelLost = false;
        throw new Error("lost after commit");
      }
      return json({
        id: followup,
        session_id: sid,
        revision: "2",
        state: deliveredState,
        due_at: at,
        inbox_message_id: null,
      });
    }
    if (path === `/v1/follow-ups/${followup}`)
      return json({
        id: followup,
        session_id: sid,
        revision: "1",
        state: deliveredState,
        due_at: at,
        inbox_message_id: null,
      });
    if (path === "/v1/consents") {
      revision = "2";
      const body = commands.at(-1)?.body;
      return json({
        id: grant,
        revision: "1",
        scope: {
          session_id: sid,
          subject_id: subject,
          purpose: "follow_up",
          fields: ["summary", "outcome"],
          recipient_id: account,
        },
        recipient: { kind: "account", account_id: account },
        grantor_id: account,
        scope_digest: "a".repeat(64),
        effective_at: body?.effective_at,
        expires_at: body?.expires_at,
        revoked_at: null,
      });
    }
    if (path === `/v1/consents/${grant}/revoke`)
      return json({
        operation_id: event,
        state: "committed",
        resource_id: grant,
        revision: "2",
        audit_ref: event,
      });
    if (path === "/v1/inbox")
      return json(
        options.malformedInbox
          ? { items: [{ ...inboxMessage, text: 9 }], next_cursor: null }
          : { items: [inboxMessage], next_cursor: null },
      );
    if (path === `/v1/inbox/${message}`) return json(inboxMessage);
    if (path === "/v1/rights")
      return json({
        id: rights,
        revision: "1",
        kind: "export",
        state: "completed",
        exceptions: [],
        download_id: rights,
        deadline: future,
      });
    if (path === `/v1/rights/${rights}`)
      return json({
        id: rights,
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
    if (path === `/v1/sessions/${sid}/outcomes` && init?.method === "POST")
      return json({
        operation_id: event,
        state: "committed",
        resource_id: message,
        revision: "2",
        audit_ref: event,
      });
    if (path === `/v1/sessions/${sid}/outcomes`)
      return json({
        items: [
          {
            id: message,
            revision: "1",
            session_id: sid,
            state: "reported_benefit",
            carer_support: true,
            observed_at: at,
          },
        ],
        next_cursor: null,
      });
    if (path === `/v1/sessions/${sid}/post-crisis`) {
      revision = "2";
      return json({
        id: event,
        session_id: sid,
        occurred_at: at,
        revision: "1",
      });
    }
    if (path === "/v1/auth/step-up") {
      verificationPurpose = String(commands.at(-1)?.body.purpose);
      return json({
        ceremony_id: ceremony,
        state: "pending",
        not_before: at,
        expires_at: future,
        authorization_url: "https://identity.qualification.localhost/authorize",
      });
    }
    if (path === `/v1/auth/step-up/proof?ceremony_id=${ceremony}`)
      return json({ proof_intent_id: message });
    if (path === "/v1/auth/step-up/confirm")
      return json({
        ceremony_id: ceremony,
        state:
          verificationPurpose === "follow_up_consent" || options.rightsVerified
            ? "verified"
            : "cooling_off",
        not_before: new Date(Date.now() + 300000).toISOString(),
        expires_at: future,
        authorization_url: null,
      });
    return json({}, 404);
  });
  vi.stubGlobal("fetch", fetcher);
  return {
    commands,
    changeSubjectRevision: (value: string) => {
      subjectRevision = value;
    },
    fetcher,
    deny: () => {
      denied = true;
    },
    allow: () => {
      denied = false;
    },
    switchActor: () => {
      actor = subject;
    },
  };
}
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});
async function accountReady(locale: "en-CA" | "fr-CA" = "en-CA") {
  const text = messages[locale];
  render(<LifecycleApp />);
  if (locale === "fr-CA")
    fireEvent.change(screen.getByLabelText("Language"), {
      target: { value: locale },
    });
  fireEvent.click(screen.getByRole("button", { name: text.check }));
  await screen.findByRole("heading", { name: text.inbox });
  return text;
}
async function openSession(text = messages["en-CA"]) {
  fireEvent.change(screen.getByLabelText(text.session), {
    target: { value: sid },
  });
  fireEvent.click(screen.getByRole("button", { name: text.load }));
  await screen.findByRole("heading", { name: text.followup });
}
it.each(["en-CA", "fr-CA"] as const)(
  "keeps pending follow-up unanchored and displays truthful cancellation in %s",
  async (locale) => {
    const network = fixture();
    const text = await accountReady(locale);
    await openSession(text);
    fireEvent.change(screen.getByLabelText(text.grant), {
      target: { value: grant },
    });
    fireEvent.click(screen.getByRole("button", { name: text.schedule }));
    await screen.findByText(`${text.state}: ${text.states.anchor_pending}`);
    expect(network.commands[0]?.body).toEqual({
      kind: "pending_anchor",
      expected_revision: "1",
      subject_id: subject,
      recipient_account_id: account,
      contact_grant_id: grant,
    });
    expect(network.commands[0]?.body).not.toHaveProperty(
      "post_crisis_event_id",
    );
    expect(screen.getByRole("button", { name: text.bind })).toBeDisabled();
    expect(screen.getByText(text.cancellation)).toBeVisible();
    expect(document.documentElement.lang).toBe(locale);
  },
);
it("preserves the original operation key and body when a cancel reply is lost", async () => {
  const network = fixture({ lostCancel: true });
  const text = await accountReady();
  await openSession();
  fireEvent.change(screen.getByLabelText(text.knownFollowup), {
    target: { value: followup },
  });
  fireEvent.submit(screen.getByLabelText(text.knownFollowup).closest("form")!);
  await screen.findByText(`${text.state}: ${text.states.scheduled}`);
  fireEvent.click(screen.getByRole("button", { name: text.cancel }));
  await screen.findByRole("button", { name: text.retry });
  expect(
    screen.queryByText(`${text.state}: ${text.states.cancelled}`),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: text.retry }));
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: text.retry }),
    ).not.toBeInTheDocument(),
  );
  await screen.findByText(`${text.state}: ${text.states.cancelled}`);
  const cancellations = network.commands.filter((v) =>
    v.path.endsWith("/cancel"),
  );
  expect(cancellations).toHaveLength(2);
  expect(cancellations[1]).toEqual(cancellations[0]);
});
it("clears private inbox content when current authentication fails", async () => {
  const network = fixture();
  const text = await accountReady();
  fireEvent.click(screen.getByRole("button", { name: text.openInbox }));
  fireEvent.click(
    await screen.findByRole("button", { name: text.openMessage }),
  );
  await screen.findByText("Synthetic private inbox content");
  network.deny();
  fireEvent.click(screen.getByRole("button", { name: text.check }));
  await screen.findByText(text.signed_out);
  expect(
    screen.queryByText("Synthetic private inbox content"),
  ).not.toBeInTheDocument();
});
it("reports backup-pending deletion and retained exceptions without completion", async () => {
  fixture();
  const text = await accountReady();
  fireEvent.change(screen.getByLabelText(text.knownRights), {
    target: { value: rights },
  });
  fireEvent.submit(screen.getByLabelText(text.knownRights).closest("form")!);
  await screen.findByText(`${text.state}: ${text.states.backup_pending}`);
  expect(screen.getByText(text.backup)).toBeVisible();
  expect(screen.getByText(text.exceptionReasons.held)).toBeVisible();
  expect(
    screen.queryByText("backup_erasure_pending_IMP09"),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: text.download }),
  ).not.toBeInTheDocument();
});
it("rejects a malformed inbox reply before rendering its content", async () => {
  fixture({ malformedInbox: true });
  const text = await accountReady();
  fireEvent.click(screen.getByRole("button", { name: text.openInbox }));
  await screen.findByText(text.invalid);
  expect(
    screen.queryByRole("button", { name: text.openMessage }),
  ).not.toBeInTheDocument();
});
it("rejects stale work after account switch and removes old private content", async () => {
  const network = fixture();
  const text = await accountReady();
  fireEvent.click(screen.getByRole("button", { name: text.openInbox }));
  fireEvent.click(
    await screen.findByRole("button", { name: text.openMessage }),
  );
  await screen.findByText("Synthetic private inbox content");
  network.switchActor();
  fireEvent.click(screen.getByRole("button", { name: text.openInbox }));
  await screen.findByText(text.rejected);
  expect(
    screen.queryByText("Synthetic private inbox content"),
  ).not.toBeInTheDocument();
  expect(
    network.fetcher.mock.calls.filter(([path]) => path === "/v1/inbox"),
  ).toHaveLength(1);
});
it("uses a purpose-bound real MFA ceremony and blocks second authentication during cooling", async () => {
  const network = fixture();
  vi.stubEnv("VITE_OIDC_ORIGIN", "https://identity.qualification.localhost");
  const popup = {
    opener: {},
    location: { href: "about:blank" },
    close: vi.fn(),
  };
  vi.spyOn(window, "open").mockReturnValue(popup as unknown as Window);
  const text = await accountReady();
  await openSession(text);
  const rightsRegion = within(
    screen.getByRole("region", { name: text.rights }),
  );
  fireEvent.click(rightsRegion.getByRole("button", { name: text.begin }));
  await screen.findByRole("button", { name: text.confirm });
  expect(network.commands[0]?.body).toEqual({
    purpose: "export",
    resource_id: subject,
    expected_revision: "1",
  });
  expect(popup.location.href).toBe(
    "https://identity.qualification.localhost/authorize",
  );
  fireEvent.click(screen.getByRole("button", { name: text.confirm }));
  await screen.findByText(new RegExp(text.cooling));
  expect(screen.getByRole("button", { name: text.second })).toBeDisabled();
  expect(
    screen.getByRole("button", { name: text.submitRights }),
  ).toBeDisabled();
  expect(network.commands.filter((v) => v.path === "/v1/rights")).toHaveLength(
    0,
  );
});

it("accepts the canonical outcome command receipt then reads attributed outcomes", async () => {
  const network = fixture();
  const text = await accountReady();
  await openSession();
  fireEvent.change(screen.getByLabelText(text.outcomeState), {
    target: { value: "reported_benefit" },
  });
  fireEvent.click(screen.getByLabelText(text.carer));
  fireEvent.change(screen.getByLabelText(text.observed), {
    target: { value: "2026-11-20T12:00" },
  });
  fireEvent.click(screen.getByRole("button", { name: text.appendOutcome }));
  await screen.findByText(text.outcomeSaved);
  expect(
    network.commands.find((v) => v.path.endsWith("/outcomes"))?.body,
  ).toMatchObject({ state: "reported_benefit", carer_support: true });
  fireEvent.click(screen.getByRole("button", { name: text.readOutcomes }));
  await screen.findByText(new RegExp(text.states.reported_benefit));
  expect(screen.queryByText(text.invalid)).not.toBeInTheDocument();
});

it("records an explicit source event and refreshes revision before scheduled follow-up", async () => {
  const network = fixture();
  const text = await accountReady();
  await openSession();
  fireEvent.change(screen.getByLabelText(text.sourceEvent), {
    target: { value: message },
  });
  fireEvent.change(screen.getByLabelText(text.occurred), {
    target: { value: "2026-11-20T12:00" },
  });
  fireEvent.click(screen.getByRole("button", { name: text.recordAnchor }));
  await waitFor(() =>
    expect(
      screen.getByText(new RegExp(text.reference + ": " + sid)),
    ).toHaveTextContent(text.revision + ": 2"),
  );
  fireEvent.change(screen.getByLabelText(text.grant), {
    target: { value: grant },
  });
  fireEvent.change(screen.getByLabelText(text.due), {
    target: { value: "2026-11-21T12:00" },
  });
  fireEvent.click(screen.getByLabelText(text.pendingAnchor));
  fireEvent.click(screen.getByRole("button", { name: text.schedule }));
  await screen.findByText(`${text.state}: ${text.states.scheduled}`);
  expect(
    network.commands.find((command) => command.path.endsWith("/follow-ups"))
      ?.body,
  ).toMatchObject({
    kind: "scheduled",
    expected_revision: "2",
    post_crisis_event_id: event,
    contact_grant_id: grant,
  });
});

it("creates distinct contact consent only after MFA and preview, then withdraws it", async () => {
  const network = fixture();
  vi.stubEnv("VITE_OIDC_ORIGIN", "https://identity.qualification.localhost");
  vi.spyOn(window, "open").mockReturnValue({
    opener: {},
    location: { href: "about:blank" },
    close: vi.fn(),
  } as unknown as Window);
  const text = await accountReady();
  await openSession();
  fireEvent.click(screen.getAllByRole("button", { name: text.begin })[0]!);
  fireEvent.click(await screen.findByRole("button", { name: text.confirm }));
  await screen.findByText(text.verified);
  fireEvent.change(screen.getByLabelText(text.contactExpiry), {
    target: { value: "2099-11-20T12:00" },
  });
  fireEvent.click(screen.getByRole("button", { name: text.previewContact }));
  expect(
    network.commands.some((command) => command.path === "/v1/consents"),
  ).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: text.confirmContact }));
  await screen.findByRole("button", { name: text.revokeContact });
  const command = network.commands.find(
    (value) => value.path === "/v1/consents",
  );
  expect(command?.body).toMatchObject({
    purpose: "follow_up",
    recipient: { kind: "account", account_id: account },
    fields: ["summary", "outcome"],
    authority_proof_id: ceremony,
  });
  expect(screen.getByLabelText(text.grant)).toHaveValue(grant);
  fireEvent.click(screen.getByRole("button", { name: text.revokeContact }));
  await screen.findByText(text.contactWithdrawn);
  expect(screen.getByLabelText(text.grant)).toHaveValue("");
});
it("preserves unsent local form input while removing private views across reauthentication", async () => {
  const network = fixture();
  const text = await accountReady();
  await openSession();
  fireEvent.change(screen.getByLabelText(text.observed), {
    target: { value: "2026-11-20T12:00" },
  });
  network.deny();
  fireEvent.click(screen.getByRole("button", { name: text.check }));
  await screen.findByText(text.signed_out);
  expect(screen.queryByLabelText(text.observed)).not.toBeInTheDocument();
  network.allow();
  fireEvent.click(screen.getByRole("button", { name: text.check }));
  await screen.findByLabelText(text.observed);
  expect(screen.getByLabelText(text.observed)).toHaveValue("2026-11-20T12:00");
});

it("takes the rights revision from authenticated session metadata and invalidates old proof on refresh", async () => {
  const network = fixture({ rightsVerified: true });
  vi.stubEnv("VITE_OIDC_ORIGIN", "https://identity.qualification.localhost");
  vi.spyOn(window, "open").mockReturnValue({
    opener: {},
    location: { href: "about:blank" },
    close: vi.fn(),
  } as unknown as Window);
  const text = await accountReady();
  expect(screen.getByText(text.loadRightsScope)).toBeVisible();
  await openSession();
  const region = within(screen.getByRole("region", { name: text.rights }));
  expect(
    region.queryByRole("textbox", { name: text.rightsRevision }),
  ).not.toBeInTheDocument();
  expect(region.getByText(subject)).toBeVisible();
  fireEvent.click(region.getByRole("button", { name: text.begin }));
  fireEvent.click(await region.findByRole("button", { name: text.confirm }));
  await region.findByText(text.verified);
  fireEvent.click(region.getByRole("button", { name: text.submitRights }));
  await region.findByText(text.progress);
  expect(
    network.commands.find((command) => command.path === "/v1/rights")?.body,
  ).toMatchObject({
    subject_id: subject,
    expected_revision: "7",
    ceremony_id: ceremony,
  });
  network.changeSubjectRevision("8");
  fireEvent.click(screen.getByRole("button", { name: text.load }));
  await waitFor(() =>
    expect(
      region.getByRole("button", { name: text.submitRights }),
    ).toBeDisabled(),
  );
  await waitFor(() =>
    expect(region.queryByText(text.verified)).not.toBeInTheDocument(),
  );
});
it("keeps new rights requests unavailable when the server omits subject revision", async () => {
  fixture({ subjectRevision: null });
  const text = await accountReady();
  await openSession();
  const region = within(screen.getByRole("region", { name: text.rights }));
  expect(region.getByText(text.loadRightsScope)).toBeVisible();
  expect(
    region.getByRole("button", { name: text.submitRights }),
  ).toBeDisabled();
  expect(region.getByRole("button", { name: text.begin })).toBeDisabled();
});
