import { parseContract, validateContract } from "@care-link/contracts";
import { csrf, request, RequestFailure } from "../../trust/api";

export const fixtures = [
  "accept",
  "reject",
  "partial",
  "delay",
  "drop_after_store",
  "receipt_unavailable",
  "poisoned_feed",
  "channel_drop",
  "regional_outage",
] as const;
export type Fixture = (typeof fixtures)[number];
export type Locale = "en-CA" | "fr-CA";

export interface Scenario {
  id: string;
  revision: string;
  state: "created" | "running" | "stopped" | "completed";
  artifact_digest: string;
  evidence_digest: string | null;
}

export interface Evaluation {
  id: string;
  state: "requested" | "running" | "completed" | "failed";
  evidence_digest: string | null;
  clinical_claim: false;
}

export interface Receipt {
  operation_id: string;
  resource_id: string | null;
  revision: string;
  state: "committed" | "pending" | "unknown" | "rejected";
  audit_ref: string;
}

export interface ScenarioCreate {
  artifact_digest: string;
  locale: Locale;
  fixture_mode: Fixture;
  business_clock_at: string;
}

export interface ReplayCreate {
  scenario_id: string;
  input_manifest_digest: string;
  recorded_outputs_digest: string;
  bundle_digest: string;
}

export type Command =
  | { type: "create"; body: ScenarioCreate }
  | { type: "stop"; scenario: Scenario }
  | { type: "replay"; body: ReplayCreate };

export type Result =
  | { type: "scenario"; receipt: Receipt }
  | { type: "evaluation"; evaluation: Evaluation };

const scenarioPath = "/v1/training/scenarios";
const replayPath = "/v1/evaluation/replays";
export const uuidPattern =
  "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
export const digestPattern = "[0-9a-f]{64}";
const uuid = new RegExp(`^${uuidPattern}$`);

interface Views {
  ScenarioView: Scenario;
  EvaluationView: Evaluation;
}

function checkEvaluation(evaluation: Evaluation): Evaluation {
  if (evaluation.state === "completed" && evaluation.evidence_digest === null)
    throw new RequestFailure("invalid");
  return evaluation;
}

async function read<K extends keyof Views>(
  path: string,
  id: string,
  contract: K,
  signal: AbortSignal,
) {
  if (!uuid.test(id)) throw new RequestFailure("invalid");
  const value = parseContract(
    contract,
    await request("", `${path}/${id}`, signal),
  ) as Views[K];
  if (value.id !== id) throw new RequestFailure("invalid");
  return value;
}

export function readScenario(id: string, signal: AbortSignal) {
  return read(scenarioPath, id, "ScenarioView", signal);
}

export async function readEvaluation(id: string, signal: AbortSignal) {
  return checkEvaluation(await read(replayPath, id, "EvaluationView", signal));
}

export async function execute(
  command: Command,
  key: string,
  signal: AbortSignal,
  onDispatch: () => void,
): Promise<Result> {
  const path =
    command.type === "stop"
      ? `${scenarioPath}/${command.scenario.id}/stop`
      : command.type === "create"
        ? scenarioPath
        : replayPath;
  const body =
    command.type === "stop"
      ? { expected_revision: command.scenario.revision }
      : command.body;
  validateContract(
    command.type === "stop"
      ? "RevisionCommand"
      : command.type === "create"
        ? "ScenarioCreate"
        : "ReplayCreate",
    body,
  );
  const token = await csrf("", signal);
  onDispatch();
  const raw = await request("", path, signal, { body, key, csrf: token });
  if (command.type === "replay")
    return {
      type: "evaluation",
      evaluation: checkEvaluation(
        parseContract("EvaluationView", raw) as Evaluation,
      ),
    };
  const receipt = parseContract("CommandResult", raw) as Receipt;
  if (
    receipt.operation_id !== key ||
    (receipt.state === "committed" &&
      (!receipt.resource_id ||
        (command.type === "stop" &&
          receipt.resource_id !== command.scenario.id)))
  )
    throw new RequestFailure("invalid");
  return { type: "scenario", receipt };
}
