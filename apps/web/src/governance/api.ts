import { parseContract, validateContract } from "@care-link/contracts";
import { csrf, request } from "../trust/api";
import type { Command, Output, Responses } from "./types";
function decode<K extends Output>(output: K, value: string): Responses[K] {
  // The closed runtime validator is the JSON-to-interface boundary.
  return parseContract(output, value) as Responses[K];
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
  dispatch: () => void,
): Promise<Responses[K]> {
  validateContract(command.input, command.body);
  const token = await csrf("", signal);
  dispatch();
  return decode(
    command.output,
    await request("", command.path, signal, {
      body: command.body,
      key: command.key,
      csrf: token,
    }),
  );
}
export const list = (value: string) =>
  value
    .split(/[\n,]/)
    .map((v) => v.trim())
    .filter(Boolean);
export const utc = (value: string) =>
  new Date(value.endsWith("Z") ? value : value + "Z").toISOString();
