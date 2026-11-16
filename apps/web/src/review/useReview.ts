import { useCallback, useEffect, useRef, useState } from "react";
import type { Session } from "../trust/api";
import { headers, json, post, ReviewFailure } from "./api";
import { useEvents } from "./useEvents";
import type {
  Context,
  Message,
  QueueItem,
  ViewLease,
  Workspace,
} from "./types";
export type Notice =
  | "loading"
  | "signedOut"
  | "unavailable"
  | "rejected"
  | "wrongActor"
  | null;
const initialId = () =>
  /^[0-9a-f-]{36}$/.test(window.location.hash.slice(1))
    ? window.location.hash.slice(1)
    : "";
export function useReview() {
  const [context, setContext] = useState<Context | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [view, setView] = useState<ViewLease | null>(null);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [selected, setSelected] = useState(initialId);
  const [notice, setNotice] = useState<Notice>("loading");
  const [busy, setBusy] = useState(false);
  const selectedRef = useRef(selected);
  const viewRef = useRef<ViewLease | null>(null);
  const contextRef = useRef<Context | null>(null);
  const mounted = useRef(true);
  const reading = useRef(false);
  const again = useRef(false);
  const publication = useRef(0);
  const select = useCallback((id: string) => {
    publication.current += 1;
    selectedRef.current = id;
    setSelected(id);
    const url = new URL(window.location.href);
    url.hash = id;
    window.history.replaceState(null, "", url);
  }, []);
  const fail = useCallback((error: unknown) => {
    if (!mounted.current) return;
    publication.current += 1;
    setWorkspace(null);
    setMessages([]);
    setQueue([]);
    if (
      error instanceof ReviewFailure &&
      (error.status === 401 ||
        error.code === "manual.identity_changed" ||
        error.code === "identity.mfa_required")
    ) {
      viewRef.current = null;
      setView(null);
      setSession(null);
      setNotice("signedOut");
    } else
      setNotice(
        error instanceof ReviewFailure && error.status < 500
          ? "rejected"
          : "unavailable",
      );
  }, []);
  const refresh = useCallback(async () => {
    if (!mounted.current) return;
    if (reading.current) {
      again.current = true;
      return;
    }
    reading.current = true;
    const generation = publication.current;
    try {
      const currentContext =
        contextRef.current ?? (await json<Context>("/v1/review/context"));
      if (
        !currentContext.enabled ||
        currentContext.origin !== window.location.origin
      )
        throw new ReviewFailure(403, "wrong_origin");
      contextRef.current = currentContext;
      const current = await json<
        Session & {
          review_run_id?: string;
          review_slot_id?: string;
          review_origin?: string;
        }
      >("/v1/auth/session", "BrowserSession");
      if (
        current.account_id !== currentContext.account_id ||
        current.role !== currentContext.role ||
        current.review_run_id !== currentContext.run_id ||
        current.review_slot_id !== currentContext.slot_id ||
        current.review_origin !== currentContext.origin
      ) {
        if (mounted.current && generation === publication.current) {
          viewRef.current = null;
          setView(null);
          setContext(currentContext);
          setSession(current);
          setNotice("wrongActor");
          setWorkspace(null);
          setMessages([]);
          setQueue([]);
        }
        return;
      }
      let currentView: ViewLease;
      try {
        currentView = viewRef.current
          ? await json<ViewLease>(
              "/v1/review/view",
              undefined,
              headers(viewRef.current.view_id),
            )
          : await post<ViewLease>("/v1/review/view", {}, null);
      } catch (error) {
        if (
          !(error instanceof ReviewFailure) ||
          error.code !== "manual.review_view_unknown"
        )
          throw error;
        currentView = await post<ViewLease>("/v1/review/view", {}, null);
      }
      if (!mounted.current || generation !== publication.current) {
        again.current = true;
        return;
      }
      // Registration already holds the lease, even if a later read fails.
      viewRef.current = currentView;
      setContext(currentContext);
      setSession(current);
      setView(currentView);
      const requested = selectedRef.current;
      const currentWorkspace = await json<Workspace>(
        "/v1/review/workspace" +
          (requested ? "?session_id=" + encodeURIComponent(requested) : ""),
        "ReviewWorkspace",
        headers(currentView.view_id),
      );
      if (currentWorkspace.run_id !== currentContext.run_id)
        throw new ReviewFailure(403, "wrong_run");
      const currentMessages =
        currentWorkspace.run_state === "active" && currentWorkspace.conversation
          ? (
              await json<{ items: Message[] }>(
                `/v1/sessions/${currentWorkspace.conversation.id}/messages?limit=50`,
                "MessagePage",
                headers(currentView.view_id),
              )
            ).items
          : [];
      const currentQueue =
        currentWorkspace.run_state === "active" &&
        (current.role === "worker" || current.role === "supervisor")
          ? (
              await json<{ items: QueueItem[] }>(
                "/v1/workforce/queue?limit=50",
                "QueuePage",
                headers(currentView.view_id),
              )
            ).items
          : [];
      if (!mounted.current || generation !== publication.current) {
        again.current = true;
        return;
      }
      setWorkspace(currentWorkspace);
      setMessages(currentMessages);
      setQueue(currentQueue);
      setNotice(null);
      if (!requested && currentWorkspace.conversation)
        select(currentWorkspace.conversation.id);
    } catch (error) {
      if (generation !== publication.current) {
        again.current = true;
        return;
      }
      if (contextRef.current && mounted.current) setContext(contextRef.current);
      fail(error);
    } finally {
      reading.current = false;
      if (again.current) {
        again.current = false;
        queueMicrotask(() => {
          void refresh();
        });
      }
    }
  }, [fail, select]);
  useEffect(() => {
    mounted.current = true;
    void refresh();
    let timer: number;
    const poll = () => {
      void refresh();
      timer = window.setTimeout(
        poll,
        viewRef.current?.state === "observer" ? 10000 : 5000,
      );
    };
    timer = window.setTimeout(poll, 5000);
    const visible = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    document.addEventListener("visibilitychange", visible);
    window.addEventListener("focus", visible);
    return () => {
      mounted.current = false;
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", visible);
      window.removeEventListener("focus", visible);
    };
  }, [refresh]);
  useEffect(() => {
    void refresh();
  }, [selected, refresh]);
  const update = useCallback(() => {
    void refresh();
  }, [refresh]);
  const lost = useCallback(() => {
    publication.current += 1;
    setWorkspace(null);
    setMessages([]);
    setQueue([]);
    setNotice("unavailable");
    void refresh();
  }, [refresh]);
  const ready = useEvents(view, update, lost);
  async function write<T>(
    path: string,
    body: unknown,
    schema?: string,
    key?: string,
  ): Promise<T | undefined> {
    const quiet = path.endsWith("/draft");
    if (!quiet) setBusy(true);
    try {
      const value = await post<T>(
        path,
        body,
        viewRef.current?.view_id ?? null,
        schema,
        key,
      );
      await refresh();
      return value;
    } catch (error) {
      fail(error);
      return undefined;
    } finally {
      if (mounted.current && !quiet) setBusy(false);
    }
  }
  async function claim() {
    if (!viewRef.current) return;
    const result = await write<ViewLease>("/v1/review/view/claim", {
      expected_revision: viewRef.current.revision,
    });
    if (result) {
      viewRef.current = result;
      setView(result);
      await refresh();
    }
  }
  return {
    context,
    session,
    view,
    workspace,
    messages,
    queue,
    selected,
    notice,
    busy,
    ready,
    enabled:
      !!session &&
      view?.state === "active" &&
      ready &&
      !busy &&
      notice !== "wrongActor" &&
      workspace?.run_state === "active",
    select,
    refresh,
    write,
    claim,
    fail,
  };
}
export type ReviewChannel = ReturnType<typeof useReview>;
