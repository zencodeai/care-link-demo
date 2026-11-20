import { useCallback, useEffect, useRef, useState } from "react";
import {
  decodePlanForm,
  emptyPlanForm,
  type PlanDraftBridge,
  type PlanFormState,
  type ReviewWorkLease,
} from "../plans/review";
import { RequestFailure } from "../trust/api";
import type { PlanDraft } from "./types";
import type { PlansReviewChannel } from "./usePlansReview";

// The component owning this hook is keyed by the server actor, run and session.
// Only editable words/settings go into the encrypted server draft; never proofs
// or a prepared grant, which must be rebuilt from current authorized resources.
export function usePlanDraft(channel: PlansReviewChannel) {
  const saved = channel.workspace?.workspace.drafts.find(
    (item): item is PlanDraft => item.kind === "plan",
  );
  const initial = () => {
    try {
      if (saved && Date.parse(saved.expires_at) <= Date.now())
        throw new Error("Expired draft");
      return {
        value: saved
          ? decodePlanForm(saved.text)
          : emptyPlanForm(channel.workspace?.selection.recipient_id ?? ""),
        invalid: false,
      };
    } catch {
      return {
        value: emptyPlanForm(channel.workspace?.selection.recipient_id ?? ""),
        invalid: true,
      };
    }
  };
  const [first] = useState(initial);
  const [value, setValue] = useState<PlanFormState>(first.value);
  const [invalid, setInvalid] = useState(first.invalid);
  const malformed = useRef(first.invalid);
  const [state, setState] = useState<
    "saved" | "saving" | "unsaved" | "draftError"
  >(first.invalid ? "draftError" : "saved");
  const latest = useRef(value),
    dirty = useRef(false),
    server = useRef(saved);
  const saving = useRef<Promise<PlanDraft | undefined> | null>(null);
  const writer = useRef(channel.saveDraft);
  writer.current = channel.saveDraft;
  useEffect(() => {
    if (
      !saved ||
      (server.current &&
        BigInt(saved.revision) < BigInt(server.current.revision))
    )
      return;
    server.current = saved;
    let decoded: PlanFormState;
    try {
      if (Date.parse(saved.expires_at) <= Date.now())
        throw new Error("Expired draft");
      decoded = decodePlanForm(saved.text);
    } catch {
      malformed.current = true;
      setInvalid(true);
      setState("draftError");
      return;
    }
    if (!dirty.current) {
      malformed.current = false;
      setInvalid(false);
      latest.current = decoded;
      setValue(decoded);
      setState("saved");
    } else if (saved.text === JSON.stringify(latest.current)) {
      dirty.current = false;
      setState("saved");
    }
  }, [saved?.revision, saved?.text]);
  const flush = useCallback(
    async (signal?: AbortSignal, work?: ReviewWorkLease): Promise<void> => {
      if (malformed.current) throw new RequestFailure("invalid");
      if (saving.current) {
        const result = await saving.current;
        if (!result) throw new RequestFailure("unavailable");
        if (dirty.current) return flush(signal, work);
        return;
      }
      if (!dirty.current) return;
      const submitted = JSON.stringify(latest.current);
      setState("saving");
      const request = writer.current(
        submitted,
        server.current?.revision ?? "0",
        signal,
        work,
      );
      saving.current = request;
      const result = await request;
      saving.current = null;
      if (!result) {
        setState("draftError");
        throw new RequestFailure("unavailable");
      }
      server.current = result;
      dirty.current = submitted !== JSON.stringify(latest.current);
      setState(dirty.current ? "unsaved" : "saved");
    },
    [],
  );
  useEffect(() => {
    if (
      !dirty.current ||
      !channel.enabled ||
      state === "draftError" ||
      state === "saving"
    )
      return;
    const timer = setTimeout(() => {
      void flush().catch(() => {});
    }, 450);
    return () => clearTimeout(timer);
  }, [value, channel.enabled, state, flush]);
  useEffect(() => {
    const guard = (event: BeforeUnloadEvent) => {
      if (dirty.current) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, []);
  const bridge: PlanDraftBridge = {
    value,
    edit: (key, next) => {
      latest.current = { ...latest.current, [key]: next };
      dirty.current = true;
      setValue(latest.current);
      setState("unsaved");
    },
  };
  const resetInvalid = () => {
    malformed.current = false;
    setInvalid(false);
    dirty.current = true;
    setState("unsaved");
  };
  return { bridge, state, flush, invalid, resetInvalid };
}
