import { useState } from "react";
import { digestPattern, uuidPattern } from "./api";
import type { Text } from "./messages";
import type { Training } from "./useTraining";

type ReplayWorkspace = Pick<
  Training,
  "evaluation" | "receipt" | "scenario" | "clearEvaluation" | "command" | "read"
>;

export function ReplayPanel({
  workspace,
  text,
  blocked,
  available,
}: {
  workspace: ReplayWorkspace;
  text: Text;
  blocked: boolean;
  available: boolean;
}) {
  const [scenarioId, setScenarioId] = useState<string | null>(null);
  const [manifest, setManifest] = useState("");
  const [recorded, setRecorded] = useState("");
  const [bundle, setBundle] = useState("");
  const [explicitId, setExplicitId] = useState<string | null>(null);
  const { evaluation, receipt, scenario } = workspace;
  const replayScenario =
    scenarioId ?? receipt?.resource_id ?? scenario?.id ?? "";
  const evaluationId = explicitId ?? evaluation?.id ?? "";
  if (!available) return null;
  return (
    <section aria-labelledby="training-replays">
      <h2 id="training-replays">{text.replays}</h2>
      <p>{text.replayScope}</p>
      <form
        autoComplete="off"
        onSubmit={(event) => {
          event.preventDefault();
          workspace.clearEvaluation();
          setExplicitId(null);
          workspace.command({
            type: "replay",
            body: {
              scenario_id: replayScenario,
              input_manifest_digest: manifest,
              recorded_outputs_digest: recorded,
              bundle_digest: bundle,
            },
          });
        }}
      >
        <fieldset disabled={blocked}>
          <legend>{text.configureReplay}</legend>
          <label htmlFor="training-replay-scenario">
            {text.replayScenario}
          </label>
          <input
            id="training-replay-scenario"
            required
            pattern={uuidPattern}
            spellCheck={false}
            value={replayScenario}
            onChange={(event) => setScenarioId(event.target.value)}
          />
          <label htmlFor="training-replay-manifest">{text.manifest}</label>
          <input
            id="training-replay-manifest"
            required
            pattern={digestPattern}
            spellCheck={false}
            value={manifest}
            onChange={(event) => setManifest(event.target.value)}
          />
          <label htmlFor="training-replay-outputs">{text.recorded}</label>
          <input
            id="training-replay-outputs"
            required
            pattern={digestPattern}
            spellCheck={false}
            value={recorded}
            onChange={(event) => setRecorded(event.target.value)}
          />
          <label htmlFor="training-replay-bundle">{text.bundle}</label>
          <input
            id="training-replay-bundle"
            required
            pattern={digestPattern}
            spellCheck={false}
            value={bundle}
            onChange={(event) => setBundle(event.target.value)}
          />
          <button type="submit">{text.createReplay}</button>
        </fieldset>
      </form>
      <form
        autoComplete="off"
        onSubmit={(event) => {
          event.preventDefault();
          setExplicitId(evaluationId);
          workspace.clearEvaluation();
          workspace.read("evaluation", evaluationId);
        }}
      >
        <label htmlFor="training-evaluation-id">
          {text.evaluationReference}
        </label>
        <input
          id="training-evaluation-id"
          required
          pattern={uuidPattern}
          disabled={blocked}
          spellCheck={false}
          value={evaluationId}
          onChange={(event) => {
            setExplicitId(event.target.value);
            workspace.clearEvaluation();
          }}
        />
        <button type="submit" disabled={blocked}>
          {text.readEvaluation}
        </button>
      </form>
      {evaluation?.id === evaluationId && (
        <div role="status">
          <dl>
            <dt>{text.status}</dt>
            <dd>{text.evaluationStates[evaluation.state]}</dd>
            <dt>{text.evidence}</dt>
            <dd>
              <code>{evaluation.evidence_digest ?? text.noEvidence}</code>
            </dd>
          </dl>
        </div>
      )}
    </section>
  );
}
