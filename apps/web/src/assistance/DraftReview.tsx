import { useEffect, useId, useRef, useState } from "react";
import type { Text } from "./messages";
import type { DraftContext, Review } from "./types";
import { ReviewSources } from "./ReviewSources";
export function DraftReview({
  context,
  text,
  busy,
  pending,
  privateHidden,
  onReview,
}: {
  context: DraftContext;
  text: Text;
  busy: boolean;
  pending: boolean;
  privateHidden: boolean;
  onReview: (decision: Review["decision"], value: string) => void;
}) {
  const id = useId();
  const [edited, setEdited] = useState(context.draft.text);
  const [expired, setExpired] = useState(
    Date.parse(context.expires_at) <= Date.now(),
  );
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
    const timer = window.setInterval(
      () => setExpired(Date.parse(context.expires_at) <= Date.now()),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [context.expires_at]);
  const stale = context.draft.state === "stale";
  const disabled =
    busy ||
    pending ||
    expired ||
    stale ||
    !["proposed", "review_pending"].includes(context.draft.state);
  if (privateHidden)
    return (
      <section aria-label={text.edit}>
        <label htmlFor={`${id}-edit`}>{text.edit}</label>
        <textarea
          id={`${id}-edit`}
          rows={6}
          maxLength={12000}
          value={edited}
          onChange={(event) => setEdited(event.target.value)}
        />
      </section>
    );
  return (
    <section className="assistance-review" aria-labelledby={`${id}-title`}>
      <h3 id={`${id}-title`} tabIndex={-1} ref={heading}>
        {text.proposed}
      </h3>
      <p>{text.provenance}</p>
      {expired && <p role="alert">{text.expired}</p>}
      {stale && <p role="alert">{text.stale}</p>}
      <h4>{text.original}</h4>
      <p className="assistance-copy">{context.original_text || text.empty}</p>
      <h4>{text.proposed}</h4>
      <p className="assistance-copy">{context.draft.text}</p>
      <h4>{text.sources}</h4>
      <p>{text.uncertainty}</p>
      <ReviewSources
        sources={context.sources.filter(({ ref }) => ref.kind !== "protocol")}
        text={text}
        empty={text.noPatientSources}
      />
      <h4>{text.clinicalSources}</h4>
      <p>{text.clinicalSourceHint}</p>
      <p>{text.sourceIntegrity}</p>
      <ReviewSources
        sources={context.sources.filter(({ ref }) => ref.kind === "protocol")}
        text={text}
        empty={text.noClinicalSources}
      />
      <h4>{text.missingness}</h4>
      <p>{text.missingnessHint}</p>
      <h4>{text.scope}</h4>
      <dl>
        <dt>{text.recipient}</dt>
        <dd>{context.scope.recipient_id ?? text.noRecipient}</dd>
        <dt>{text.fields}</dt>
        <dd>{context.scope.fields.map((field) => text[field]).join(", ")}</dd>
        <dt>{text.purpose}</dt>
        <dd>{text.support}</dd>
        <dt>{text.expiry}</dt>
        <dd>
          <time dateTime={context.expires_at}>{context.expires_at}</time>
        </dd>
      </dl>
      <p>{text.effect}</p>
      <label htmlFor={`${id}-edit`}>{text.edit}</label>
      <textarea
        id={`${id}-edit`}
        aria-describedby={`${id}-hint`}
        rows={6}
        maxLength={12000}
        value={edited}
        onChange={(event) => setEdited(event.target.value)}
      />
      <p id={`${id}-hint`}>{text.editHint}</p>
      <div className="actions">
        <button
          type="button"
          disabled={disabled || edited !== context.draft.text}
          onClick={() => onReview("accept", edited)}
        >
          {text.accept}
        </button>
        <button
          type="button"
          disabled={disabled || !edited.trim() || edited === context.draft.text}
          onClick={() => onReview("edit", edited)}
        >
          {text.save}
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={() => onReview("reject", edited)}
        >
          {text.reject}
        </button>
      </div>
    </section>
  );
}
