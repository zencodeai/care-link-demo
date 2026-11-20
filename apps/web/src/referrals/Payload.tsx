import type { Payload as PayloadValue } from "./types";
import { label, type Text } from "./messages";
import type { Source } from "../plans/api";
export function Provenance({
  sources,
  text,
}: {
  sources: Source[];
  text: Text;
}) {
  return (
    <ul>
      {sources.map((source) => (
        <li key={`${source.kind}:${source.id}:${source.revision}`}>
          <span>
            {label(source.kind, text)} · {source.id} · {text.revision}{" "}
            {source.revision}
          </span>
          <br />
          <span>
            {text.verification}: {label(source.verification, text)} ·{" "}
            {source.observed_at}
          </span>
          <br />
          <span className="referral-digest">{source.digest}</span>
        </li>
      ))}
    </ul>
  );
}
export function Payload({
  payload,
  text,
}: {
  payload: PayloadValue;
  text: Text;
}) {
  return (
    <div className="referral-payload">
      <dl>
        <dt>{text.subject}</dt>
        <dd>{payload.subject_id}</dd>
        <dt>{text.recipient}</dt>
        <dd>{payload.recipient_service_id}</dd>
        <dt>{text.purpose}</dt>
        <dd>{label(payload.purpose, text)}</dd>
      </dl>
      <h3>{text.qualifications}</h3>
      {payload.qualifications.length ? (
        <ul>
          {payload.qualifications.map((value, index) => (
            <li key={index}>{value}</li>
          ))}
        </ul>
      ) : (
        <p>{text.noQualifications}</p>
      )}
      {payload.fields.map((field, index) => (
        <article key={`${field.field}:${index}`}>
          <h3>{label(field.field, text)}</h3>
          <p>
            {text.value}:{" "}
            {field.value.kind === "text"
              ? field.value.text
              : field.value.kind === "choice"
                ? field.value.value
                : `${text.unknownValue}: ${label(field.value.reason, text)}`}
          </p>
          <h4>{text.provenance}</h4>
          <Provenance sources={field.sources} text={text} />
        </article>
      ))}
    </div>
  );
}
export function DeliveryState({ state, text }: { state: string; text: Text }) {
  const description =
    state === "pending"
      ? text.pending
      : state === "authorized"
        ? text.authorization
        : state === "attempted"
          ? text.attempted
          : state === "received"
            ? text.received
            : state === "accepted"
              ? text.accepted
              : state === "partial"
                ? text.partialState
                : state === "rejected"
                  ? text.rejectedState
                  : state === "cancelled"
                    ? text.cancelled
                    : text.unresolved;
  return <p role="status">{description}</p>;
}
