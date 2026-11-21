import { useEffect, useState } from "react";
import { Field } from "./Fields";
import { read, utc } from "./api";
import type { Text } from "./messages";
import type { Outcome, Page, SessionContext } from "./types";
import type { Channel } from "./useLifecycle";
const states: Outcome["state"][] = [
  "offered",
  "chosen",
  "declined",
  "attempted",
  "received",
  "accepted",
  "connected",
  "reported_benefit",
  "unknown",
];
export function OutcomePanel({
  channel,
  text,
  session,
}: {
  channel: Channel;
  text: Text;
  session: SessionContext;
}) {
  const [state, setState] = useState<Outcome["state"]>("unknown");
  const [carer, setCarer] = useState(false);
  const [observed, setObserved] = useState("");
  const [saved, setSaved] = useState(false);
  const [page, setPage] = useState<Page<Outcome> | null>(null);
  useEffect(() => {
    setPage(null);
    setSaved(false);
  }, [channel.privateEpoch]);
  function load(cursor?: string | null) {
    void channel.run(async (signal) =>
      setPage(
        await read(
          `/v1/sessions/${session.id}/outcomes${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`,
          "OutcomePage",
          signal,
        ),
      ),
    );
  }
  if (!channel.account) return null;
  return (
    <section aria-labelledby="outcomes-title">
      <h2 id="outcomes-title">{text.outcomes}</h2>
      <p>{text.outcomeHint}</p>
      {saved && <p role="status">{text.outcomeSaved}</p>}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          channel.command(
            {
              path: `/v1/sessions/${session.id}/outcomes`,
              input: "OutcomeCreate",
              output: "CommandResult",
              body: {
                expected_revision: session.revision,
                pathway_id: null,
                state,
                carer_support: carer,
                observed_at: utc(observed),
                source: null,
              },
            },
            () => {
              setPage(null);
              setSaved(true);
            },
          );
        }}
      >
        <label htmlFor="outcome-state">{text.outcomeState}</label>
        <select
          id="outcome-state"
          value={state}
          onChange={(e) => {
            const next = states.find((value) => value === e.target.value);
            if (next) setState(next);
          }}
        >
          {states.map((value) => (
            <option key={value} value={value}>
              {text.states[value]}
            </option>
          ))}
        </select>
        <label>
          <input
            type="checkbox"
            checked={carer}
            onChange={(e) => setCarer(e.target.checked)}
          />
          {text.carer}
        </label>
        <Field
          id="outcome-time"
          label={text.observed}
          value={observed}
          onChange={setObserved}
          type="datetime-local"
        />
        <button disabled={channel.disabled}>{text.appendOutcome}</button>
      </form>
      <button disabled={channel.busy} onClick={() => load()}>
        {text.readOutcomes}
      </button>
      {page &&
        (page.items.length ? (
          <ul>
            {page.items.map((value) => (
              <li key={value.id}>
                {text.states[value.state]} ·{" "}
                {value.carer_support ? text.carer : text.outcomes} ·{" "}
                <time dateTime={value.observed_at}>{value.observed_at}</time>
              </li>
            ))}
          </ul>
        ) : (
          <p>{text.noOutcomes}</p>
        ))}
      {page?.next_cursor && (
        <button disabled={channel.busy} onClick={() => load(page.next_cursor)}>
          {text.next}
        </button>
      )}
    </section>
  );
}
