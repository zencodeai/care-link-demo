import { lstatSync, mkdirSync, readFileSync } from "node:fs";
import { isAbsolute } from "node:path";
export type Row = Record<string, unknown>;
export const slots = [
  "participant",
  "worker1",
  "worker2",
  "supervisor",
] as const;
export type Slot = (typeof slots)[number];
export function row(value: unknown): Row {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Invalid structured result; private body suppressed");
  return value as Row;
}
export function text(value: Row, key: string): string {
  if (typeof value[key] !== "string" || !value[key])
    throw new Error("Missing result field: " + key);
  return value[key];
}
export function privateFile(path: string) {
  const stat = lstatSync(path);
  if (
    !isAbsolute(path) ||
    !stat.isFile() ||
    stat.mode & 0o077 ||
    stat.uid !== process.getuid?.()
  )
    throw new Error("Absolute owner-only regular file required");
}
export function uuid(value: string) {
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
      value,
    )
  )
    throw new Error("Canonical synthetic UUID required");
  return value;
}
export function origin(value: string) {
  const url = new URL(value);
  if (
    url.protocol !== "https:" ||
    url.origin !== value ||
    url.username ||
    url.password
  )
    throw new Error("Exact HTTPS actor origin required");
  return value;
}
export interface ReviewConfig {
  environmentId: string;
  stateRoot: string;
  vaultKeyFile: string | null;
  expectedBrowserVersion: string;
  wsEndpoint: string;
}
export function readConfig(): ReviewConfig {
  const file = process.env.CARE_LINK_REVIEW_E2E_CONFIG;
  if (!file) throw new Error("Set owner-only CARE_LINK_REVIEW_E2E_CONFIG");
  privateFile(file);
  const value = row(JSON.parse(readFileSync(file, "utf8")) as unknown);
  const chrome = text(value, "chrome_server_file");
  privateFile(chrome);
  const server = row(JSON.parse(readFileSync(chrome, "utf8")) as unknown);
  const endpoint = text(server, server.endpoint ? "endpoint" : "wsEndpoint");
  if (!["ws:", "wss:"].includes(new URL(endpoint).protocol))
    throw new Error("Private Chrome WebSocket endpoint required");
  const expected = text(value, "expected_browser_version");
  if (expected !== "157.0.8103.78")
    throw new Error("Exact Google Chrome for Testing version required");
  const stateRoot = text(value, "state_root");
  if (!isAbsolute(stateRoot))
    throw new Error("Explicit absolute toolkit state root required");
  const vault = value.vault_key_file;
  if (vault !== undefined && vault !== null && typeof vault !== "string")
    throw new Error("Invalid private vault pointer");
  if (typeof vault === "string") privateFile(vault);
  privateFile(text(value, "ca_file"));
  return {
    environmentId: text(value, "environment_id"),
    stateRoot,
    vaultKeyFile: typeof vault === "string" ? vault : null,
    expectedBrowserVersion: expected,
    wsEndpoint: endpoint,
  };
}
export function evidenceDirectory(): string {
  const path = process.env.CARE_LINK_REVIEW_E2E_OUTPUT;
  if (!path || !isAbsolute(path))
    throw new Error("Set absolute CARE_LINK_REVIEW_E2E_OUTPUT");
  mkdirSync(path, { recursive: true, mode: 0o700 });
  const stat = lstatSync(path);
  if (
    !stat.isDirectory() ||
    stat.mode & 0o077 ||
    stat.uid !== process.getuid?.()
  )
    throw new Error("Private review output directory required");
  return path;
}
