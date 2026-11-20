import { useEffect, useRef, useState } from "react";
import { uuid, type Locale } from "./api";
import { ConsentPanel } from "./ConsentPanel";
import { DirectoryOptions } from "./DirectoryOptions";
import { PlanEditor, OwnReport } from "./PlanEditor";
import { textFor } from "./messages";
import { usePlans } from "./usePlans";
import type {
  PlanDraftBridge,
  PlansReviewActions,
  PlansSelection,
} from "./review";
export function PlansWorkspace({
  locale,
  initialSessionId,
  viewId = null,
  review,
  draft,
  selection,
  resumption = 0,
}: {
  locale: Locale;
  initialSessionId?: string;
  viewId?: string | null;
  review?: PlansReviewActions;
  draft?: PlanDraftBridge;
  selection?: PlansSelection;
  resumption?: number;
}) {
  const channel = usePlans(viewId, review);
  const text = textFor(locale);
  const [sessionId, setSessionId] = useState(initialSessionId ?? "");
  const [planId, setPlanId] = useState("");
  const [invalid, setInvalid] = useState(false);
  const previousAccount = useRef("");
  const loadedSelection = useRef("");
  if (channel.account)
    previousAccount.current =
      channel.account.account_id + ":" + channel.account.role;
  const disabled = channel.busy || !!channel.pending;
  useEffect(() => {
    if (review) return;
    if (initialSessionId && uuid.test(initialSessionId)) {
      setSessionId(initialSessionId);
      void channel.loadSession(initialSessionId);
    }
  }, [initialSessionId]);
  useEffect(() => {
    if (!review?.enabled || !selection) return;
    const key = selection.session_id + ":" + (selection.plan_id ?? "");
    if (loadedSelection.current === key) return;
    loadedSelection.current = key;
    void channel.loadSelection(selection);
  }, [selection?.session_id, selection?.plan_id, review?.enabled, resumption]);
  return (
    <section aria-labelledby="plans-title">
      <h2 id="plans-title">{text.title}</h2>
      <p className="notice">{text.scope}</p>
      <p
        role={
          channel.notice === "rejected" || channel.notice === "invalid"
            ? "alert"
            : "status"
        }
      >
        {text[channel.notice]}
      </p>
      <div
        hidden={channel.recovering || (!!review && !review.enabled)}
        inert={channel.recovering || (!!review && !review.enabled)}
      >
        {review && channel.pending && (
          <div className="notice">
            <p>{text.operationUnknown}</p>
            <button
              type="button"
              disabled={channel.busy || !channel.account}
              onClick={channel.reconcile}
            >
              {text.reconcile}
            </button>
          </div>
        )}
        <div hidden={!!review}>
          <button
            type="button"
            disabled={channel.busy}
            onClick={() => {
              void channel.check();
            }}
          >
            {text.check}
          </button>
          {channel.account && (
            <p>
              {channel.account.role} · <code>{channel.account.account_id}</code>{" "}
              · {channel.account.assurance}
            </p>
          )}
          {channel.pending && (
            <div className="notice">
              <p>{text.operationUnknown}</p>
              <p>
                {text.operation}: <code>{channel.pending.key}</code>
              </p>
              <button
                type="button"
                disabled={channel.busy || !channel.account}
                onClick={channel.reconcile}
              >
                {text.reconcile}
              </button>
              <button
                type="button"
                disabled={channel.busy || !channel.account}
                onClick={channel.retry}
              >
                {text.retry}
              </button>
            </div>
          )}
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (!uuid.test(sessionId)) {
                setInvalid(true);
                return;
              }
              setInvalid(false);
              void channel.loadSession(sessionId);
            }}
          >
            <label htmlFor="plans-session">{text.session}</label>
            <input
              id="plans-session"
              value={sessionId}
              autoComplete="off"
              onChange={(event) => setSessionId(event.target.value)}
            />
            <button type="submit" disabled={disabled}>
              {text.loadSession}
            </button>
          </form>
          <p>{text.selectSession}</p>
          {channel.session && (
            <p>
              {text.session}: <code>{channel.session.id}</code> ·{" "}
              {text.revision}: {channel.session.revision}
            </p>
          )}
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (!uuid.test(planId)) {
                setInvalid(true);
                return;
              }
              setInvalid(false);
              void channel.loadPlan(planId);
            }}
          >
            <label htmlFor="plans-id">{text.planId}</label>
            <input
              id="plans-id"
              value={planId}
              autoComplete="off"
              onChange={(event) => setPlanId(event.target.value)}
            />
            <button type="submit" disabled={disabled}>
              {text.loadPlan}
            </button>
          </form>
          {invalid && <p role="alert">{text.invalid}</p>}
        </div>
        {channel.account?.role === "pid" &&
          channel.session?.subject_id &&
          (!review || !channel.currentPlan) && (
            <button
              type="button"
              disabled={disabled}
              onClick={() =>
                channel.command("/v1/plans", "PlanCreate", "PlanView", {
                  subject_id: channel.session?.subject_id,
                  expected_revision: channel.session?.revision,
                })
              }
            >
              {text.create}
            </button>
          )}
        <div key={previousAccount.current}>
          <PlanEditor channel={channel} locale={locale} draft={draft} />
          <OwnReport channel={channel} locale={locale} draft={draft} />
          <ConsentPanel channel={channel} locale={locale} draft={draft} />
        </div>
        <DirectoryOptions channel={channel} locale={locale} />
      </div>
    </section>
  );
}
