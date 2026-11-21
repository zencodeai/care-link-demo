import type { Page } from "@playwright/test";
export const ids = {
  account: "10000000-0000-4000-8000-000000000001",
  backup: "20000000-0000-4000-8000-000000000001",
  target: "30000000-0000-4000-8000-000000000001",
  proposal: "40000000-0000-4000-8000-000000000001",
  approval: "50000000-0000-4000-8000-000000000001",
  ceremony: "60000000-0000-4000-8000-000000000001",
  journal: "70000000-0000-4000-8000-000000000001",
};
export const binding = {
  target_id: ids.target,
  backup_digest: "a".repeat(64),
  schema_digest: "b".repeat(64),
  artifact_digest: "c".repeat(64),
  journal_id: ids.journal,
  journal_generation: "1",
  head_digest: "d".repeat(64),
  restriction_barrier: "9",
  validation_digest: "e".repeat(64),
  serving_generation: "2",
};
export const exactDigest =
  "86c4d72f04a78cf9c07ca0be739090fee812faf4b5d8e09654067e63cf4dd69c";
export const backup = {
  id: ids.backup,
  manifest_digest: binding.backup_digest,
  capture_at: "2026-11-21T12:00:00Z",
  expires_at: "2099-11-28T12:00:00Z",
  schema_version: "v12",
  journal_barrier: "4",
  audit_digest: "f".repeat(64),
  state: "verified",
};
export const target = {
  id: ids.target,
  revision: "5",
  backup_id: ids.backup,
  state: "validated",
  head: {
    journal_id: ids.journal,
    generation: "1",
    tip: "12",
    tip_digest: binding.head_digest,
    restriction_barrier: "9",
    signature: "signed-fixture-only",
    observed_at: "2026-11-21T13:00:00Z",
  },
  validation_digest: binding.validation_digest,
  serving_generation: "2",
};
export class RecoveryFixture {
  role = "operator";
  signedOut = false;
  proposalState = "proposed";
  expired = false;
  malformed = false;
  mismatch = false;
  reject = false;
  lost = false;
  ackState = "committed";
  commands: { path: string; body: unknown; key: string | null }[] = [];
  reply(
    path: string,
    method: string,
    body: unknown,
    key: string | null,
  ): { body: unknown; status: number } {
    const ok = (value: unknown, status = 200) => ({ body: value, status });
    if (path === "/v1/auth/session")
      return this.signedOut
        ? ok({}, 401)
        : ok({
            account_id: ids.account,
            role: this.role,
            assurance: "AL2",
            revision: "1",
            expires_at: "2099-11-21T12:00:00Z",
            auth_time: "2026-11-21T12:00:00Z",
          });
    if (path === "/v1/auth/csrf") return ok({ csrf_token: "z".repeat(48) });
    if (method === "POST") {
      this.commands.push({ path, body, key });
      if (this.reject) return ok({}, 409);
      if (this.lost) {
        this.lost = false;
        return ok({}, 503);
      }
    }
    if (
      path === "/v1/recovery/backups" ||
      path === `/v1/recovery/backups/${ids.backup}`
    )
      return ok(backup);
    if (
      path === "/v1/recovery/targets" ||
      path === `/v1/recovery/targets/${ids.target}` ||
      path.endsWith("/validate")
    )
      return ok(target);
    if (path.endsWith("/evidence"))
      return ok(
        this.malformed ? { ...binding, bearer_token: "forbidden" } : binding,
      );
    if (path === `/v1/recovery/promotions/${ids.proposal}`)
      return ok({
        id: ids.proposal,
        revision: "1",
        target_id: ids.target,
        binding_digest: this.mismatch ? "0".repeat(64) : exactDigest,
        state: this.proposalState,
        approval_id: this.proposalState === "approved" ? ids.approval : null,
        expires_at:
          this.proposalState === "approved"
            ? this.expired
              ? "2020-01-01T00:00:00Z"
              : "2099-11-21T12:00:00Z"
            : null,
      });
    if (path.startsWith("/v1/recovery/promotions/"))
      return ok({
        operation_id: ids.approval,
        state: this.ackState,
        resource_id: ids.proposal,
        revision: "1",
        audit_ref: ids.journal,
      });
    return ok({}, 404);
  }
}
export async function installFixture(
  page: Page,
  configure?: (fixture: RecoveryFixture) => void,
) {
  const fixture = new RecoveryFixture();
  configure?.(fixture);
  await page.route("**/v1/**", (route) => {
    const request = route.request();
    const value = fixture.reply(
      new URL(request.url()).pathname,
      request.method(),
      request.method() === "POST" ? request.postDataJSON() : null,
      request.headers()["idempotency-key"] ?? null,
    );
    return route.fulfill({
      status: value.status,
      contentType: "application/json",
      body: JSON.stringify(value.body),
    });
  });
  return fixture;
}
