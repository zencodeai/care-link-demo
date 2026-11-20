import {
  expect,
  type Page,
  type BrowserContext,
  type Request,
  type Response,
} from "@playwright/test";
import { createHmac, randomUUID } from "node:crypto";
import {
  closeSync,
  constants,
  existsSync,
  fsyncSync,
  lstatSync,
  openSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { dirname, resolve } from "node:path";
import { trustMessages } from "../../../apps/web/src/trust/messages";
import {
  row,
  text,
  type ActorConfig,
  type LiveConfig,
  type Row,
  type Slot,
  privateFile,
  evidenceDirectory,
} from "./config";

export interface Result {
  status: number;
  value: unknown;
  transport_error?: string | null;
  duration_ms?: number;
  stage?: string;
}

/** Require an actual frame; host deadline cannot be suspended with a hidden page. */
export async function renderedFrame(page: Page, stage: string): Promise<void> {
  if (!/^[a-z][a-z0-9_]{0,63}$/.test(stage))
    throw new Error("Fixed rendering checkpoint stage required");
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    await Promise.race([
      page.evaluate(
        () =>
          new Promise<void>((resolve) =>
            requestAnimationFrame(() => resolve()),
          ),
      ),
      new Promise<never>((_, reject) => {
        timer = setTimeout(
          () =>
            reject(
              new Error(
                `Actual rendered frame not observed; stage=${stage}; limit_ms=3000`,
              ),
            ),
          3000,
        );
      }),
    ]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}
const otpWindows = new Map<string, number>();
function otpWindowFile(): string {
  const config = process.env.CARE_LINK_IMP04_E2E_CONFIG;
  if (!config)
    throw new Error("Private OTP window custody requires configured target");
  privateFile(config);
  const parent = dirname(config);
  const target = resolve(parent, "otp-used-windows.json");
  if (target !== "/private/tmp/care-link-imp04-002/otp-used-windows.json")
    throw new Error("Exact private IMP04 OTP window custody required");
  const info = lstatSync(parent);
  if (
    !info.isDirectory() ||
    info.isSymbolicLink() ||
    (info.mode & 0o077) !== 0 ||
    info.uid !== process.getuid?.()
  )
    throw new Error("Owner-only target OTP counter directory required");
  return target;
}
function loadOtpWindows(): void {
  const file = otpWindowFile();
  if (!existsSync(file)) return;
  privateFile(file);
  const saved = row(JSON.parse(readFileSync(file, "utf8")) as unknown);
  for (const [username, counter] of Object.entries(saved)) {
    if (
      typeof counter !== "number" ||
      !Number.isSafeInteger(counter) ||
      counter < 0
    )
      throw new Error("Invalid private OTP use-window counter");
    otpWindows.set(username, Math.max(counter, otpWindows.get(username) ?? -1));
  }
}
function reserveOtpWindow(username: string, window: number): void {
  const file = otpWindowFile();
  if (existsSync(file)) privateFile(file);
  otpWindows.set(username, window);
  const fd = openSync(
    file,
    constants.O_WRONLY |
      constants.O_CREAT |
      constants.O_TRUNC |
      constants.O_NOFOLLOW,
    0o600,
  );
  try {
    writeFileSync(fd, JSON.stringify(Object.fromEntries(otpWindows)));
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
}
function otp(secret: string, window: number): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = 0,
    buffer = 0;
  const bytes: number[] = [];
  for (const char of secret.toUpperCase().replace(/[\s=]/g, "")) {
    const n = alphabet.indexOf(char);
    if (n < 0) throw new Error("Invalid private OTP input");
    buffer = (buffer << 5) | n;
    bits += 5;
    if (bits >= 8) {
      bits -= 8;
      bytes.push((buffer >>> bits) & 255);
    }
  }
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(window));
  const hmac = createHmac("sha1", Buffer.from(bytes)).update(counter).digest();
  const offset = (hmac[hmac.length - 1] ?? 0) & 15;
  return String((hmac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).padStart(
    6,
    "0",
  );
}

export class Actor {
  private apiShell = false;
  parkedState: Awaited<ReturnType<BrowserContext["storageState"]>> | null =
    null;
  documentPolicy: string | null = null;
  constructor(
    readonly page: Page,
    readonly slot: Slot,
    readonly issued: ActorConfig,
    readonly config: LiveConfig,
  ) {}

  async park(): Promise<void> {
    this.parkedState = await this.page.context().storageState();
    await this.page.context().close();
  }

  async ensureMain(visible = false): Promise<void> {
    const settleVisible = async (): Promise<void> => {
      await this.page.locator("#plans-title").waitFor({ state: "visible" });
      await renderedFrame(this.page, "ensure_main_visible");
    };
    if (visible) await this.page.bringToFront();
    if (
      visible &&
      this.apiShell &&
      this.page.url() !== "about:blank" &&
      new URL(this.page.url()).origin === this.config.mainOrigin &&
      (await this.page.locator("#plans-title").count()) > 0
    ) {
      this.apiShell = false;
      await settleVisible();
      return;
    }
    if (this.page.url() === "about:blank" || (visible && this.apiShell)) {
      if (visible) {
        // An API-only document has no mounted client state to preserve. Fully
        // unload its intentionally aborted module before loading the real UI.
        if (this.apiShell)
          await this.page.goto("about:blank", {
            waitUntil: "domcontentloaded",
          });
        const document = await this.page.goto(this.config.mainOrigin, {
          waitUntil: "domcontentloaded",
        });
        this.documentPolicy =
          (await document?.headerValue("content-security-policy")) ?? null;
        this.apiShell = false;
        await settleVisible();
      } else {
        // Keep the actual main HTML/CSP and real cookies, while aborting only
        // application JS assets so idle API actors run no React timers. JSON
        // health pages cannot be used: their intentional CSP denies fetch.
        const abortClient = (route: import("@playwright/test").Route) =>
          route.abort("blockedbyclient");
        await this.page.route("**/assets/*.js", abortClient);
        try {
          const document = await this.page.goto(this.config.mainOrigin, {
            waitUntil: "domcontentloaded",
          });
          this.documentPolicy =
            (await document?.headerValue("content-security-policy")) ?? null;
          this.apiShell = true;
        } finally {
          await this.page.unroute("**/assets/*.js", abortClient);
        }
      }
      return;
    }
    if (new URL(this.page.url()).origin !== this.config.mainOrigin)
      throw new Error(
        "API caller must be on the exact main origin or a parked blank page",
      );
    if (visible) await settleVisible();
  }

  async api(path: string, body?: Row, key?: string): Promise<Result> {
    if (!path.startsWith("/v1/") || path.includes("://"))
      throw new Error("Same-origin application operation required");
    await this.ensureMain();
    return this.page.evaluate(
      async ({ path, body, key, origin }) => {
        if (location.origin !== origin) throw new Error("Wrong actor origin");
        const headers: Record<string, string> = {};
        const started = performance.now();
        const signal = AbortSignal.timeout(15000);
        let stage = "csrf_fetch";
        try {
          if (body !== undefined) {
            const bootstrap = await fetch("/v1/auth/csrf", {
              cache: "no-store",
              signal,
            });
            if (!bootstrap.ok)
              return {
                status: bootstrap.status,
                value: null,
                stage,
                duration_ms: Math.round(performance.now() - started),
                transport_error: null,
              };
            stage = "csrf_body";
            const proof = (await bootstrap.json()) as { csrf_token?: unknown };
            if (typeof proof.csrf_token !== "string")
              throw new Error("Missing real CSRF proof");
            headers["X-CSRF-Token"] = proof.csrf_token;
            headers["Content-Type"] = "application/json";
            headers["Idempotency-Key"] = key;
          }
          stage = "fetch";
          const reply = await fetch(path, {
            method: body === undefined ? "GET" : "POST",
            headers,
            cache: "no-store",
            signal,
            ...(body === undefined ? {} : { body: JSON.stringify(body) }),
          });
          stage = "response_body";
          const value = (await reply.json()) as unknown;
          return {
            status: reply.status,
            value,
            stage: "complete",
            duration_ms: Math.round(performance.now() - started),
            transport_error: null,
          };
        } catch (error) {
          const name = error instanceof Error ? error.name : "unknown";
          const allowed = [
            "AbortError",
            "TimeoutError",
            "TypeError",
            "SyntaxError",
            "Error",
          ];
          return {
            status: 0,
            value: null,
            stage,
            duration_ms: Math.round(performance.now() - started),
            transport_error: allowed.includes(name) ? name : "unknown",
          };
        }
      },
      { path, body, key: key ?? randomUUID(), origin: this.config.mainOrigin },
    );
  }
  async ok(path: string, body?: Row, key?: string): Promise<Row> {
    const reply = await this.api(path, body, key);
    if (reply.status !== 200) {
      const code =
        reply.value && typeof reply.value === "object" && "code" in reply.value
          ? String(reply.value.code)
          : "no_code";
      const messageKey =
        reply.value &&
        typeof reply.value === "object" &&
        "message_key" in reply.value &&
        typeof reply.value.message_key === "string" &&
        /^(manual|identity)\.[a-z_]+$/.test(reply.value.message_key)
          ? reply.value.message_key
          : "none";
      throw new Error(
        `Live API failed: slot=${this.slot}; path=${path}; status=${reply.status}; code=${code}; message_key=${messageKey}; transport_error=${reply.transport_error ?? "none"}; stage=${reply.stage ?? "unknown"}; duration_ms=${reply.duration_ms ?? -1}`,
      );
    }
    return row(reply.value);
  }
  async current(): Promise<Row> {
    const current = await this.ok("/v1/auth/session");
    expect(
      current.account_id === this.issued.accountId &&
        current.role === this.issued.role,
      "Real issuer session matches the exact separately issued actor",
    ).toBe(true);
    return current;
  }
  async signIn(visible = true): Promise<void> {
    const network: Row[] = [];
    const allowedPath = (raw: string): string | null => {
      try {
        const url = new URL(raw);
        return url.origin === this.config.mainOrigin &&
          ["/v1/auth/csrf", "/v1/auth/login"].includes(url.pathname)
          ? url.pathname
          : null;
      } catch {
        return null;
      }
    };
    const requested = (request: Request): void => {
      const path = allowedPath(request.url());
      if (path)
        network.push({ event: "request", path, method: request.method() });
    };
    const responded = (response: Response): void => {
      const path = allowedPath(response.url());
      if (path)
        network.push({ event: "response", path, status: response.status() });
    };
    const failed = (request: Request): void => {
      const path = allowedPath(request.url());
      if (path) network.push({ event: "requestfailed", path });
    };
    // Install observation before navigation/click: CSRF can fail without a
    // subsequent login POST. Never capture headers, body, forms or URL queries.
    this.page.on("request", requested);
    this.page.on("response", responded);
    this.page.on("requestfailed", failed);
    try {
      await this.page.goto(this.config.mainOrigin, {
        waitUntil: "domcontentloaded",
      });
      this.apiShell = false;
      if (visible && !["operator", "security"].includes(this.issued.role)) {
        await this.page
          .locator("#main-account-role")
          .selectOption(this.issued.role);
        const panel = this.page.locator(
          'section[aria-labelledby="main-account-title"]',
        );
        const button = panel.getByRole("button", {
          name: "Sign in",
          exact: true,
        });
        const states = [
          "unchecked",
          "checking",
          "unavailable",
          "signed_out",
          "rejected",
          "invalid",
          "unknown",
        ] as const;
        const panelState = async (): Promise<Row> => {
          const state = await panel
            .locator('[role="status"]')
            .first()
            .textContent()
            .catch(() => null);
          return {
            status:
              states.find((key) => state === trustMessages["en-CA"][key]) ??
              "other_known_or_dynamic_status",
            login_disabled: await button.isDisabled().catch(() => null),
            requested_role_matches: await this.page
              .locator("#main-account-role")
              .inputValue()
              .then((value) => value === this.issued.role)
              .catch(() => false),
          };
        };
        const before = await panelState();
        const login = this.page
          .waitForResponse(
            (r) =>
              r.url() === this.config.mainOrigin + "/v1/auth/login" &&
              r.request().method() === "POST",
          )
          .catch(() => null);
        await button.click();
        const reply = await login;
        if (!reply) {
          const after = await panelState();
          throw new Error(
            `Visible login POST unobserved; slot=${this.slot}; before=${JSON.stringify(before)}; after=${JSON.stringify(after)}; network=${JSON.stringify(network.slice(-20))}`,
          );
        }
        expect(reply.status(), "Visible login intent accepted").toBe(200);
      } else {
        const participant = [
          "pid",
          "carer",
          "professional_participant",
        ].includes(this.issued.role);
        const result = await this.ok("/v1/auth/login", {
          role: this.issued.role,
          return_route: participant
            ? "participant"
            : ["operator", "security"].includes(this.issued.role)
              ? "operations"
              : "workforce",
          locale: "en-CA",
        });
        const destination = new URL(text(result, "authorization_url"));
        this.validateProvider(destination);
        await this.page.goto(destination.href, {
          waitUntil: "domcontentloaded",
        });
      }
      await this.providerLogin();
      await this.current();
    } finally {
      this.page.off("request", requested);
      this.page.off("response", responded);
      this.page.off("requestfailed", failed);
    }
  }
  validateProvider(url: URL): void {
    if (
      url.origin !== this.config.oidcOrigin ||
      url.username ||
      url.password ||
      !url.pathname.startsWith("/realms/care-link-imp04-002/")
    )
      throw new Error("Unexpected real-provider origin/realm; URL suppressed");
  }
  async providerLogin(): Promise<void> {
    let passwordSeen = false,
      otpSeen = false;
    let stage = "provider_navigation";
    const submitted = new Set<string>();
    const providerStarted = Date.now();
    const providerEvents: Row[] = [];
    const checkpoint = (name: string): void => {
      let location = { origin: "unavailable", path: "unavailable" };
      try {
        const current = new URL(this.page.url());
        if (
          [this.config.mainOrigin, this.config.oidcOrigin].includes(
            current.origin,
          )
        )
          location = { origin: current.origin, path: current.pathname };
        else location = { origin: "unexpected", path: "withheld" };
      } catch {
        /* Raw URLs and authorization query values are never retained. */
      }
      const event = {
        stage: name,
        at: new Date().toISOString(),
        elapsed_ms: Date.now() - providerStarted,
        slot: this.slot,
        ...location,
      };
      providerEvents.push(event);
      writeFileSync(
        resolve(evidenceDirectory(), `provider-progress-${this.slot}.json`),
        JSON.stringify(
          {
            ...event,
            event_count: providerEvents.length,
            first: providerEvents.slice(0, 20),
            last: providerEvents.slice(-40),
          },
          null,
          2,
        ),
        { mode: 0o600 },
      );
    };
    const navigated = (frame: import("@playwright/test").Frame): void => {
      if (frame === this.page.mainFrame())
        checkpoint("provider_navigation_event");
    };
    this.page.on("framenavigated", navigated);
    try {
      checkpoint("provider_login_start");
      // The login-intent response arrives before the application's redirect.
      // Its initial main-origin document must never count as an auth callback.
      // Every qualification ceremony requires actual provider authenticators.
      await this.page.waitForURL(
        (url) => url.origin === this.config.oidcOrigin,
        { timeout: 30_000, waitUntil: "domcontentloaded" },
      );
      checkpoint("provider_origin_observed");
      for (let step = 0; step < 8; step++) {
        stage = "provider_challenge";
        checkpoint("provider_challenge_wait");
        if (new URL(this.page.url()).origin === this.config.mainOrigin) break;
        this.validateProvider(new URL(this.page.url()));
        const challenge = await Promise.race([
          this.page
            .locator("#username")
            .waitFor({ state: "visible", timeout: 30_000 })
            .then(() => "credentials"),
          this.page
            .locator("#password")
            .waitFor({ state: "visible", timeout: 30_000 })
            .then(() => "credentials"),
          this.page
            .locator("#otp")
            .waitFor({ state: "visible", timeout: 30_000 })
            .then(() => "otp"),
          this.page
            .waitForURL(
              (u) =>
                u.origin === this.config.mainOrigin &&
                !u.pathname.startsWith("/v1/auth/"),
              { timeout: 30_000, waitUntil: "domcontentloaded" },
            )
            .then(() => "returned"),
        ]);
        if (challenge === "returned") break;
        stage = "submit_" + challenge;
        checkpoint(stage);
        if (submitted.has(challenge))
          throw new Error("Repeated authenticator challenge");
        submitted.add(challenge);
        if (challenge === "otp") {
          loadOtpWindows();
          checkpoint("provider_otp_window_wait");
          const previous = otpWindows.get(this.issued.username) ?? -1;
          await expect
            .poll(() => Math.floor(Date.now() / 30_000) > previous, {
              timeout: 31_000,
              intervals: [250, 500],
            })
            .toBe(true);
          const reservedWindow = Math.floor(Date.now() / 30_000);
          reserveOtpWindow(this.issued.username, reservedWindow);
          checkpoint("provider_otp_window_ready");
          await this.page
            .locator("#otp")
            .fill(otp(this.issued.totpSecret, reservedWindow), {
              timeout: 30_000,
            });
          otpSeen = true;
        } else {
          if (await this.page.locator("#username").isVisible())
            await this.page
              .locator("#username")
              .fill(this.issued.username, { timeout: 30_000 });
          if (await this.page.locator("#password").isVisible()) {
            await this.page
              .locator("#password")
              .fill(this.issued.password, { timeout: 30_000 });
            passwordSeen = true;
          }
        }
        // Arm navigation before submission: waiting for a load state after
        // click may observe the old form's already-loaded document.
        checkpoint("provider_form_submit_start");
        await Promise.all([
          this.page.waitForNavigation({
            waitUntil: "domcontentloaded",
            timeout: 30_000,
          }),
          this.page
            .locator(
              "#kc-login, #kc-login-button, input[type=submit], button[type=submit]",
            )
            .first()
            .click({ timeout: 30_000 }),
        ]);
        checkpoint("provider_form_navigation_complete");
      }
      stage = "application_callback";
      checkpoint("provider_application_callback_wait");
      await this.page.waitForURL(
        (u) =>
          u.origin === this.config.mainOrigin &&
          !u.pathname.startsWith("/v1/auth/"),
        { timeout: 30_000, waitUntil: "domcontentloaded" },
      );
      if (!passwordSeen || !otpSeen)
        throw new Error("Actual password+OTP authentication not observed");
      checkpoint("provider_login_complete");
    } catch (error) {
      checkpoint("provider_login_failed");
      let current = { origin: "unavailable", path: "unavailable" };
      try {
        const url = new URL(this.page.url());
        current = { origin: url.origin, path: url.pathname };
      } catch {
        // Never include raw URLs, auth queries, form contents or credentials.
      }
      const known = [
        "Repeated authenticator challenge",
        "Actual password+OTP authentication not observed",
        "Unexpected real-provider origin/realm; URL suppressed",
        "Invalid private OTP input",
      ];
      const category =
        error instanceof Error && known.includes(error.message)
          ? error.message
          : error instanceof Error && error.name === "TimeoutError"
            ? "navigation_or_challenge_timeout"
            : "provider_driver_failure";
      // eslint-disable-next-line preserve-caught-error -- Raw provider errors can expose credentials or authorization URLs.
      throw new Error(
        `Real provider login failed; slot=${this.slot}; stage=${stage}; category=${category}; password=${passwordSeen}; otp=${otpSeen}; origin=${current.origin}; path=${current.path}; private details suppressed`,
      );
    } finally {
      this.page.off("framenavigated", navigated);
    }
  }
  async verifySubject(subject: string): Promise<string> {
    const current = await this.current();
    const ceremony = await this.ok("/v1/auth/step-up", {
      purpose: "plan_edit",
      resource_id: subject,
      expected_revision: current.revision,
    });
    const url = new URL(text(ceremony, "authorization_url"));
    this.validateProvider(url);
    await this.page.goto(url.href, { waitUntil: "domcontentloaded" });
    await this.providerLogin();
    const updated = await this.current();
    const proof = await this.ok(
      `/v1/auth/step-up/proof?ceremony_id=${text(ceremony, "ceremony_id")}`,
    );
    const confirmed = await this.ok("/v1/auth/step-up/confirm", {
      ceremony_id: ceremony.ceremony_id,
      proof_intent_id: proof.proof_intent_id,
      expected_revision: updated.revision,
    });
    expect(confirmed.state, "Real subject-bound ceremony completed").toBe(
      "verified",
    );
    return text(ceremony, "ceremony_id");
  }
}
