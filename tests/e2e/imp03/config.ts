import { lstatSync, readFileSync, mkdirSync } from "node:fs";
import { isAbsolute, resolve } from "node:path";
import type { LabConfig, LabUser } from "../imp02/lab";

export type Role = "pid" | "worker" | "supervisor";
export interface LiveConfig extends LabConfig {
  supervisor: LabUser;
  accounts: Record<Role, string>;
}
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("G-03 configuration requires an object");
  return value as Record<string, unknown>;
}
function text(value: unknown): string {
  if (typeof value !== "string" || !value)
    throw new Error("Missing G-03 field");
  return value;
}
function origin(value: unknown): string {
  const raw = text(value);
  const url = new URL(raw);
  if (url.origin !== raw || url.protocol !== "https:")
    throw new Error("Exact private HTTPS origin required");
  return raw;
}
function user(value: unknown): LabUser {
  const row = record(value);
  return {
    username: text(row.username),
    password: text(row.password),
    totpSecret: text(row.totpSecret),
  };
}
export function privateFile(path: string): void {
  const stat = lstatSync(path);
  if (
    !isAbsolute(path) ||
    !stat.isFile() ||
    (stat.mode & 0o077) !== 0 ||
    stat.uid !== process.getuid?.()
  )
    throw new Error("G-03 secrets require an absolute owner-only regular file");
}
export function readConfig(): LiveConfig {
  const path = process.env.CARE_LINK_IMP03_E2E_CONFIG;
  if (!path)
    throw new Error(
      "Set CARE_LINK_IMP03_E2E_CONFIG; live G-03 never silently skips",
    );
  privateFile(path);
  const row = record(JSON.parse(readFileSync(path, "utf8")) as unknown);
  if (row.session !== "imp03-002") throw new Error("Wrong runtime lease");
  const ids = record(row.accounts);
  const accounts = {
    pid: text(ids.pid),
    worker: text(ids.worker),
    supervisor: text(ids.supervisor),
  };
  if (
    Object.values(accounts).some(
      (id) =>
        !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
          id,
        ),
    ) ||
    new Set(Object.values(accounts)).size !== 3
  )
    throw new Error("Three distinct preissued account UUIDs required");
  const result: LiveConfig = {
    mainOrigin: origin(row.mainOrigin),
    helpOrigin: origin(row.helpOrigin),
    staticOrigin: origin(row.staticOrigin),
    oidcOrigin: origin(row.oidcOrigin),
    participant: user(row.participant),
    worker: user(row.worker),
    supervisor: user(row.supervisor),
    otherParticipant: user(row.supervisor),
    accounts,
    ignoreHTTPSErrors: row.ignoreHTTPSErrors === true,
    staticReviewProfile: "independent",
  };
  if (
    new Set(
      [
        result.mainOrigin,
        result.helpOrigin,
        result.staticOrigin,
        result.oidcOrigin,
      ].map((o) => new URL(o).hostname),
    ).size !== 4 ||
    new Set([
      result.participant.username,
      result.worker.username,
      result.supervisor.username,
    ]).size !== 3
  )
    throw new Error(
      "Separate cookie hosts and separately issued actors required",
    );
  return result;
}
export function evidenceDirectory(): string {
  const path = process.env.CARE_LINK_IMP03_E2E_OUTPUT;
  if (!path || !isAbsolute(path))
    throw new Error("Set absolute CARE_LINK_IMP03_E2E_OUTPUT");
  mkdirSync(path, { recursive: true, mode: 0o700 });
  const stat = lstatSync(path);
  if (
    !stat.isDirectory() ||
    (stat.mode & 0o077) !== 0 ||
    stat.uid !== process.getuid?.()
  )
    throw new Error("Private G-03 evidence directory required");
  return resolve(path);
}
