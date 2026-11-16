// Self-contained functions passed to page.evaluate. CSRF proofs stay in browser
// memory, never in the Node-side test inputs or observation files.
type Row = Record<string, unknown>;
type BarrierMemory = {
  g03BarrierProof?: { path: string; token: string };
};
export interface BrowserRequest {
  path: string;
  body?: Row | undefined;
  key?: string | undefined;
  preparedMutation?: boolean | undefined;
}
export interface BrowserResponse {
  status: number;
  value: unknown;
  attempted: { method: "GET" | "POST"; path: string } | null;
}

export async function prepareBarrierMutation(path: string): Promise<number> {
  const memory = window as unknown as BarrierMemory;
  delete memory.g03BarrierProof;
  try {
    const response = await fetch("/v1/auth/csrf", { cache: "no-store" });
    if (!response.ok) return response.status;
    const proof = (await response.json()) as { csrf_token?: unknown };
    if (typeof proof.csrf_token !== "string" || !proof.csrf_token)
      throw new Error(
        "Invalid pre-barrier CSRF proof; private body suppressed",
      );
    memory.g03BarrierProof = { path, token: proof.csrf_token };
    return response.status;
  } catch {
    return 0;
  }
}

export async function browserRequest({
  path,
  body,
  key,
  preparedMutation,
}: BrowserRequest): Promise<BrowserResponse> {
  let headers: Record<string, string> = {};
  if (body !== undefined) {
    let token: string;
    if (preparedMutation) {
      const memory = window as unknown as BarrierMemory;
      const proof = memory.g03BarrierProof;
      delete memory.g03BarrierProof;
      if (!proof || proof.path !== path)
        throw new Error("Missing exact pre-barrier CSRF proof");
      token = proof.token;
    } else {
      const bootstrap = await fetch("/v1/auth/csrf", { cache: "no-store" });
      if (!bootstrap.ok)
        return { status: bootstrap.status, value: {}, attempted: null };
      const proof = (await bootstrap.json()) as { csrf_token: string };
      token = proof.csrf_token;
    }
    headers = {
      Origin: location.origin,
      "Content-Type": "application/json",
      "X-CSRF-Token": token,
      "Idempotency-Key": key ?? crypto.randomUUID(),
    };
  } else if (preparedMutation) {
    throw new Error("A prepared barrier mutation requires a body");
  }
  const attempted = {
    method: body === undefined ? "GET" : "POST",
    path,
  } as const;
  try {
    const response = await fetch(path, {
      method: attempted.method,
      headers,
      cache: "no-store",
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    return {
      status: response.status,
      value: (await response.json().catch(() => null)) as unknown,
      attempted,
    };
  } catch {
    return { status: 0, value: null as unknown, attempted };
  }
}
