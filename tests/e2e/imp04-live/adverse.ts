import { expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { type Actor, type Result } from "./browser";
import { BarrierBridge, type BarrierRequest } from "./barrier_bridge";
import {
  instantNanos,
  type Actors,
  type Observations,
  type PlanState,
} from "./cases";
import { evidenceDirectory, privateFile, row, text, type Row } from "./config";
import { createRaceScope } from "./race_scope";

function uuid(value: string): string {
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
      value,
    )
  )
    throw new Error("Canonical issued qualification identifier required");
  return value;
}
function control(module: "fault", args: string[]): Row {
  try {
    const output = execFileSync(
      resolve(".venv/bin/python"),
      ["-m", `tools.imp04_deployment.${module}`, ...args],
      { encoding: "utf8", timeout: 15_000, stdio: ["ignore", "pipe", "pipe"] },
    );
    return row(JSON.parse(output) as unknown);
  } catch {
    throw new Error(
      `Receipt-bound new-target ${module} control failed; private details suppressed`,
    );
  }
}
function noProjection(result: Result): void {
  if (result.value === null) return;
  const value = row(result.value);
  expect(
    value.fields === undefined && value.items === undefined,
    "Rejected response contains no plan/report projection",
  ).toBe(true);
}
async function fresh(actor: Actor): Promise<void> {
  const current = await actor.current();
  const age = Date.now() - Date.parse(text(current, "auth_time"));
  if (!Number.isFinite(age) || age >= 210_000) await actor.signIn(false);
}
async function selfGrant(
  pid: Actor,
  recipient: Actor,
  state: PlanState,
  proof: string,
  selected: string[],
): Promise<Row> {
  const current = await pid.ok(`/v1/sessions/${uuid(state.session)}`);
  return pid.ok("/v1/consents", {
    subject_id: uuid(state.subject),
    session_id: uuid(state.session),
    expected_revision: current.revision,
    purpose: "plan",
    recipient: {
      kind: "account",
      account_id: uuid(recipient.issued.accountId),
    },
    fields: selected,
    basis: "self",
    authority_proof_id: uuid(proof),
    effective_at: new Date(Date.now() - 1000).toISOString(),
    expires_at: new Date(Date.now() + 240_000).toISOString(),
  });
}

export async function dependencies(
  actors: Actors,
  observations: Observations,
  state: PlanState,
): Promise<void> {
  const pid = actors.pid;
  await fresh(pid);
  await pid.ensureMain();
  const path = `/v1/plans/${uuid(state.plan)}`;
  await pid.ok(path);
  for (const role of ["identity", "pdp", "journal"] as const) {
    let paused = false;
    let pause: Row,
      resume: Row = {},
      result: Result;
    try {
      // The freezer transition may occur before its acknowledgement is lost.
      // Record recovery intent before the call, not after the acknowledgement.
      paused = true;
      pause = control("fault", ["--role", role, "--action", "pause"]);
      expect(pause.target).toBe("care-link-imp04-002");
      expect(pause.role).toBe(role);
      expect(pause.action).toBe("pause");
      expect(pause.container_identity_verified).toBe(true);
      expect(pause.paused_observed).toBe(true);
      result = await pid.api(path);
      expect(
        result.status,
        `Actual paused ${role} must not permit plan disclosure`,
      ).not.toBe(200);
      noProjection(result);
    } finally {
      if (paused) {
        resume = control("fault", ["--role", role, "--action", "resume"]);
        expect(resume.target).toBe("care-link-imp04-002");
        expect(resume.action).toBe("resume");
      }
    }
    await expect
      .poll(async () => (await pid.api(path)).status, {
        timeout: 30_000,
        intervals: [250, 500, 1000],
        message: `Current ${role} recovery restores ordinarily authorized own-plan read`,
      })
      .toBe(200);
    const restored = await pid.ok(path);
    expect(restored.id).toBe(state.plan);
    observations.push({
      case: "A08",
      status: "passed",
      role,
      pause,
      resume,
      during_fault_status: result.status,
      forbidden_projection_absent: true,
      ordinary_current_read_restored: true,
      accepted_target_touched: false,
    });
  }
}

