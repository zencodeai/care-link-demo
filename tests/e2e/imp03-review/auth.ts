import { expect, type Frame } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { ActorPage, words } from "./browser";
import { evidenceDirectory, text } from "./config";
import type { Toolkit } from "./toolkit";

export async function signIn(
  actor: ActorPage,
  toolkit: Toolkit,
  navigate = true,
) {
  let stage = "workspace";
  const navigations: { origin: string; path: string; at: string }[] = [];
  const recordNavigation = (frame: Frame) => {
    if (frame !== actor.page.mainFrame()) return;
    try {
      const url = new URL(frame.url());
      navigations.push({
        origin: url.origin,
        path: url.pathname,
        at: new Date().toISOString(),
      });
      if (navigations.length > 20) navigations.shift();
    } catch {
      /* no raw authentication URL */
    }
  };
  actor.page.on("framenavigated", recordNavigation);
  let passwordSeen = false,
    otpSeen = false;
  try {
    if (navigate)
      await actor.page.goto(actor.actor.url, { waitUntil: "domcontentloaded" });
    stage = "login_intent";
    const reply = actor.page.waitForResponse(
      (response) =>
        response.url() === actor.actor.origin + "/v1/auth/login" &&
        response.request().method() === "POST",
    );
    await actor.button(words.signIn).click();
    const result = await reply;
    if (result.status() !== 200) throw new Error("intent_denied");
    const providerOrigin = "https://id.localhost:20443";
    const realm =
      actor.actor.slot === "participant"
        ? "care-link-imp03-cont1"
        : `care-link-imp03-cont1-${actor.actor.slot}`;
    const expectedProvider = (url: URL) =>
      url.origin === providerOrigin &&
      !url.username &&
      !url.password &&
      url.pathname.startsWith(`/realms/${realm}/`);
    // The product validates its authorization URL before navigating. Observe
    // that visible navigation without reading a response body after it leaves.
    await actor.page.waitForURL(expectedProvider);
    const submitted = new Set<string>();
    for (let step = 0; step < 8; step += 1) {
      stage = "provider_challenge";
      const form = await Promise.race([
        actor.page
          .locator("#username")
          .waitFor({ state: "visible" })
          .then(() => "username"),
        actor.page
          .locator("#password")
          .waitFor({ state: "visible" })
          .then(() => "password"),
        actor.page
          .locator("#otp")
          .waitFor({ state: "visible" })
          .then(() => "otp"),
        actor.page
          .waitForURL(
            (url) =>
              url.origin === actor.actor.origin &&
              !url.pathname.startsWith("/v1/auth/"),
          )
          .then(() => "returned"),
      ]);
      if (form === "returned") break;
      if (!expectedProvider(new URL(actor.page.url())))
        throw new Error("unexpected_provider_origin_or_realm");
      const username =
        form !== "otp" && (await actor.page.locator("#username").isVisible());
      const password =
        form !== "otp" && (await actor.page.locator("#password").isVisible());
      const challenge =
        form === "otp"
          ? "otp"
          : username && password
            ? "username_password"
            : form;
      if (submitted.has(challenge))
        throw new Error("repeated_challenge_no_retry");
      submitted.add(challenge);
      stage = "submit_" + challenge;
      if (username)
        await actor.page.locator("#username").fill(actor.actor.username);
      if (password) {
        await actor.page
          .locator("#password")
          .fill(await toolkit.password(actor.actor.slot));
        passwordSeen = true;
      }
      if (form === "otp") {
        await actor.page
          .locator("#otp")
          .fill(await toolkit.otp(actor.actor.slot));
        otpSeen = true;
      }
      await actor.page
        .locator(
          "#kc-login, #kc-login-button, input[type=submit], button[type=submit]",
        )
        .first()
        .click();
      await actor.page.waitForLoadState("domcontentloaded");
    }
    stage = "returned_identity";
    if (!passwordSeen || !otpSeen)
      throw new Error("fresh_visible_password_mfa_not_observed");
    await actor.page.waitForURL(
      (url) =>
        url.origin === actor.actor.origin &&
        !url.pathname.startsWith("/v1/auth/"),
    );
    await actor.assertVisibleIdentity();
  } catch (error) {
    try {
      const current = new URL(actor.page.url());
      const visible = await actor.page
        .locator("body")
        .innerText({ timeout: 1500 })
        .catch(() => "unavailable");
      const forms = await Promise.all(
        ["#username", "#password", "#otp"].map(async (selector) => ({
          selector,
          visible: await actor.page
            .locator(selector)
            .isVisible()
            .catch(() => false),
        })),
      );
      writeFileSync(
        resolve(evidenceDirectory(), "auth-failure.json"),
        JSON.stringify(
          {
            slot: actor.actor.slot,
            stage,
            password_form: passwordSeen,
            mfa_form: otpSeen,
            current: { origin: current.origin, path: current.pathname },
            navigations,
            forms,
            visible_body: visible.slice(0, 20000),
            underlying_error:
              error instanceof Error
                ? (error.stack ?? error.message).slice(0, 30000)
                : "Non-Error failure; value suppressed",
          },
          null,
          2,
        ),
        { mode: 0o600, flag: "wx" },
      );
    } catch {
      /* Diagnostic failure never exposes the original private error. */
    }
    // eslint-disable-next-line preserve-caught-error -- Raw cause stays in owner-only auth-failure.json.
    throw new Error(
      `Real provider sign-in failed; slot=${actor.actor.slot}; stage=${stage}; password_form=${String(passwordSeen)}; mfa_form=${String(otpSeen)}; private details suppressed`,
    );
  } finally {
    actor.page.off("framenavigated", recordNavigation);
  }
}
export async function signOutIsolated(
  actor: ActorPage,
  others: ActorPage[],
  toolkit: Toolkit,
) {
  await actor.postUI("/v1/auth/logout", () =>
    actor.button(words.signOut).click(),
  );
  await expect(actor.button(words.signOut)).toHaveCount(0);
  for (const other of others) await other.assertVisibleIdentity();
  await signIn(actor, toolkit, false);
  for (const other of others) await other.assertVisibleIdentity();
}

export async function ensureFreshMfa(
  actor: ActorPage,
  toolkit: Toolkit,
): Promise<boolean> {
  if (actor.actor.role === "pid") return false;
  const current = await actor.current();
  const authenticated = Date.parse(text(current, "auth_time"));
  if (!Number.isFinite(authenticated))
    throw new Error("Actual privileged auth_time unavailable");
  if (Date.now() - authenticated < 240_000) return false;
  // Explicit visible provider password/MFA ceremony before a privileged action;
  // no expiry extension, synthetic assurance or retry of a rejected action.
  await signIn(actor, toolkit, false);
  return true;
}
