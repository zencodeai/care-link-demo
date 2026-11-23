import { useState } from "react";
import { digestPattern, fixtures, uuidPattern } from "./api";
import type { Fixture, Locale } from "./api";
import type { Text } from "./messages";
import type { Training } from "./useTraining";

type ScenarioWorkspace = Pick<
  Training,
  "scenario" | "receipt" | "clearScenario" | "command" | "read"
>;

export function ScenarioPanel({
  workspace,
  locale,
  text,
  blocked,
  available,
}: {
  workspace: ScenarioWorkspace;
  locale: Locale;
  text: Text;
  blocked: boolean;
  available: boolean;
}) {
  const [artifact, setArtifact] = useState("");
  const [clock, setClock] = useState("");
  const [fixture, setFixture] = useState<Fixture>("accept");
  const [explicitId, setExplicitId] = useState<string | null>(null);
  const { scenario, receipt } = workspace;
  const scenarioId = explicitId ?? receipt?.resource_id ?? "";
  if (!available) return null;
  return (
    <section aria-labelledby="training-scenarios">
      <h2 id="training-scenarios">{text.scenarios}</h2>
      <form
        autoComplete="off"
        onSubmit={(event) => {
          event.preventDefault();
          workspace.clearScenario();
          setExplicitId(null);
          workspace.command({
            type: "create",
            body: {
              artifact_digest: artifact,
              locale,
              fixture_mode: fixture,
              business_clock_at: clock,
            },
          });
        }}
      >
        <fieldset disabled={blocked}>
          <legend>{text.configureScenario}</legend>
          <label htmlFor="training-artifact">{text.scenarioArtifact}</label>
          <input
            id="training-artifact"
            required
            pattern={digestPattern}
            spellCheck={false}
            value={artifact}
            onChange={(event) => setArtifact(event.target.value)}
          />
          <label htmlFor="training-fixture">{text.fixture}</label>
          <select
            id="training-fixture"
            value={fixture}
            onChange={(event) => {
              const next = fixtures.find(
                (value) => value === event.target.value,
              );
              if (next) setFixture(next);
            }}
          >
            {fixtures.map((value) => (
              <option key={value} value={value}>
                {text.fixtures[value]}
              </option>
            ))}
          </select>
          <label htmlFor="training-clock">{text.clock}</label>
          <input
            id="training-clock"
            required
            aria-describedby="training-clock-format"
            spellCheck={false}
            value={clock}
            onChange={(event) => setClock(event.target.value)}
          />
          <p id="training-clock-format" className="hint">
            {text.clockHint}
          </p>
          <button type="submit">{text.createScenario}</button>
        </fieldset>
      </form>
      <p role="status">{receipt && text.committed}</p>
      <form
        autoComplete="off"
        onSubmit={(event) => {
          event.preventDefault();
          setExplicitId(scenarioId);
          workspace.clearScenario();
          workspace.read("scenario", scenarioId);
        }}
      >
        <label htmlFor="training-scenario-id">{text.scenarioReference}</label>
        <input
          id="training-scenario-id"
          required
          pattern={uuidPattern}
          disabled={blocked}
          spellCheck={false}
          value={scenarioId}
          onChange={(event) => {
            setExplicitId(event.target.value);
            workspace.clearScenario();
          }}
        />
        <button type="submit" disabled={blocked}>
          {text.readScenario}
        </button>
      </form>
      {scenario?.id === scenarioId && (
        <>
          <div role="status">
            <dl>
              <dt>{text.status}</dt>
              <dd>{text.scenarioStates[scenario.state]}</dd>
              <dt>{text.revision}</dt>
              <dd>{scenario.revision}</dd>
              <dt>{text.scenarioArtifact}</dt>
              <dd>
                <code>{scenario.artifact_digest}</code>
              </dd>
              <dt>{text.evidence}</dt>
              <dd>
                <code>{scenario.evidence_digest ?? text.noEvidence}</code>
              </dd>
            </dl>
          </div>
          {(scenario.state === "created" || scenario.state === "running") && (
            <button
              type="button"
              disabled={blocked}
              onClick={() => workspace.command({ type: "stop", scenario })}
            >
              {text.stopScenario}
            </button>
          )}
        </>
      )}
    </section>
  );
}
