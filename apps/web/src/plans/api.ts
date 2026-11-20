import { parseContract, validateContract } from "@care-link/contracts";
import {
  csrf,
  request,
  RequestFailure,
  decodeSession,
  type Session,
} from "../trust/api";

export const planFields = [
  "plan.warning_signs",
  "plan.strategies",
  "plan.responders",
  "plan.medication_report",
  "plan.advance_wishes",
  "plan.contacts",
  "plan.substitute_decision_maker",
] as const;
export type PlanField = (typeof planFields)[number];
export type Locale = "en-CA" | "fr-CA";
export type AssertionValue =
  | { kind: "text"; text: string }
  | { kind: "choice"; value: string }
  | { kind: "unknown"; reason: string };
export interface Source {
  kind: string;
  id: string;
  revision: string;
  digest: string;
  observed_at: string;
  verification: string;
}
export interface Assertion {
  id: string;
  revision: string;
  subject_id: string;
  field: string;
  value: AssertionValue;
  author_id: string;
  source: Source | null;
  verification: string;
  supersedes_id: string | null;
  effective_at: string;
}
export interface OwnReportPage {
  items: Assertion[];
  next_cursor: null;
}
export interface Plan {
  id: string;
  subject_id: string;
  revision: string;
  state: "active" | "retired";
  fields: Assertion[];
  retired_at: string | null;
}
export interface Consent {
  id: string;
  revision: string;
  scope: {
    session_id: string | null;
    subject_id: string | null;
    purpose: string;
    fields: string[];
    recipient_id: string | null;
  };
  recipient:
    | { kind: "account"; account_id: string }
    | { kind: "service"; service_id: string; directory_revision: string };
  grantor_id: string;
  scope_digest: string;
  effective_at: string;
  expires_at: string;
  revoked_at: string | null;
}
export const operatingStates = [
  "normal_operations",
  "temporary_closure",
  "regional_outage",
  "holiday_hours",
  "severe_weather",
  "api_failure",
  "conflicting_source",
] as const;
export type OperatingState = (typeof operatingStates)[number];
export interface DirectoryEntry {
  id: string;
  revision: string;
  facts: {
    name: string;
    jurisdictions: string[];
    languages: string[];
    age_scope: string;
    availability: string;
    police_involvement: string;
    qualifications: string[];
    alternative_service_id: string | null;
    hours_description: string;
    operating_state: OperatingState;
  };
  sources: Source[];
  state: string;
  verified_at: string;
  expires_at: string;
}
export interface DirectoryPage {
  items: DirectoryEntry[];
  next_cursor: string | null;
}
export interface Conversation {
  id: string;
  revision: string;
  subject_id: string | null;
  participant_kind: string;
}
export interface Operation {
  operation_id: string;
  state: string;
  safe_reason: string | null;
}
export interface Command {
  key: string;
  path: string;
  input: string;
  output: string;
  body: unknown;
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function strings(value: Record<string, unknown>, keys: string[]) {
  return keys.every((key) => typeof value[key] === "string");
}
function stringArray(value: unknown): value is string[] {
  return (
    Array.isArray(value) &&
    value.every((item: unknown) => typeof item === "string")
  );
}
function nullable(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}
function source(value: unknown): value is Source {
  return (
    record(value) &&
    strings(value, [
      "kind",
      "id",
      "revision",
      "digest",
      "observed_at",
      "verification",
    ])
  );
}
function assertionValue(value: unknown): value is AssertionValue {
  return (
    record(value) &&
    ((value.kind === "text" && typeof value.text === "string") ||
      (value.kind === "choice" && typeof value.value === "string") ||
      (value.kind === "unknown" && typeof value.reason === "string"))
  );
}
export function assertion(value: unknown): value is Assertion {
  return (
    record(value) &&
    strings(value, [
      "id",
      "revision",
      "subject_id",
      "field",
      "author_id",
      "verification",
      "effective_at",
    ]) &&
    assertionValue(value.value) &&
    (value.source === null || source(value.source)) &&
    nullable(value.supersedes_id)
  );
}
export function ownReportPage(value: unknown): value is OwnReportPage {
  return (
    record(value) &&
    Array.isArray(value.items) &&
    value.items.every(assertion) &&
    value.next_cursor === null
  );
}
export function plan(value: unknown): value is Plan {
  return (
    record(value) &&
    strings(value, ["id", "subject_id", "revision"]) &&
    (value.state === "active" || value.state === "retired") &&
    Array.isArray(value.fields) &&
    value.fields.every(assertion) &&
    nullable(value.retired_at)
  );
}
export function consent(value: unknown): value is Consent {
  return (
    record(value) &&
    strings(value, [
      "id",
      "revision",
      "grantor_id",
      "scope_digest",
      "effective_at",
      "expires_at",
    ]) &&
    nullable(value.revoked_at) &&
    record(value.scope) &&
    nullable(value.scope.session_id) &&
    nullable(value.scope.subject_id) &&
    typeof value.scope.purpose === "string" &&
    stringArray(value.scope.fields) &&
    nullable(value.scope.recipient_id) &&
    record(value.recipient) &&
    ((value.recipient.kind === "account" &&
      typeof value.recipient.account_id === "string") ||
      (value.recipient.kind === "service" &&
        strings(value.recipient, ["service_id", "directory_revision"])))
  );
}
export function directoryEntry(value: unknown): value is DirectoryEntry {
  return (
    record(value) &&
    strings(value, ["id", "revision", "state", "verified_at", "expires_at"]) &&
    record(value.facts) &&
    strings(value.facts, [
      "name",
      "age_scope",
      "availability",
      "police_involvement",
      "hours_description",
    ]) &&
    stringArray(value.facts.jurisdictions) &&
    stringArray(value.facts.languages) &&
    stringArray(value.facts.qualifications) &&
    nullable(value.facts.alternative_service_id) &&
    operatingStates.some(
      (state) =>
        value.facts &&
        record(value.facts) &&
        state === value.facts.operating_state,
    ) &&
    Array.isArray(value.sources) &&
    value.sources.every(source)
  );
}
export function directoryPage(value: unknown): value is DirectoryPage {
  return (
    record(value) &&
    Array.isArray(value.items) &&
    value.items.every(directoryEntry) &&
    nullable(value.next_cursor)
  );
}
export function conversation(value: unknown): value is Conversation {
  return (
    record(value) &&
    strings(value, ["id", "revision", "participant_kind"]) &&
    nullable(value.subject_id)
  );
}
export function operation(value: unknown): value is Operation {
  return (
    record(value) &&
    strings(value, ["operation_id", "state"]) &&
    nullable(value.safe_reason)
  );
}
export function decode<T>(
  schema: string,
  value: unknown,
  guard: (value: unknown) => value is T,
): T {
  validateContract(schema, value);
  if (!guard(value)) throw new RequestFailure("invalid");
  return value;
}
export async function read<T>(
  path: string,
  schema: string,
  guard: (value: unknown) => value is T,
  signal: AbortSignal,
): Promise<T> {
  return decode(
    schema,
    parseContract(schema, await request("", path, signal)),
    guard,
  );
}
export async function identity(signal: AbortSignal): Promise<Session> {
  return decodeSession(await request("", "/v1/auth/session", signal));
}
export async function send(
  command: Command,
  signal: AbortSignal,
  onDispatch: () => void,
  viewId: string | null = null,
): Promise<unknown> {
  validateContract(command.input, command.body);
  const token = await csrf("", signal);
  if (signal.aborted) throw new RequestFailure("unavailable");
  onDispatch();
  if (!viewId)
    return parseContract(
      command.output,
      await request("", command.path, signal, {
        body: command.body,
        key: command.key,
        csrf: token,
      }),
    );
  let response: Response;
  try {
    response = await fetch(command.path, {
      method: "POST",
      credentials: "include",
      cache: "no-store",
      redirect: "error",
      signal,
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": token,
        "Idempotency-Key": command.key,
        "X-Review-View": viewId,
      },
      body: JSON.stringify(command.body),
    });
  } catch {
    throw new RequestFailure("unknown");
  }
  if (!response.ok)
    throw new RequestFailure(
      response.status === 401
        ? "signed_out"
        : response.status >= 500
          ? "unknown"
          : "rejected",
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
    throw new RequestFailure("unknown");
  }
  if (signal.aborted) throw new RequestFailure("unknown");
  if (raw.length > 65536) throw new RequestFailure("invalid");
  return parseContract(command.output, raw);
}
export function valueText(value: AssertionValue): string {
  switch (value.kind) {
    case "text":
      return value.text;
    case "choice":
      return value.value;
    case "unknown":
      return value.reason;
  }
}
export const uuid =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
