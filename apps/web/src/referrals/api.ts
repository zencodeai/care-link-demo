import { parseContract, validateContract } from "@care-link/contracts";
import { csrf, request, type Ceremony } from "../trust/api";
import type { DirectoryPage } from "../plans/api";
import type {
  Consent,
  Context,
  Conversation,
  DirectoryEntry,
  Dispatch,
  Inbox,
  Payload,
  Receipt,
  ReceiverDetail,
  Referral,
  Review,
  Selection,
} from "./types";
export interface SourcePage {
  items: { selected: Selection; field: Payload["fields"][number] }[];
  next_cursor: null;
}
interface Responses {
  SessionView: Conversation;
  DirectoryView: DirectoryEntry;
  DirectoryPage: DirectoryPage;
  ReferralView: Referral;
  ReferralContext: Context;
  ReferralSourcePage: SourcePage;
  ReviewView: Review;
  ConsentView: Consent;
  DispatchView: Dispatch;
  ReceiptView: Receipt;
  ReceiverDetail: ReceiverDetail;
  ReceiverPackagePage: Inbox;
  Ceremony: Ceremony;
  CommandResult: {
    operation_id: string;
    state: string;
    resource_id: string | null;
    revision: string;
    audit_ref: string;
  };
}
export type Output = keyof Responses;
// The schema is fixed at each call site. Runtime validation precedes this sole
// JSON-to-type boundary; callers cannot choose an unrelated response type.
function decode<K extends Output>(schema: K, raw: string): Responses[K] {
  return parseContract(schema, raw) as Responses[K];
}
export async function read<K extends Output>(
  path: string,
  schema: K,
  signal: AbortSignal,
): Promise<Responses[K]> {
  return decode(schema, await request("", path, signal));
}
export interface Command<K extends Output = Output> {
  key: string;
  path: string;
  input: string;
  output: K;
  body: unknown;
}
export async function write<K extends Output>(
  command: Command<K>,
  signal: AbortSignal,
): Promise<Responses[K]> {
  validateContract(command.input, command.body);
  const token = await csrf("", signal);
  return decode(
    command.output,
    await request("", command.path, signal, {
      body: command.body,
      key: command.key,
      csrf: token,
    }),
  );
}
export const identifierPattern =
  "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