export async function absentGrantRace(
  actors: Actors,
  observations: Observations,
): Promise<Row> {
  const pid = actors.pid,
    recipient = actors.worker2;
  const state = await createRaceScope(pid, observations, "A04");
  const proof = state.proof;
  const oldGrant = await selfGrant(pid, recipient, state, proof, [
    "plan.strategies",
  ]);
  const current = await pid.ok(`/v1/sessions/${uuid(state.session)}`);
  const pendingKey = randomUUID(),
    nonce = randomUUID();
  const body: Row = {
    subject_id: state.subject,
    session_id: state.session,
    expected_revision: current.revision,
    purpose: "plan",
    recipient: { kind: "account", account_id: recipient.issued.accountId },
    fields: ["plan.strategies", "plan.medication_report"],
    basis: "self",
    authority_proof_id: proof,
    effective_at: new Date(Date.now() - 1000).toISOString(),
    expires_at: new Date(Date.now() + 240_000).toISOString(),
  };
  await pid.ensureMain();
  await recipient.ensureMain();
  const prior = await recipient.ok(`/v1/plans/${uuid(state.plan)}`);
  if (!Array.isArray(prior.fields))
    throw new Error("Missing prior real projection");
  expect(
    new Set(prior.fields.map((field) => text(row(field), "field"))),
  ).toEqual(new Set(["plan.strategies"]));
  writeFileSync(
    resolve(evidenceDirectory(), "absent-race-command.json"),
    JSON.stringify(
      { state, old_grant: oldGrant, pending_key: pendingKey, request: body },
      null,
      2,
    ),
    { mode: 0o600 },
  );
  const revokeKey = randomUUID();
  const preparedCsrf = await pid.page.evaluate(
    async ({ path, revision, key }) => {
      const memory = window as unknown as {
        imp04AbsentRevoke?: {
          path: string;
          revision: unknown;
          key: string;
          csrf: string;
        };
      };
      delete memory.imp04AbsentRevoke;
      const response = await fetch("/v1/auth/csrf", {
        cache: "no-store",
        credentials: "same-origin",
        signal: AbortSignal.timeout(15000),
      });
      if (!response.ok) return response.status;
      const value = (await response.json()) as { csrf_token?: unknown };
      if (typeof value.csrf_token !== "string")
        throw new Error("Actual pre-held CSRF required");
      memory.imp04AbsentRevoke = {
        path,
        revision,
        key,
        csrf: value.csrf_token,
      };
      return response.status;
    },
    {
      path: `/v1/consents/${text(oldGrant, "id")}/revoke`,
      revision: oldGrant.revision,
      key: revokeKey,
    },
  );
  expect(preparedCsrf).toBe(200);
  const bridge = await BarrierBridge.open();
  const controlBarrier = async (
    action: BarrierRequest["action"],
  ): Promise<Row> => {
    try {
      return await bridge.request({
        action,
        phase: "before_policy",
        operation: "consent_grant",
        actor: pid.issued.accountId,
        nonce,
      });
    } catch (error) {
      observations.push({
        case: "A04-control-failure",
        status: "failed",
        action,
        nonce,
        category:
          error instanceof Error &&
          error.message.startsWith("Receipt-bound barrier operation failed;")
            ? error.message
            : "bridge_control_unavailable",
      });
      throw error;
    }
  };
  try {
    await controlBarrier("arm");
    const sent = pid.page.waitForRequest(
      (request) =>
        request.url() === pid.config.mainOrigin + "/v1/consents" &&
        request.method() === "POST",
    );
    const pending = pid.api("/v1/consents", body, pendingKey);
    await sent;
    const revokeInvokedAt = new Date().toISOString();
    const revokeRequest = pid.page.evaluate(async () => {
      const memory = window as unknown as {
        imp04AbsentRevoke?: {
          path: string;
          revision: unknown;
          key: string;
          csrf: string;
        };
      };
      const command = memory.imp04AbsentRevoke;
      delete memory.imp04AbsentRevoke;
      if (!command) throw new Error("Missing actual prepared revoke command");
      const requestStartedAt = new Date().toISOString();
      const response = await fetch(command.path, {
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": command.csrf,
          "Idempotency-Key": command.key,
        },
        body: JSON.stringify({ expected_revision: command.revision }),
        signal: AbortSignal.timeout(15000),
      });
      return {
        status: response.status,
        value: (await response.json()) as unknown,
        request_started_at: requestStartedAt,
        response_observed_at: new Date().toISOString(),
      };
    });
    let ready: Row = {};
    let revokeResult: Row = {};
    let revokeTiming: Row = {};
    let entered = false;
    try {
      const [entry, revoked] = await Promise.all([
        controlBarrier("wait").then((value) => {
          ready = value;
          entered = true;
          return value;
        }),
        revokeRequest,
      ]);
      ready = entry;
      expect(
        ready.operation_id,
        "Barrier belongs to the exact pending grant command",
      ).toBe(pendingKey);
      expect(
        revoked.status,
        "Genuine same-cookie revoke succeeds during absent-grant hold",
      ).toBe(200);
      revokeResult = row(revoked.value);
      revokeTiming = {
        request_started_at: revoked.request_started_at,
        response_observed_at: revoked.response_observed_at,
      };
    } finally {
      // A not-entered timeout is a failed harness attempt, never evidence that a
      // concurrent restriction succeeded. The app's one-shot marker self-expires.
      if (entered) await controlBarrier("release");
    }
    const result = await pending;
    const finished = await controlBarrier("finished");
    const errorKey =
      result.value &&
      typeof result.value === "object" &&
      "message_key" in result.value &&
      typeof result.value.message_key === "string" &&
      /^(manual|identity)\.[a-z_]+$/.test(result.value.message_key)
        ? result.value.message_key
        : null;
    const timing: Row = {
      case: "A04-timing",
      status: "observed",
      nonce,
      ready,
      finished,
      pending_status: result.status,
      pending_message_key: errorKey,
      genuine_csrf_prefetched_before_hold: true,
      revoke_invoked_at: revokeInvokedAt,
      revoke_timing: revokeTiming,
      coordination:
        "Native preflights overlap; recorded revocation follows hold entry and genuine HTTP200 commit acknowledgement precedes release",
    };
    observations.push(timing);
    const revokedGrant = await pid.ok(`/v1/consents/${text(oldGrant, "id")}`);
    const revokedAt = text(revokedGrant, "revoked_at");
    timing.revoked_at = revokedAt;
    expect(
      instantNanos(revokedAt),
      "Recorded revocation strictly follows hold entry",
    ).toBeGreaterThan(instantNanos(text(ready, "entered_at")));
    expect(
      instantNanos(revokedAt),
      "Recorded revocation precedes output release",
    ).toBeLessThan(instantNanos(text(finished, "released_at")));
    expect(
      instantNanos(text(revokeTiming, "response_observed_at")),
      "Actual HTTP200 acknowledges commit before release",
    ).toBeLessThan(instantNanos(text(finished, "released_at")));
    expect(
      Date.parse(text(finished, "released_at")) -
        Date.parse(text(finished, "entered_at")),
    ).toBeLessThan(800);
    expect(
      [403, 404, 409],
      "Stale missing-grant command must not create wider sharing",
    ).toContain(result.status);
    noProjection(result);
    const operation = await pid.api(`/v1/operations/${pendingKey}`);
    if (operation.status === 200)
      expect(
        row(operation.value).state,
        "No durable committed pending grant effect",
      ).not.toBe("committed");
    else expect(operation.status).toBe(404);
    const disclosure = await recipient.api(`/v1/plans/${uuid(state.plan)}`);
    expect(
      [403, 404],
      "Recipient has no rights from rejected absent-grant command",
    ).toContain(disclosure.status);
    noProjection(disclosure);
    const record = {
      case: "A04",
      status: "passed",
      nonce,
      ready,
      pending_operation_id: pendingKey,
      old_grant_id: oldGrant.id,
      revoke_result: revokeResult,
      finished,
      pending_status: result.status,
      operation_status_http: operation.status,
      operation_state:
        operation.status === 200 ? row(operation.value).state : "absent",
      recipient_disclosure_status: disclosure.status,
      new_grant_effect_count: "coordinator_read_only_DB_verification_required",
      original_expected_revision: body.expected_revision,
    };
    observations.push(record);
    return record;
  } finally {
    await bridge.close();
  }
}

