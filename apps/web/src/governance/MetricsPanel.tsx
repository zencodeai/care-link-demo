import { usePrivateValue } from "./usePrivateValue";
import { useState } from "react";
import { Field, Select } from "./Fields";
import { utc } from "./api";
import type { Text } from "./messages";
import type { Metrics } from "./types";
import type { Channel } from "./useGovernance";
import { Choices } from "./Labels";
const coupled = [
  "safety",
  "access",
  "equity",
  "police_avoidance",
  "exposure_aggregate",
] as const;
export function MetricsPanel({
  channel,
  text,
}: {
  channel: Channel;
  text: Text;
}) {
  const [definition, setDefinition] = useState(""),
    [start, setStart] = useState(""),
    [end, setEnd] = useState(""),
    [cohort, setCohort] = useState("all"),
    [report, setReport] = usePrivateValue<Metrics>(channel);
  return (
    <section aria-labelledby="metrics-title">
      <h2 id="metrics-title">{text.metrics}</h2>
      <p>{text.reportHint}</p>
      <form
        onChange={() => setReport(null)}
        onSubmit={(e) => {
          e.preventDefault();
          channel.command(
            {
              path: "/v1/metrics/query",
              input: "MetricsQuery",
              output: "MetricsView",
              body: {
                definition_version: definition,
                period_start: utc(start),
                period_end: utc(end),
                cohort,
              },
            },
            setReport,
          );
        }}
      >
        <fieldset disabled={channel.disabled}>
          <Field
            id="metric-definition"
            label={text.definition}
            value={definition}
            onChange={setDefinition}
          />
          <Field
            id="metric-start"
            label={text.periodStart}
            value={start}
            onChange={setStart}
            type="datetime-local"
          />
          <Field
            id="metric-end"
            label={text.periodEnd}
            value={end}
            onChange={setEnd}
            type="datetime-local"
          />
          <Select
            id="metric-cohort"
            label={text.cohort}
            value={cohort}
            onChange={setCohort}
          >
            <Choices
              values={["all", "en-CA", "fr-CA", "CA-XX", "CA-YY"]}
              text={text}
            />
          </Select>
          <button>{text.queryMetrics}</button>
        </fieldset>
      </form>
      {report && (
        <div>
          {report.suppressed ? (
            <p>{text.suppressed}</p>
          ) : (
            <>
              <p>
                {text.definition}: {report.definition_version} ·{" "}
                {text.cohortSize}: {report.cohort_size}
              </p>
              {coupled.map((name) => (
                <section key={name} aria-label={text[name]}>
                  <h3>{text[name]}</h3>
                  {report[name] === null ? (
                    <p>{text.notMeasured}</p>
                  ) : (
                    <dl>
                      <dt>{text.numerator}</dt>
                      <dd>{report[name].numerator}</dd>
                      <dt>{text.denominator}</dt>
                      <dd>{report[name].denominator}</dd>
                      <dt>{text.unknownCount}</dt>
                      <dd>{report[name].unknown}</dd>
                    </dl>
                  )}
                </section>
              ))}
            </>
          )}
        </div>
      )}
    </section>
  );
}
