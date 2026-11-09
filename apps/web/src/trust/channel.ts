import { useEffect, useRef, useState } from "react";
import {
  csrf,
  decodeSession,
  decodeCreateIntent,
  request,
  RequestFailure,
  type Session,
} from "./api";
type Notice =
  | "unchecked"
  | "checking"
  | "unavailable"
  | "signed_out"
  | "rejected"
  | "invalid"
  | "unknown";
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export function useChannel(origin: string) {
  const [session, setSession] = useState<Session | null>(null);
  const [completedCeremony, setCompletedCeremony] = useState<string | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice>("unchecked");
  const active = useRef<AbortController | null>(null);
  const commands = useRef(new Map<string, string>());
  useEffect(
    () => () => {
      active.current?.abort();
      active.current = null;
    },
    [],
  );
  useEffect(() => {
    if (!session) return;
    const timer = window.setTimeout(
      () => {
        active.current?.abort();
        setSession(null);
        setNotice("signed_out");
      },
      Math.max(
        0,
        Math.min(Date.parse(session.expires_at) - Date.now(), 2147483647),
      ),
    );
    return () => window.clearTimeout(timer);
  }, [session]);
  async function run(action: (signal: AbortSignal) => Promise<void>) {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setNotice("checking");
    const timeout = window.setTimeout(() => controller.abort(), 5000);
    try {
      await action(controller.signal);
      if (active.current === controller && !controller.signal.aborted)
        setNotice("unchecked");
    } catch (error) {
      if (active.current === controller) {
        const kind = error instanceof RequestFailure ? error.kind : "invalid";
        setNotice(kind);
        if (kind !== "rejected") setSession(null);
      }
    } finally {
      window.clearTimeout(timeout);
      if (active.current === controller) {
        active.current = null;
        setBusy(false);
      }
    }
  }
  async function mutate<T>(
    path: string,
    body: unknown,
    signal: AbortSignal,
    decode: (raw: string) => T,
    operationKey?: string,
  ): Promise<T> {
    // Transient keys cover the current mounted page. Help creation supplies a
    // server-held durable key so OIDC navigation/reload cannot create a new effect.
    const signature =
      (session?.account_id ?? "anonymous") + path + JSON.stringify(body);
    let key = operationKey ?? commands.current.get(signature);
    if (!key) {
      key = crypto.randomUUID();
      commands.current.set(signature, key);
    }
    const token = await csrf(origin, signal);
    const raw = await request(origin, path, signal, { body, key, csrf: token });
    const result = decode(raw);
    commands.current.delete(signature);
    return result;
  }
  async function prepareHelpCreate(body: unknown, signal: AbortSignal) {
    const token = await csrf(origin, signal);
    return decodeCreateIntent(
      await request(origin, "/help/v1/create-intent", signal, {
        body,
        csrf: token,
      }),
    );
  }
  async function loadSession(signal: AbortSignal) {
    let ceremonyId: string | null = null;
    const raw = await request(
      origin,
      "/v1/auth/session",
      signal,
      undefined,
      (headers) => {
        ceremonyId = headers.get("X-Ceremony-Id");
        if (ceremonyId !== null && !uuid.test(ceremonyId))
          throw new RequestFailure("invalid");
      },
    );
    const current = decodeSession(raw);
    setSession(current);
    setCompletedCeremony(ceremonyId);
  }
  return {
    session,
    setSession,
    busy,
    notice,
    run,
    mutate,
    origin,
    loadSession,
    completedCeremony,
    prepareHelpCreate,
  };
}
export type Channel = ReturnType<typeof useChannel>;
