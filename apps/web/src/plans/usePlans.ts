import { useCallback, useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { RequestFailure, type Ceremony, type Session } from "../trust/api";
import {
  assertion,
  conversation,
  ownReportPage,
  consent,
  decode,
  directoryPage,
  directoryEntry,
  identity,
  operation,
  plan,
  read,
  send,
  type Assertion,
  type Command,
  type Consent,
  type Conversation,
  type DirectoryPage,
  type Plan,
} from "./api";
import type {
  PlansReviewActions,
  PlansSelection,
  ReviewWorkLease,
} from "./review";
export type Notice =
  | "ready"
  | "pending"
  | "committed"
  | "rejected"
  | "unavailable"
  | "signed_out"
  | "invalid"
  | "operationUnknown";
interface Selection {
  session: string;
  plan: string;
  grant: string;
}
interface PendingVerification {
  account: string;
  role: Session["role"];
  subject: string;
  ceremony: string;
  expires: number;
  selection: Selection;
}
export function usePlans(viewId: string | null, review?: PlansReviewActions) {
  const [account, setAccount] = useState<Session | null>(null);
  const [session, setSession] = useState<Conversation | null>(null);
  const [currentPlan, setPlan] = useState<Plan | null>(null);
  const [ownReports, setOwnReports] = useState<Assertion[]>([]);
  const ownReportsRef = useRef<Assertion[]>([]);
  const selectedSubject = useRef<string | null>(null);
  const [grant, setGrant] = useState<Consent | null>(null);
  const [directory, setDirectory] = useState<DirectoryPage | null>(null);
  const [notice, setNotice] = useState<Notice>("ready");
  const [busy, setBusy] = useState(false);
  const [recovering, setRecovering] = useState(false);
  const [pending, setPending] = useState<Command | null>(null);
  const accountRef = useRef<Session | null>(null);
  const active = useRef<AbortController | null>(null);
  const activeWork = useRef<ReviewWorkLease | undefined>(undefined);
  const currentView = useRef(viewId);
  const lastViewProp = useRef(viewId);
  if (lastViewProp.current !== viewId) {
    lastViewProp.current = viewId;
    currentView.current = viewId;
  }
  const reviewRef = useRef(review);
  reviewRef.current = review;
  const background = useRef<Promise<void> | null>(null);
  const backgroundController = useRef<AbortController | null>(null);
  const skipReviewResume = useRef(false);
  const selected = useRef({ session: "", plan: "", grant: "" });
  const owner = useRef("");
  const lastPrincipal = useRef("");
  // Keep only selected IDs/cursor between reads, never cached facts or permission.
  const directorySelection = useRef<{
    ids: string[];
    next_cursor: string | null;
  } | null>(null);
  const verification = useRef<PendingVerification | null>(null);
  // This is a negative attempt budget, never cached permission or a proof.
  const recoveredCeremonies = useRef(new Set<string>());
  const trackPendingVerification = useCallback(
    (subject: string | null, ceremony: Ceremony | null) => {
      const current = accountRef.current;
      if (
        !current ||
        !subject ||
        subject !== selectedSubject.current ||
        !selected.current.session ||
        !ceremony ||
        ceremony.state === "verified" ||
        ceremony.state === "expired" ||
        !Number.isFinite(Date.parse(ceremony.expires_at)) ||
        Date.parse(ceremony.expires_at) <= Date.now()
      ) {
        verification.current = null;
        return;
      }
      verification.current = {
        account: current.account_id,
        role: current.role,
        subject,
        ceremony: ceremony.ceremony_id,
        expires: Date.parse(ceremony.expires_at),
        selection: { ...selected.current },
      };
    },
    [],
  );
  function clearPrivate() {
    verification.current = null;
    setPlan(null);
    setGrant(null);
    setSession(null);
    setOwnReports([]);
    ownReportsRef.current = [];
    selectedSubject.current = null;
  }
  function acceptAccount(next: Session) {
    const principal = next.account_id + ":" + next.role;
    if (lastPrincipal.current && lastPrincipal.current !== principal) {
      clearPrivate();
      selected.current = { session: "", plan: "", grant: "" };
      setPending(null);
      owner.current = "";
      directorySelection.current = null;
      setDirectory(null);
    }
    lastPrincipal.current = principal;
    accountRef.current = next;
    setAccount(next);
  }
  function sameSelection(left: Selection, right: Selection): boolean {
    return (
      left.session === right.session &&
      left.plan === right.plan &&
      left.grant === right.grant
    );
  }
  function assertActive(signal: AbortSignal) {
    if (signal.aborted) throw new RequestFailure("unavailable");
  }
  function verificationCurrent(expected: PendingVerification): boolean {
    return (
      verification.current === expected &&
      expected.expires > Date.now() &&
      accountRef.current?.account_id === expected.account &&
      accountRef.current.role === expected.role &&
      selectedSubject.current === expected.subject &&
      sameSelection(selected.current, expected.selection)
    );
  }
  async function refreshOnce(
    signal: AbortSignal,
    expected?: PendingVerification,
  ) {
    const next = await identity(signal);
    assertActive(signal);
    if (
      reviewRef.current &&
      (next.account_id !== reviewRef.current.account_id ||
        next.role !== reviewRef.current.role ||
        Date.parse(reviewRef.current.expires_at) <= Date.now())
    )
      throw new RequestFailure("invalid");
    if (expected) {
      if (!verificationCurrent(expected)) throw new RequestFailure("invalid");
      if (next.account_id !== expected.account || next.role !== expected.role) {
        // Current identity may legitimately have switched. Clear old actor
        // state and remount its local inputs, without reading old selections.
        acceptAccount(next);
        throw new RequestFailure("invalid");
      }
    } else acceptAccount(next);
    const ids = { ...selected.current };
    let nextSession: Conversation | null = null;
    let nextReports: Assertion[] = [];
    let nextPlan: Plan | null = null;
    let nextGrant: Consent | null = null;
    let nextDirectory: DirectoryPage | null = null;
    if (ids.session) {
      const value = await read(
        `/v1/sessions/${ids.session}`,
        "SessionView",
        conversation,
        signal,
      );
      nextSession = value;
      if (expected && value.subject_id !== expected.subject)
        throw new RequestFailure("invalid");
      if (ids.session === selected.current.session) {
        if (next.role === "carer" || next.role === "professional_participant") {
          const reports = await read(
            `/v1/sessions/${ids.session}/own-reports`,
            "OwnReportPage",
            ownReportPage,
            signal,
          );
          if (
            reports.items.some(
              (report) =>
                report.author_id !== next.account_id ||
                report.subject_id !== value.subject_id,
            )
          )
            throw new RequestFailure("invalid");
          nextReports = reports.items;
        }
      }
    }
    if (ids.plan) {
      const value = await read(
        `/v1/plans/${ids.plan}`,
        "PlanView",
        plan,
        signal,
      );
      if (expected && value.subject_id !== expected.subject)
        throw new RequestFailure("invalid");
      nextPlan = value;
    }
    if (ids.grant) {
      const value = await read(
        `/v1/consents/${ids.grant}`,
        "ConsentView",
        consent,
        signal,
      );
      if (expected && value.scope.subject_id !== expected.subject)
        throw new RequestFailure("invalid");
      nextGrant = value;
    }
    if (directorySelection.current) {
      const previous = directorySelection.current;
      const items: DirectoryPage["items"] = [];
      // Each read independently rechecks current authority. Keep one request
      // outstanding so a seven-entry refresh does not burst through the shared
      // gateway guard; publish only after every current read succeeds.
      for (const id of previous.ids) {
        items.push(
          await read(
            `/v1/directory/${id}`,
            "DirectoryView",
            directoryEntry,
            signal,
          ),
        );
      }
      nextDirectory = { next_cursor: previous.next_cursor, items };
    }
    assertActive(signal);
    if (
      !sameSelection(ids, selected.current) ||
      (expected && !verificationCurrent(expected))
    )
      throw new RequestFailure("invalid");
    // No partially revalidated projection becomes visible. The original
    // controller and its five-second budget cover both read passes.
    acceptAccount(next);
    setSession(nextSession);
    selectedSubject.current = nextSession?.subject_id ?? null;
    ownReportsRef.current = nextReports;
    setOwnReports(nextReports);
    setPlan(nextPlan);
    setGrant(nextGrant);
    setDirectory(nextDirectory);
  }
  async function refresh(signal: AbortSignal) {
    try {
      await refreshOnce(signal);
      if (reviewRef.current) setRecovering(false);
    } catch (error) {
      if (
        reviewRef.current &&
        error instanceof RequestFailure &&
        error.kind === "signed_out" &&
        !signal.aborted
      ) {
        skipReviewResume.current = true;
        flushSync(() => setRecovering(true));
        currentView.current = await reviewRef.current.renew(
          signal,
          activeWork.current,
        );
        await refreshOnce(signal);
        setRecovering(false);
        return;
      }
      const pendingVerification = verification.current;
      if (
        !(error instanceof RequestFailure) ||
        error.kind !== "signed_out" ||
        signal.aborted ||
        !pendingVerification ||
        !verificationCurrent(pendingVerification) ||
        recoveredCeremonies.current.has(pendingVerification.ceremony)
      )
        throw error;
      recoveredCeremonies.current.add(pendingVerification.ceremony);
      // Remove projections from visual/accessibility interaction before the
      // second identity request starts, while keeping their editors mounted.
      flushSync(() => setRecovering(true));
      await refreshOnce(signal, pendingVerification);
      setRecovering(false);
    }
  }
  async function run(
    work: (signal: AbortSignal) => Promise<void>,
    success: Notice = "ready",
  ) {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setNotice("pending");
    const timer = window.setTimeout(() => controller.abort(), 5000);
    try {
      // Review background reads never disable typing. A foreground action
      // waits for that read using its original click-time budget.
      if (reviewRef.current && background.current) await background.current;
      assertActive(controller.signal);
      if (reviewRef.current) {
        const lease = await reviewRef.current.enter(controller.signal);
        activeWork.current = lease;
        if (currentView.current !== lease.view_id) {
          currentView.current = lease.view_id;
          await refresh(controller.signal);
        }
      }
      if (
        reviewRef.current &&
        Date.parse(reviewRef.current.expires_at) <= Date.now()
      )
        throw new RequestFailure("rejected");
      await work(controller.signal);
      if (!controller.signal.aborted) setNotice(success);
    } catch (error) {
      clearPrivate();
      setDirectory(null);
      setRecovering(false);
      const kind = error instanceof RequestFailure ? error.kind : "invalid";
      if (!reviewRef.current || kind !== "unavailable")
        directorySelection.current = null;
      setNotice(kind === "unknown" ? "operationUnknown" : kind);
      if (kind === "signed_out") {
        accountRef.current = null;
        setAccount(null);
      }
    } finally {
      window.clearTimeout(timer);
      activeWork.current?.release();
      activeWork.current = undefined;
      if (active.current === controller) {
        active.current = null;
        setBusy(false);
      }
    }
  }
  async function execute(command: Command, signal: AbortSignal) {
    let dispatched = false;
    try {
      const result = await send(
        command,
        signal,
        () => {
          dispatched = true;
          setPending(command);
          owner.current = accountRef.current?.account_id ?? "";
        },
        currentView.current,
      );
      if (command.output === "PlanView") {
        const value = decode("PlanView", result, plan);
        if (selected.current.plan !== value.id) verification.current = null;
        selected.current.plan = value.id;
        setPlan(value);
      } else if (command.output === "ConsentView") {
        const value = decode("ConsentView", result, consent);
        if (selected.current.grant !== value.id) verification.current = null;
        selected.current.grant = value.id;
        setGrant(value);
      } else if (
        command.output === "AssertionView" &&
        command.path === `/v1/sessions/${selected.current.session}/assertions`
      ) {
        const value = decode("AssertionView", result, assertion);
        if (
          value.author_id !== accountRef.current?.account_id ||
          value.subject_id !== selectedSubject.current
        )
          throw new RequestFailure("invalid");
        ownReportsRef.current = [
          ...ownReportsRef.current.filter((report) => report.id !== value.id),
          value,
        ];
        setOwnReports(ownReportsRef.current);
      } else if (command.output === "DirectoryPage") {
        const page = decode("DirectoryPage", result, directoryPage);
        directorySelection.current = {
          ids: page.items.map((entry) => entry.id),
          next_cursor: page.next_cursor,
        };
        setDirectory(page);
      }
      setPending(null);
      if (command.output !== "DirectoryPage") await refresh(signal);
    } catch (error) {
      if (
        reviewRef.current &&
        error instanceof RequestFailure &&
        error.kind === "signed_out"
      ) {
        const recovery = new AbortController();
        const timeout = setTimeout(() => recovery.abort(), 5000);
        // Restore authority for a later explicit action, never replay a write.
        void reviewRef.current
          .renew(recovery.signal)
          .catch(() => {})
          .finally(() => clearTimeout(timeout));
      }
      if (
        !dispatched ||
        (error instanceof RequestFailure &&
          (error.kind === "rejected" || error.kind === "signed_out"))
      )
        setPending(null);
      throw error;
    }
  }
  function command(path: string, input: string, output: string, body: unknown) {
    if (pending) return;
    const value = { key: crypto.randomUUID(), path, input, output, body };
    void run((signal) => execute(value, signal), "committed");
  }
  const check = () => run(refresh);
  const loadSession = (id: string) => {
    if (active.current) return Promise.resolve();
    verification.current = null;
    selected.current.session = id;
    setSession(null);
    selectedSubject.current = null;
    ownReportsRef.current = [];
    setOwnReports([]);
    return run(refresh);
  };
  const loadPlan = (id: string) => {
    if (active.current) return Promise.resolve();
    verification.current = null;
    selected.current.plan = id;
    setPlan(null);
    return run(refresh);
  };
  const loadGrant = (id: string) => {
    if (active.current) return Promise.resolve();
    verification.current = null;
    selected.current.grant = id;
    setGrant(null);
    return run(refresh);
  };
  const loadSelection = (selection: PlansSelection) => {
    if (active.current || background.current) return Promise.resolve();
    verification.current = null;
    selected.current = {
      session: selection.session_id,
      plan: selection.plan_id ?? "",
      grant: "",
    };
    return run(refresh);
  };
  function retry() {
    if (!pending || owner.current !== accountRef.current?.account_id) return;
    void run(async (signal) => {
      await refresh(signal);
      await execute(pending, signal);
    }, "committed");
  }
  function reconcile() {
    if (!pending || owner.current !== accountRef.current?.account_id) return;
    void run(async (signal) => {
      const status = await read(
        `/v1/operations/${pending.key}`,
        "OperationStatus",
        operation,
        signal,
      );
      if (status.state === "committed") {
        await refresh(signal);
        await execute(pending, signal);
      } else if (status.state === "rejected") {
        setPending(null);
        await refresh(signal);
      } else throw new RequestFailure("unknown");
    });
  }
  useEffect(
    () => () => {
      active.current?.abort();
      backgroundController.current?.abort();
    },
    [],
  );
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!accountRef.current || active.current || background.current) return;
      if (!reviewRef.current) {
        void run(refresh);
        return;
      }
      if (!reviewRef.current.enabled) return;
      const controller = new AbortController(),
        timeout = setTimeout(() => controller.abort(), 5000);
      backgroundController.current = controller;
      const update = refresh(controller.signal)
        .then(() => {
          setNotice((previous) =>
            previous === "unavailable" || previous === "signed_out"
              ? "ready"
              : previous,
          );
        })
        .catch((error: unknown) => {
          clearPrivate();
          setDirectory(null);
          setRecovering(false);
          const kind = error instanceof RequestFailure ? error.kind : "invalid";
          if (kind !== "unavailable") directorySelection.current = null;
          setNotice(kind === "unknown" ? "operationUnknown" : kind);
        })
        .finally(() => {
          clearTimeout(timeout);
          background.current = null;
          backgroundController.current = null;
        });
      background.current = update;
    }, 5000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    if (!review) return;
    if (!review.enabled) {
      setRecovering(true);
    } else if (skipReviewResume.current) {
      // The renewing read already owns its single fresh pass.
      skipReviewResume.current = false;
    } else if (selected.current.session) {
      if (!active.current && !background.current) void run(refresh);
    }
  }, [review?.enabled]);
  useEffect(() => {
    if (!account) return;
    const timer = window.setTimeout(
      () => {
        active.current?.abort();
        clearPrivate();
        accountRef.current = null;
        setAccount(null);
        setNotice("signed_out");
      },
      Math.max(
        0,
        Math.min(Date.parse(account.expires_at) - Date.now(), 2147483647),
      ),
    );
    return () => window.clearTimeout(timer);
  }, [account]);
  useEffect(() => {
    if (!grant) return;
    const timer = window.setTimeout(
      () => {
        setPlan(null);
        setGrant(null);
      },
      Math.max(
        0,
        Math.min(Date.parse(grant.expires_at) - Date.now(), 2147483647),
      ),
    );
    return () => window.clearTimeout(timer);
  }, [grant]);
  return {
    account,
    session,
    currentPlan,
    ownReports,
    grant,
    directory,
    notice,
    busy,
    recovering,
    pending,
    check,
    loadSession,
    loadPlan,
    loadGrant,
    loadSelection,
    command,
    retry,
    reconcile,
    run,
    trackPendingVerification,
    review,
    reviewWork: () => activeWork.current,
    refreshCurrent: refresh,
    adoptReviewView: (id: string) => {
      currentView.current = id;
    },
  };
}
export type PlansChannel = ReturnType<typeof usePlans>;
