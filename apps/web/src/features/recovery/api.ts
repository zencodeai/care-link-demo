import { parseContract, validateContract } from "@care-link/contracts";
import { csrf, request, RequestFailure } from "../../trust/api";
import type {
  Command,
  Output,
  Responses,
  TargetEvidence,
  ProposalEvidence,
} from "./types";
function decode<K extends Output>(output: K, value: string): Responses[K] {
  // Closed schema and canonical-decimal validation precede this typed boundary.
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
export async function targetEvidence(
  id: string,
  signal: AbortSignal,
): Promise<TargetEvidence> {
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(id)
  )
    throw new RequestFailure("invalid");
  const target = await read(
    `/v1/recovery/targets/${id}`,
    "RestoreView",
    signal,
  );
  if (target.id !== id) throw new RequestFailure("invalid");
  if (!["validated", "promotion_pending"].includes(target.state))
    return { target, binding: null };
  const binding = await read(
    `/v1/recovery/targets/${id}/evidence`,
    "PromotionBinding",
    signal,
  );
  if (
    binding.target_id !== target.id ||
    binding.validation_digest !== target.validation_digest ||
    binding.journal_id !== target.head.journal_id ||
    binding.journal_generation !== target.head.generation ||
    binding.head_digest !== target.head.tip_digest ||
    binding.restriction_barrier !== target.head.restriction_barrier ||
    binding.serving_generation !== target.serving_generation
  )
    throw new RequestFailure("invalid");
  return { target, binding };
}
export async function bindingDigest(
  binding: Responses["PromotionBinding"],
): Promise<string> {
  const ordered = Object.fromEntries(
    Object.entries(binding).sort(([left], [right]) =>
      left < right ? -1 : left > right ? 1 : 0,
    ),
  );
  const bytes = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(JSON.stringify(ordered)),
  );
  return Array.from(new Uint8Array(bytes), (value) =>
    value.toString(16).padStart(2, "0"),
  ).join("");
}
export async function proposalEvidence(
  id: string,
  signal: AbortSignal,
): Promise<ProposalEvidence> {
  const promotion = await read(
    `/v1/recovery/promotions/${encodeURIComponent(id)}`,
    "PromotionView",
    signal,
  );
  const binding = await read(
    `/v1/recovery/promotions/${promotion.id}/evidence`,
    "PromotionBinding",
    signal,
  );
  if (
    promotion.id !== id ||
    binding.target_id !== promotion.target_id ||
    (await bindingDigest(binding)) !== promotion.binding_digest
  )
    throw new RequestFailure("invalid");
  return { promotion, binding };
}
