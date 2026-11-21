import { usePrivateValue } from "./usePrivateValue";
import { useState } from "react";
import { Field, Select, digestPattern, uuidPattern } from "./Fields";
import { read } from "./api";
import type { Text } from "./messages";
import type { Incident } from "./types";
import type { Channel } from "./useGovernance";
import { Choices, State } from "./Labels";
export function IncidentPanel({
  channel,
  text,
}: {
  channel: Channel;
  text: Text;
}) {
  const [incident, setIncident] = usePrivateValue<Incident>(channel),
    [id, setId] = useState("");
  const [kind, setKind] = useState("security"),
    [severity, setSeverity] = useState("warning"),
    [session, setSession] = useState(""),
    [subject, setSubject] = useState(""),
    [evidence, setEvidence] = useState(""),
    [target, setTarget] = useState("contained"),
    [recovery, setRecovery] = useState("");
  const mayChange = ["operator", "security"].includes(channel.role ?? "");
  return (
    <section aria-labelledby="incident-title">
      <h2 id="incident-title">{text.incidents}</h2>
      <p>{text.incidentHint}</p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void channel.run(async (signal) =>
            setIncident(
              await read(`/v1/incidents/${id}`, "IncidentView", signal),
              signal,
            ),
          );
        }}
      >
        <fieldset disabled={channel.disabled}>
          <Field
            id="known-incident"
            label={text.knownIncident}
            value={id}
            onChange={setId}
            pattern={uuidPattern}
          />
          <button>{text.readIncident}</button>
        </fieldset>
      </form>
      {mayChange && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            channel.command(
              {
                path: "/v1/incidents",
                input: "IncidentCreate",
                output: "IncidentView",
                body: {
                  kind,
                  severity,
                  scope: {
                    session_id: session || null,
                    subject_id: subject || null,
                    purpose: "security",
                    fields: [],
                    recipient_id: null,
                  },
                  evidence_refs: [evidence],
                },
              },
              (value) => {
                setIncident(value);
                setId(value.id);
              },
            );
          }}
        >
          <fieldset disabled={channel.disabled}>
            <Select
              id="incident-kind"
              label={text.incidentKind}
              value={kind}
              onChange={setKind}
            >
              <Choices
                values={[
                  "security",
                  "contamination",
                  "outage",
                  "language",
                  "governance",
                ]}
                text={text}
              />
            </Select>
            <Select
              id="incident-severity"
              label={text.severity}
              value={severity}
              onChange={setSeverity}
            >
              <Choices values={["info", "warning", "critical"]} text={text} />
            </Select>
            <Field
              id="incident-session"
              label={text.session}
              value={session}
              onChange={setSession}
              pattern={uuidPattern}
              required={false}
            />
            <Field
              id="incident-subject"
              label={text.subject}
              value={subject}
              onChange={setSubject}
              pattern={uuidPattern}
              required={false}
            />
            <Field
              id="incident-evidence"
              label={text.evidence}
              value={evidence}
              onChange={setEvidence}
              pattern={digestPattern}
            />
            <button>{text.openIncident}</button>
          </fieldset>
        </form>
      )}
      {incident && (
        <>
          <dl>
            <dt>{text.reference}</dt>
            <dd>
              <code>{incident.id}</code>
            </dd>
            <dt>{text.state}</dt>
            <dd>
              <State value={incident.state} text={text} />
            </dd>
            <dt>{text.revision}</dt>
            <dd>{incident.revision}</dd>
            <dt>{text.reviewDue}</dt>
            <dd>
              <time dateTime={incident.review_due_at}>
                {incident.review_due_at}
              </time>
            </dd>
          </dl>
          {mayChange && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                channel.command(
                  {
                    path: `/v1/incidents/${incident.id}/transition`,
                    input: "IncidentTransition",
                    output: "IncidentView",
                    body: {
                      expected_revision: incident.revision,
                      target_state: target,
                      evidence_digest: evidence,
                      recovery_approval_id: recovery || null,
                    },
                  },
                  setIncident,
                );
              }}
            >
              <fieldset disabled={channel.disabled}>
                <Select
                  id="incident-target"
                  label={text.target}
                  value={target}
                  onChange={setTarget}
                >
                  <Choices
                    values={["contained", "reviewing", "remediated", "closed"]}
                    text={text}
                  />
                </Select>
                <Field
                  id="transition-evidence"
                  label={text.evidence}
                  value={evidence}
                  onChange={setEvidence}
                  pattern={digestPattern}
                />
                <Field
                  id="incident-recovery"
                  label={text.recovery}
                  value={recovery}
                  onChange={setRecovery}
                  pattern={uuidPattern}
                  required={false}
                />
                <button>{text.transition}</button>
              </fieldset>
            </form>
          )}
        </>
      )}
    </section>
  );
}
