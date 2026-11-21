import type { Consent } from "../plans/api";
import { parseContract, validateContract } from "@care-link/contracts";
import { csrf, request, type Ceremony } from "../trust/api";
import type {
  Anchor,
  Export,
  FollowUp,
  InboxMessage,
  Outcome,
  Page,
  Rights,
  SessionContext,
} from "./types";
export interface Responses {
  SessionView: SessionContext;
  ConsentView: Consent;
  PostCrisisView: Anchor;
  FollowUpView: FollowUp;
  InboxPage: Page<InboxMessage>;
  InboxMessageView: InboxMessage;
  OutcomeView: Outcome;
  OutcomePage: Page<Outcome>;
  RightsView: Rights;
  ExportView: Export;
  Ceremony: Ceremony;
  CommandResult: { resource_id: string | null; revision: string };
}
export type Output = keyof Responses;
export interface Command<K extends Output = Output> {
  key: string;
  path: string;
  input: string;
  output: K;
  body: unknown;
}
// Each call fixes its schema; runtime validation precedes the only JSON/type boundary.
function decode<K extends Output>(schema: K, raw: string): Responses[K] {
  return parseContract(schema, raw) as Responses[K];
}
export async function read<K extends Output>(
  path: string,
  output: K,
  signal: AbortSignal,
): Promise<Responses[K]> {
  return decode(output, await request("", path, signal));
}
export async function write<K extends Output>(
  command: Command<K>,
  signal: AbortSignal,
  onDispatch: () => void,
): Promise<Responses[K]> {
  validateContract(command.input, command.body);
  const token = await csrf("", signal);
  onDispatch();
  return decode(
    command.output,
    await request("", command.path, signal, {
      body: command.body,
      key: command.key,
      csrf: token,
    }),
  );
}
export const uuidPattern =
  "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
export function utc(value: string): string {
  return new Date(value).toISOString();
}
