import { useCallback, useEffect, useRef, useState } from "react";
import { RequestFailure, type Ceremony } from "../trust/api";
import {
  ReviewViewUnknown,
  assertActor,
  assertContext,
  assertWorkspace,
  read,
  write,
} from "./api";
import { WorkGate, withinSignal } from "./WorkGate";
import type { ReviewWorkLease } from "../plans/review";
import { useConnection } from "./useConnection";
import type {
  PlanDraft,
  PlansReviewContext,
  PlansReviewWorkspace,
  ReviewSession,
  ViewLease,
} from "./types";

type Status =
  | "loading"
  | "ready"
  | "renewing"
  | "observer"
  | "expired"
  | "rejected"
  | "unavailable";
export function usePlansReview() {
  const [context, setContext] = useState<PlansReviewContext | null>(null);
  const [workspace, setWorkspace] = useState<PlansReviewWorkspace | null>(null);
  const [view, setView] = useState<ViewLease | null>(null);
  const [status, setStatus] = useState<Status>("loading");
  const [connected, setConnected] = useState<string | null>(null);
  const [resumption, setResumption] = useState(0);
  const [connectionEpoch, setConnectionEpoch] = useState(0);
  const [sessionExpiry, setSessionExpiry] = useState<string | null>(null);
  const [assuranceExpiry, setAssuranceExpiry] = useState<number | null>(null);
  const current = useRef<PlansReviewContext | null>(null);
  const currentView = useRef<ViewLease | null>(null);
  const readyView = useRef<string | null>(null);
  const checkedView = useRef<string | null>(null);
  const observerNeedsLogin = useRef(false);
  const unknownView = useRef(false);
  const gate = useRef(new WorkGate());
  const authGeneration = useRef(0);
  const publication = useRef(0);
  const rotating = useRef<Promise<string> | null>(null);
  const mounted = useRef(true);
  const requests = useRef(new Set<AbortController>());
  const reading = useRef(false),
    again = useRef(false),
    transitioning = useRef(false);
  const waits = useRef(
    new Set<{ id: string; resolve: () => void; reject: () => void }>(),
  );
  const live = useCallback(() => {
    if (!current.current) throw new RequestFailure("rejected");
    assertContext(current.current);
    return current.current;
  }, []);
  const hide = useCallback((error: unknown) => {
    readyView.current = null;
    checkedView.current = null;
    setConnected(null);
    setStatus(
      current.current &&
        (current.current.run_state !== "active" ||
          Date.parse(current.current.expires_at) <= Date.now())
        ? "expired"
        : error instanceof RequestFailure &&
            ["rejected", "signed_out", "invalid"].includes(error.kind)
          ? "rejected"
          : "unavailable",
    );
  }, []);
  const ready = useCallback(
    (id: string) => {
      if (
        currentView.current?.view_id !== id ||
        currentView.current.state !== "active" ||
        !mounted.current
      )
        return;
      try {
        live();
      } catch (error) {
        hide(error);
        return;
      }
      readyView.current = id;
      setConnected(id);
      if (checkedView.current === id) setStatus("ready");
      for (const waiting of waits.current)
        if (waiting.id === id) waiting.resolve();
    },
    [live, hide],
  );
  const waitReady = useCallback((id: string, signal: AbortSignal) => {
    if (signal.aborted)
      return Promise.reject(new RequestFailure("unavailable"));
    if (readyView.current === id) return Promise.resolve();
    return new Promise<void>((resolve, reject) => {
      const done = () => {
        waits.current.delete(waiting);
        signal.removeEventListener("abort", aborted);
      };
      const waiting = {
        id,
        resolve: () => {
          done();
          resolve();
        },
        reject: () => {
          done();
          reject(new RequestFailure("unavailable"));
        },
      };
      const aborted = () => waiting.reject();
      waits.current.add(waiting);
      signal.addEventListener("abort", aborted, { once: true });
    });
  }, []);
  const register = useCallback(async (signal: AbortSignal, force = false) => {
    let next: ViewLease;
    if (currentView.current && !force)
      next = await read<ViewLease>(
        "/v1/review/view",
        "ReviewView",
        signal,
        currentView.current.view_id,
      );
    else
      next = await write<ViewLease>(
        "/v1/review/view",
        {},
        "Empty",
        "ReviewView",
        signal,
      );
    if (signal.aborted) throw new RequestFailure("unavailable");
    if (
      force ||
      next.view_id !== currentView.current?.view_id ||
      next.state !== currentView.current?.state
    ) {
      readyView.current = null;
      checkedView.current = null;
      setConnected(null);
      setConnectionEpoch((value) => value + 1);
    }
    currentView.current = next;
    setView(next);
    if (next.state === "observer") setStatus("observer");
    return next;
  }, []);
  const loadWorkspace = useCallback(
    async (ctx: PlansReviewContext, lease: ViewLease, signal: AbortSignal) => {
      const next = await read<PlansReviewWorkspace>(
        "/v1/plans-review/workspace",
        "PlansReviewWorkspace",
        signal,
        lease.view_id,
      );
      assertWorkspace(next, ctx);
      if (
        signal.aborted ||
        !mounted.current ||
        currentView.current !== lease ||
        current.current?.run_id !== ctx.run_id ||
        current.current?.slot_id !== ctx.slot_id ||
        current.current?.account_id !== ctx.account_id ||
        current.current?.role !== ctx.role
      )
        throw new RequestFailure("unavailable");
      setWorkspace(next);
      checkedView.current = lease.view_id;
      if (readyView.current === lease.view_id)
        setStatus(lease.state === "active" ? "ready" : "observer");
    },
    [],
  );
  const rotate = useCallback(
    async (signal: AbortSignal, explicitTakeover = false) => {
      if (currentView.current?.state === "observer" && !explicitTakeover) {
        setStatus("observer");
        throw new RequestFailure("rejected");
      }
      const expected = live();
      publication.current += 1;
      transitioning.current = true;
      setStatus("renewing");
      readyView.current = null;
      checkedView.current = null;
      setConnected(null);
      try {
        const latest = await read<PlansReviewContext | { enabled: false }>(
          "/v1/plans-review/context",
          "PlansReviewContext",
          signal,
        );
        assertContext(latest);
        if (
          latest.run_id !== expected.run_id ||
          latest.slot_id !== expected.slot_id ||
          latest.account_id !== expected.account_id ||
          latest.role !== expected.role
        )
          throw new RequestFailure("invalid");
        const session = await write<ReviewSession>(
          "/v1/auth/review/login",
          {},
          "Empty",
          "BrowserSession",
          signal,
        );
        authGeneration.current += 1;
        assertActor(session, latest);
        if (session.assurance !== "AL2" && session.assurance !== "AL3")
          throw new RequestFailure("rejected");
        setSessionExpiry(session.expires_at);
        observerNeedsLogin.current = false;
        setAssuranceExpiry(Date.parse(session.auth_time) + 240000);
        current.current = latest;
        setContext(latest);
        const lease = await register(signal, true);
        await loadWorkspace(latest, lease, signal);
        if (lease.state !== "active") throw new RequestFailure("rejected");
        await waitReady(lease.view_id, signal);
        setResumption((value) => value + 1);
        return lease.view_id;
      } catch (error) {
        hide(error);
        throw error;
      } finally {
        transitioning.current = false;
      }
    },
    [live, register, loadWorkspace, waitReady, hide],
  );
  const enter = useCallback(
    (signal: AbortSignal) =>
      gate.current.acquire(signal, () => {
        live();
        const lease = currentView.current;
        if (
          !lease ||
          lease.state !== "active" ||
          readyView.current !== lease.view_id ||
          checkedView.current !== lease.view_id
        )
          throw new RequestFailure("rejected");
        return lease.view_id;
      }),
    [live],
  );
  const renew = useCallback(
    async (
      signal: AbortSignal,
      work?: ReviewWorkLease,
      explicitTakeover = false,
    ): Promise<string> => {
      if (rotating.current) return withinSignal(rotating.current, signal);
      const generation = authGeneration.current;
      const owned = gate.current.owns(work);
      const held = owned
        ? work!
        : await gate.current.acquire(signal, () => {
            live();
            return currentView.current?.view_id ?? "";
          });
      try {
        if (
          generation !== authGeneration.current &&
          currentView.current?.state === "active" &&
          readyView.current === currentView.current.view_id &&
          checkedView.current === currentView.current.view_id
        )
          return currentView.current.view_id;
        const operation = rotate(signal, explicitTakeover);
        rotating.current = operation;
        gate.current.hold(held, operation);
        const settled = () => {
          if (rotating.current === operation) rotating.current = null;
        };
        void operation.then(settled, settled);
        return await withinSignal(operation, signal);
      } finally {
        if (!owned) held.release();
      }
    },
    [live, rotate],
  );
  const refresh = useCallback(async () => {
    if (!mounted.current || transitioning.current) return;
    if (reading.current) {
      again.current = true;
      return;
    }
    reading.current = true;
    const generation = publication.current;
    const controller = new AbortController(),
      timer = setTimeout(() => controller.abort(), 5000);
    requests.current.add(controller);
    try {
      const ctx = await read<PlansReviewContext | { enabled: false }>(
        "/v1/plans-review/context",
        "PlansReviewContext",
        controller.signal,
      );
      if (generation !== publication.current || controller.signal.aborted)
        return;
      if (
        ctx.enabled &&
        (ctx.run_state !== "active" || Date.parse(ctx.expires_at) <= Date.now())
      ) {
        current.current = ctx;
        setContext(ctx);
      }
      assertContext(ctx);
      if (
        current.current &&
        ["run_id", "slot_id", "account_id", "role"].some(
          (key) =>
            current.current?.[key as keyof PlansReviewContext] !==
            ctx[key as keyof PlansReviewContext],
        )
      ) {
        for (const pending of requests.current)
          if (pending !== controller) pending.abort();
        currentView.current = null;
        readyView.current = null;
        checkedView.current = null;
        setView(null);
        setWorkspace(null);
        setConnected(null);
      }
      current.current = ctx;
      setContext(ctx);
      let session: ReviewSession;
      try {
        session = await read<ReviewSession>(
          "/v1/auth/session",
          "BrowserSession",
          controller.signal,
        );
      } catch (error) {
        if (!(error instanceof RequestFailure) || error.kind !== "signed_out")
          throw error;
        if (currentView.current?.state === "observer") {
          observerNeedsLogin.current = true;
          setStatus("observer");
          return;
        }
        await renew(controller.signal);
        return;
      }
      if (generation !== publication.current || controller.signal.aborted)
        return;
      assertActor(session, ctx);
      const lease = await register(controller.signal);
      if (session.assurance !== "AL2" && session.assurance !== "AL3") {
        if (lease.state === "observer") {
          await loadWorkspace(ctx, lease, controller.signal);
          setStatus("observer");
          return;
        }
        await renew(controller.signal);
        return;
      }
      setSessionExpiry(session.expires_at);
      setAssuranceExpiry(Date.parse(session.auth_time) + 240000);
      await loadWorkspace(ctx, lease, controller.signal);
      setStatus(
        lease.state === "observer"
          ? "observer"
          : readyView.current === lease.view_id
            ? "ready"
            : "loading",
      );
    } catch (error) {
      if (generation !== publication.current) return;
      if (
        mounted.current &&
        error instanceof ReviewViewUnknown &&
        currentView.current
      ) {
        unknownView.current = true;
        currentView.current = { ...currentView.current, state: "observer" };
        readyView.current = null;
        checkedView.current = null;
        setConnected(null);
        setView(currentView.current);
        setStatus("observer");
      } else if (mounted.current) hide(error);
    } finally {
      clearTimeout(timer);
      requests.current.delete(controller);
      reading.current = false;
      if (again.current && mounted.current) {
        again.current = false;
        queueMicrotask(() => {
          void refresh();
        });
      }
    }
  }, [renew, register, loadWorkspace, hide]);
  const changed = useCallback(() => {
    void refresh();
  }, [refresh]);
  const lost = useCallback(
    (id: string) => {
      if (currentView.current?.view_id !== id) return;
      readyView.current = null;
      checkedView.current = null;
      checkedView.current = null;
      setConnected(null);
      setStatus(
        currentView.current.state === "observer" ? "observer" : "loading",
      );
      if (!transitioning.current) void refresh();
    },
    [refresh],
  );
  useConnection(view, connectionEpoch, ready, changed, lost);
  useEffect(() => {
    if (!assuranceExpiry) return;
    const timer = setTimeout(
      () => {
        if (currentView.current?.state === "observer") return;
        const generation = authGeneration.current;
        const waiter = new AbortController(),
          waitDeadline = setTimeout(() => waiter.abort(), 15000);
        requests.current.add(waiter);
        void gate.current
          .acquire(waiter.signal, () => {
            live();
            if (currentView.current?.state === "observer")
              throw new RequestFailure("rejected");
            return currentView.current?.view_id ?? "";
          })
          .then(async (work) => {
            const controller = new AbortController(),
              deadline = setTimeout(() => controller.abort(), 5000);
            requests.current.add(controller);
            try {
              if (generation !== authGeneration.current) return;
              await renew(controller.signal, work);
            } finally {
              clearTimeout(deadline);
              requests.current.delete(controller);
              work.release();
            }
          })
          .catch((error) => {
            if (mounted.current && currentView.current?.state !== "observer")
              hide(error);
          })
          .finally(() => {
            clearTimeout(waitDeadline);
            requests.current.delete(waiter);
          });
      },
      Math.max(0, Math.min(assuranceExpiry - Date.now(), 2147483647)),
    );
    return () => clearTimeout(timer);
  }, [assuranceExpiry, renew, live, hide]);
  useEffect(() => {
    if (!sessionExpiry) return;
    const timer = setTimeout(
      () => {
        void refresh();
      },
      Math.max(
        0,
        Math.min(Date.parse(sessionExpiry) - Date.now() + 10, 2147483647),
      ),
    );
    return () => clearTimeout(timer);
  }, [sessionExpiry, refresh]);
  useEffect(() => {
    mounted.current = true;
    void refresh();
    const focus = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    window.addEventListener("focus", focus);
    document.addEventListener("visibilitychange", focus);
    return () => {
      mounted.current = false;
      for (const controller of requests.current) controller.abort();
      requests.current.clear();
      for (const waiting of [...waits.current]) waiting.reject();
      window.removeEventListener("focus", focus);
      document.removeEventListener("visibilitychange", focus);
    };
  }, [refresh]);
  useEffect(() => {
    if (!context) return;
    const timer = setTimeout(
      () => {
        for (const pending of requests.current) pending.abort();
        readyView.current = null;
        checkedView.current = null;
        setConnected(null);
        setStatus("expired");
      },
      Math.max(
        0,
        Math.min(Date.parse(context.expires_at) - Date.now(), 2147483647),
      ),
    );
    return () => clearTimeout(timer);
  }, [context?.expires_at]);
  const verify = useCallback(
    async (
      subject: string,
      revision: string,
      signal: AbortSignal,
      work: ReviewWorkLease,
    ) => {
      if (!gate.current.owns(work)) throw new RequestFailure("rejected");
      const ctx = live(),
        lease = currentView.current;
      if (!lease || readyView.current !== lease.view_id)
        throw new RequestFailure("rejected");
      publication.current += 1;
      transitioning.current = true;
      try {
        const ceremony = await write<Ceremony>(
          "/v1/auth/review/verify",
          {
            purpose: "plan_edit",
            resource_id: subject,
            expected_revision: revision,
          },
          "StepUpStart",
          "Ceremony",
          signal,
          lease.view_id,
        );
        authGeneration.current += 1;
        if (ceremony.state !== "verified") throw new RequestFailure("invalid");
        readyView.current = null;
        checkedView.current = null;
        setConnected(null);
        setStatus("renewing");
        const session = await read<ReviewSession>(
          "/v1/auth/session",
          "BrowserSession",
          signal,
        );
        assertActor(session, ctx);
        setSessionExpiry(session.expires_at);
        setAssuranceExpiry(Date.parse(session.auth_time) + 240000);
        const next = await register(signal, true);
        await loadWorkspace(ctx, next, signal);
        if (next.state !== "active") throw new RequestFailure("rejected");
        await waitReady(next.view_id, signal);
        return { ceremony, view_id: next.view_id };
      } catch (error) {
        hide(error);
        throw error;
      } finally {
        transitioning.current = false;
      }
    },
    [live, register, loadWorkspace, waitReady, hide],
  );
  const saveDraft = useCallback(
    async (
      text: string,
      revision: string,
      originalSignal?: AbortSignal,
      work?: ReviewWorkLease,
    ): Promise<PlanDraft | undefined> => {
      const ctx = live();
      const controller = new AbortController(),
        timer = setTimeout(() => controller.abort(), 5000);
      requests.current.add(controller);
      const signal = originalSignal ?? controller.signal;
      let held: ReviewWorkLease | undefined;
      const owned = gate.current.owns(work);
      try {
        held = owned ? work : await enter(signal);
        const lease = currentView.current;
        if (!lease || readyView.current !== lease.view_id || !workspace)
          throw new RequestFailure("rejected");
        const result = await write<PlanDraft>(
          `/v1/review/sessions/${workspace.selection.session_id}/draft`,
          { kind: "plan", text, expected_revision: revision },
          "ReviewDraftSave",
          "ReviewDraftView",
          signal,
          lease.view_id,
        );
        const latest = live();
        if (
          signal.aborted ||
          ctx.run_id !== latest.run_id ||
          ctx.account_id !== latest.account_id ||
          ctx.role !== latest.role ||
          ctx.slot_id !== latest.slot_id ||
          result.kind !== "plan" ||
          result.session_id !== workspace.selection.session_id
        )
          throw new RequestFailure("invalid");
        return result;
      } catch (error) {
        hide(error);
        // Authentication may recover for later actions; this write is not resent.
        if (error instanceof RequestFailure && error.kind === "signed_out")
          void refresh();
        return undefined;
      } finally {
        clearTimeout(timer);
        requests.current.delete(controller);
        if (!owned) held?.release();
      }
    },
    [workspace, live, hide, refresh, enter],
  );
  const claim = async () => {
    if (!currentView.current) return;
    const controller = new AbortController(),
      timer = setTimeout(() => controller.abort(), 5000);
    requests.current.add(controller);
    let held: ReviewWorkLease | undefined,
      attemptedLogin = false;
    try {
      held = await gate.current.acquire(controller.signal, () => {
        live();
        return currentView.current?.view_id ?? "";
      });
      publication.current += 1;
      transitioning.current = true;
      if (observerNeedsLogin.current) {
        attemptedLogin = true;
        await renew(controller.signal, held, true);
        return;
      }
      const lease = unknownView.current
        ? await register(controller.signal, true)
        : currentView.current;
      unknownView.current = false;
      const next =
        lease.state === "active"
          ? lease
          : await write<ViewLease>(
              "/v1/review/view/claim",
              { expected_revision: lease.revision },
              "RevisionCommand",
              "ReviewView",
              controller.signal,
              lease.view_id,
            );
      currentView.current = next;
      readyView.current = null;
      checkedView.current = null;
      setConnected(null);
      setView(next);
      setConnectionEpoch((value) => value + 1);
      const session = await read<ReviewSession>(
        "/v1/auth/session",
        "BrowserSession",
        controller.signal,
      );
      assertActor(session, live());
      if (session.assurance !== "AL2" && session.assurance !== "AL3") {
        attemptedLogin = true;
        await renew(controller.signal, held);
        return;
      }
      await loadWorkspace(live(), next, controller.signal);
    } catch (error) {
      if (
        !attemptedLogin &&
        error instanceof RequestFailure &&
        error.kind === "signed_out" &&
        held &&
        !controller.signal.aborted
      ) {
        try {
          await renew(controller.signal, held, true);
        } catch (failure) {
          hide(failure);
        }
      } else hide(error);
    } finally {
      transitioning.current = false;
      clearTimeout(timer);
      requests.current.delete(controller);
      held?.release();
    }
  };
  return {
    context,
    workspace,
    view,
    status,
    resumption,
    refresh,
    renew,
    enter,
    verify,
    saveDraft,
    claim,
    enabled:
      status === "ready" &&
      connected === view?.view_id &&
      view?.state === "active" &&
      !!context &&
      Date.parse(context.expires_at) > Date.now(),
  };
}
export type PlansReviewChannel = ReturnType<typeof usePlansReview>;
