import type { Page } from "@playwright/test";

export const fixture = {
  account: "10000000-0000-4000-8000-000000000001",
  trainerReplacement: "10000000-0000-4000-8000-000000000002",
  scenario: "20000000-0000-4000-8000-000000000001",
  evaluation: "30000000-0000-4000-8000-000000000001",
  audit: "40000000-0000-4000-8000-000000000001",
  artifact: "a".repeat(64),
  manifest: "b".repeat(64),
  recorded: "c".repeat(64),
  bundle: "d".repeat(64),
  evidence: "e".repeat(64),
  clock: "2026-11-23T12:00:00Z",
};

interface Mutation {
  path: string;
  key: string;
  csrf: string;
  body: unknown;
}

export async function installFixture(page: Page, role = "trainer") {
  const state = {
    role,
    account: fixture.account,
    assurance: "AL2",
    scenario: "created",
    evaluation: "completed",
    signedOut: false,
    lostMutation: false,
    malformedRead: false,
    mutations: [] as Mutation[],
    reads: [] as string[],
  };
  await page.route("**/v1/**", async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    const json = (value: unknown, status = 200) =>
      route.fulfill({ json: value, status });
    const key = req.headers()["idempotency-key"] ?? "";
    const csrf = req.headers()["x-csrf-token"] ?? "";
    const stopping = path === `/v1/training/scenarios/${fixture.scenario}/stop`;
    if (path === "/v1/auth/session") {
      if (state.signedOut) return json({}, 401);
      return json({
        account_id: state.account,
        role: state.role,
        assurance: state.assurance,
        auth_time: "2026-11-23T12:00:00Z",
        expires_at: "2099-11-23T12:00:00Z",
        revision: "1",
      });
    }
    if (path === "/v1/auth/csrf") return json({ csrf_token: "s".repeat(48) });
    if (req.method() === "POST") {
      state.mutations.push({ path, key, csrf, body: req.postDataJSON() });
      if (state.lostMutation) {
        state.lostMutation = false;
        return json({}, 503);
      }
      if (path === "/v1/training/scenarios" || stopping) {
        if (stopping) state.scenario = "stopped";
        return json({
          operation_id: key,
          resource_id: fixture.scenario,
          revision: stopping ? "2" : "1",
          state: "committed",
          audit_ref: fixture.audit,
        });
      }
    } else {
      state.reads.push(path);
    }
    if (path === `/v1/training/scenarios/${fixture.scenario}`)
      return json({
        id: state.malformedRead ? fixture.evaluation : fixture.scenario,
        state: state.scenario,
        artifact_digest: fixture.artifact,
        evidence_digest: null,
        revision: state.scenario === "stopped" ? "2" : "1",
      });
    if (
      (path === "/v1/evaluation/replays" && req.method() === "POST") ||
      path === `/v1/evaluation/replays/${fixture.evaluation}`
    )
      return json({
        id: fixture.evaluation,
        state: state.evaluation,
        evidence_digest:
          state.evaluation === "completed" ? fixture.evidence : null,
        clinical_claim: false,
      });
    return json({}, 404);
  });
  return state;
}
