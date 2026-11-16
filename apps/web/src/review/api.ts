import { parseContract } from "@care-link/contracts";
export class ReviewFailure extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
  ) {
    super(code);
  }
}
export async function json<T>(
  path: string,
  schema?: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    cache: "no-store",
    redirect: "error",
    signal: AbortSignal.timeout(10000),
    ...init,
  });
  if (!response.ok) {
    let code = "service_unavailable";
    try {
      const value = (await response.json()) as {
        code?: string;
        message_key?: string;
      };
      code = value.message_key ?? value.code ?? code;
    } catch {
      /* bounded generic status only */
    }
    throw new ReviewFailure(response.status, code);
  }
  const raw = await response.text();
  if (raw.length > 262144) throw new ReviewFailure(503, "invalid_result");
  return (schema ? parseContract(schema, raw) : JSON.parse(raw)) as T;
}
export async function post<T>(
  path: string,
  body: unknown,
  view: string | null,
  schema?: string,
  operationId: string = crypto.randomUUID(),
): Promise<T> {
  const csrf = await json<{ csrf_token: string }>(
    "/v1/auth/csrf",
    "BrowserCsrf",
  );
  return json<T>(path, schema, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrf.csrf_token,
      "Idempotency-Key": operationId,
      ...(view ? { "X-Review-View": view } : {}),
    },
    body: JSON.stringify(body),
  });
}
export function headers(view: string | null): RequestInit {
  return view ? { headers: { "X-Review-View": view } } : {};
}
