import { useEffect, useRef, useState } from "react";
import { ContractError } from "@care-link/contracts";
import {
  decodeSession,
  request,
  RequestFailure,
  type Session,
} from "../../trust/api";
import { execute, readEvaluation, readScenario } from "./api";
import type { Command, Evaluation, Receipt, Scenario } from "./api";

type Notice = "unchecked" | "checking" | "ready" | RequestFailure["kind"];

interface Pending {
  command: Command;
  key: string;
  owner: Session;
}

function sameOwner(left: Session, right: Session) {
  return left.account_id === right.account_id && left.role === right.role;
}

function allowed(session: Session, trainerOnly = false) {
  return (
    (session.assurance === "AL2" || session.assurance === "AL3") &&
    (session.role === "trainer" ||
      (!trainerOnly && session.role === "governance"))
  );
}

function failureKind(error: unknown): RequestFailure["kind"] {
  return error instanceof RequestFailure
    ? error.kind
    : error instanceof ContractError
      ? "invalid"
      : "unavailable";
}

export function useTraining() {
  const [account, setAccount] = useState<Session | null>(null);
  const [notice, setNotice] = useState<Notice>("unchecked");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null);
  const [epoch, setEpoch] = useState(0);
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const active = useRef<AbortController | null>(null);
  const owner = useRef<Session | null>(null);
  const uncertain = useRef<Pending | null>(null);

  function recordPending(operation: Pending | null) {
    uncertain.current = operation;
    setPending(operation);
  }

  function clearResults() {
    setScenario(null);
    setReceipt(null);
    setEvaluation(null);
  }

  useEffect(() => () => active.current?.abort(), []);
  useEffect(() => {
    if (!account) return;
    const expires = Date.parse(account.expires_at);
    let timeout: number;
    function checkExpiry() {
      const remaining = expires - Date.now();
      if (remaining > 0) {
        timeout = window.setTimeout(
          checkExpiry,
          Math.min(remaining, 2147483647),
        );
        return;
      }
      active.current?.abort();
      setAccount(null);
      clearResults();
      setNotice("signed_out");
    }
    checkExpiry();
    return () => window.clearTimeout(timeout);
  }, [account]);

  async function run(
    work?: (current: Session, signal: AbortSignal) => Promise<void>,
  ) {
    if (active.current) return;
    const controller = new AbortController();
    const { signal } = controller;
    active.current = controller;
    setBusy(true);
    setNotice("checking");
    const timeout = window.setTimeout(() => controller.abort(), 10000);
    let verified: Session | null = null;
    try {
      const current = decodeSession(
        await request("", "/v1/auth/session", signal),
      );
      verified = current;
      const previous = owner.current;
      owner.current = current;
      setAccount(current);
      const changed = previous && !sameOwner(previous, current);
      if (changed) {
        recordPending(null);
        setEpoch((value) => value + 1);
      }
      if (
        changed ||
        (previous &&
          (previous.revision !== current.revision ||
            previous.assurance !== current.assurance))
      ) {
        clearResults();
        if (work) throw new RequestFailure("rejected");
      }
      await work?.(current, signal);
      if (!signal.aborted) setNotice("ready");
    } catch (error) {
      const lastKnown = verified ?? account;
      const kind =
        lastKnown && Date.parse(lastKnown.expires_at) <= Date.now()
          ? "signed_out"
          : failureKind(error);
      clearResults();
      if (kind === "signed_out" || (!verified && kind !== "rejected"))
        setAccount(null);
      setNotice(kind);
    } finally {
      window.clearTimeout(timeout);
      if (active.current === controller) active.current = null;
      setBusy(false);
    }
  }

  function read(kind: "scenario" | "evaluation", id: string) {
    if (active.current || uncertain.current) return;
    void run(async (current, signal) => {
      if (!allowed(current, kind === "scenario"))
        throw new RequestFailure("rejected");
      if (kind === "scenario") {
        const value = await readScenario(id, signal);
        if (!signal.aborted) setScenario(value);
      } else {
        const value = await readEvaluation(id, signal);
        if (!signal.aborted) setEvaluation(value);
      }
    });
  }

  function submit(operation: Pending, retry: boolean) {
    void run(async (current, signal) => {
      if (
        !sameOwner(operation.owner, current) ||
        !allowed(current, operation.command.type !== "replay")
      )
        throw new RequestFailure("rejected");
      let dispatched = false;
      try {
        const result = await execute(
          operation.command,
          operation.key,
          signal,
          () => {
            dispatched = true;
            recordPending(operation);
          },
        );
        if (signal.aborted) throw new RequestFailure("unknown");
        if (result.type === "scenario") {
          if (
            result.receipt.state === "unknown" ||
            result.receipt.state === "pending"
          )
            throw new RequestFailure("unknown");
          if (result.receipt.state === "rejected") {
            recordPending(null);
            throw new RequestFailure("rejected");
          }
          setScenario(null);
          setReceipt(result.receipt);
        } else {
          setEvaluation(result.evaluation);
        }
        recordPending(null);
      } catch (error) {
        const kind = failureKind(error);
        if (
          dispatched &&
          !retry &&
          (kind === "rejected" || kind === "signed_out")
        )
          recordPending(null);
        if (dispatched && (kind === "invalid" || kind === "unavailable"))
          throw new RequestFailure("unknown");
        throw error;
      }
    });
  }

  function command(value: Command) {
    if (!account || active.current || uncertain.current) return;
    submit({ command: value, key: crypto.randomUUID(), owner: account }, false);
  }

  function retry() {
    if (account && !active.current && uncertain.current)
      submit(uncertain.current, true);
  }

  return {
    account,
    busy,
    notice,
    pending,
    epoch,
    scenario,
    receipt,
    evaluation,
    workspace: account !== null && allowed(account),
    previousRole:
      owner.current && allowed(owner.current) ? owner.current.role : null,
    check: () => void run(),
    read,
    command,
    retry,
    clearScenario: () => {
      setScenario(null);
      setReceipt(null);
    },
    clearEvaluation: () => setEvaluation(null),
  };
}
export type Training = ReturnType<typeof useTraining>;
