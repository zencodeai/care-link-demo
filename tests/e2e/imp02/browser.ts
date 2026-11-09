import { createHmac, randomUUID } from "node:crypto";
import {
  expect,
  type APIResponse,
  type Locator,
  type Page,
} from "@playwright/test";
import type { LabConfig, LabUser } from "./lab";

const lastOtpWindow = new Map<string, number>();
function totp(secret: string): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = 0;
  let buffer = 0;
  const bytes: number[] = [];
  for (const letter of secret.toUpperCase().replace(/[\s=]/g, "")) {
    const position = alphabet.indexOf(letter);
    if (position < 0) throw new Error("Invalid private lab TOTP configuration");
    buffer = (buffer << 5) | position;
    bits += 5;
    if (bits >= 8) {
      bits -= 8;
      bytes.push((buffer >>> bits) & 255);
    }
  }
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30_000)));
  const result = createHmac("sha1", Buffer.from(bytes))
    .update(counter)
    .digest();
  const offset = (result[result.length - 1] ?? 0) & 15;
  return String(
    (result.readUInt32BE(offset) & 0x7fffffff) % 1_000_000,
  ).padStart(6, "0");
}

/** Drive the actual provider UI. Never inject tokens, cookies or an app session. */
export async function providerLogin(
  page: Page,
  lab: LabConfig,
  user: LabUser,
  returnOrigin: string,
  onMfaSubmitted?: () => void,
): Promise<void> {
  let stage = "awaiting_challenge";
  const challenges: string[] = [];
  const submitted = new Set<string>();
  try {
    for (let step = 0; step < 8; step += 1) {
      const visible = await Promise.race([
        page
          .locator("#username")
          .waitFor({ state: "visible", timeout: 20_000 })
          .then(() => "username" as const),
        page
          .locator("#password")
          .waitFor({ state: "visible", timeout: 20_000 })
          .then(() => "password" as const),
        page
          .locator("#otp")
          .waitFor({ state: "visible", timeout: 20_000 })
          .then(() => "otp" as const),
        page
          .waitForURL(
            (url) =>
              url.origin === returnOrigin &&
              !url.pathname.startsWith("/v1/auth/"),
            { timeout: 20_000 },
          )
          .then(() => "returned" as const),
      ]);
      if (visible === "returned") {
        challenges.push(visible);
        return;
      }
      if (new URL(page.url()).origin !== lab.oidcOrigin)
        throw new Error("Unexpected authentication origin");
      const hasUsername =
        visible !== "otp" && (await page.locator("#username").isVisible());
      const hasPassword =
        visible !== "otp" && (await page.locator("#password").isVisible());
      const challenge =
        visible === "otp"
          ? "otp"
          : hasUsername && hasPassword
            ? "username_password"
            : visible;
      challenges.push(challenge);
      stage = `submit_${challenge}`;
      if (submitted.has(challenge))
        throw new Error("Repeated challenge denied; no brute-force retry");
      submitted.add(challenge);
      if (visible !== "otp") {
        // Either locator can win the visibility race on the combined form.
        // Fill every visible credential field, once, rather than an empty username.
        if (hasUsername) await page.locator("#username").fill(user.username);
        if (hasPassword) await page.locator("#password").fill(user.password);
      } else {
        if (!user.totpSecret)
          throw new Error(
            "Real provider unexpectedly requires unconfigured MFA",
          );
        const last = lastOtpWindow.get(user.username) ?? -1;
        await expect
          .poll(() => Math.floor(Date.now() / 30_000) > last, {
            message: "Wait for a fresh provider OTP time window",
            timeout: 31_000,
            intervals: [250, 500],
          })
          .toBe(true);
        const window = Math.floor(Date.now() / 30_000);
        await page.locator("#otp").fill(totp(user.totpSecret));
        lastOtpWindow.set(user.username, window);
      }
      await page
        .locator(
          "#kc-login, #kc-login-button, input[type=submit], button[type=submit]",
        )
        .first()
        .click();
      await page.waitForLoadState("domcontentloaded");
      if (visible === "otp") onMfaSubmitted?.();
    }
    throw new Error("Provider authentication did not complete");
  } catch {
    // Emit only enumerated challenge/phase metadata and canonical safe error keys.
    // Never forward raw URLs, credentials, provider bodies or Playwright call logs.
    let callback = false;
    let canonicalError = "none_observed";
    let location = "unavailable";
    let requiredProfile = false;
    let requiredOtpSetup = false;
    try {
      const current = new URL(page.url());
      callback =
        current.origin === returnOrigin &&
        current.pathname === "/v1/auth/callback";
      location =
        current.origin === lab.oidcOrigin
          ? current.pathname.includes("/login-actions/required-action")
            ? "provider_required_action"
            : current.pathname.includes("/login-actions/authenticate")
              ? "provider_authenticate"
              : "provider_other"
          : callback
            ? "bff_callback"
            : current.origin === returnOrigin
              ? "app_return"
              : "unexpected_origin";
      requiredProfile = await page
        .locator("#kc-update-profile-form")
        .isVisible();
      requiredOtpSetup = await page
        .locator("#kc-totp-settings-form, #kc-config-totp-form")
        .first()
        .isVisible();
      if (callback) {
        const text = await page.locator("body").innerText({ timeout: 1000 });
        canonicalError =
          /(?:identity|help)[.][a-z_]+/.exec(text)?.[0] ?? "none_observed";
      }
    } catch {
      /* Diagnostic absence is not authority. */
    }
    throw new Error(
      `Actual provider authentication failed; stage=${stage}; challenges=${challenges.join(",")}; callback=${String(callback)}; location=${location}; required_profile=${String(requiredProfile)}; required_otp_setup=${String(requiredOtpSetup)}; canonical_error=${canonicalError}; private details suppressed`,
    );
  }
}
export function accountPanel(page: Page, surface: "main" | "help"): Locator {
  return page.getByRole("region", {
    name: surface === "main" ? "Main account" : "Separate private-help account",
    exact: true,
  });
}
export async function signIn(
  page: Page,
  lab: LabConfig,
  user: LabUser,
  role: "pid" | "worker",
  surface: "main" | "help" = "help",
): Promise<Locator> {
  const origin = surface === "help" ? lab.helpOrigin : lab.mainOrigin;
  await page.goto(origin + (surface === "help" ? "/private-help" : "/"));
  const panel = accountPanel(page, surface);
  await panel.getByLabel("Requested sign-in role").selectOption(role);
  // Register the provider navigation before clicking so fast redirects/SSO cannot
  // accidentally count the initial app URL as a completed login.
  const navigation = page.waitForURL((url) => url.origin === lab.oidcOrigin, {
    waitUntil: "domcontentloaded",
  });
  await panel.getByRole("button", { name: "Sign in", exact: true }).click();
  await navigation;
  await providerLogin(page, lab, user, origin);
  const current = accountPanel(page, surface);
  const checkedResponse = page
    .waitForResponse(
      (response) =>
        response.url() === `${origin}/v1/auth/session` &&
        response.request().method() === "GET",
      { timeout: 15_000 },
    )
    .catch(() => null);
  await current
    .getByRole("button", { name: "Check sign-in", exact: true })
    .click();
  try {
    await expect(
      current.getByText(new RegExp(`Current server role: ${role} \\u00b7`)),
    ).toBeVisible();
  } catch {
    const response = await checkedResponse;
    const body: unknown = response
      ? await response.json().catch(() => null)
      : null;
    const row = isRecord(body) ? body : {};
    const errorKeys = [
      "identity.session_unavailable",
      "identity.session_revoked",
      "identity.current_authority_unavailable",
      "identity.account_unavailable",
      "identity.store_unavailable",
      "identity.workload_denied",
      "identity.unconfigured",
    ];
    const roles = [
      "pid",
      "carer",
      "professional_participant",
      "worker",
      "supervisor",
      "receiver",
      "operator",
      "governance",
      "auditor",
      "security",
      "trainer",
    ];
    const location = new URL(page.url());
    const cookies = await page.context().cookies(origin);
    // Only closed enums/booleans are emitted; never response text, identifiers,
    // cookie values, provider URLs or query strings.
    throw new Error(
      `Sign-in role check failed: ${JSON.stringify({
        status: response?.status() ?? null,
        canonical_error: errorKeys.includes(String(row.message_key))
          ? row.message_key
          : "none_or_unrecognized",
        role: roles.includes(String(row.role)) ? row.role : "absent_or_invalid",
        assurance: ["AL0", "AL1", "AL2", "AL3"].includes(String(row.assurance))
          ? row.assurance
          : "absent_or_invalid",
        location:
          location.origin === origin
            ? location.pathname === "/v1/auth/callback"
              ? "bff_callback"
              : "app_return"
            : location.origin === lab.oidcOrigin
              ? "provider"
              : "unexpected_origin",
        cookies: cookies.map((cookie) => ({
          name: [
            "__Host-care_link_help",
            "__Host-care-link-session",
            "__Host-care-link-binding",
          ].includes(cookie.name)
            ? cookie.name
            : "other",
          secure: cookie.secure,
          httpOnly: cookie.httpOnly,
          sameSite: cookie.sameSite,
          domainMatchesOrigin: cookie.domain === new URL(origin).hostname,
        })),
      })}`,
    );
  }
  return current;
}
export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
export interface HelpResult {
  id: string;
  revision: string;
  state: string;
  connection_confirmed: false;
}
export async function helpResult(response: APIResponse): Promise<HelpResult> {
  const value: unknown = await response.json().catch(() => null);
  const errorKeys = [
    "help.identity_unavailable",
    "help.login_required",
    "help.authority_denied",
    "help.authority_expired",
    "help.role_denied",
    "help.spool_unavailable",
    "help.not_found",
    "help.replayed_decision",
    "help.revision_conflict",
    "help.state_conflict",
    "help.lifecycle_unavailable",
    "help.lifecycle_migration_pending",
  ];
  const error =
    isRecord(value) && errorKeys.includes(String(value.message_key))
      ? value.message_key
      : "none_or_unrecognized";
  expect(
    response.status(),
    `Help response canonical_error=${String(error)}`,
  ).toBe(200);
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    typeof value.revision !== "string" ||
    typeof value.state !== "string" ||
    value.connection_confirmed !== false
  )
    throw new Error("Invalid actual help projection");
  return {
    id: value.id,
    revision: value.revision,
    state: value.state,
    connection_confirmed: false,
  };
}
export async function csrfProof(page: Page, origin: string): Promise<string> {
  const response = await page.request.get(origin + "/v1/auth/csrf");
  expect(response.status()).toBe(200);
  const value: unknown = await response.json();
  if (!isRecord(value) || typeof value.csrf_token !== "string")
    throw new Error("Invalid actual CSRF response");
  return value.csrf_token;
}
export async function cancelOwned(
  page: Page,
  lab: LabConfig,
  id: string,
): Promise<void> {
  const state = await page.request.get(
    `${lab.helpOrigin}/help/v1/requests/${id}`,
  );
  const view = await helpResult(state);
  if (view.state === "cancelled") return;
  const token = await csrfProof(page, lab.helpOrigin);
  const response = await page.request.post(
    `${lab.helpOrigin}/help/v1/requests/${id}/cancel`,
    {
      headers: {
        Origin: lab.helpOrigin,
        "X-CSRF-Token": token,
        "Idempotency-Key": randomUUID(),
      },
      data: { expected_revision: view.revision },
    },
  );
  expect((await helpResult(response)).state).toBe("cancelled");
}

