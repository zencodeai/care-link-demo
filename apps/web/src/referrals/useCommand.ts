import { useRef, useState } from "react";
import { ContractError } from "@care-link/contracts";
import { validateContract } from "@care-link/contracts";
import { RequestFailure } from "../trust/api";
import { write, type Command } from "./api";
import type { Actions } from "./useActions";
type Apply = (result: unknown, signal: AbortSignal) => Promise<void> | void;
interface Pending {
  command: Command;
  apply: Apply;
}
/** An uncertain mutation retains its exact key and body until reconciled or replayed. */
export function useCommand(actions: Actions) {
  const current = useRef<Pending | null>(null);
  const [pending, setPending] = useState<Command | null>(null);
  function clear() {
    current.current = null;
    setPending(null);
  }
  async function execute(value: Pending, signal: AbortSignal) {
    let result: unknown;
    try {
      result = await write(value.command, signal);
    } catch (error) {
      if (
        error instanceof RequestFailure &&
        (error.kind === "rejected" || error.kind === "signed_out")
      )
        clear();
      throw error;
    }
    clear();
    await value.apply(result, signal);
  }
  function send(command: Omit<Command, "key">, apply: Apply) {
    if (actions.busy || current.current) return;
    // Local input failure precedes any HTTP effect and must not create an uncertain command.
    try {
      validateContract(command.input, command.body);
    } catch (error) {
      if (error instanceof ContractError) {
        void actions.run(() => Promise.reject(error));
        return;
      }
      throw error;
    }
    const value = { command: { ...command, key: crypto.randomUUID() }, apply };
    current.current = value;
    setPending(value.command);
    void actions.run((signal) => execute(value, signal));
  }
  function retry() {
    const value = current.current;
    if (value && !actions.busy)
      void actions.run((signal) => execute(value, signal));
  }
  return { pending, send, retry, clear };
}
