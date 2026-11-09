import { lstatSync, readFileSync } from "node:fs";
import { isAbsolute } from "node:path";

export interface LabUser {
  username: string;
  password: string;
  totpSecret: string | null;
}
export interface LabConfig {
  mainOrigin: string;
  helpOrigin: string;
  oidcOrigin: string;
  staticOrigin: string;
  participant: LabUser;
  otherParticipant: LabUser;
  worker: LabUser;
  ignoreHTTPSErrors: boolean;
  staticReviewProfile: "independent" | "owner_review_local_demo";
}
function object(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    throw new Error("Invalid IMP-02 browser lab configuration");
  return value as Record<string, unknown>;
}
function string(value: unknown): string {
  if (typeof value !== "string" || !value)
    throw new Error("Missing IMP-02 browser lab field");
  return value;
}
function origin(value: unknown): string {
  const raw = string(value);
  const url = new URL(raw);
  if (
    url.origin !== raw ||
    url.protocol !== "https:" ||
    !(
      ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname) ||
      /^[a-z0-9-]+\.localhost$/.test(url.hostname)
    )
  )
    throw new Error(
      "IMP-02 browser tests require exact HTTPS loopback origins",
    );
  return raw;
}
function user(value: unknown): LabUser {
  const row = object(value);
  return {
    username: string(row.username),
    password: string(row.password),
    totpSecret:
      row.totpSecret === null || row.totpSecret === undefined
        ? null
        : string(row.totpSecret),
  };
}
export function readLabConfig(): LabConfig {
  const file = process.env.CARE_LINK_IMP02_E2E_CONFIG;
  if (!file || !isAbsolute(file))
    throw new Error(
      "Set CARE_LINK_IMP02_E2E_CONFIG to the private lab JSON path; real-provider tests never silently skip",
    );
  const metadata = lstatSync(file);
  if (!metadata.isFile() || (metadata.mode & 0o077) !== 0)
    throw new Error(
      "IMP-02 credential configuration must be a regular owner-only file",
    );
  const row = object(JSON.parse(readFileSync(file, "utf8")) as unknown);
  const result = {
    mainOrigin: origin(row.mainOrigin),
    helpOrigin: origin(row.helpOrigin),
    oidcOrigin: origin(row.oidcOrigin),
    staticOrigin: origin(row.staticOrigin),
    participant: user(row.participant),
    otherParticipant: user(row.otherParticipant),
    worker: user(row.worker),
    ignoreHTTPSErrors: row.ignoreHTTPSErrors === true,
    staticReviewProfile:
      row.staticReviewProfile === "owner_review_local_demo"
        ? ("owner_review_local_demo" as const)
        : ("independent" as const),
  };
  if (
    new Set([
      result.mainOrigin,
      result.helpOrigin,
      result.oidcOrigin,
      result.staticOrigin,
    ]).size !== 4
  )
    throw new Error("IMP-02 browser origins must be separate");
  if (
    new Set(
      [
        result.mainOrigin,
        result.helpOrigin,
        result.oidcOrigin,
        result.staticOrigin,
      ].map((value) => new URL(value).hostname),
    ).size !== 4
  )
    throw new Error(
      "BFF/provider/static cookie custody requires distinct hostnames, not only ports",
    );
  if (
    new Set([
      result.participant.username,
      result.otherParticipant.username,
      result.worker.username,
    ]).size !== 3
  )
    throw new Error(
      "IMP-02 browser role accounts must be distinct scoped identities",
    );
  if (!result.worker.totpSecret)
    throw new Error(
      "Worker qualification requires configured real-provider MFA",
    );
  return result;
}
