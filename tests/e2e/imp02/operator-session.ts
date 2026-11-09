/** Explicit operator protocol + real provider MFA; exports only one short-lived cookie. */
import {
  lstatSync,
  openSync,
  closeSync,
  fsyncSync,
  fstatSync,
  unlinkSync,
  readFileSync,
  writeFileSync,
  constants,
} from "node:fs";
import { dirname, isAbsolute } from "node:path";
import { randomUUID } from "node:crypto";
import { parseArgs } from "node:util";
import { chromium, type Browser } from "@playwright/test";
import { isRecord, providerLogin } from "./browser.ts";
import { readLabConfig, type LabUser } from "./lab.ts";

function privateJson(path: string): unknown {
  if (!isAbsolute(path))
    throw new Error("An absolute private configuration path is required");
  const metadata = lstatSync(path);
  if (!metadata.isFile() || metadata.mode & 0o077)
    throw new Error("Private regular owner-only configuration required");
  return JSON.parse(readFileSync(path, "utf8")) as unknown;
}
function nonempty(value: unknown): string {
  if (typeof value !== "string" || value.length === 0)
    throw new Error("Missing private operator configuration");
  return value;
}

let phase = "configuration";
let browser: Browser | null = null;
let reserved: { descriptor: number; path: string; inode: number } | null = null;
let exported = false;
try {
  const { values } = parseArgs({
    options: {
      "provider-state": { type: "string" },
      "output-cookie": { type: "string" },
      "lab-config": { type: "string" },
      "session-cookie-name": {
        type: "string",
        default: "__Host-care-link-session",
      },
    },
  });
  if (
    !values["provider-state"] ||
    !values["output-cookie"] ||
    !isAbsolute(values["output-cookie"])
  )
    throw new Error(
      "Explicit private provider state and fresh cookie output paths are required",
    );
  if (values["lab-config"])
    process.env.CARE_LINK_IMP02_E2E_CONFIG = values["lab-config"];
  const lab = readLabConfig();
  const state = privateJson(values["provider-state"]);
  if (!isRecord(state) || !isRecord(state.users) || !isRecord(state.users.main))
    throw new Error("Actual provisioned main account configuration required");
  if (
    state.main_origin !== lab.mainOrigin ||
    state.help_origin !== lab.helpOrigin
  )
    throw new Error("Provisioned state and browser lab origins differ");
  const actual = state.users.main;
  const user: LabUser = {
    username: nonempty(actual.username),
    password: nonempty(actual.password),
    totpSecret: nonempty(actual.totp_secret),
  };
  const accountId = nonempty(actual.account_id);
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
      accountId,
    )
  )
    throw new Error("Actual main account UUID required");
  const output = values["output-cookie"];
  const parent = lstatSync(dirname(output));
  if (!parent.isDirectory() || (parent.mode & 0o077) !== 0)
    throw new Error("Cookie output parent must be owner-only");
  // Reserve only the caller-named new file, never overwrite a prior cookie.
  // No session data is written until all real provider/server checks succeed.
  const reservation = openSync(
    output,
    constants.O_WRONLY |
      constants.O_CREAT |
      constants.O_EXCL |
      constants.O_NOFOLLOW,
    0o600,
  );
  reserved = {
    descriptor: reservation,
    path: output,
    inode: fstatSync(reservation).ino,
  };
  phase = "browser_launch";
  browser = await chromium.launch({
    headless: true,
    args: ["--host-resolver-rules=MAP *.localhost 127.0.0.1"],
    ...(process.env.CARE_LINK_IMP02_BROWSER_PATH
      ? { executablePath: process.env.CARE_LINK_IMP02_BROWSER_PATH }
      : {
          channel:
            process.env.CARE_LINK_IMP02_BROWSER_CHANNEL === "chrome"
              ? "chrome"
              : "chromium",
        }),
  });
  const context = await browser.newContext({
    ignoreHTTPSErrors: lab.ignoreHTTPSErrors,
  });
  const page = await context.newPage();
  phase = "real_bff_protocol_initiation";
  await page.goto(lab.mainOrigin + "/");
  const csrfResponse = await context.request.get(
    lab.mainOrigin + "/v1/auth/csrf",
  );
  if (csrfResponse.status() !== 200)
    throw new Error("Current BFF bootstrap unavailable");
  const csrf: unknown = await csrfResponse.json();
  if (!isRecord(csrf) || typeof csrf.csrf_token !== "string")
    throw new Error("Invalid actual BFF bootstrap");
  const loginResponse = await context.request.post(
    lab.mainOrigin + "/v1/auth/login",
    {
      headers: {
        Origin: lab.mainOrigin,
        "X-CSRF-Token": csrf.csrf_token,
        "Idempotency-Key": randomUUID(),
      },
      data: { role: "operator", return_route: "operations", locale: "en-CA" },
    },
  );
  if (loginResponse.status() !== 200)
    throw new Error("Operator login intent rejected");
  const intent: unknown = await loginResponse.json();
  if (!isRecord(intent) || typeof intent.authorization_url !== "string")
    throw new Error("Invalid actual operator login intent");
  const authorization = new URL(intent.authorization_url);
  if (
    authorization.origin !== lab.oidcOrigin ||
    authorization.protocol !== "https:" ||
    authorization.username ||
    authorization.password ||
    authorization.hash ||
    authorization.pathname !==
      `/realms/${nonempty(state.realm)}/protocol/openid-connect/auth`
  )
    throw new Error("Unexpected actual provider destination");
  phase = "actual_provider_ui_mfa";
  await page.goto(authorization.href);
  let otpSubmitted = false;
  await providerLogin(page, lab, user, lab.mainOrigin, () => {
    otpSubmitted = true;
  });
  phase = "current_operator_session_validation";
  const sessionResponse = await context.request.get(
    lab.mainOrigin + "/v1/auth/session",
  );
  if (sessionResponse.status() !== 200)
    throw new Error("Current operator authority unavailable");
  const session: unknown = await sessionResponse.json();
  if (
    !isRecord(session) ||
    session.account_id !== accountId ||
    session.role !== "operator" ||
    session.assurance !== "AL2" ||
    typeof session.auth_time !== "string" ||
    typeof session.expires_at !== "string" ||
    !otpSubmitted
  )
    throw new Error(
      "Actual operator identity/MFA assurance did not match main",
    );
  const authTime = Date.parse(session.auth_time),
    expiry = Date.parse(session.expires_at);
  if (
    !Number.isFinite(authTime) ||
    !Number.isFinite(expiry) ||
    Date.now() - authTime > 300_000 ||
    authTime - Date.now() > 5000 ||
    expiry <= Date.now()
  )
    throw new Error("Current operator MFA is not fresh");
  const cookieName = values["session-cookie-name"];
  if (!cookieName.startsWith("__Host-"))
    throw new Error("Exact main host-only session cookie required");
  const cookie = (await context.cookies(lab.mainOrigin)).find(
    (item) => item.name === cookieName,
  );
  if (
    !cookie ||
    !cookie.httpOnly ||
    !cookie.secure ||
    cookie.sameSite !== "Lax" ||
    cookie.path !== "/" ||
    cookie.domain !== new URL(lab.mainOrigin).hostname ||
    !cookie.value
  )
    throw new Error("Exact main HttpOnly session cookie unavailable");
  phase = "private_cookie_export";
  if (lstatSync(output).ino !== reserved.inode)
    throw new Error("Reserved private cookie output changed");
  writeFileSync(reserved.descriptor, cookie.value);
  fsyncSync(reserved.descriptor);
  closeSync(reserved.descriptor);
  reserved = null;
  exported = true;
  process.stdout.write(
    JSON.stringify({
      login_initiation: "real_bff_protocol_then_provider_ui",
      browser: browser.version(),
      role: "operator",
      assurance: "AL2",
      main_account_mapping_verified: true,
      provider_otp_submitted: true,
      server_mfa_assurance_verified: true,
      cookie_exported: true,
      ignore_https_errors: lab.ignoreHTTPSErrors,
      scope: "temporary local qualification; no independent human acceptance",
    }) + "\n",
  );
  await context.close();
} catch {
  process.stderr.write(
    `Operator MFA qualification failed during ${phase}; private details suppressed and no successful cookie export is claimed.\n`,
  );
  process.exitCode = 1;
} finally {
  if (reserved) {
    closeSync(reserved.descriptor);
    if (!exported) {
      try {
        if (lstatSync(reserved.path).ino === reserved.inode)
          unlinkSync(reserved.path);
      } catch {
        /* No unrelated path is removed. */
      }
    }
  }
  await browser?.close();
}
