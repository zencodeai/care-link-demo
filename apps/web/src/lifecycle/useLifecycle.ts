import { useEffect, useRef, useState } from "react";
import { ContractError, validateContract } from "@care-link/contracts";
import {
  decodeSession,
  request,
  RequestFailure,
  type Session,
} from "../trust/api";
import { write, type Command, type Output, type Responses } from "./api";
export type Notice =
  | "unchecked"
  | "busy"
  | "ready"
  | "unavailable"
  | "signed_out"
  | "rejected"
  | "invalid"
  | "unknown";
type Work = (signal: AbortSignal, actor: Session) => Promise<void>;
interface Pending {
  command: Command;
  owner: string;
  execute: Work;
}
export function useLifecycle() {
  const [account, setAccount] = useState<Session | null>(null);
  const accountRef = useRef<Session | null>(null);
  const [notice, setNotice] = useState<Notice>("unchecked");
  const [busy, setBusy] = useState(false);
  const [epoch, setEpoch] = useState(0);
  const [privateEpoch, setPrivateEpoch] = useState(0);
  const [sessionEpoch, setSessionEpoch] = useState(0);
  const [pending, setPending] = useState<Pending | null>(null);
  const pendingRef = useRef<Pending | null>(null);
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);
  useEffect(() => {
    if (!account) return;
    const timer = setTimeout(
      () => {
        active.current?.abort();
        setAccount(null);
        setPrivateEpoch((v) => v + 1);
        setNotice("signed_out");
      },
      Math.max(
        0,
        Math.min(Date.parse(account.expires_at) - Date.now(), 2147483647),
      ),
    );
    return () => clearTimeout(timer);
  }, [account]);
  async function run(work?: Work) {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setNotice("busy");
    const timer = setTimeout(() => controller.abort(), 10000);
    try {
      const current = decodeSession(
        await request("", "/v1/auth/session", controller.signal),
      );
      const old = accountRef.current;
      accountRef.current = current;
      setAccount(current);
      if (
        old &&
        (old.account_id !== current.account_id || old.role !== current.role)
      ) {
        pendingRef.current = null;
        setPending(null);
        setEpoch((v) => v + 1);
        if (work) throw new RequestFailure("rejected");
      }
      await work?.(controller.signal, current);
      if (controller.signal.aborted)
        throw new RequestFailure(
          pendingRef.current ? "unknown" : "unavailable",
        );
      setNotice("ready");
    } catch (error) {
      const kind =
        error instanceof RequestFailure
          ? error.kind
          : error instanceof ContractError
            ? "invalid"
            : "unavailable";
      setNotice(kind);
      setPrivateEpoch((v) => v + 1);
      if (kind === "signed_out") setAccount(null);
    } finally {
      clearTimeout(timer);
      if (active.current === controller) active.current = null;
      setBusy(false);
    }
  }
  function command<K extends Output>(
    input: Omit<Command<K>, "key">,
    apply: (value: Responses[K]) => void,
  ) {
    if (active.current || pendingRef.current || !accountRef.current) return;
    try {
      validateContract(input.input, input.body);
    } catch {
      setNotice("invalid");
      return;
    }
    const value = { ...input, key: crypto.randomUUID() };
    const owner = accountRef.current.account_id + ":" + accountRef.current.role;
    const execute: Work = async (signal, actor) => {
      if (owner !== actor.account_id + ":" + actor.role)
        throw new RequestFailure("rejected");
      let dispatched = false;
      try {
        const result = await write(value, signal, () => {
          dispatched = true;
        });
        pendingRef.current = null;
        setPending(null);
        if (!signal.aborted) {
          apply(result);
          if (
            value.path.startsWith("/v1/sessions/") ||
            value.path.startsWith("/v1/consents")
          )
            setSessionEpoch((v) => v + 1);
        }
      } catch (error) {
        if (
          !dispatched ||
          (error instanceof RequestFailure &&
            ["rejected", "signed_out"].includes(error.kind))
        ) {
          pendingRef.current = null;
          setPending(null);
        }
        throw error;
      }
    };
    const next = { command: value, owner, execute };
    pendingRef.current = next;
    setPending(next);
    void run(execute);
  }
  function retry() {
    if (pendingRef.current) void run(pendingRef.current.execute);
  }
  return {
    account,
    notice,
    busy,
    epoch,
    privateEpoch,
    sessionEpoch,
    pending,
    run,
    command,
    retry,
    disabled: busy || pending !== null,
  };
}
export type Channel = ReturnType<typeof useLifecycle>;