function delegationInput(actor: Actor, state: PlanState): Row {
  const file =
    process.env.CARE_LINK_IMP04_E2E_DELEGATION ??
    resolve(dirname(dirname(actor.config.caFile)), "delegation.json");
  privateFile(file);
  const value = row(JSON.parse(readFileSync(file, "utf8")) as unknown);
  uuid(text(value, value.id ? "id" : "delegation_id"));
  if (
    value.subject_id !== state.subject ||
    value.grantor_id !== actor.issued.accountId ||
    JSON.stringify(value.fields) !== JSON.stringify(["plan.strategies"]) ||
    JSON.stringify(value.purposes) !== JSON.stringify(["plan"]) ||
    value.revoked_at !== null ||
    !Number.isFinite(Date.parse(text(value, "expires_at")))
  )
    throw new Error(
      "Exact independently admitted PID/carer/field/purpose/time delegation required",
    );
  return value;
}
export async function delegation(
  actors: Actors,
  observations: Observations,
  state: PlanState,
  expired: boolean,
): Promise<Row> {
  const carer = actors.carer,
    pid = actors.pid,
    recipient = actors.worker2;
  await fresh(carer);
  const authority = delegationInput(carer, state);
  const authorityId = text(authority, authority.id ? "id" : "delegation_id");
  const expiresAt = text(authority, "expires_at");
  if (expired) {
    if (Date.now() <= Date.parse(expiresAt))
      throw new Error(
        "Delegation expiry phase requires actual wall-clock expiry; no synthetic clock or premature pass",
      );
    const knownGrantId = uuid(text(authority, "grant_id"));
    const knownGrantExpiresAt = text(authority, "grant_expires_at");
    if (
      !Number.isFinite(Date.parse(knownGrantExpiresAt)) ||
      Date.parse(knownGrantExpiresAt) <= Date.parse(expiresAt) ||
      Date.now() >= Date.parse(knownGrantExpiresAt)
    )
      throw new Error(
        "Delegation expiry attribution requires the actual prior sharing grant still within its own interval",
      );
    const prior = await carer.ok(`/v1/consents/${knownGrantId}`);
    expect(
      prior.expires_at,
      "Actual retained grant interval matches the independently recorded issued grant",
    ).toBe(knownGrantExpiresAt);
    expect(prior.revoked_at, "Grant itself has not been revoked").toBeNull();
    expect(prior.grantor_id).toBe(carer.issued.accountId);
    const scope = row(prior.scope);
    expect(scope.subject_id).toBe(state.subject);
    expect(scope.purpose).toBe("plan");
    expect(scope.fields).toEqual(["plan.strategies"]);
    expect(scope.recipient_id).toBe(recipient.issued.accountId);
  } else if (Date.now() >= Date.parse(expiresAt))
    throw new Error("Admitted delegation expired before positive live check");
  const request = async (changes: Row = {}): Promise<Result> => {
    const current = await pid.ok(`/v1/sessions/${uuid(state.session)}`);
    return carer.api("/v1/consents", {
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
      authority_proof_id: uuid(authorityId),
      effective_at: new Date(Date.now() - 1000).toISOString(),
      // The positive sharing interval deliberately outlasts delegation by
      // five minutes. Later denial can therefore be attributed to delegation
      // expiry while the issued sharing grant is still naturally unexpired.
      expires_at: new Date(Date.parse(expiresAt) + 300_000).toISOString(),
      ...changes,
    });
  };
  if (expired) {
    const denied = await request();
    expect(
      [403, 404],
      "Natural delegation expiry denies later grant creation",
    ).toContain(denied.status);
    noProjection(denied);
    expect(
      Date.now(),
      "Prior grant must remain within its own interval during disclosure check",
    ).toBeLessThan(Date.parse(text(authority, "grant_expires_at")));
    const stoppedDisclosure = await recipient.api(
      `/v1/plans/${uuid(state.plan)}`,
    );
    expect(
      [403, 404],
      "Previously delegated sharing stops at natural delegation expiry",
    ).toContain(stoppedDisclosure.status);
    noProjection(stoppedDisclosure);
    const result = {
      case: "A05-expired",
      status: "passed",
      delegation_id: authorityId,
      expires_at: expiresAt,
      prior_grant_id: authority.grant_id,
      prior_grant_expires_at: authority.grant_expires_at,
      prior_grant_still_unexpired_and_unrevoked: true,
      observed_after: new Date().toISOString(),
      grant_status: denied.status,
      recipient_disclosure_status: stoppedDisclosure.status,
      clock_unchanged: true,
    };
    observations.push(result);
    return result;
  }
  for (const [name, changes] of [
    ["wider_fields", { fields: ["plan.strategies", "plan.medication_report"] }],
    ["wrong_purpose", { purpose: "follow_up" }],
    ["wrong_subject_binding", { subject_id: randomUUID() }],
  ] as const) {
    const result = await request(changes);
    expect([403, 404], `Explicit delegation must reject ${name}`).toContain(
      result.status,
    );
    noProjection(result);
    observations.push({
      case: "A05-scope",
      status: "passed",
      variant: name,
      delegation_id: authorityId,
      http_status: result.status,
    });
  }
  const result = await request();
  if (result.status !== 200)
    throw new Error(
      `Exact live delegation grant failed; status=${result.status}; body suppressed`,
    );
  const granted = row(result.value);
  const grantExpiresAt = text(granted, "expires_at");
  expect(
    Date.parse(grantExpiresAt),
    "Issued sharing interval outlasts independently provisioned delegation",
  ).toBeGreaterThan(Date.parse(expiresAt));
  const disclosed = await recipient.ok(`/v1/plans/${uuid(state.plan)}`);
  if (!Array.isArray(disclosed.fields))
    throw new Error("Missing delegated permitted projection");
  expect(
    new Set(disclosed.fields.map((field) => text(row(field), "field"))),
  ).toEqual(new Set(["plan.strategies"]));
  const record = {
    case: "A05",
    status: "passed",
    delegation_id: authorityId,
    grant_id: granted.id,
    grant_expires_at: grantExpiresAt,
    expires_at: expiresAt,
    grantor_id: carer.issued.accountId,
    recipient_id: recipient.issued.accountId,
    disclosed_fields: ["plan.strategies"],
    runtime_delegation_write_rights: "coordinator_DB_privilege_check_required",
  };
  observations.push(record);
  return record;
}
