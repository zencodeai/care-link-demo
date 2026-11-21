import type { Page } from "@playwright/test";
export const ids = {
  account: "10000000-0000-4000-8000-000000000001",
  activation: "20000000-0000-4000-8000-000000000001",
  grant: "30000000-0000-4000-8000-000000000001",
  export: "40000000-0000-4000-8000-000000000001",
  incident: "50000000-0000-4000-8000-000000000001",
  event: "60000000-0000-4000-8000-000000000001",
};
export const digest = "a".repeat(64),
  evidence = "b".repeat(64);
export type Role = "operator" | "security" | "governance" | "auditor";
const at = "2026-11-21T12:00:00Z",
  future = "2099-11-21T12:00:00Z";
export async function installFixture(
  page: Page,
  options: {
    role?: Role;
    lostCommit?: boolean;
    malformedMetrics?: boolean;
    suppressed?: boolean;
    exportPages?: boolean;
  } = {},
) {
  const commands: {
    path: string;
    body: Record<string, unknown>;
    key: string | undefined;
  }[] = [];
  let signedOut = false,
    lostCommit = options.lostCommit ?? false,
    state = "ready",
    role = options.role ?? "operator";
  await page.route("**/v1/**", async (route) => {
    const request = route.request(),
      path = new URL(request.url()).pathname;
    const fulfill = (value: unknown, status = 200) =>
      route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(value),
      });
    if (path === "/v1/auth/session")
      return signedOut
        ? fulfill({}, 401)
        : fulfill({
            account_id: ids.account,
            role,
            assurance: "AL2",
            revision: "1",
            expires_at: future,
            auth_time: at,
          });
    if (path === "/v1/auth/csrf")
      return fulfill({ csrf_token: "a".repeat(48) });
    if (request.method() === "POST")
      commands.push({
        path,
        body: request.postDataJSON() as Record<string, unknown>,
        key: request.headers()["idempotency-key"],
      });
    if (path === "/v1/operations/health")
      return fulfill({
        capability: "manual",
        ready: true,
        reasons: [],
        epoch: "7",
        serving_generation: "3",
      });
    if (path === `/v1/artifacts/${digest}/review-context`)
      return fulfill({
        artifact: {
          digest,
          kind: "policy",
          version: "v1",
          state: "review_pending",
        },
        source_revision: "abcdef123456",
        change_class: "C2",
        governed_domains: ["policy"],
        changed_paths: ["config/demo/imp08/policy.json"],
        required_authorities: ["technical", "security"],
        missing_authorities: ["technical", "security"],
        evidence_digests: [evidence],
        previous_digest: "c".repeat(64),
        payload_digest: "d".repeat(64),
      });
    if (path === `/v1/activations/${ids.activation}/commit`) {
      state = "active";
      if (lostCommit) {
        lostCommit = false;
        return route.abort("failed");
      }
    }
    if (path.startsWith("/v1/activations/"))
      return fulfill({
        id: ids.activation,
        epoch: "8",
        bundle_digest: digest,
        state,
        missing_instances: [],
        revision: "2",
      });
    if (path === "/v1/metrics/query") {
      const count = { numerator: 20, denominator: 35, unknown: 4 };
      return fulfill(
        options.malformedMetrics
          ? { definition_version: "v1", police_avoidance: count }
          : options.suppressed
            ? {
                definition_version: "v1",
                cohort_size: null,
                suppressed: true,
                safety: null,
                access: null,
                equity: null,
                police_avoidance: null,
                exposure_aggregate: null,
              }
            : {
                definition_version: "v1",
                cohort_size: 35,
                suppressed: false,
                safety: count,
                access: count,
                equity: count,
                police_avoidance: count,
                exposure_aggregate: null,
              },
      );
    }
    if (options.exportPages && path === `/v1/audit/exports/${ids.export}`) {
      const next =
        new URL(request.url()).searchParams.get("cursor") === "export-page-2";
      return fulfill({
        items: [
          {
            id: ids.event,
            sequence: next ? "2" : "1",
            operation_id: ids.event,
            action: next ? "artifact_review" : "artifact_register",
            decision: "PERMIT",
            input_digest: digest,
            output_digest: digest,
            previous_hash: "0".repeat(64),
            hash: digest,
            created_at: at,
          },
        ],
        next_cursor: next ? null : "export-page-2",
      });
    }
    if (path === "/v1/audit/search")
      return fulfill({
        items: [
          {
            id: ids.event,
            sequence: "1",
            operation_id: ids.event,
            action: "artifact_register",
            decision: "PERMIT",
            input_digest: digest,
            output_digest: digest,
            previous_hash: "0".repeat(64),
            hash: digest,
            created_at: at,
          },
        ],
        next_cursor: null,
      });
    if (path === "/v1/artifacts/reviews")
      return fulfill({
        operation_id: ids.event,
        state: "committed",
        resource_id: ids.grant,
        revision: "1",
        audit_ref: ids.event,
      });
    return fulfill({}, 404);
  });
  return {
    commands,
    signOut: () => {
      signedOut = true;
    },
    switchRole: (value: Role) => {
      role = value;
    },
  };
}
