import { readFileSync } from "node:fs";
import { readConfig, type LiveConfig } from "../imp03/config";
import type { LabUser } from "../imp02/lab";

export type ActorName = "pid" | "worker" | "worker2" | "supervisor";
export type Locale = "en-CA" | "fr-CA";
export interface ExtendedConfig extends LiveConfig {
  worker2: LabUser;
  accounts: LiveConfig["accounts"] & { worker2: string };
}
export function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Invalid projection; private body suppressed");
  return value as Record<string, unknown>;
}
export function text(value: Record<string, unknown>, field: string): string {
  if (typeof value[field] !== "string")
    throw new Error("Missing projection field: " + field);
  return value[field];
}
export function readExtendedConfig(): ExtendedConfig {
  const base = readConfig();
  if (base.ignoreHTTPSErrors)
    throw new Error("Extended qualification requires browser TLS verification");
  const path = process.env.CARE_LINK_IMP03_E2E_CONFIG;
  if (!path) throw new Error("Private browser config required");
  const raw = object(JSON.parse(readFileSync(path, "utf8")) as unknown);
  const worker = object(raw.worker2);
  const id = text(object(raw.accounts), "worker2");
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
      id,
    ) ||
    Object.values(base.accounts).includes(id)
  )
    throw new Error("Fourth distinct issued worker account UUID required");
  const second = {
    username: text(worker, "username"),
    password: text(worker, "password"),
    totpSecret: text(worker, "totpSecret"),
  };
  if (
    [base.participant, base.worker, base.supervisor].some(
      (u) => u.username === second.username,
    )
  )
    throw new Error("Second worker must be separately issued");
  return {
    ...base,
    worker2: second,
    accounts: { ...base.accounts, worker2: id },
  };
}
export function readLocale(): Locale {
  const value = process.env.CARE_LINK_IMP03_EXTENDED_LOCALE ?? "en-CA";
  if (value !== "en-CA" && value !== "fr-CA")
    throw new Error("Exact EN/FR demo locale required");
  return value;
}
