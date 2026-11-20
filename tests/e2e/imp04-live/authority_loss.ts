import { expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { BarrierBridge, type BarrierRequest } from "./barrier_bridge";
import { type Actors, type Observations } from "./cases";
import { evidenceDirectory, privateFile, row, text, type Row } from "./config";
import { createRaceScope } from "./race_scope";
import { AuthorityBridge } from "./authority_bridge";

function uuid(value: string): string {
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
      value,
    )
  )
    throw new Error("Canonical actual authority-case identifier required");
  return value;
}
function hostCase(args: string[]): Row {
  try {
    const result = execFileSync(
      resolve(".venv/bin/python"),
      ["-m", "tools.imp04_deployment.authority_case", ...args],
      { encoding: "utf8", timeout: 30_000, stdio: ["ignore", "pipe", "pipe"] },
    );
    const value = row(JSON.parse(result) as unknown);
    if (value.target !== "care-link-imp04-002")
      throw new Error("Wrong authority-case target");
    return value;
  } catch {
    throw new Error(
      "Fixed new-case authority operation failed; private details suppressed",
    );
  }
}
function errorKey(value: unknown): string | null {
  if (!value || typeof value !== "object" || !("message_key" in value))
    return null;
  return typeof value.message_key === "string" &&
    /^(manual|identity)\.[a-z_]+$/.test(value.message_key)
    ? value.message_key
    : null;
}