export async function reviewManifest(
  page: Page,
  lab: LabConfig,
  locale: "en-CA" | "fr-CA",
) {
  const canonical = await page.request.get(
    `${lab.staticOrigin}/static/v1/manifest?locale=${locale}`,
  );
  const owner = lab.staticReviewProfile === "owner_review_local_demo";
  expect(canonical.status()).toBe(owner ? 503 : 200);
  const response = owner
    ? await page.request.get(
        `${lab.staticOrigin}/demo-static/v1/manifest?locale=${locale}`,
      )
    : canonical;
  expect(response.status()).toBe(200);
  const body: unknown = await response.json();
  if (
    !isRecord(body) ||
    typeof body.digest !== "string" ||
    !/^[0-9a-f]{64}$/.test(body.digest) ||
    body.locale !== locale
  )
    throw new Error("Actual publication manifest is invalid");
  const reviewDigest = owner
    ? body.owner_review_digest
    : body.independent_review_digest;
  if (typeof reviewDigest !== "string" || !/^[0-9a-f]{64}$/.test(reviewDigest))
    throw new Error("Actual publication review digest is invalid");
  if (owner) {
    expect(body.review_profile).toBe("owner_review_local_demo");
    expect(body.participant_admission).toBe(false);
    expect(body.independent_review).toBe(false);
    expect("independent_review_digest" in body).toBe(false);
  }
  return {
    digest: body.digest,
    locale,
    review_profile: lab.staticReviewProfile,
    review_digest: reviewDigest,
    independent_manifest_available: !owner,
    participant_admission: false,
  };
}
