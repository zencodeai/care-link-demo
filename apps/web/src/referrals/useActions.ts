import { useEffect, useRef, useState } from "react";
import { ContractError } from "@care-link/contracts";
import {
  decodeSession,
  request,
  RequestFailure,
  type Session,
} from "../trust/api";
import type { Text } from "./messages";
export type Work = (signal: AbortSignal) => Promise<void>;
export function useActions(text: Text) {
  const [session, setSession] = useState<Session | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] =
    useState<
      keyof Pick<
        Text,
        | "done"
        | "unavailable"
        | "rejected"
        | "unknown"
        | "invalid"
        | "signedOut"
      >
    >("signedOut");
  const flight = useRef<AbortController | null>(null);
  const current = useRef<Session | null>(null);
  const [epoch, setEpoch] = useState(0);
  const [failureEpoch, setFailureEpoch] = useState(0);
  useEffect(() => () => flight.current?.abort(), []);
  useEffect(() => {
    if (!session) return;
    const timer = setTimeout(
      () => {
        flight.current?.abort();
        current.current = null;
        setSession(null);
        setNotice("signedOut");
      },
      Math.max(
        0,
        Math.min(Date.parse(session.expires_at) - Date.now(), 2147483647),
      ),
    );
    return () => clearTimeout(timer);
  }, [session]);
  async function run(work?: Work) {
    if (flight.current) return;
    const controller = new AbortController();
    flight.current = controller;
    setBusy(true);
    try {
      const actor = decodeSession(
        await request("", "/v1/auth/session", controller.signal),
      );
      if (
        current.current &&
        (current.current.account_id !== actor.account_id ||
          current.current.role !== actor.role)
      ) {
        current.current = actor;
        setSession(actor);
        setEpoch((value) => value + 1);
        if (work) throw new RequestFailure("rejected");
      }
      current.current = actor;
      setSession(actor);
      await work?.(controller.signal);
      if (!controller.signal.aborted) setNotice("done");
    } catch (error) {
      if (!controller.signal.aborted) {
        const failure =
          error instanceof RequestFailure
            ? error.kind
            : error instanceof ContractError
              ? "invalid"
              : "unavailable";
        setNotice(failure === "signed_out" ? "signedOut" : failure);
        setFailureEpoch((value) => value + 1);
        if (failure === "signed_out") setSession(null);
      }
    } finally {
      if (flight.current === controller) flight.current = null;
      setBusy(false);
    }
  }
  return {
    session,
    busy,
    notice,
    epoch,
    failureEpoch,
    run,
    status: busy ? text.busy : text[notice],
  };
}
export type Actions = ReturnType<typeof useActions>;
