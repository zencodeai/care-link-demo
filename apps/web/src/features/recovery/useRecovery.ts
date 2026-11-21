import { useEffect, useRef, useState } from "react";
import { ContractError, validateContract } from "@care-link/contracts";
import {
  decodeSession,
  request,
  RequestFailure,
  type Session,
} from "../../trust/api";
import { write } from "./api";
import type { Command, Output, Responses } from "./types";
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
  execute: Work;
}
export function useRecovery() {
  const [account, setAccount] = useState<Session | null>(null);
  const previous = useRef<Session | null>(null);
  const [notice, setNotice] = useState<Notice>("unchecked");
  const [busy, setBusy] = useState(false);
  const [epoch, setEpoch] = useState(0);
  const [privateEpoch, setPrivateEpoch] = useState(0);
  const privateEpochRef = useRef(0);
  function invalidatePrivate() {
    privateEpochRef.current += 1;
    setPrivateEpoch(privateEpochRef.current);
  }
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
        setNotice("signed_out");
        invalidatePrivate();
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
      const old = previous.current;
      previous.current = current;
      setAccount(current);
      if (
        old &&
        (old.account_id !== current.account_id || old.role !== current.role)
      ) {
        pendingRef.current = null;
        setPending(null);
        setEpoch((v) => v + 1);
        invalidatePrivate();
        if (work) throw new RequestFailure("rejected");
      }
      if (old && old.revision !== current.revision) {
        invalidatePrivate();
        if (work) throw new RequestFailure("rejected");
      }
      await work?.(controller.signal, current);
      if (controller.signal.aborted)
        throw new RequestFailure(
          pendingRef.current ? "unknown" : "unavailable",
        );
      setNotice("ready");
    } catch (error) {
      const expired =
        previous.current !== null &&
        Date.parse(previous.current.expires_at) <= Date.now();
      const kind = expired
        ? "signed_out"
        : error instanceof RequestFailure
          ? error.kind
          : error instanceof ContractError
            ? "invalid"
            : "unavailable";
      setNotice(kind);
      invalidatePrivate();
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
    if (active.current || pendingRef.current || !previous.current) return;
    try {
      validateContract(input.input, input.body);
    } catch {
      setNotice("invalid");
      return;
    }
    const value = { ...input, key: crypto.randomUUID() };
    const owner = previous.current.account_id + ":" + previous.current.role;
    const execute: Work = async (signal, actor) => {
      if (owner !== actor.account_id + ":" + actor.role)
        throw new RequestFailure("rejected");
      let dispatched = false;
      try {
        const result = await write(value, signal, () => {
          dispatched = true;
        });
        if (value.output === "CommandResult" && "state" in result) {
          if (result.state === "pending" || result.state === "unknown")
            throw new RequestFailure("unknown");
          if (result.state === "rejected") throw new RequestFailure("rejected");
        }
        pendingRef.current = null;
        setPending(null);
        if (!signal.aborted) apply(result);
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
    const next = { command: value, execute };
    pendingRef.current = next;
    setPending(next);
    void run(execute);
  }
  return {
    account,
    role: previous.current?.role ?? null,
    notice,
    busy,
    epoch,
    privateEpoch,
    currentPrivateEpoch: () => privateEpochRef.current,
    pending,
    run,
    command,
    retry: () => {
      if (pendingRef.current) void run(pendingRef.current.execute);
    },
    disabled: busy || pending !== null || account === null,
  };
}
export type Channel = ReturnType<typeof useRecovery>;
