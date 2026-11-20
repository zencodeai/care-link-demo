import { useEffect, useRef } from "react";
import { planFields, valueText, type Locale } from "./api";
import { fieldLabels, textFor } from "./messages";
import type { PlansChannel } from "./usePlans";
import { usePlanFormField, type PlanDraftBridge } from "./review";
export function PlanEditor({
  channel,
  locale,
  draft,
}: {
  channel: PlansChannel;
  locale: Locale;
  draft?: PlanDraftBridge | undefined;
}) {
  const text = textFor(locale),
    labels = fieldLabels[locale];
  const [field, setField] = usePlanFormField(
    draft,
    "planField",
    "plan.warning_signs",
  );
  const [value, setValue] = usePlanFormField(draft, "planWords", "");
  const [unknown, setUnknown] = usePlanFormField(draft, "planUnknown", false);
  const [safety, setSafety] = usePlanFormField(draft, "planSafety", false);
  const current = channel.currentPlan;
  const lastPlan = useRef("");
  useEffect(() => {
    if (!current) return;
    if (lastPlan.current && lastPlan.current !== current.id) {
      setValue("");
      setUnknown(false);
      setSafety(false);
    }
    lastPlan.current = current.id;
  }, [current?.id]);
  const disabled = channel.busy || !!channel.pending;
  const editable =
    channel.account?.role === "pid" || channel.account?.role === "worker";
  return (
    <div>
      {current && (
        <>
          <h3>{current.state === "active" ? text.active : text.retired}</h3>
          <p>
            <code>{current.id}</code> · {text.revision}: {current.revision}
          </p>
          <p>{text.access}</p>
          {current.fields.length === 0 && <p>{text.noFields}</p>}
          <ul>
            {current.fields.map((item) => (
              <li key={item.id}>
                <strong>
                  {planFields.find((name) => name === item.field)
                    ? labels[
                        planFields.find((name) => name === item.field) ??
                          "plan.warning_signs"
                      ]
                    : item.field}
                </strong>
                <p>{valueText(item.value)}</p>
                <p>
                  {text.author}: <code>{item.author_id}</code> ·{" "}
                  {text.verification}: {item.verification}
                </p>
                {item.verification === "disputed" && (
                  <p role="alert">{text.conflict}</p>
                )}
                <p>
                  {text.effective}:{" "}
                  <time dateTime={item.effective_at}>{item.effective_at}</time>
                </p>
                {item.source ? (
                  <p>
                    {text.source}: {item.source.kind} ·{" "}
                    <code>{item.source.id}</code> · {text.revision}{" "}
                    {item.source.revision} · {item.source.verification}
                  </p>
                ) : (
                  <p>{text.noSource}</p>
                )}
              </li>
            ))}
          </ul>
          {editable && current.state === "active" && (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                channel.command(
                  `/v1/plans/${current.id}/fields`,
                  "PlanFieldCreate",
                  "PlanView",
                  {
                    expected_revision: current.revision,
                    field,
                    value: unknown
                      ? { kind: "unknown", reason: "not_known" }
                      : { kind: "text", text: value },
                    source: null,
                    safety_relevant: safety,
                  },
                );
              }}
            >
              <label htmlFor="plan-field">{text.field}</label>
              <select
                id="plan-field"
                value={field}
                disabled={disabled}
                onChange={(event) => {
                  const selected = planFields.find(
                    (item) => item === event.target.value,
                  );
                  if (selected) setField(selected);
                }}
              >
                {planFields.map((item) => (
                  <option key={item} value={item}>
                    {labels[item]}
                  </option>
                ))}
              </select>
              <label htmlFor="plan-words">{text.value}</label>
              <textarea
                id="plan-words"
                rows={3}
                maxLength={2000}
                value={value}
                disabled={disabled || unknown}
                onChange={(event) => setValue(event.target.value)}
              />
              <label>
                <input
                  type="checkbox"
                  checked={unknown}
                  disabled={disabled}
                  onChange={(event) => setUnknown(event.target.checked)}
                />
                {text.unknown}
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={safety}
                  disabled={disabled}
                  onChange={(event) => setSafety(event.target.checked)}
                />
                {text.safety}
              </label>
              <button
                type="submit"
                disabled={disabled || (!unknown && !value.trim())}
              >
                {text.append}
              </button>
            </form>
          )}
          {channel.account?.role === "pid" && current.state === "active" && (
            <button
              type="button"
              disabled={disabled}
              onClick={() =>
                channel.command(
                  `/v1/plans/${current.id}/retire`,
                  "RevisionCommand",
                  "PlanView",
                  { expected_revision: current.revision },
                )
              }
            >
              {text.retire}
            </button>
          )}
        </>
      )}
    </div>
  );
}
export function OwnReport({
  channel,
  locale,
  draft,
}: {
  channel: PlansChannel;
  locale: Locale;
  draft?: PlanDraftBridge | undefined;
}) {
  const text = textFor(locale);
  const [words, setWords] = usePlanFormField(draft, "reportWords", "");
  const session = channel.session;
  const lastSession = useRef("");
  useEffect(() => {
    if (!session) return;
    if (lastSession.current && lastSession.current !== session.id) setWords("");
    lastSession.current = session.id;
  }, [session?.id]);
  if (
    !session ||
    !["carer", "professional_participant"].includes(channel.account?.role ?? "")
  )
    return null;
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        channel.command(
          `/v1/sessions/${session.id}/assertions`,
          "AssertionCreate",
          "AssertionView",
          {
            expected_revision: session.revision,
            subject_id: session.subject_id,
            field: "observations",
            value: { kind: "text", text: words },
            supersedes_id: null,
            effective_at: new Date().toISOString(),
          },
        );
      }}
    >
      <h3>{text.report}</h3>
      <p>{text.reportHint}</p>
      <h4>{text.ownReports}</h4>
      {channel.ownReports.length === 0 && <p>{text.noReports}</p>}
      <ul>
        {channel.ownReports.map((report) => (
          <li key={report.id}>
            <p>{valueText(report.value)}</p>
            <p>
              {text.author}: <code>{report.author_id}</code> · {text.revision}:{" "}
              {report.revision}
            </p>
            <p>
              {text.verification}: {report.verification}
            </p>
            {report.verification === "disputed" && (
              <p role="alert">{text.conflict}</p>
            )}
            <p>
              {text.effective}:{" "}
              <time dateTime={report.effective_at}>{report.effective_at}</time>
            </p>
            {report.source ? (
              <p>
                {text.source}: {report.source.kind} ·{" "}
                <code>{report.source.id}</code> · {text.revision}:{" "}
                {report.source.revision} · {report.source.verification} ·{" "}
                <time dateTime={report.source.observed_at}>
                  {report.source.observed_at}
                </time>{" "}
                · <code>{report.source.digest}</code>
              </p>
            ) : (
              <p>{text.noSource}</p>
            )}
          </li>
        ))}
      </ul>
      <label htmlFor="own-report">{text.value}</label>
      <textarea
        id="own-report"
        value={words}
        rows={3}
        maxLength={2000}
        onChange={(event) => setWords(event.target.value)}
      />
      <button
        type="submit"
        disabled={
          channel.busy ||
          !!channel.pending ||
          !words.trim() ||
          !session.subject_id
        }
      >
        {text.reportSubmit}
      </button>
    </form>
  );
}
