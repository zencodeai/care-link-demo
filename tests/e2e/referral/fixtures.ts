import type { Page } from "@playwright/test";
export const sid = "10000000-0000-4000-8000-000000000001",
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
export const at = "2026-11-20T12:00:00Z",
  future = "2099-11-20T12:00:00Z";
export const digest = "a".repeat(64),
  sourceDigest = "b".repeat(64);
export const source = {
  kind: "assertion",
  id: sourceId,
  revision: "1",
  digest: sourceDigest,
  observed_at: at,
  verification: "disputed",
};
export const field = {
  field: "needs",
  value: { kind: "text", text: "Synthetic request for navigation" },
  sources: [source],
};
export const secondField = {
  field: "preferences",
  value: { kind: "unknown", reason: "not_known" },
  sources: [{ ...source, id: "40000000-0000-4000-8000-000000000002" }],
};
export const payload = {
  session_id: sid,
  subject_id: subject,
  recipient_service_id: service,
  purpose: "referral",
  fields: [field, secondField],
  qualifications: ["Fictional option; capacity is unknown"],
};
export const directory = {
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
export const versions = Object.fromEntries(
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
export const conversation = {
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
export const consent = {
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
export interface Mutation {
  path: string;
  body: Record<string, unknown>;
  key: string | undefined;
}
/** Synthetic API/provider boundary fixtures, not deployed identity or data evidence. */
export async function installFixture(
  page: Page,
  role: "pid" | "worker" | "receiver",
) {
  let reviewed = false,
    sent = false,
    reconciled = false,
    decided = false;
  const mutations: Mutation[] = [];
  const referral = () => ({
    id: rid,
    revision: reviewed ? "2" : "1",
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
    status: reconciled || decided ? "partial" : "received",
    accepted_fields: reconciled || decided ? ["needs"] : [],
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
  const requested: string[] = [];
  await page.route("**/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== "http://127.0.0.1:5175")
      throw new Error("Browser fixture refuses an external API origin");
    const path = url.pathname;
    requested.push(path);
    const body =
      request.method() === "POST"
        ? (JSON.parse(request.postData() ?? "null") as Record<string, unknown>)
        : {};
    if (request.method() === "POST")
      mutations.push({ path, body, key: request.headers()["idempotency-key"] });
    const respond = async (value: unknown) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: { "Cache-Control": "no-store" },
        body: JSON.stringify(value),
      });
    if (path === "/v1/auth/session")
      return respond({
        account_id: actor,
        role,
        assurance: "AL2",
        revision: "1",
        expires_at: future,
        auth_time: at,
      });
    if (path === "/v1/auth/csrf")
      return respond({ csrf_token: "x".repeat(40) });
    if (path === `/v1/sessions/${sid}`) return respond(conversation);
    if (path === `/v1/sessions/${sid}/referral-sources`)
      return respond({
        items: [
          { selected: { field: "needs", source }, field },
          {
            selected: { field: "preferences", source: secondField.sources[0] },
            field: secondField,
          },
        ],
        next_cursor: null,
      });
    if (path === "/v1/directory/search")
      return respond({ items: [directory], next_cursor: null });
    if (path === `/v1/directory/${service}`) return respond(directory);
    if (
      path === `/v1/sessions/${sid}/referrals` ||
      path === `/v1/referrals/${rid}`
    )
      return respond(referral());
    if (path === `/v1/referrals/${rid}/context`)
      return respond({
        referral: referral(),
        versions,
        review: reviewed ? review() : null,
        consent_expires_at: future,
      });
    if (path === `/v1/consents/${consentId}`) return respond(consent);
    if (path === `/v1/referrals/${rid}/review`) {
      reviewed = true;
      return respond(review());
    }
    if (path === `/v1/referrals/${rid}/dispatch`) return respond(dispatch());
    if (path === `/v1/dispatches/${did}`) return respond(dispatch());
    if (path === `/v1/dispatches/${did}/send`) {
      sent = true;
      return respond(dispatch());
    }
    if (path === `/v1/dispatches/${did}/reconcile`) {
      reconciled = true;
      return respond(dispatch());
    }
    if (path === `/v1/dispatches/${did}/receipt`) return respond(receipt());
    if (path === "/v1/receiver/inbox")
      return respond({ dispatch_ids: [did], next_cursor: null });
    if (path === `/v1/receiver/packages/${did}/detail`)
      return respond({
        payload,
        revision: decided ? "2" : "1",
        receipt: receipt(),
      });
    if (path === `/v1/receiver/packages/${did}/decision`) {
      decided = true;
      return respond(receipt());
    }
    if (path === "/v1/auth/step-up" || path === "/v1/auth/step-up/confirm")
      return respond({
        ceremony_id: ceremonyId,
        state: path.endsWith("confirm") ? "verified" : "confirmation_required",
        not_before: at,
        expires_at: future,
        authorization_url: null,
      });
    if (
      path === "/v1/auth/step-up/proof" &&
      url.searchParams.get("ceremony_id") === ceremonyId
    )
      return respond({ proof_intent_id: sourceId });
    if (path === "/v1/consents") return respond(consent);
    throw new Error("Unexpected synthetic API route: " + path);
  });
  return { mutations, requested };
}