/** Journalled grantor principal loss, using only a fresh separately issued case actor. */
export async function authorityLoss(
  actors: Actors,
  observations: Observations,
): Promise<Row> {
  const pid = actors.pid,
    grantor = actors.carer,
    recipient = actors.worker2;
  const state = await createRaceScope(pid, observations, "A03-authority-loss");
  const admitted = hostCase(["admit", "--subject", uuid(state.subject)]);
  expect(admitted.account_id).toBe(grantor.issued.accountId);
  expect(admitted.subject_id).toBe(state.subject);
  const delegationId = uuid(text(admitted, "delegation_id"));
  const delegationExpiresAt = text(admitted, "expires_at");
  expect(Date.parse(delegationExpiresAt)).toBeGreaterThan(Date.now());
  const current = await pid.ok(`/v1/sessions/${uuid(state.session)}`);
  const grant = await grantor.ok("/v1/consents", {
    subject_id: uuid(state.subject),
    session_id: uuid(state.session),
    expected_revision: current.revision,
    purpose: "plan",
    recipient: {
      kind: "account",
      account_id: uuid(recipient.issued.accountId),
    },
    fields: ["plan.strategies"],
    basis: "explicit_demo_delegation",
    authority_proof_id: delegationId,
    effective_at: new Date(Date.now() - 1000).toISOString(),
    expires_at: new Date(Date.now() + 240_000).toISOString(),
  });
  const grantId = uuid(text(grant, "id"));
  const grantExpiresAt = text(grant, "expires_at");
  await recipient.ensureMain();
  const path = `/v1/plans/${uuid(state.plan)}`;
  const permitted = await recipient.ok(path);
  if (!Array.isArray(permitted.fields))
    throw new Error("Missing actual delegated projection");
  expect(
    new Set(permitted.fields.map((field) => text(row(field), "field"))),
  ).toEqual(new Set(["plan.strategies"]));
  const operatorState = resolve(evidenceDirectory(), "sessions/operator.json");
  privateFile(operatorState);
  // Open the inspected control channel and warm application traffic BEFORE
  // minting the short-lived, signed current-operator restriction proof.
  const bridge = await BarrierBridge.open();
  let authority: AuthorityBridge | undefined;
  let proof: Row = {},
    restriction: Row = {},
    ready: Row = {},
    finished: Row = {};
  let nonce = "",
    entered = false;
  let proofObservedAt: string | null = null,
    restrictionInvokedAt: string | null = null,
    restrictionReturnedAt: string | null = null;
  try {
    authority = await AuthorityBridge.open(grantor.issued.accountId);
    proof = hostCase(["proof", "--operator-state", operatorState]);
    proofObservedAt = new Date().toISOString();
    expect(proof.account_id).toBe(grantor.issued.accountId);
    uuid(text(proof, "operation_id"));
    nonce = uuid(text(proof, "nonce"));
    const proofExpiresAt = text(proof, "proof_expires_at");
    expect(Date.parse(proofExpiresAt)).toBeGreaterThan(Date.now());
    const control = (action: BarrierRequest["action"]) =>
      bridge.request({
        action,
        phase: "before_policy",
        operation: "plan_read",
        actor: uuid(recipient.issued.accountId),
        nonce,
      });
    await control("arm");
    const sent = recipient.page.waitForRequest(
      (request) =>
        request.url() === recipient.config.mainOrigin + path &&
        request.method() === "GET",
    );
    const pending = recipient.api(path);
    await sent;
    try {
      ready = await control("wait");
      entered = true;
      restrictionInvokedAt = new Date().toISOString();
      restriction = await authority.restrict();
      restrictionReturnedAt = new Date().toISOString();
      expect(restriction.account_id).toBe(grantor.issued.accountId);
      expect(restriction.principal_revoked).toBe(true);
      expect(restriction.state).toBe("committed");
      expect(restriction.operation_id).toBe(proof.operation_id);
      expect(restriction.authority_loss).toBe(
        "journalled_business_principal_revocation",
      );
    } finally {
      if (entered) await control("release");
    }
    const result = await pending;
    finished = await control("finished");
    observations.push({
      case: "A03-grantor-authority-loss-timing",
      status: "observed",
      principal_id: grantor.issued.accountId,
      subject_id: state.subject,
      plan_id: state.plan,
      grant_id: grantId,
      delegation_id: delegationId,
      proof_operation_id: proof.operation_id,
      proof_nonce: nonce,
      proof_expires_at: proofExpiresAt,
      proof_observed_at: proofObservedAt,
      restriction_invoked_at: restrictionInvokedAt,
      restriction_returned_at: restrictionReturnedAt,
      ready,
      finished,
      restriction,
      pending_status: result.status,
      pending_message_key: errorKey(result.value),
    });
    expect(
      Date.parse(text(finished, "released_at")) -
        Date.parse(text(finished, "entered_at")),
    ).toBeLessThan(800);
    expect(
      [403, 404, 409],
      "Pending disclosure denies current grantor principal loss",
    ).toContain(result.status);
    const denied = row(result.value);
    expect(denied.fields === undefined && denied.items === undefined).toBe(
      true,
    );
    const later = await recipient.api(path);
    expect(
      [403, 404],
      "Later disclosure cannot retain revoked grantor authority",
    ).toContain(later.status);
    expect(
      row(later.value).fields === undefined &&
        row(later.value).items === undefined,
    ).toBe(true);
    expect(Date.now()).toBeLessThan(Date.parse(delegationExpiresAt));
    expect(Date.now()).toBeLessThan(Date.parse(grantExpiresAt));
    const retainedGrant = await pid.ok(`/v1/consents/${grantId}`);
    expect(retainedGrant.grantor_id).toBe(grantor.issued.accountId);
    expect(retainedGrant.revoked_at).toBeNull();
    expect(retainedGrant.expires_at).toBe(grantExpiresAt);
    const record = {
      case: "A03-grantor-authority-loss",
      status: "passed",
      authority_loss: "journalled_business_principal_revocation",
      literal_provider_role_changed: false,
      new_case_principal_id: grantor.issued.accountId,
      session_id: state.session,
      subject_id: state.subject,
      plan_id: state.plan,
      grant_id: grantId,
      grant_expires_at: grantExpiresAt,
      delegation_id: delegationId,
      delegation_expires_at: delegationExpiresAt,
      proof_operation_id: proof.operation_id,
      proof_nonce: nonce,
      restriction,
      ready,
      finished,
      pending_status: result.status,
      later_disclosure_status: later.status,
      zero_forbidden_projection: true,
      grant_and_delegation_otherwise_unexpired: true,
      grant_itself_not_revoked: true,
      old_actors_and_restrictions_untouched: true,
      clock_or_deadline_change: false,
    };
    observations.push(record);
    writeFileSync(
      resolve(evidenceDirectory(), "authority-loss-state.json"),
      JSON.stringify(record, null, 2),
      { mode: 0o600 },
    );
    return record;
  } catch (error) {
    observations.push({
      case: "A03-grantor-authority-loss-failure",
      status: "failed",
      principal_id: grantor.issued.accountId,
      subject_id: state.subject,
      plan_id: state.plan,
      grant_id: grantId,
      delegation_id: delegationId,
      proof_operation_id: proof.operation_id ?? null,
      proof_nonce: nonce || null,
      proof_expires_at: proof.proof_expires_at ?? null,
      proof_observed_at: proofObservedAt,
      restriction_invoked_at: restrictionInvokedAt,
      restriction_returned_at: restrictionReturnedAt,
      ready,
      finished,
      restriction,
      category:
        error instanceof Error && error.message.startsWith("Fixed new-case")
          ? "fixed_case_control_failed"
          : "strict_authority_loss_expectation_failed",
    });
    throw error;
  } finally {
    await authority?.close();
    await bridge.close();
  }
}
