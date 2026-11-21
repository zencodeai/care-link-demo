import { parseContract, validateContract } from "@care-link/contracts";
import { csrf, request } from "../trust/api";
import type {
  Availability,
  KnowledgeResults,
  DraftContext,
  Review,
  Task,
  TaskContext,
} from "./types";
export interface Responses {
  AssistanceStatus: Availability;
  AssistanceTaskContext: TaskContext;
  AssistanceDraftContext: DraftContext;
  TaskView: Task;
  ReviewView: Review;
  KnowledgeResults: KnowledgeResults;
}
export type Output = keyof Responses;
// Each call fixes the schema; this sole cast follows complete contract validation.
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
