import { useEffect, useRef, useState } from "react";
import {
  decodeSession,
  request,
  RequestFailure,
  type Session,
} from "../trust/api";
import {
  conversation,
  get,
  message,
  outcome,
  page,
  queueItem,
  send,
  type Command,
  type Conversation,
  type Message,
  type Outcome,
  type QueueItem,
} from "./api";

export type Notice =
  | "unchecked"
  | "checking"
  | "unavailable"
  | "signed_out"
  | "rejected"
  | "invalid"
  | "pending"
  | "committed"
  | "unknown";
interface PendingCommand {
  command: Command;
  receive: (value: unknown) => void;
  principal: string;
  dispatched: boolean;
  uncertain: boolean;
}
const principal = (session: Session) => `${session.account_id}:${session.role}`;
export function useManual() {
  const [identity, setIdentity] = useState<Session | null>(null);
  const [view, setView] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [nextMessages, setNextMessages] = useState<string | null>(null);
  const [nextQueue, setNextQueue] = useState<string | null>(null);
  const [activeId, setActiveId] = useState("");
  const [notice, setNotice] = useState<Notice>("unchecked");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<PendingCommand | null>(null);
  const [lastAck, setLastAck] = useState<PendingCommand | null>(null);
  const [status, setStatus] = useState<Outcome | null>(null);
  const active = useRef<AbortController | null>(null);
  const identityRef = useRef<Session | null>(null);
  const workspaceRef = useRef<Session | null>(null);
  const pendingRef = useRef<PendingCommand | null>(null);
  const viewRef = useRef<Conversation | null>(null);
  const epoch = useRef(0);
  const publication = useRef(0);
  const mounted = useRef(true);
  const queuedRefresh = useRef<{ id: string; epoch: number } | null>(null);

  function rememberPending(value: PendingCommand | null) {
    pendingRef.current = value;
    setPending(value);
  }
  function currentRead(signal: AbortSignal, generation: number) {
    return (
      mounted.current && !signal.aborted && generation === publication.current
    );
  }
  function requestRefresh(id: string, context: number) {
    if (!mounted.current || context !== epoch.current || !identityRef.current)
      return;
    if (active.current) {
      queuedRefresh.current = { id, epoch: context };
      return;
    }
    void refresh(id);
  }

  function hidePrivate() {
    viewRef.current = null;
    setView(null);
    setMessages([]);
    setQueue([]);
    setNextMessages(null);
    setNextQueue(null);
  }
  async function access(signal: AbortSignal, switching = false) {
    const current = decodeSession(
      await request("", "/v1/auth/session", signal),
    );
    const previous = workspaceRef.current;
    if (
      previous &&
      (previous.account_id !== current.account_id ||
        previous.role !== current.role)
    ) {
      hidePrivate();
      setActiveId("");
      rememberPending(null);
      setLastAck(null);
      setStatus(null);
      epoch.current += 1;
      queuedRefresh.current = null;
      if (!switching) throw new RequestFailure("signed_out");
    }
    identityRef.current = current;
    workspaceRef.current = current;
    setIdentity(current);
    return current;
  }
  async function snapshot(id: string, signal: AbortSignal, generation: number) {
    const result = await get(
      `/v1/sessions/${id}`,
      "SessionView",
      conversation,
      signal,
    );
    if (!currentRead(signal, generation)) return;
    const previous = viewRef.current;
    if (
      previous &&
      previous.id === id &&
      BigInt(result.control_epoch) < BigInt(previous.control_epoch)
    )
      throw new RequestFailure("invalid");
    // Do not retain a projection while another epoch's message request is pending.
    setMessages([]);
    viewRef.current = result;
    setView(result);
    setActiveId(result.id);
    const resultMessages = await get(
      `/v1/sessions/${id}/messages?limit=50`,
      "MessagePage",
      page(message),
      signal,
    );
    if (
      !currentRead(signal, generation) ||
      viewRef.current?.control_epoch !== result.control_epoch
    )
      return;
    setMessages(resultMessages.items);
    setNextMessages(resultMessages.next_cursor);
  }
  async function run(
    action: (signal: AbortSignal, generation: number) => Promise<void>,
    checking: Notice = "checking",
  ) {
    if (active.current || !mounted.current) return;
    const controller = new AbortController();
    active.current = controller;
    const generation = publication.current;
    setBusy(true);
    setNotice(checking);
    const timeout = window.setTimeout(() => controller.abort(), 5000);
    try {
      await action(controller.signal, generation);
      if (!currentRead(controller.signal, generation))
        throw new RequestFailure(
          checking === "pending" ? "unknown" : "unavailable",
        );
      setNotice(
        checking === "pending"
          ? "committed"
          : pendingRef.current?.uncertain
            ? "unknown"
            : "unchecked",
      );
    } catch (error) {
      const kind = error instanceof RequestFailure ? error.kind : "invalid";
      setNotice(kind);
      hidePrivate();
      if (kind === "signed_out") {
        setLastAck(null);
        identityRef.current = null;
        setIdentity(null);
        epoch.current += 1;
        queuedRefresh.current = null;
      }
    } finally {
      window.clearTimeout(timeout);
      active.current = null;
      setBusy(false);
      const queued = queuedRefresh.current;
      queuedRefresh.current = null;
      if (queued) queueMicrotask(() => requestRefresh(queued.id, queued.epoch));
    }
  }
  async function check() {
    await run(async (signal) => {
      await access(signal, true);
    });
  }
  async function refresh(id = activeId) {
    await run(async (signal, generation) => {
      const current = await access(signal);
      if (id) await snapshot(id, signal, generation);
      else if (current.role === "worker" || current.role === "supervisor") {
        const result = await get(
          "/v1/workforce/queue?limit=50",
          "QueuePage",
          page(queueItem),
          signal,
        );
        if (currentRead(signal, generation)) {
          setQueue(result.items);
          setNextQueue(result.next_cursor);
        }
      }
    });
  }
  async function loadQueue(cursor: string | null = null) {
    await run(async (signal, generation) => {
      await access(signal);
      const result = await get(
        `/v1/workforce/queue?limit=50${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        "QueuePage",
        page(queueItem),
        signal,
      );
      if (currentRead(signal, generation)) {
        setQueue(result.items);
        setNextQueue(result.next_cursor);
      }
    });
  }
  async function loadMessages() {
    if (!activeId || !nextMessages) return;
    await run(async (signal, generation) => {
      await access(signal);
      const current = await get(
        `/v1/sessions/${activeId}`,
        "SessionView",
        conversation,
        signal,
      );
      if (current.control_epoch !== viewRef.current?.control_epoch) {
        await snapshot(activeId, signal, generation);
        return;
      }
      const result = await get(
        `/v1/sessions/${activeId}/messages?limit=50&cursor=${encodeURIComponent(nextMessages)}`,
        "MessagePage",
        page(message),
        signal,
      );
      if (currentRead(signal, generation)) {
        setMessages(result.items);
        setNextMessages(result.next_cursor);
      }
    });
  }
  async function execute(item: PendingCommand) {
    let committed = false;
    await run(async (signal, generation) => {
      try {
        const current = await access(signal);
        if (principal(current) !== item.principal)
          throw new RequestFailure("signed_out");
        const value = await send(item.command, signal, () => {
          item.dispatched = true;
        });
        if (!currentRead(signal, generation))
          throw new RequestFailure("unknown");
        item.receive(value);
        if (item.command.output === "ChannelAckView") setLastAck(item);
        rememberPending(null);
        setStatus(null);
        committed = true;
      } catch (error) {
        const kind = error instanceof RequestFailure ? error.kind : "invalid";
        if (pendingRef.current === item) {
          if (!item.dispatched || (kind === "rejected" && !item.uncertain))
            rememberPending(null);
          else if (kind !== "rejected") item.uncertain = true;
        }
        throw error;
      }
    }, "pending");
    const currentId = viewRef.current?.id ?? activeId;
    if (committed && currentId) await refresh(currentId);
  }
  async function perform(
    path: string,
    input: string,
    body: unknown,
    output: string,
    receive: (value: unknown) => void = () => {},
  ) {
    if (pendingRef.current || active.current || !identityRef.current) return;
    const item: PendingCommand = {
      command: { key: crypto.randomUUID(), path, input, body, output },
      receive,
      principal: principal(identityRef.current),
      dispatched: false,
      uncertain: false,
    };
    rememberPending(item);
    await execute(item);
  }
  async function read<T>(
    path: string,
    schema: string,
    guard: (value: unknown) => value is T,
  ): Promise<T | null> {
    let result: T | null = null;
    await run(async (signal, generation) => {
      await access(signal);
      const value = await get(path, schema, guard, signal);
      if (currentRead(signal, generation)) result = value;
    });
    return result;
  }
  async function reconcile() {
    if (!pending) return;
    await run(async (signal, generation) => {
      await access(signal);
      const result = await get(
        `/v1/operations/${pending.command.key}`,
        "OperationStatus",
        outcome,
        signal,
      );
      if (!currentRead(signal, generation)) return;
      setStatus(result);
      // Even a committed status has no private result. Retry the exact key to
      // rebuild it under current authority; unknown never becomes a new action.
      if (result.state === "rejected") rememberPending(null);
    });
  }
  function receiveView(value: unknown) {
    if (!conversation(value)) throw new RequestFailure("invalid");
    setMessages([]);
    viewRef.current = value;
    setView(value);
    setActiveId(value.id);
  }
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      queuedRefresh.current = null;
      active.current?.abort();
    };
  }, []);
  useEffect(() => {
    if (!identity) return;
    const timer = window.setTimeout(
      () => {
        active.current?.abort();
        publication.current += 1;
        epoch.current += 1;
        queuedRefresh.current = null;
        identityRef.current = null;
        setIdentity(null);
        hidePrivate();
        setNotice("signed_out");
      },
      Math.max(
        0,
        Math.min(Date.parse(identity.expires_at) - Date.now(), 2147483647),
      ),
    );
    return () => window.clearTimeout(timer);
  }, [identity]);
  useEffect(() => {
    if (!identity || !activeId) return;
    const context = epoch.current;
    let disposed = false;
    let source: EventSource | null = null;
    const update = () => {
      if (!disposed) requestRefresh(activeId, context);
    };
    const lost = () => {
      if (disposed || context !== epoch.current) return;
      publication.current += 1;
      active.current?.abort();
      hidePrivate();
      setNotice("unavailable");
      update();
    };
    if (typeof EventSource !== "undefined") {
      source = new EventSource(`/v1/sessions/${activeId}/events`, {
        withCredentials: true,
      });
      source.onmessage = update;
      source.onopen = update;
      for (const kind of [
        "session_changed",
        "message_available",
        "queue_changed",
      ])
        source.addEventListener(kind, update);
      for (const kind of ["rights_changed", "resync_required"])
        source.addEventListener(kind, lost);
      source.onerror = () => {
        // Native EventSource reconnects with the current cookie. Until a fresh
        // authorized projection succeeds, display no cached private output.
        lost();
      };
    }
    const timer = window.setInterval(update, 15000);
    return () => {
      disposed = true;
      source?.close();
      window.clearInterval(timer);
    };
    // All refresh authority comes from current server state; connection identity
    // and session are the subscription scope, not fetched projection revisions.
  }, [identity?.account_id, identity?.role, activeId]);
  return {
    identity,
    view,
    messages,
    queue,
    nextMessages,
    nextQueue,
    activeId,
    notice,
    busy,
    pending,
    status,
    check,
    refresh,
    loadQueue,
    loadMessages,
    perform,
    read,
    reconcile,
    receiveView,
    repeatAck: () => {
      if (!lastAck) return Promise.resolve();
      rememberPending(lastAck);
      return execute(lastAck);
    },
    retry: () => (pending ? execute(pending) : Promise.resolve()),
  };
}
export type ManualChannel = ReturnType<typeof useManual>;
