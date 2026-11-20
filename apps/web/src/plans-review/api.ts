import { parseContract, validateContract } from "@care-link/contracts";
import { csrf, decodeSession, RequestFailure } from "../trust/api";
import { send, uuid } from "../plans/api";
import type {
  PlansReviewContext,
  PlansReviewWorkspace,
  ReviewSession,
} from "./types";
export class ReviewViewUnknown extends RequestFailure {
  constructor() {
    super("rejected");
  }
}

export async function read<T>(
  path: string,
  schema: string,
  signal: AbortSignal,
  view?: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    cache: "no-store",
    redirect: "error",
    signal,
    ...(view ? { headers: { "X-Review-View": view } } : {}),
    ...init,
  });
  if (!response.ok && response.status === 409 && schema === "ReviewView") {
    try {
      if (
        !response.headers
          .get("content-type")
          ?.toLowerCase()
          .startsWith("application/json")
      )
        throw new RequestFailure("invalid");
      const raw = await response.text();
      if (signal.aborted || raw.length > 4096)
        throw new RequestFailure("invalid");
      const error = parseContract("Error", raw) as { message_key: string };
      if (error.message_key === "manual.review_view_unknown")
        throw new ReviewViewUnknown();
    } catch (error) {
      if (error instanceof ReviewViewUnknown) throw error;
    }
  }
  if (!response.ok)
    throw new RequestFailure(
      response.status === 401
        ? "signed_out"
        : response.status < 500
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
  const raw = await response.text();
  if (signal.aborted || raw.length > 262144)
    throw new RequestFailure("unavailable");
  if (schema !== "ReviewView") return parseContract(schema, raw) as T;
  const value = JSON.parse(raw) as Record<string, unknown>;
  if (
    !value ||
    Object.keys(value).length !== 3 ||
    typeof value.view_id !== "string" ||
    !uuid.test(value.view_id) ||
    !["active", "observer"].includes(value.state as string) ||
    typeof value.revision !== "string" ||
    !/^(0|[1-9][0-9]{0,18})$/.test(value.revision) ||
    BigInt(value.revision) > 9223372036854775807n
  )
    throw new RequestFailure("invalid");
  return value as T;
}
export async function write<T>(
  path: string,
  body: unknown,
  input: string,
  output: string,
  signal: AbortSignal,
  view: string | null = null,
): Promise<T> {
  if (output === "ReviewView") {
    validateContract(input, body);
    const token = await csrf("", signal);
    if (signal.aborted) throw new RequestFailure("unavailable");
    return read<T>(path, output, signal, view ?? undefined, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": token,
        "Idempotency-Key": crypto.randomUUID(),
        ...(view ? { "X-Review-View": view } : {}),
      },
      body: JSON.stringify(body),
    });
  }
  return send(
    { key: crypto.randomUUID(), path, input, output, body },
    signal,
    () => {},
    view,
  ) as Promise<T>;
}
export function assertContext(
  value: PlansReviewContext | { enabled: false },
): asserts value is PlansReviewContext {
  if (
    !value.enabled ||
    value.mode !== "plans" ||
    value.authentication_mode !== "automatic_review" ||
    value.environment !== "synthetic-review" ||
    value.origin !== window.location.origin ||
    value.run_state !== "active" ||
    !Number.isFinite(Date.parse(value.expires_at)) ||
    Date.parse(value.expires_at) <= Date.now()
  )
    throw new RequestFailure("rejected");
}
export function assertActor(
  value: ReviewSession,
  context: PlansReviewContext,
): void {
  decodeSession(JSON.stringify(value));
  if (
    value.account_id !== context.account_id ||
    value.role !== context.role ||
    value.review_run_id !== context.run_id ||
    value.review_slot_id !== context.slot_id ||
    value.review_origin !== context.origin
  )
    throw new RequestFailure("invalid");
}
export function assertWorkspace(
  value: PlansReviewWorkspace,
  context: PlansReviewContext,
): void {
  if (
    value.workspace.run_id !== context.run_id ||
    value.workspace.run_state !== "active" ||
    !Number.isFinite(Date.parse(value.expires_at)) ||
    value.workspace.conversation?.id !== value.selection.session_id ||
    Date.parse(value.expires_at) <= Date.now() ||
    Date.parse(value.expires_at) > Date.parse(context.expires_at)
  )
    throw new RequestFailure("invalid");
}
