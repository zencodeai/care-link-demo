import { useEffect, useRef, useState } from "react";
import { RequestFailure } from "../trust/api";
import { read, write, type Command, type Output, type Responses } from "./api";
import type {
  Availability,
  DraftContext,
  Review,
  SessionContext,
  Task,
} from "./types";
export type Notice =
  | "loading"
  | "ready"
  | "unavailable"
  | "working"
  | "unknown"
  | "failed"
  | "signedOut"
  | "cancelled"
  | "accepted"
  | "edited"
  | "rejected"
  | "timedOut"
  | "completed"
  | "sourcesChanged";
export function useAssistance(session: SessionContext, allowAutomatic = false) {
  const [availability, setAvailability] = useState<Availability | null>(null);
  const [task, setTask] = useState<Task | null>(null);
  const [context, setContext] = useState<DraftContext | null>(null);
  const [privateVisible, setPrivateVisible] = useState(false);
  const [notice, setNotice] = useState<Notice>("loading");
  const [busy, setBusy] = useState(false);
  const [automatic, setAutomatic] = useState(false);
  const prepared = useRef(new Set<string>());
  const pollCount = useRef(0);
  const sourceRevision = useRef(session.revision);
  const active = useRef<AbortController | null>(null);
  const pending = useRef<(() => Promise<void>) | null>(null);
  const epoch = useRef(0);
  function controller() {
    active.current?.abort();
    const next = new AbortController();
    active.current = next;
    return next;
  }
  function failure(error: unknown) {
    setPrivateVisible(false);
    setAvailability(null);
    setNotice(
      error instanceof RequestFailure && error.kind === "signed_out"
        ? "signedOut"
        : "failed",
    );
  }
  async function check() {
    const current = controller();
    setBusy(true);
    setNotice("loading");
    setPrivateVisible(false);
    try {
      const status = await read(
        "/v1/assistance",
        "AssistanceStatus",
        current.signal,
      );
      if (current.signal.aborted) return;
      setAvailability(status);
      setNotice(
        status.available && status.functions.includes("worker_summary")
          ? "ready"
          : "unavailable",
      );
      if (status.available && task) await refresh(task);
    } catch (error) {
      if (!current.signal.aborted) {
        failure(error);
      }
    } finally {
      if (!current.signal.aborted) setBusy(false);
    }
  }
  async function refresh(currentTask = task) {
    if (!currentTask || pending.current) return;
    const current = controller();
    const timeout = window.setTimeout(
      () => {
        if (active.current !== current) return;
        current.abort();
        setPrivateVisible(false);
        setNotice("timedOut");
        setBusy(false);
      },
      Math.min(
        5000,
        Math.max(1, Date.parse(currentTask.deadline) - Date.now()),
      ),
    );
    setBusy(true);
    setPrivateVisible(false);
    try {
      const next = await read(
        `/v1/tasks/${currentTask.id}/context`,
        "AssistanceTaskContext",
        current.signal,
      );
      if (current.signal.aborted) return;
      setTask(next.task);
      if (next.task.state === "cancelled") {
        setContext(null);
        setNotice("cancelled");
      } else if (next.draft_id) {
        const draft = await read(
          `/v1/drafts/${next.draft_id}/context`,
          "AssistanceDraftContext",
          current.signal,
        );
        if (current.signal.aborted) return;
        setContext(draft);
        setPrivateVisible(true);
        setNotice("ready");
      } else {
        setContext(null);
        setNotice(
          next.task.state === "completed"
            ? "completed"
            : next.task.state === "failed"
              ? "failed"
              : Date.parse(next.task.deadline) <= Date.now()
                ? "timedOut"
                : next.available
                  ? "working"
                  : "unavailable",
        );
      }
    } catch (error) {
      if (!current.signal.aborted) {
        failure(error);
      }
    } finally {
      window.clearTimeout(timeout);
      if (!current.signal.aborted) setBusy(false);
    }
  }
  async function command<K extends Output>(
    cmd: Command<K>,
    complete: (value: Responses[K]) => Promise<void> | void,
  ) {
    const version = epoch.current;
    const execute = async () => {
      const current = controller();
      setBusy(true);
      try {
        const result = await write(cmd, current.signal);
        if (current.signal.aborted || epoch.current !== version) return;
        pending.current = null;
        await complete(result);
      } catch (error) {
        if (current.signal.aborted || epoch.current !== version) return;
        if (error instanceof RequestFailure && error.kind === "unknown") {
          pending.current = execute;
          setNotice("unknown");
        } else {
          pending.current = null;
          failure(error);
        }
      } finally {
        if (!current.signal.aborted && epoch.current === version)
          setBusy(false);
      }
    };
    pending.current = execute;
    await execute();
  }
  function start() {
    if (
      busy ||
      pending.current ||
      !availability?.available ||
      !availability.functions.includes("worker_summary")
    )
      return;
    prepared.current.add(`${session.id}:${session.revision}`);
    pollCount.current = 0;
    setContext(null);
    setPrivateVisible(false);
    void command(
      {
        key: crypto.randomUUID(),
        path: "/v1/tasks",
        input: "TaskCreate",
        output: "TaskView",
        body: {
          expected_revision: session.revision,
          function: "worker_summary",
          goal: "prepare_summary",
          scope: {
            session_id: session.id,
            subject_id: session.subject_id,
            purpose: "support",
            fields: ["needs", "preferences", "observations"],
            recipient_id: null,
          },
          binding: { kind: "session", session_id: session.id },
          inputs: [],
          completion: "draft_ready",
        },
      },
      async (next) => {
        setTask(next);
        setNotice("working");
        await refresh(next);
      },
    );
  }
  function cancel() {
    if (!task || busy || pending.current) return;
    void command(
      {
        key: crypto.randomUUID(),
        path: `/v1/tasks/${task.id}/cancel`,
        input: "RevisionCommand",
        output: "TaskView",
        body: { expected_revision: task.revision },
      },
      (next) => {
        setTask(next);
        setContext(null);
        setNotice(next.state === "cancelled" ? "cancelled" : "working");
      },
    );
  }
  function review(decision: Review["decision"], editedText: string) {
    if (
      !context ||
      !privateVisible ||
      busy ||
      pending.current ||
      Date.parse(context.expires_at) <= Date.now()
    )
      return;
    const draft = context.draft;
    void command(
      {
        key: crypto.randomUUID(),
        path: `/v1/drafts/${draft.id}/review`,
        input: "ReviewCommand",
        output: "ReviewView",
        body: {
          expected_revision: draft.revision,
          draft_id: draft.id,
          exact_digest: draft.payload_digest,
          source_vector: draft.source_vector,
          decision,
          edited_text: decision === "edit" ? editedText : null,
          expires_at: context.expires_at,
        },
      },
      async () => {
        if (decision === "edit") {
          await refresh();
          setNotice("edited");
        } else {
          setContext(null);
          setNotice(decision === "accept" ? "accepted" : "rejected");
        }
      },
    );
  }
  useEffect(() => {
    epoch.current += 1;
    setAutomatic(false);
    prepared.current.clear();
    pollCount.current = 0;
    sourceRevision.current = session.revision;
    setTask(null);
    setContext(null);
    setPrivateVisible(false);
    pending.current = null;
    void check();
    return () => {
      epoch.current += 1;
      active.current?.abort();
      active.current = null;
    };
  }, [session.id, allowAutomatic]);
  useEffect(() => {
    if (sourceRevision.current === session.revision) return;
    sourceRevision.current = session.revision;
    // A changed source projection cannot revive a previous private draft. Keep
    // uncertain command custody intact; its original key must be reconciled.
    setPrivateVisible(false);
    if (!pending.current && task) {
      setNotice("sourcesChanged");
      void refresh(task);
    }
  }, [session.revision]);
  useEffect(() => {
    const activeTask =
      task &&
      !["completed", "cancelled", "failed"].includes(task.state) &&
      !["accepted", "rejected", "cancelled"].includes(notice);
    if (
      allowAutomatic &&
      automatic &&
      !activeTask &&
      !busy &&
      !pending.current &&
      availability?.available &&
      availability.functions.includes("worker_summary") &&
      !prepared.current.has(`${session.id}:${session.revision}`) &&
      !["failed", "signedOut", "unknown", "timedOut"].includes(notice)
    )
      start();
  }, [
    automatic,
    allowAutomatic,
    availability,
    busy,
    task,
    notice,
    session.id,
    session.revision,
  ]);
  useEffect(() => {
    if (
      !task ||
      context ||
      busy ||
      pending.current ||
      notice !== "working" ||
      ["completed", "cancelled", "failed"].includes(task.state)
    )
      return;
    const remaining = Date.parse(task.deadline) - Date.now();
    if (remaining <= 0 || pollCount.current >= 60) {
      setNotice("timedOut");
      return;
    }
    // Polling reads existing authorized work. It never creates a task or
    // retries a mutation, and is bounded by both count and server deadline.
    const timer = window.setTimeout(
      () => {
        pollCount.current += 1;
        void refresh(task);
      },
      Math.min(2000, remaining),
    );
    return () => window.clearTimeout(timer);
  }, [task, context, busy, notice]);
  return {
    availability,
    task,
    context,
    privateVisible,
    notice,
    busy,
    automatic,
    setAutomatic,
    pending: !!pending.current,
    check,
    refresh,
    start,
    cancel,
    review,
    retry: () => {
      void pending.current?.();
    },
  };
}
