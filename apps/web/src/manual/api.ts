import { parseContract, validateContract } from "@care-link/contracts";
import { csrf, request, RequestFailure } from "../trust/api";

export interface Conversation {
  id: string;
  revision: string;
  participant_kind: string;
  service_phase:
    | "active"
    | "human_requested"
    | "queued"
    | "worker_assigned"
    | "handoff_pending"
    | "human_controlled"
    | "ended";
  control_epoch: string;
  transport: string;
  owner_id: string | null;
  unresolved: boolean;
  degraded_reasons: string[];
}
export interface QueueItem {
  session_id: string;
  ticket_id: string;
  revision: string;
  state: string;
  mode: string;
  connection_confirmed: boolean;
  wait_estimate_seconds: number | null;
}
export interface Assignment {
  id: string;
  session_id: string;
  worker_id: string;
  revision: string;
  state: string;
  control_epoch: string;
  expires_at: string;
}
export interface Preparation {
  assignment: Assignment;
  challenge_id: string;
  expires_at: string;
}
export interface Challenge {
  challenge_id: string;
  assignment_id: string;
  party: string;
  nonce: string;
  transport_generation: string;
  control_epoch: string;
  expires_at: string;
}
export interface Acknowledgement {
  ack_id: string;
  challenge_id: string;
  evidence_id: string | null;
  state: string;
  expires_at: string;
}
export interface Message {
  id: string;
  text: string;
  kind: string;
  sender_id: string;
  control_epoch: string;
  created_at: string;
}
export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}
export interface Outcome {
  operation_id: string;
  state: string;
  safe_reason: string | null;
}
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function strings(value: Record<string, unknown>, names: string[]): boolean {
  return names.every((name) => typeof value[name] === "string");
}
function nullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}
function phase(value: unknown): value is Conversation["service_phase"] {
  return (
    value === "active" ||
    value === "human_requested" ||
    value === "queued" ||
    value === "worker_assigned" ||
    value === "handoff_pending" ||
    value === "human_controlled" ||
    value === "ended"
  );
}
export function conversation(value: unknown): value is Conversation {
  return (
    record(value) &&
    strings(value, [
      "id",
      "revision",
      "participant_kind",
      "control_epoch",
      "transport",
    ]) &&
    phase(value.service_phase) &&
    nullableString(value.owner_id) &&
    typeof value.unresolved === "boolean" &&
    Array.isArray(value.degraded_reasons) &&
    value.degraded_reasons.every((item: unknown) => typeof item === "string")
  );
}
export function queueItem(value: unknown): value is QueueItem {
  return (
    record(value) &&
    strings(value, ["session_id", "ticket_id", "revision", "state", "mode"]) &&
    typeof value.connection_confirmed === "boolean" &&
    (value.wait_estimate_seconds === null ||
      typeof value.wait_estimate_seconds === "number")
  );
}
export function assignment(value: unknown): value is Assignment {
  return (
    record(value) &&
    strings(value, [
      "id",
      "session_id",
      "worker_id",
      "revision",
      "state",
      "control_epoch",
      "expires_at",
    ])
  );
}
export function preparation(value: unknown): value is Preparation {
  return (
    record(value) &&
    assignment(value.assignment) &&
    strings(value, ["challenge_id", "expires_at"])
  );
}
export function challenge(value: unknown): value is Challenge {
  return (
    record(value) &&
    strings(value, [
      "challenge_id",
      "assignment_id",
      "party",
      "nonce",
      "transport_generation",
      "control_epoch",
      "expires_at",
    ])
  );
}
export function acknowledgement(value: unknown): value is Acknowledgement {
  return (
    record(value) &&
    strings(value, ["ack_id", "challenge_id", "state", "expires_at"]) &&
    nullableString(value.evidence_id)
  );
}
export function message(value: unknown): value is Message {
  return (
    record(value) &&
    strings(value, [
      "id",
      "text",
      "kind",
      "sender_id",
      "control_epoch",
      "created_at",
    ])
  );
}
export function page<T>(guard: (value: unknown) => value is T) {
  return (value: unknown): value is Page<T> =>
    record(value) &&
    Array.isArray(value.items) &&
    value.items.every(guard) &&
    nullableString(value.next_cursor);
}
export function outcome(value: unknown): value is Outcome {
  return (
    record(value) &&
    strings(value, ["operation_id", "state"]) &&
    nullableString(value.safe_reason)
  );
}
export function decode<T>(
  schema: string,
  raw: string,
  guard: (value: unknown) => value is T,
): T {
  const value = parseContract(schema, raw);
  if (!guard(value)) throw new RequestFailure("invalid");
  return value;
}
export async function get<T>(
  path: string,
  schema: string,
  guard: (value: unknown) => value is T,
  signal: AbortSignal,
): Promise<T> {
  return decode(schema, await request("", path, signal), guard);
}
export interface Command {
  key: string;
  path: string;
  input: string;
  body: unknown;
  output: string;
}
export async function send(
  command: Command,
  signal: AbortSignal,
  onDispatch?: () => void,
): Promise<unknown> {
  validateContract(command.input, command.body);
  const token = await csrf("", signal);
  if (signal.aborted) throw new RequestFailure("unavailable");
  onDispatch?.();
  const raw = await request("", command.path, signal, {
    body: command.body,
    key: command.key,
    csrf: token,
  });
  return parseContract(command.output, raw);
}
