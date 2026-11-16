import { useCallback, useEffect, useRef, useState } from "react";
import type { ReviewChannel } from "./useReview";
import type { Draft } from "./types";
export function useDraft(
  channel: ReviewChannel,
  sessionId: string,
  kind: Draft["kind"],
) {
  const saved = channel.workspace?.drafts.find(
    (d) => d.session_id === sessionId && d.kind === kind,
  );
  const [text, setText] = useState(saved?.text ?? "");
  const [state, setState] = useState<
    "saved" | "saving" | "unsaved" | "draftError"
  >("saved");
  const dirty = useRef(false);
  const value = useRef(text);
  const server = useRef<Draft | undefined>(saved);
  const saving = useRef<Promise<Draft | undefined> | null>(null);
  const write = useRef(channel.write);
  write.current = channel.write;
  useEffect(() => {
    if (!channel.workspace) return;
    if (
      saved &&
      server.current &&
      BigInt(saved.revision) < BigInt(server.current.revision)
    )
      return;
    if (saved?.text === value.current) {
      dirty.current = false;
      setState("saved");
    }
    if (!dirty.current) {
      server.current = saved;
      value.current = saved?.text ?? "";
      setText(value.current);
    }
  }, [saved?.id, saved?.revision, saved?.text, !!channel.workspace]);
  const flush = useCallback(async (): Promise<Draft | undefined> => {
    if (saving.current) {
      await saving.current;
      if (dirty.current) return flush();
      return server.current;
    }
    if (!dirty.current) return server.current;
    const submitted = value.current;
    setState("saving");
    const request = write.current<Draft>(
      `/v1/review/sessions/${sessionId}/draft`,
      {
        kind,
        text: submitted,
        expected_revision: server.current?.revision ?? "0",
      },
      "ReviewDraftView",
    );
    saving.current = request;
    const result = await request;
    saving.current = null;
    if (result) {
      server.current = result;
      dirty.current = value.current !== submitted;
      setState(dirty.current ? "unsaved" : "saved");
    } else setState("draftError");
    return result;
  }, [kind, sessionId]);
  useEffect(() => {
    if (!dirty.current || !channel.enabled || state === "draftError") return;
    const timer = setTimeout(() => {
      void flush();
    }, 450);
    return () => clearTimeout(timer);
  }, [text, channel.enabled, state, flush]);
  useEffect(() => {
    const protect = (event: BeforeUnloadEvent) => {
      if (dirty.current) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", protect);
    return () => window.removeEventListener("beforeunload", protect);
  }, []);
  const edit = (next: string) => {
    value.current = next;
    dirty.current = true;
    setText(next);
    setState("unsaved");
  };
  return { text, edit, state, flush };
}
