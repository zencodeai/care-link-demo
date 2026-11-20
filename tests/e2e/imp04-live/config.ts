import { lstatSync, mkdirSync, readFileSync } from "node:fs";
import { isAbsolute, resolve } from "node:path";

export type Row = Record<string, unknown>;
export const slots = [
  "pid",
  "pid-other",
  "carer",
  "professional",
  "worker1",
  "worker2",
  "supervisor",
  "operator",
  "security",
] as const;
export type Slot = (typeof slots)[number];
export interface ActorConfig {
  accountId: string;
  role: string;
  username: string;
  password: string;
  totpSecret: string;
}
export interface LiveConfig {
  mainOrigin: string;
  oidcOrigin: string;
  caFile: string;
  endpoint: string;
  actors: Record<Slot, ActorConfig>;
}
export function row(value: unknown): Row {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Expected structured live result; body suppressed");
  return value as Row;
}
export function text(value: Row, key: string): string {
  const result = value[key];
  if (typeof result !== "string" || !result)
    throw new Error(`Missing structured field ${key}; body suppressed`);
  return result;
}
export function privateFile(file: string): void {
  const info = lstatSync(file);
  if (
    !isAbsolute(file) ||
    !info.isFile() ||
    info.isSymbolicLink() ||
    (info.mode & 0o077) !== 0 ||
    info.uid !== process.getuid?.()
  )
    throw new Error("Absolute owner-only regular live input required");
}
export function readConfig(): LiveConfig {
  const file = process.env.CARE_LINK_IMP04_E2E_CONFIG;
  if (!file)
    throw new Error(
      "Set CARE_LINK_IMP04_E2E_CONFIG; live tests never silently skip",
    );
  privateFile(file);
  const value = row(JSON.parse(readFileSync(file, "utf8")) as unknown);
  const mainOrigin = text(value, "mainOrigin");
  const oidcOrigin = text(value, "oidcOrigin");
  if (
    mainOrigin !== "https://plans.localhost:30443" ||
    oidcOrigin !== "https://id.plans.localhost:31443" ||
    value.ignoreHTTPSErrors === true
  )
    throw new Error(
      "Exact IMP04 origins and native certificate validation required",
    );
  const caFile = text(value, "caFile");
  privateFile(caFile);
  let endpoint = value.endpoint ?? value.wsEndpoint;
  if (value.chromeServerFile) {
    const serverFile = text(value, "chromeServerFile");
    privateFile(serverFile);
    const server = row(JSON.parse(readFileSync(serverFile, "utf8")) as unknown);
    endpoint = server.endpoint ?? server.wsEndpoint;
  }
  if (
    typeof endpoint !== "string" ||
    !["ws:", "wss:"].includes(new URL(endpoint).protocol) ||
    !["localhost", "127.0.0.1", "[::1]"].includes(new URL(endpoint).hostname)
  )
    throw new Error("New target private loopback browser broker required");
  const actors = {} as Record<Slot, ActorConfig>;
  const configured = row(value.actors);
  const roles = [
    "pid",
    "pid",
    "carer",
    "professional_participant",
    "worker",
    "worker",
    "supervisor",
    "operator",
    "security",
  ];
  for (const [index, slot] of slots.entries()) {
    const actor = row(configured[slot]);
    const accountId = text(actor, "accountId");
    if (
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
        accountId,
      ) ||
      text(actor, "role") !== roles[index]
    )
      throw new Error("Exact separate actor role/account binding required");
    actors[slot] = {
      accountId,
      role: text(actor, "role"),
      username: text(actor, "username"),
      password: text(actor, "password"),
      totpSecret: text(actor, "totpSecret"),
    };
  }
  if (
    new Set(slots.map((slot) => actors[slot].accountId)).size !==
      slots.length ||
    new Set(slots.map((slot) => actors[slot].username)).size !== slots.length
  )
    throw new Error(
      "All nine synthetic actors must have different issued accounts",
    );
  return { mainOrigin, oidcOrigin, caFile, endpoint, actors };
}
export function evidenceDirectory(): string {
  const path = process.env.CARE_LINK_IMP04_E2E_OUTPUT;
  if (!path || !isAbsolute(path))
    throw new Error("Set absolute CARE_LINK_IMP04_E2E_OUTPUT");
  mkdirSync(path, { recursive: true, mode: 0o700 });
  const info = lstatSync(path);
  if (
    !info.isDirectory() ||
    info.isSymbolicLink() ||
    (info.mode & 0o077) !== 0 ||
    info.uid !== process.getuid?.()
  )
    throw new Error("Owner-only evidence directory required");
  return resolve(path);
}
