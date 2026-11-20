// @vitest-environment jsdom
// @vitest-environment-options {"url":"https://referral.qualification.localhost/referrals"}
import "@testing-library/jest-dom/vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ReferralApp } from "./ReferralApp";
import { messages, type Locale } from "./messages";
const sid = "10000000-0000-4000-8000-000000000001",
  subject = "20000000-0000-4000-8000-000000000001",
  service = "30000000-0000-4000-8000-000000000001",
  sourceId = "40000000-0000-4000-8000-000000000001",
  rid = "50000000-0000-4000-8000-000000000001",
  consentId = "60000000-0000-4000-8000-000000000001",
  reviewId = "70000000-0000-4000-8000-000000000001",
  did = "80000000-0000-4000-8000-000000000001",
  receiptId = "90000000-0000-4000-8000-000000000001",
  actor = "a0000000-0000-4000-8000-000000000001",
  ceremonyId = "b0000000-0000-4000-8000-000000000001";
const at = "2026-11-20T12:00:00Z",
  future = "2099-11-20T12:00:00Z";
const digest = "a".repeat(64),
  sourceDigest = "b".repeat(64);
const source = {
  kind: "assertion",
  id: sourceId,
  revision: "1",
  digest: sourceDigest,
  observed_at: at,
  verification: "disputed",
};
const field = {
  field: "needs",
  value: { kind: "text", text: "Synthetic request for navigation" },
  sources: [source],
};
const secondField = {
  field: "preferences",
  value: { kind: "unknown", reason: "not_known" },
  sources: [{ ...source, id: "40000000-0000-4000-8000-000000000002" }],
};
const payload = {
  session_id: sid,
  subject_id: subject,
  recipient_service_id: service,
  purpose: "referral",
  fields: [field, secondField],
  qualifications: ["Fictional option; capacity is unknown"],
};
const directory = {
  id: service,
  revision: "1",
  facts: {
    name: "Fictional navigation service",
    jurisdictions: ["CA-XX"],
    languages: ["en-CA", "fr-CA"],
    age_scope: "all_fixture",
    availability: "unknown",
    police_involvement: "unknown",
    qualifications: ["No verified capacity"],
    alternative_service_id: null,
    hours_description: "Hours unknown",
    operating_state: "normal_operations",
  },
  sources: [{ ...source, kind: "directory" }],
  state: "verified",
  verified_at: at,
  expires_at: future,
};
const versions = Object.fromEntries(
  [
    "identity",
    "roles",
    "subject",
    "session_access",
    "assignment",
    "resource",
    "directory",
    "policy_epoch",
    "control_epoch",
    "serving_generation",
    "restriction_barrier",
  ].map((key) => [key, "1"]),
);
const conversation = {
  id: sid,
  revision: "1",
  subject_id: subject,
  persona_id: subject,
  tags: { environment: "demo", population: "synthetic" },
  participant_kind: "pid",
  jurisdiction: null,
  locale: "en-CA",
  service_phase: "human_controlled",
  transport: "connected",
  control_epoch: "1",
  owner_id: actor,
  degraded_reasons: [],
  tier: null,
  unresolved: true,
};
const consent = {
  id: consentId,
  revision: "1",
  scope: {
    session_id: sid,
    subject_id: subject,
    purpose: "referral",
    fields: ["needs", "preferences"],
    recipient_id: service,
  },
  recipient: { kind: "service", service_id: service, directory_revision: "1" },
  grantor_id: actor,
  scope_digest: "c".repeat(64),
  effective_at: at,
  expires_at: future,
  revoked_at: null,
};
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
function fixture(
  options: {
    role?: string;
    lostReply?: boolean;
    denySources?: boolean;
    malformed?: boolean;
    expiredConsent?: boolean;
  } = {},
) {
  let revision = "1",
    reviewed = false,
    sent = false,
    reconciled = false,
    receiverDecision = false;
  let role = options.role ?? "worker";
  let lostSend = options.lostReply ?? false;
  const mutations: {
    path: string;
    body: Record<string, unknown>;
    key: string | undefined;
  }[] = [];
  const referral = () => ({
    id: rid,
    revision,
    generation: "1",
    payload,
    digest,
    state: reviewed ? "ready" : "awaiting_review",
    consent_id: consentId,
    review_id: reviewed ? reviewId : null,
    dispatch_id: sent ? did : null,
  });
  const review = () => ({
    id: reviewId,
    draft_id: rid,
    decision: "accept",
    reviewer_id: actor,
    exact_digest: digest,
    expires_at: future,
    revision: "1",
  });
  const receipt = () => ({
    id: receiptId,
    dispatch_id: did,
    recipient_service_id: service,
    payload_digest: digest,
    status: reconciled || receiverDecision ? "partial" : "received",
    accepted_fields: reconciled || receiverDecision ? ["needs"] : [],
    observed_at: at,
  });
  const dispatch = () => ({
    dispatch_id: did,
    referral_id: rid,
    revision: sent ? "2" : "1",
    state: reconciled ? "partial" : sent ? "unknown" : "pending",
    attempt_count: sent ? 1 : 0,
    receipt_id: reconciled ? receiptId : null,
  });
  const fetcher = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const path =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    const body = init?.body
      ? (JSON.parse(
          typeof init.body === "string" ? init.body : "null",
        ) as Record<string, unknown>)
      : {};
    const key = init?.headers
      ? (new Headers(init.headers).get("Idempotency-Key") ?? undefined)
      : undefined;
    if (init?.method === "POST") mutations.push({ path, body, key });
    if (path === "/v1/auth/session")
      return json({
        account_id: actor,
        role,
        assurance: "AL2",
        revision: "1",
        expires_at: future,
        auth_time: at,
      });
    if (path === "/v1/auth/csrf") return json({ csrf_token: "x".repeat(40) });
    if (path === `/v1/sessions/${sid}`) return json(conversation);
    if (path === `/v1/sessions/${sid}/referral-sources`)
      return options.denySources
        ? json({}, 403)
        : json({
            items: [
              { selected: { field: "needs", source }, field },
              {
                selected: {
                  field: "preferences",
                  source: secondField.sources[0],
                },
                field: secondField,
              },
            ],
            next_cursor: null,
          });
    if (path === `/v1/directory/${service}`) return json(directory);
    if (path === "/v1/directory/search")
      return json({ items: [directory], next_cursor: null });
    if (path === `/v1/sessions/${sid}/referrals`)
      return json(
        options.malformed ? { ...referral(), unexpected: true } : referral(),
      );
    if (path === `/v1/referrals/${rid}`) return json(referral());
    if (path === `/v1/referrals/${rid}/context`)
      return json({
        referral: referral(),
        versions,
        review: reviewed ? review() : null,
        consent_expires_at: future,
      });
    if (path === `/v1/consents/${consentId}`)
      return json(
        options.expiredConsent ? { ...consent, expires_at: at } : consent,
      );
    if (path === `/v1/referrals/${rid}/review`) {
      reviewed = true;
      revision = "2";
      return json(review());
    }
    if (path === `/v1/referrals/${rid}/dispatch`) return json(dispatch());
    if (path === `/v1/dispatches/${did}`) return json(dispatch());
    if (path === `/v1/dispatches/${did}/send`) {
      sent = true;
      if (lostSend) {
        lostSend = false;
        return json({}, 503);
      }
      return json(dispatch());
    }
    if (path === `/v1/dispatches/${did}/reconcile`) {
      reconciled = true;
      return json(dispatch());
    }
    if (path === `/v1/dispatches/${did}/receipt`) return json(receipt());
    if (path === "/v1/receiver/inbox")
      return json({ dispatch_ids: [did], next_cursor: null });
    if (path === `/v1/receiver/packages/${did}/detail`)
      return json({
        payload,
        revision: receiverDecision ? "2" : "1",
        receipt: receipt(),
      });
    if (path === `/v1/receiver/packages/${did}/decision`) {
      receiverDecision = true;
      return json(receipt());
    }
    if (path === "/v1/auth/step-up" || path === "/v1/auth/step-up/confirm")
      return json({
        ceremony_id: ceremonyId,
        state: path.endsWith("confirm") ? "verified" : "confirmation_required",
        not_before: at,
        expires_at: future,
        authorization_url: null,
      });
    if (path === `/v1/auth/step-up/proof?ceremony_id=${ceremonyId}`)
      return json({ proof_intent_id: sourceId });
    if (path === "/v1/consents") return json(consent);
    throw new Error("Unexpected route " + path);
  });
  vi.stubGlobal("fetch", fetcher);
  return {
    mutations,
    fetcher,
    setRole: (next: string) => {
      role = next;
    },
  };
}
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});
function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label, { selector: "input,select" }), {
    target: { value },
  });
}
async function click(label: string) {
  fireEvent.click(screen.getByRole("button", { name: label }));
  await waitFor(() =>
    expect(
      screen.getByRole("button", {
        name: /^(Check account|Vérifier le compte)$/,
      }),
    ).not.toBeDisabled(),
  );
}
async function openWorker(
  locale: Locale = "en-CA",
  options: Parameters<typeof fixture>[0] = {},
) {
  const f = fixture(options),
    text = messages[locale];
  render(<ReferralApp />);
  if (locale === "fr-CA") fill("Language", locale);
  await click(text.check);
  fill(text.session, sid);
  await click(text.load);
  fill(text.service, service);
  await click(text.loadService);
  fireEvent.click(
    screen.getByRole("checkbox", {
      name: new RegExp(`${text.labels.needs} · Synthetic`),
    }),
  );
  await click(text.draft);
  return { ...f, text };
}
async function prepareSend(
  locale: Locale = "en-CA",
  options: Parameters<typeof fixture>[0] = {},
) {
  const f = await openWorker(locale, options),
    text = f.text;
  fill(text.consent, consentId);
  await click(text.loadConsent);
  await click(text.approve);
  await click(text.enqueue);
  return f;
}
for (const locale of ["en-CA", "fr-CA"] as const) {
  it(`reviews exact fields and reconciles one dispatch without inferring acceptance (${locale})`, async () => {
    const f = await prepareSend(locale),
      text = f.text;
    expect(screen.getByText(text.pending)).toBeInTheDocument();
    expect(
      screen.getByText(/Fictional option; capacity is unknown/),
    ).toBeInTheDocument();
    expect(
      screen.getAllByText(new RegExp(text.labels.disputed)).length,
    ).toBeGreaterThan(0);
    expect(
      f.mutations.find((item) => item.path.endsWith("/review"))?.body,
    ).toMatchObject({
      exact_digest: digest,
      source_vector: versions,
      decision: "accept",
      edited_text: null,
    });
    expect(f.mutations.some((item) => item.path.endsWith("/send"))).toBe(false);
    await click(text.send);
    expect(screen.getByText(text.unresolved)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: text.send }),
    ).not.toBeInTheDocument();
    await click(text.reconcile);
    expect(screen.getByText(text.partialState)).toBeInTheDocument();
    await click(text.receipt);
    expect(screen.getByText(text.support)).toBeInTheDocument();
    expect(
      f.mutations.filter((item) => item.path.endsWith("/send")),
    ).toHaveLength(1);
    expect(
      f.mutations.find((item) => item.path.endsWith("/dispatch"))?.body,
    ).toMatchObject({
      consent_id: consentId,
      review_id: reviewId,
      exact_payload_digest: digest,
      generation: "1",
    });
    expect(document.documentElement.lang).toBe(locale);
  });
}
it("keeps an unknown send unresolved and restores the same dispatch before reconciliation", async () => {
  const f = await prepareSend("en-CA", { lostReply: true }),
    text = f.text;
  fireEvent.click(screen.getByRole("button", { name: text.send }));
  await waitFor(() =>
    expect(screen.getAllByText(text.unknown).length).toBeGreaterThan(0),
  );
  expect(
    screen.queryByText("Synthetic request for navigation"),
  ).not.toBeInTheDocument();
  fill(text.dispatch, did);
  await click(text.loadDispatch);
  expect(screen.getByText(text.unresolved)).toBeInTheDocument();
  await click(text.reconcile);
  expect(
    f.mutations.filter((item) => item.path.endsWith("/send")),
  ).toHaveLength(1);
});
it("clears disclosed fields after a source authorization denial", async () => {
  fixture({ denySources: true });
  const text = messages["en-CA"];
  render(<ReferralApp />);
  await click(text.check);
  fill(text.session, sid);
  await click(text.load);
  expect(screen.getByText(text.rejected)).toBeInTheDocument();
  expect(
    screen.queryByText(/Synthetic request for navigation/),
  ).not.toBeInTheDocument();
  await click(text.check);
  expect(
    screen.queryByText(/Synthetic request for navigation/),
  ).not.toBeInTheDocument();
});
it("rejects an invalid extra-key response without presenting a reviewed draft", async () => {
  const f = await openWorker("en-CA", { malformed: true });
  expect(screen.getByText(f.text.invalid)).toBeInTheDocument();
  expect(
    screen.queryByRole("heading", { name: f.text.review }),
  ).not.toBeInTheDocument();
});
it("discards old private results when the authenticated role changes", async () => {
  const f = await openWorker();
  expect(
    screen.getByRole("heading", { name: f.text.review }),
  ).toBeInTheDocument();
  f.setRole("receiver");
  await click(f.text.check);
  expect(
    screen.queryByRole("heading", { name: f.text.review }),
  ).not.toBeInTheDocument();
});
for (const locale of ["en-CA", "fr-CA"] as const) {
  it(`records only receiver-selected fields with the receiver revision (${locale})`, async () => {
    const f = fixture({ role: "receiver" }),
      text = messages[locale];
    render(<ReferralApp />);
    if (locale === "fr-CA") fill("Language", locale);
    await click(text.check);
    fireEvent.click(screen.getByRole("button", { name: text.receiver }));
    await click(text.loadInbox);
    await click(did);
    fill(text.decision, "partial");
    fireEvent.click(screen.getByRole("checkbox", { name: text.labels.needs }));
    await click(text.submitDecision);
    expect(
      f.mutations.find((item) => item.path.endsWith("/decision"))?.body,
    ).toEqual({
      expected_revision: "1",
      dispatch_id: did,
      payload_digest: digest,
      decision: "partial",
      accepted_fields: ["needs"],
      reason: "scope",
    });
    expect(screen.getByText(text.partialState)).toBeInTheDocument();
    expect(screen.getByText(text.support)).toBeInTheDocument();
  });
}
it("requires actual provider proof and an exact consent confirmation before granting", async () => {
  const f = fixture({ role: "pid" }),
    text = messages["en-CA"];
  vi.stubEnv("VITE_OIDC_ORIGIN", "https://identity.qualification.localhost");
  const close = vi.fn();
  vi.spyOn(window, "open").mockReturnValue({
    close,
    location: { href: "about:blank" },
    opener: null,
  } as unknown as Window);
  render(<ReferralApp />);
  await click(text.check);
  fireEvent.click(screen.getByRole("button", { name: text.client }));
  fill(text.open, rid);
  await click(text.openReferral);
  fireEvent.click(screen.getByRole("checkbox", { name: text.labels.needs }));
  expect(
    screen.getByRole("button", { name: text.previewConsent }),
  ).toBeDisabled();
  await click(text.beginVerification);
  await click(text.confirmVerification);
  await click(text.previewConsent);
  expect(f.mutations.some((item) => item.path === "/v1/consents")).toBe(false);
  await click(text.grantConsent);
  const grant = f.mutations.find((item) => item.path === "/v1/consents");
  expect(grant?.body).toMatchObject({
    subject_id: subject,
    session_id: sid,
    purpose: "referral",
    fields: ["needs"],
    basis: "self",
    authority_proof_id: ceremonyId,
    recipient: {
      kind: "service",
      service_id: service,
      directory_revision: "1",
    },
  });
  expect(
    f.mutations.find((item) => item.path === "/v1/auth/step-up")?.body,
  ).toMatchObject({ purpose: "referral_consent", resource_id: subject });
  expect(
    f.mutations.find((item) => item.path === "/v1/auth/step-up/confirm")?.body,
  ).toMatchObject({ ceremony_id: ceremonyId, proof_intent_id: sourceId });
  expect(close).toHaveBeenCalled();
  expect(screen.getByText(text.grantRecorded)).toBeInTheDocument();
});

