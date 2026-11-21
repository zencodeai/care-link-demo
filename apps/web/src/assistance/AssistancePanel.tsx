import { useId } from "react";
import { DraftReview } from "./DraftReview";
import { messages } from "./messages";
import { useAssistance } from "./useAssistance";
import type { Locale, SessionContext } from "./types";
import "./styles.css";
export function AssistancePanel({
  locale,
  session,
  allowAutomatic = false,
}: {
  locale: Locale;
  session: SessionContext;
  allowAutomatic?: boolean;
}) {
  const text = messages[locale],
    id = useId();
  const actions = useAssistance(session, allowAutomatic);
  const active =
    actions.task &&
    !["completed", "cancelled", "failed"].includes(actions.task.state) &&
    !["accepted", "rejected", "cancelled"].includes(actions.notice);
  return (
    <section className="assistance" aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`}>{text.title}</h2>
      <p>{text.intro}</p>
      <p
        role={
          ["failed", "unknown", "signedOut", "timedOut"].includes(
            actions.notice,
          )
            ? "alert"
            : "status"
        }
      >
        {text[actions.notice]}
      </p>
      {allowAutomatic && (
        <>
          <label className="assistance-automatic" htmlFor={`${id}-automatic`}>
            <input
              id={`${id}-automatic`}
              type="checkbox"
              checked={actions.automatic}
              onChange={(event) => actions.setAutomatic(event.target.checked)}
            />
            {text.automatic}
          </label>
          <p className="hint">{text.automaticScope}</p>
        </>
      )}
      <ol aria-label={text.workflow} className="assistance-workflow">
        <li>{text.gather}</li>
        <li>{text.prepare}</li>
        <li>{text.reviewStep}</li>
      </ol>
      <div className="actions">
        <button
          type="button"
          disabled={actions.busy || actions.pending}
          onClick={() => void actions.check()}
        >
          {text.check}
        </button>
        <button
          type="button"
          disabled={
            actions.busy ||
            actions.pending ||
            !!active ||
            !actions.availability?.available ||
            !actions.availability.functions.includes("worker_summary")
          }
          onClick={actions.start}
        >
          {text.start}
        </button>
        {actions.task && (
          <button
            type="button"
            disabled={actions.busy || actions.pending}
            onClick={() => void actions.refresh()}
          >
            {text.refresh}
          </button>
        )}
        {active && (
          <button
            type="button"
            disabled={actions.busy || actions.pending}
            onClick={actions.cancel}
          >
            {text.cancel}
          </button>
        )}
        {actions.pending && (
          <button type="button" disabled={actions.busy} onClick={actions.retry}>
            {text.retry}
          </button>
        )}
      </div>
      {actions.task && (
        <details>
          <summary>{text.details}</summary>
          <dl>
            <dt>{text.state}</dt>
            <dd>{actions.task.state}</dd>
            <dt>{text.steps}</dt>
            <dd>{actions.task.steps_used} / 4</dd>
            <dt>{text.tools}</dt>
            <dd>{actions.task.tools_used} / 3</dd>
          </dl>
        </details>
      )}
      {actions.context && (
        <DraftReview
          key={`${actions.context.draft.id}:${actions.context.draft.revision}`}
          context={actions.context}
          text={text}
          busy={
            actions.busy ||
            !actions.privateVisible ||
            ["failed", "signedOut", "unavailable"].includes(actions.notice)
          }
          pending={actions.pending}
          privateHidden={!actions.privateVisible}
          onReview={actions.review}
        />
      )}
    </section>
  );
}
