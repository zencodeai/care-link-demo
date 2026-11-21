import { useEffect, useState } from "react";
import { valueText } from "../plans/api";
import { Field } from "./Fields";
import { read } from "./api";
import { Verification } from "./Verification";
import { exceptionLabel, type Text } from "./messages";
import type { Export, Rights, SessionContext } from "./types";
import type { Channel } from "./useLifecycle";
export function RightsPanel({
  channel,
  text,
  session,
}: {
  channel: Channel;
  text: Text;
  session: SessionContext | null;
}) {
  const subject = session?.subject_id ?? "";
  const revision = session?.subject_revision;
  const scoped = !!subject && revision !== undefined;
  const [kind, setKind] = useState<"export" | "delete">("export");
  const [ceremony, setCeremony] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [knownId, setKnownId] = useState("");
  const [rights, setRights] = useState<Rights | null>(null);
  const [exported, setExported] = useState<Export | null>(null);
  useEffect(() => {
    setRights(null);
    setExported(null);
    setCeremony(null);
  }, [channel.privateEpoch]);
  useEffect(() => {
    setCeremony(null);
    setConfirmed(false);
  }, [subject, revision]);
  function receive(value: Rights) {
    setRights(value);
    setKnownId(value.id);
    setExported(null);
  }
  if (!channel.account) return null;
  return (
    <section aria-labelledby="rights-title">
      <h2 id="rights-title">{text.rights}</h2>
      <p>{text.rightsScope}</p>
      <p>{text.ownSubject}</p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!ceremony || !scoped) return;
          channel.command(
            {
              path: "/v1/rights",
              input: "RightsCreate",
              output: "RightsView",
              body: {
                expected_revision: revision,
                subject_id: subject,
                kind,
                ceremony_id: ceremony,
              },
            },
            receive,
          );
        }}
      >
        {scoped ? (
          <p>
            {text.subject}: <span>{subject}</span>
          </p>
        ) : (
          <p>{text.loadRightsScope}</p>
        )}
        <label htmlFor="rights-kind">{text.kind}</label>
        <select
          id="rights-kind"
          value={kind}
          onChange={(e) => {
            setKind(e.target.value === "delete" ? "delete" : "export");
            setConfirmed(false);
            setCeremony(null);
          }}
        >
          <option value="export">{text.export}</option>
          <option value="delete">{text.delete}</option>
        </select>
        <Verification
          key={`${subject}:${revision ?? ""}`}
          channel={channel}
          text={text}
          subject={scoped ? subject : ""}
          purpose={kind}
          onVerified={setCeremony}
        />
        {kind === "delete" && (
          <>
            <p>{text.deletionHint}</p>
            <label>
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              {text.deleteConfirm}
            </label>
          </>
        )}
        <button
          disabled={
            channel.disabled ||
            !scoped ||
            !ceremony ||
            (kind === "delete" && !confirmed)
          }
        >
          {text.submitRights}
        </button>
      </form>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void channel.run(async (signal) =>
            receive(await read(`/v1/rights/${knownId}`, "RightsView", signal)),
          );
        }}
      >
        <Field
          id="known-rights"
          label={text.knownRights}
          value={knownId}
          onChange={setKnownId}
          identifier
        />
        <button disabled={channel.busy}>{text.refresh}</button>
      </form>
      {rights && (
        <div aria-live="polite">
          <h3>{text.progress}</h3>
          <p>
            {text.reference}: {rights.id}
          </p>
          <p>
            {text.kind}: {text[rights.kind]}
          </p>
          <p>
            {text.state}: {text.states[rights.state]}
          </p>
          <p>
            {text.deadline}:{" "}
            <time dateTime={rights.deadline}>{rights.deadline}</time>
          </p>
          {rights.kind === "delete" && <p>{text.backup}</p>}
          <h4>{text.exceptions}</h4>
          {rights.exceptions.length ? (
            <ul>
              {rights.exceptions.map((item) => (
                <li key={item}>{exceptionLabel(item, text)}</li>
              ))}
            </ul>
          ) : (
            <p>{text.noExceptions}</p>
          )}
          <p>{text.holdHint}</p>
          {rights.kind === "export" &&
            rights.download_id &&
            rights.state === "completed" && (
              <>
                <p>{text.exportHint}</p>
                <button
                  disabled={channel.busy || exported !== null}
                  onClick={() =>
                    void channel.run(async (signal) =>
                      setExported(
                        await read(
                          `/v1/rights/${rights.id}/download`,
                          "ExportView",
                          signal,
                        ),
                      ),
                    )
                  }
                >
                  {text.download}
                </button>
              </>
            )}
        </div>
      )}
      {exported && (
        <article aria-labelledby="export-title">
          <h3 id="export-title">{text.exportData}</h3>
          <p>
            {text.subject}: {exported.subject_id}
          </p>
          <h4>{text.assertions}</h4>
          <ul>
            {exported.assertions.map((item) => (
              <li key={item.id}>
                {item.field}: {valueText(item.value)}
              </li>
            ))}
          </ul>
          <h4>{text.plans}</h4>
          <ul>
            {exported.plans.map((plan) => (
              <li key={plan.id}>
                {plan.id}
                <ul>
                  {plan.fields.map((item) => (
                    <li key={item.id}>
                      {item.field}: {valueText(item.value)}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
          <h4>{text.outcomeRefs}</h4>
          <ul>
            {exported.outcome_refs.map((id) => (
              <li key={id}>{id}</li>
            ))}
          </ul>
          <h4>{text.exceptions}</h4>
          <ul>
            {exported.exceptions.map((item) => (
              <li key={item}>{exceptionLabel(item, text)}</li>
            ))}
          </ul>
        </article>
      )}
    </section>
  );
}