it("resumes an uncertain send using the same immutable operation key and body", async () => {
  const f = await prepareSend("en-CA", { lostReply: true }),
    text = f.text;
  await click(text.send);
  await click(text.resume);
  const sends = f.mutations.filter((item) => item.path.endsWith("/send"));
  expect(sends).toHaveLength(2);
  expect(sends[0]?.key).toBe(sends[1]?.key);
  expect(sends[0]?.body).toEqual(sends[1]?.body);
  expect(
    f.mutations.filter((item) => item.path.endsWith("/dispatch")),
  ).toHaveLength(1);
  expect(screen.getByText(text.unresolved)).toBeInTheDocument();
});
it("keeps review distinct from expired consent", async () => {
  const f = await openWorker("en-CA", { expiredConsent: true }),
    text = f.text;
  fill(text.consent, consentId);
  await click(text.loadConsent);
  await click(text.approve);
  expect(screen.getByRole("button", { name: text.enqueue })).toBeDisabled();
  expect(f.mutations.some((item) => item.path.endsWith("/dispatch"))).toBe(
    false,
  );
});
it("selects an admitted fictional service by name without copying its identifier", async () => {
  fixture();
  const text = messages["en-CA"];
  render(<ReferralApp />);
  await click(text.check);
  await click(text.findOptions);
  fill(text.chooseOption, service);
  expect(
    screen.getByRole("heading", { name: "Fictional navigation service" }),
  ).toBeInTheDocument();
  expect(
    screen.getByLabelText(text.service, { selector: "input" }),
  ).toHaveValue(service);
});
