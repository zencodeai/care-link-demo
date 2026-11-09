import { parseContract } from "@care-link/contracts";

export type Role =
  | "pid"
  | "carer"
  | "professional_participant"
  | "worker"
  | "supervisor"
  | "receiver"
  | "operator"
  | "governance"
  | "auditor"
  | "security"
  | "trainer";
export interface Session {
  account_id: string;
  role: Role;
  assurance: "AL0" | "AL1" | "AL2" | "AL3";
  revision: string;
  expires_at: string;
  auth_time: string;
}
export interface HelpView {
  id: string;
  revision: string;
  state: "recorded" | "accepted_unconnected" | "cancelled" | "reconciled";
  created_at: string;
  connection_confirmed: false;
}
export interface Ceremony {
  ceremony_id: string;
  state:
    | "pending"
    | "cooling_off"
    | "confirmation_required"
    | "verified"
    | "expired";
  not_before: string;
  expires_at: string;
  authorization_url: string | null;
}
export interface LoginIntent {
  intent_id: string;
  authorization_url: string;
  expires_at: string;
}
export class RequestFailure extends Error {
  constructor(
    readonly kind:
      | "unavailable"
      | "signed_out"
      | "rejected"
      | "invalid"
      | "unknown",
  ) {
    super(kind);
  }
}
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function strings(value: Record<string, unknown>, keys: string[]): boolean {
  return keys.every((key) => typeof value[key] === "string");
}
function member<T extends string>(
  value: unknown,
  values: readonly T[],
): value is T {
  return typeof value === "string" && values.some((item) => item === value);
}
function session(value: unknown): value is Session {
  return (
    record(value) &&
    strings(value, ["account_id", "revision", "expires_at", "auth_time"]) &&
    member(value.role, [
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
    ] as const) &&
    member(value.assurance, ["AL0", "AL1", "AL2", "AL3"] as const)
  );
}
function help(value: unknown): value is HelpView {
  return (
    record(value) &&
    strings(value, ["id", "revision", "created_at"]) &&
    member(value.state, [
      "recorded",
      "accepted_unconnected",
      "cancelled",
      "reconciled",
    ] as const) &&
    value.connection_confirmed === false
  );
}
function ceremony(value: unknown): value is Ceremony {
  return (
    record(value) &&
    strings(value, ["ceremony_id", "not_before", "expires_at"]) &&
    member(value.state, [
      "pending",
      "cooling_off",
      "confirmation_required",
      "verified",
      "expired",
    ] as const) &&
    (value.authorization_url === null ||
      typeof value.authorization_url === "string")
  );
}
function login(value: unknown): value is LoginIntent {
  return (
    record(value) &&
    strings(value, ["intent_id", "authorization_url", "expires_at"])
  );
}
export function decodeSession(raw: string): Session {
  const value = parseContract("BrowserSession", raw);
  if (!session(value) || Date.parse(value.expires_at) <= Date.now())
    throw new RequestFailure("invalid");
  return value;
}
export function decodeHelp(raw: string): HelpView {
  const value = parseContract("HelpView", raw);
  if (!help(value)) throw new RequestFailure("invalid");
  return value;
}
export function decodeCeremony(raw: string): Ceremony {
  const value = parseContract("Ceremony", raw);
  if (!ceremony(value)) throw new RequestFailure("invalid");
  return value;
}
export function decodeLogin(raw: string): LoginIntent {
  const value = parseContract("LoginIntent", raw);
  if (!login(value) || Date.parse(value.expires_at) <= Date.now())
    throw new RequestFailure("invalid");
  return value;
}
export function configuredOrigin(raw: string | undefined): string | null {
  if (!raw) return null;
  try {
    const url = new URL(raw);
    return url.protocol === "https:" && url.origin === raw ? raw : null;
  } catch {
    return null;
  }
}
export function authorizationUrl(
  raw: string,
  oidcOrigin: string | null,
): string {
  const url = new URL(raw);
  if (
    !oidcOrigin ||
    url.origin !== oidcOrigin ||
    url.protocol !== "https:" ||
    url.username ||
    url.password ||
    url.hash
  )
    throw new RequestFailure("invalid");
  return url.href;
}
export async function csrf(
  origin: string,
  signal: AbortSignal,
): Promise<string> {
  const raw = await request(origin, "/v1/auth/csrf", signal);
  // This BFF bootstrap DTO is local to the browser transport, not a product operation.
  const value = parseContract("BrowserCsrf", raw);
  if (
    !record(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.csrf_token !== "string" ||
    !/^[A-Za-z0-9_-]{32,512}$/.test(value.csrf_token)
  )
    throw new RequestFailure("invalid");
  return value.csrf_token;
}
export async function request(
  origin: string,
  path: string,
  signal: AbortSignal,
  command?: { body: unknown; key?: string; csrf: string },
  metadata?: (headers: Headers) => void,
): Promise<string> {
  let response: Response;
  try {
    response = await fetch(origin + path, {
      method: command ? "POST" : "GET",
      credentials: "include",
      cache: "no-store",
      redirect: "error",
      signal,
      ...(command
        ? {
            headers: {
              "Content-Type": "application/json",
              "X-CSRF-Token": command.csrf,
              ...(command.key ? { "Idempotency-Key": command.key } : {}),
            },
            body: JSON.stringify(command.body),
          }
        : {}),
    });
  } catch {
    throw new RequestFailure(command ? "unknown" : "unavailable");
  }
  if (!response.ok)
    throw new RequestFailure(
      command && response.status >= 500
        ? "unknown"
        : response.status === 401
          ? "signed_out"
          : response.status >= 400 && response.status < 500
            ? "rejected"
            : "unavailable",
    );
  if (
    !response.headers
      .get("content-type")
      ?.toLowerCase()
      .startsWith("application/json")
  )
    throw new RequestFailure("invalid");
  let raw: string;
  try {
    raw = await response.text();
  } catch {
    throw new RequestFailure(command ? "unknown" : "unavailable");
  }
  if (signal.aborted)
    throw new RequestFailure(command ? "unknown" : "unavailable");
  if (raw.length > 64 * 1024) throw new RequestFailure("invalid");
  metadata?.(response.headers);
  return raw;
}

export function decodeProof(raw: string): string {
  const value = parseContract("StepUpProof", raw);
  if (
    !record(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.proof_intent_id !== "string" ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
      value.proof_intent_id,
    )
  )
    throw new RequestFailure("invalid");
  return value.proof_intent_id;
}

export function decodeCreateIntent(raw: string): string {
  const value = parseContract("HelpCreateIntent", raw);
  if (
    !record(value) ||
    typeof value.operation_id !== "string" ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
      value.operation_id,
    )
  )
    throw new RequestFailure("invalid");
  return value.operation_id;
}
