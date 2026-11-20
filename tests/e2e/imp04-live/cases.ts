import AxeBuilder from "@axe-core/playwright";
import { expect, type Request, type Response } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  fieldLabels,
  stateLabels,
  textFor,
} from "../../../apps/web/src/plans/messages";
import { Actor } from "./browser";
import { BarrierBridge, type BarrierRequest } from "./barrier_bridge";
import { createRaceScope } from "./race_scope";
import { nativeZoom } from "./zoom";
import { evidenceDirectory, row, text, type Row, type Slot } from "./config";

export type Actors = Record<Slot, Actor>;
export type Observations = Row[];
export interface PlanState {
  session: string;
  subject: string;
  plan: string;
  proof: string;
  grant: string;
}
export function instantNanos(value: string): bigint {
  const match =
    /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})$/.exec(
      value,
    );
  if (!match?.[1] || !match[3])
    throw new Error("Exact timeline timestamp required");
  const whole = Date.parse(match[1] + match[3]);
  if (!Number.isFinite(whole))
    throw new Error("Valid timeline timestamp required");
  return BigInt(whole) * 1_000_000n + BigInt((match[2] ?? "").padEnd(9, "0"));
}
const workflowStages: { stage: string; at: string }[] = [];
function workflowProgress(stage: string): void {
  if (!/^[a-z][a-z0-9_]{0,63}$/.test(stage))
    throw new Error("Fixed workflow checkpoint stage required");
  const entry = { stage, at: new Date().toISOString() };
  workflowStages.push(entry);
  writeFileSync(
    resolve(evidenceDirectory(), "workflow-progress.json"),
    JSON.stringify({ ...entry, stages: workflowStages }, null, 2),
    { mode: 0o600 },
  );
}
function fields(plan: Row): Row[] {
  if (!Array.isArray(plan.fields)) throw new Error("Plan fields absent");
  return plan.fields.map(row);
}
function fieldKeys(plan: Row): string[] {
  return [...new Set(fields(plan).map((field) => text(field, "field")))].sort();
}
async function settleErrorReads(reads: Promise<void>[]): Promise<boolean> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      Promise.allSettled(reads).then(() => true),
      new Promise<boolean>((resolve) => {
        timer = setTimeout(() => resolve(false), 1500);
      }),
    ]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}
async function denied(actor: Actor, path: string, body?: Row): Promise<void> {
  const result = await actor.api(path, body);
  expect(
    [403, 404],
    `No authorization/content for ${actor.slot} ${path}`,
  ).toContain(result.status);
  const value = row(result.value);
  expect(
    value.fields === undefined && value.items === undefined,
    "Denied response contains no plan or report projection",
  ).toBe(true);
}
async function session(actor: Actor, kind = actor.issued.role): Promise<Row> {
  return actor.ok("/v1/sessions", {
    tags: { environment: "demo", population: "synthetic" },
    participant_kind: kind,
    jurisdiction: null,
    locale: "en-CA",
    channel: "web",
    persona_id: null,
    fixture_id: null,
  });
}
export async function loadVisiblePlan(
  actor: Actor,
  state: Pick<PlanState, "session" | "plan">,
): Promise<void> {
  workflowProgress("visible_plan_ensure_main_start");
  await actor.ensureMain(true);
  workflowProgress("visible_plan_ensure_main_complete");
  const workspace = actor.page.locator(
    'section[aria-labelledby="plans-title"]',
  );
  const check = workspace.getByRole("button", {
    name: textFor("en-CA").check,
    exact: true,
  });
  const loadSession = workspace.getByRole("button", {
    name: textFor("en-CA").loadSession,
    exact: true,
  });
  const loadPlan = workspace.getByRole("button", {
    name: textFor("en-CA").loadPlan,
    exact: true,
  });
  const network: Row[] = [];
  let stage = "check_current_access";
  const matchingResponse = (path: string) =>
    actor.page.waitForResponse(
      (response) =>
        response.url() === actor.config.mainOrigin + path &&
        response.request().method() === "GET",
    );
  const record = (response: Response): void => {
    const url = new URL(response.url());
    if (
      url.origin === actor.config.mainOrigin &&
      [
        "/v1/auth/session",
        `/v1/sessions/${state.session}`,
        `/v1/plans/${state.plan}`,
      ].includes(url.pathname)
    )
      network.push({ path: url.pathname, status: response.status() });
  };
  const requireOk = async (response: Response): Promise<void> => {
    if (response.status() === 200) return;
    let messageKey = "none",
      code = "none";
    try {
      const value = row((await response.json()) as unknown);
      if (
        typeof value.message_key === "string" &&
        /^(identity|manual)\.[a-z_]+$/.test(value.message_key)
      )
        messageKey = value.message_key;
      if (typeof value.code === "string" && /^[A-Z_]{1,64}$/.test(value.code))
        code = value.code;
    } catch {
      /* Private error body is never retained. */
    }
    throw new Error(
      `visible_load_http_${response.status()}_${code}_${messageKey}`,
    );
  };
  const idle = async (): Promise<void> => {
    await expect(
      check,
      "Visible channel has completed its actual request",
    ).toBeEnabled();
    await expect(
      workspace
        .locator(':scope > [role="status"], :scope > [role="alert"]')
        .first(),
    ).toHaveText(textFor("en-CA").ready);
  };
  actor.page.on("response", record);
  try {
    await expect(check).toBeEnabled();
    const checked = matchingResponse("/v1/auth/session");
    await check.click();
    await requireOk(await checked);
    await idle();
    stage = "load_conversation";
    await actor.page.locator("#plans-session").fill(state.session);
    await expect(loadSession).toBeEnabled();
    const loadedSession = matchingResponse(`/v1/sessions/${state.session}`);
    await loadSession.click();
    await requireOk(await loadedSession);
    await idle();
    await expect(
      workspace.getByText(state.session, { exact: true }),
    ).toBeVisible();
    stage = "load_plan";
    await actor.page.locator("#plans-id").fill(state.plan);
    await expect(loadPlan).toBeEnabled();
    const loadedPlan = matchingResponse(`/v1/plans/${state.plan}`);
    await loadPlan.click();
    await requireOk(await loadedPlan);
    await idle();
    await expect(
      workspace.getByText(state.plan, { exact: true }),
    ).toBeVisible();
  } catch (error) {
    const actualNotice = await workspace
      .locator(':scope > [role="status"], :scope > [role="alert"]')
      .first()
      .textContent()
      .catch(() => null);
    const known = [
      "ready",
      "pending",
      "committed",
      "rejected",
      "unavailable",
      "signed_out",
      "invalid",
      "operationUnknown",
    ] as const;
    const diagnostic = {
      stage,
      network: network.slice(-20),
      notice:
        known.find((name) => actualNotice === textFor("en-CA")[name]) ??
        "other_or_unavailable",
      check_disabled: await check.isDisabled().catch(() => null),
      load_session_disabled: await loadSession.isDisabled().catch(() => null),
      load_plan_disabled: await loadPlan.isDisabled().catch(() => null),
      error:
        error instanceof Error &&
        /^visible_load_http_[0-9]{3}_[A-Za-z_.]+$/.test(error.message)
          ? error.message
          : "visible_load_driver_or_projection_failure",
    };
    writeFileSync(
      resolve(evidenceDirectory(), "visible-load-diagnostic.json"),
      JSON.stringify(diagnostic, null, 2),
      { mode: 0o600 },
    );
    // eslint-disable-next-line preserve-caught-error -- Raw browser errors may contain private URLs; retain only the sanitized diagnostic.
    throw new Error(
      `Visible load failed; safe diagnostic=${JSON.stringify(diagnostic)}`,
    );
  } finally {
    actor.page.off("response", record);
  }
}
async function visibleGrant(
  pid: Actor,
  recipient: Actor,
  state: Pick<PlanState, "session" | "plan">,
  observations: Observations,
): Promise<{ grant: Row; proof: string }> {
  workflowProgress("visible_grant_load_start");
  await loadVisiblePlan(pid, state);
  workflowProgress("visible_grant_load_complete");
  const proof = await visibleAuthority(pid, observations);
  workflowProgress("visible_grant_authority_complete");
  await pid.page.locator("#share-recipient").fill(recipient.issued.accountId);
  await pid.page
    .getByLabel(fieldLabels["en-CA"]["plan.strategies"], { exact: true })
    .check();
  await pid.page
    .getByRole("button", { name: textFor("en-CA").preview, exact: true })
    .click();
  const sharing = pid.page.locator('section[aria-labelledby="sharing-title"]');
  await expect(
    sharing.getByText(recipient.issued.accountId, { exact: true }),
  ).toBeVisible();
  await expect(
    sharing.getByText(textFor("en-CA").purpose, { exact: true }),
  ).toBeVisible();
  const response = pid.page.waitForResponse(
    (r) =>
      r.url() === pid.config.mainOrigin + "/v1/consents" &&
      r.request().method() === "POST",
  );
  await sharing
    .getByRole("button", { name: textFor("en-CA").grant, exact: true })
    .click();
  const granted = await response;
  expect(granted.status(), "Visible exact sharing command succeeded").toBe(200);
  return { grant: row((await granted.json()) as unknown), proof };
}
async function visibleAuthority(
  pid: Actor,
  observations: Observations,
): Promise<string> {
  workflowProgress("visible_authority_draft_start");
  const draft = `Fictional unsent plan draft ${randomUUID()}.`;
  const textarea = pid.page.locator("#plan-words");
  await textarea.fill(draft);
  workflowProgress("visible_authority_draft_ready");
  let appendRequests = 0;
  const network: Row[] = [];
  const errorReads: Promise<void>[] = [];
  const observedSince = Date.now();
  const requestStarts = new Map<Request, number>();
  const businessPath =
    /^\/v1\/(?:sessions|plans)\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
  const eventTime = (): Row => ({
    observed_at: new Date().toISOString(),
    elapsed_ms: Date.now() - observedSince,
  });
  const allowed = new Set([
    "/v1/auth/session",
    "/v1/auth/step-up",
    "/v1/auth/step-up/proof",
    "/v1/auth/step-up/confirm",
    "/v1/auth/csrf",
  ]);
  const pathOf = (raw: string): string | null => {
    try {
      const url = new URL(raw);
      return url.origin === pid.config.mainOrigin &&
        (allowed.has(url.pathname) || businessPath.test(url.pathname))
        ? url.pathname
        : null;
    } catch {
      return null;
    }
  };
  const sent = (request: Request): void => {
    const target = new URL(request.url());
    if (
      target.origin === pid.config.mainOrigin &&
      request.method() === "POST" &&
      /^\/v1\/plans\/[0-9a-f-]+\/fields$/.test(target.pathname)
    )
      appendRequests += 1;
    const path = pathOf(request.url());
    if (path) {
      requestStarts.set(request, Date.now());
      network.push({
        event: "request",
        path,
        method: request.method(),
        ...eventTime(),
      });
    }
  };
  const reply = (response: Response): void => {
    const path = pathOf(response.url());
    if (!path) return;
    const began = requestStarts.get(response.request());
    requestStarts.delete(response.request());
    const entry: Row = {
      event: "response",
      path,
      status: response.status(),
      ...eventTime(),
      request_elapsed_ms: began === undefined ? null : Date.now() - began,
    };
    network.push(entry);
    if (response.status() >= 400)
      errorReads.push(
        (async () => {
          try {
            const value = row((await response.json()) as unknown);
            if (
              typeof value.message_key === "string" &&
              /^(identity|manual)\.[a-z_]+$/.test(value.message_key)
            )
              entry.message_key = value.message_key;
            if (
              typeof value.code === "string" &&
              /^[A-Z][A-Z0-9_]{0,63}$/.test(value.code)
            )
              entry.code = value.code;
          } catch {
            /* Only fixed-format error keys/codes can be retained; no body. */
          }
        })(),
      );
  };
  const failed = (request: Request): void => {
    const path = pathOf(request.url());
    if (path) {
      const began = requestStarts.get(request);
      requestStarts.delete(request);
      network.push({
        event: "requestfailed",
        path,
        ...eventTime(),
        request_elapsed_ms: began === undefined ? null : Date.now() - began,
      });
    }
  };
  let stage = "start_visible_ceremony";
  pid.page.on("request", sent);
  pid.page.on("response", reply);
  pid.page.on("requestfailed", failed);
  try {
    const popupPromise = pid.page
      .waitForEvent("popup", { timeout: 30_000 })
      .catch(() => null);
    const stepUpResponse = pid.page.waitForResponse(
      (response) =>
        response.url() === pid.config.mainOrigin + "/v1/auth/step-up" &&
        response.request().method() === "POST",
      { timeout: 30_000 },
    );
    workflowProgress("visible_authority_popup_start");
    await pid.page
      .getByRole("button", {
        name: textFor("en-CA").beginVerification,
        exact: true,
      })
      .click();
    const initiated = await stepUpResponse;
    expect(
      initiated.status(),
      "Actual subject-bound step-up initiation succeeds before provider driver",
    ).toBe(200);
    const issuedCeremony = row((await initiated.json()) as unknown);
    const hasProviderUrl =
      typeof issuedCeremony.authorization_url === "string" &&
      new URL(issuedCeremony.authorization_url).origin ===
        pid.config.oidcOrigin;
    observations.push({
      case: "Q04-ceremony-start",
      status: "observed",
      state: [
        "pending",
        "cooling_off",
        "confirmation_required",
        "verified",
        "expired",
      ].includes(String(issuedCeremony.state))
        ? issuedCeremony.state
        : "unknown",
      actual_provider_url_issued: hasProviderUrl,
    });
    expect(
      hasProviderUrl,
      "Server issued an actual provider navigation URL",
    ).toBe(true);
    workflowProgress("visible_authority_stepup_response");
    const popup = await popupPromise;
    if (!popup) throw new Error("visible_popup_unobserved");
    workflowProgress("visible_authority_popup_ready");
    stage = "provider_navigation";
    // The popup event can precede the parent's async step-up continuation.
    // Keep that real document active until it navigates its own popup.
    await pid.page.bringToFront();
    await popup.waitForURL((url) => url.origin === pid.config.oidcOrigin, {
      timeout: 10_000,
      waitUntil: "domcontentloaded",
    });
    workflowProgress("visible_authority_provider_navigation");
    await popup.bringToFront();
    stage = "provider_authentication";
    const verifier = new Actor(popup, pid.slot, pid.issued, pid.config);
    await verifier.providerLogin();
    workflowProgress("visible_authority_provider_complete");
    stage = "return_to_main_window";
    await pid.page.bringToFront();
    workflowProgress("visible_authority_main_focused");
    expect(
      (await textarea.inputValue({ timeout: 5000 })) === draft,
      "Mounted-page unsent plan words survive actual provider callback",
    ).toBe(true);
    stage = "visible_confirmation";
    workflowProgress("visible_authority_confirmation_start");
    const confirm = pid.page
      .waitForResponse(
        (r) =>
          r.url() === pid.config.mainOrigin + "/v1/auth/step-up/confirm" &&
          r.request().method() === "POST",
      )
      .catch(() => null);
    await pid.page
      .getByRole("button", {
        name: textFor("en-CA").confirmVerification,
        exact: true,
      })
      .click();
    const confirmedResponse = await confirm;
    workflowProgress("visible_authority_confirmation_response");
    if (!confirmedResponse) throw new Error("visible_confirm_post_unobserved");
    expect(
      confirmedResponse.status(),
      "Visible subject-bound authority confirmation",
    ).toBe(200);
    const confirmed = row((await confirmedResponse.json()) as unknown);
    expect(confirmed.state).toBe("verified");
    expect(
      (await textarea.inputValue()) === draft,
      "Mounted-page unsent plan words survive visible verification confirmation",
    ).toBe(true);
    expect(
      appendRequests,
      "Unsent draft must never submit a field append",
    ).toBe(0);
    observations.push({
      case: "Q09-draft",
      status: "passed",
      unsent_input_retained_after_provider_callback: true,
      unsent_input_retained_after_visible_confirmation: true,
      field_append_not_submitted: true,
      mounted_page_only: true,
      browser_persistent_storage_used: false,
      full_reload_persistence_claimed: false,
    });
    workflowProgress("visible_authority_complete");
    return text(confirmed, "ceremony_id");
  } catch (error) {
    const errorBodiesComplete = await settleErrorReads(errorReads);
    const workspace = pid.page.locator(
      'section[aria-labelledby="plans-title"]',
    );
    const notice = await workspace
      .locator(':scope > [role="status"], :scope > [role="alert"]')
      .first()
      .textContent()
      .catch(() => null);
    const knownNotice = [
      "ready",
      "pending",
      "committed",
      "rejected",
      "unavailable",
      "signed_out",
      "invalid",
      "operationUnknown",
    ] as const;
    const ui: Row = {
      notice:
        knownNotice.find((key) => notice === textFor("en-CA")[key]) ??
        "other_or_unavailable",
      ceremony_verified: await workspace
        .getByText(textFor("en-CA").authorityVerified, { exact: true })
        .count()
        .then((count) => count > 0)
        .catch(() => false),
      ceremony_expired: await workspace
        .getByText(textFor("en-CA").expiredPermission, { exact: true })
        .count()
        .then((count) => count > 0)
        .catch(() => false),
      ceremony_provider_pending: await workspace
        .getByText(textFor("en-CA").provider, { exact: true })
        .count()
        .then((count) => count > 0)
        .catch(() => false),
      confirm_disabled: await workspace
        .getByRole("button", {
          name: textFor("en-CA").confirmVerification,
          exact: true,
        })
        .isDisabled()
        .catch(() => null),
    };
    const diagnostic = {
      stage,
      error_bodies_complete: errorBodiesComplete,
      caught_error_name:
        error instanceof Error &&
        ["TimeoutError", "AssertionError", "Error"].includes(error.name)
          ? error.name
          : "unknown",
      ui,
      network: network.slice(-30),
      network_first: network.slice(0, 20),
      error_responses: network
        .filter((entry) => Number(entry.status) >= 400)
        .slice(0, 20),
      network_last: network.slice(-30),
      error:
        error instanceof Error &&
        error.message === "visible_confirm_post_unobserved"
          ? "visible_confirm_post_unobserved"
          : "visible_ceremony_driver_failure",
    };
    writeFileSync(
      resolve(evidenceDirectory(), "visible-authority-diagnostic.json"),
      JSON.stringify(diagnostic, null, 2),
      { mode: 0o600 },
    );
    // eslint-disable-next-line preserve-caught-error -- Raw ceremony errors may contain provider codes; retain only the sanitized diagnostic.
    throw new Error(
      `Visible authority ceremony failed; safe diagnostic=${JSON.stringify(diagnostic)}`,
    );
  } finally {
    pid.page.off("request", sent);
    pid.page.off("response", reply);
    pid.page.off("requestfailed", failed);
  }
}
async function grant(
  pid: Actor,
  recipient: Actor,
  state: PlanState,
  selected: string[],
  lifetimeSeconds: number,
): Promise<Row> {
  const current = await pid.ok(`/v1/sessions/${state.session}`);
  return pid.ok("/v1/consents", {
    subject_id: state.subject,
    session_id: state.session,
    expected_revision: current.revision,
    purpose: "plan",
    recipient: { kind: "account", account_id: recipient.issued.accountId },
    fields: selected,
    basis: "self",
    authority_proof_id: state.proof,
    effective_at: new Date(Date.now() - 1000).toISOString(),
    expires_at: new Date(Date.now() + lifetimeSeconds * 1000).toISOString(),
  });
}
export async function normal(
  actors: Actors,
  observations: Observations,
): Promise<PlanState> {
  workflowStages.length = 0;
  workflowProgress("normal_start");
  const pid = actors.pid;
  const own = await session(pid);
  workflowProgress("normal_session_created");
  const key = randomUUID();
  const createBody = {
    subject_id: own.subject_id,
    expected_revision: own.revision,
  };
  let plan = await pid.ok("/v1/plans", createBody, key);
  workflowProgress("normal_plan_created");
  const planId = text(plan, "id");
  const checkpoint = {
    session: text(own, "id"),
    subject: text(own, "subject_id"),
    plan: planId,
    proof: null,
    grant: null,
  };
  writeFileSync(
    resolve(evidenceDirectory(), "normal-checkpoint.json"),
    JSON.stringify(
      { ...checkpoint, at: new Date().toISOString(), stage: "plan_created" },
      null,
      2,
    ),
    { mode: 0o600 },
  );
  for (const field of ["plan.strategies", "plan.medication_report"]) {
    workflowProgress(
      field === "plan.strategies"
        ? "normal_strategies_append_start"
        : "normal_medication_append_start",
    );
    plan = await pid.ok(`/v1/plans/${planId}/fields`, {
      expected_revision: plan.revision,
      field,
      value: {
        kind: "text",
        text: `Fictional live qualification ${field} ${randomUUID()}`,
      },
      source: null,
      safety_relevant: false,
    });
    workflowProgress(
      field === "plan.strategies"
        ? "normal_strategies_append_complete"
        : "normal_medication_append_complete",
    );
  }
  workflowProgress("normal_create_replay_start");
  const replay = await pid.ok("/v1/plans", createBody, key);
  workflowProgress("normal_create_replay_complete");
  expect(
    replay.id === plan.id &&
      replay.revision === plan.revision &&
      fields(replay).length === 2,
    "Stable logical creation key reprojects the one durable edited plan",
  ).toBe(true);
  for (const slot of [
    "carer",
    "professional",
    "pid-other",
    "worker2",
  ] as const) {
    workflowProgress("normal_unshared_denial_start");
    await denied(actors[slot], `/v1/plans/${planId}`);
    workflowProgress("normal_unshared_denial_complete");
  }
  observations.push({
    case: "Q03/A01",
    status: "passed",
    plan_id: planId,
    plan_revision: plan.revision,
    fields: fields(plan).map((f) => f.field),
    attribution_all_owner: fields(plan).every(
      (f) => f.author_id === pid.issued.accountId,
    ),
    stable_create_replayed_current_projection: true,
    denied_unshared_roles: 4,
  });
  expect(fields(plan).every((f) => f.author_id === pid.issued.accountId)).toBe(
    true,
  );

  for (const slot of ["carer", "professional"] as const) {
    workflowProgress(
      slot === "carer"
        ? "normal_carer_report_start"
        : "normal_professional_report_start",
    );
    const actor = actors[slot];
    const ownSession = await session(actor);
    const assertion = await actor.ok(
      `/v1/sessions/${text(ownSession, "id")}/assertions`,
      {
        expected_revision: ownSession.revision,
        subject_id: ownSession.subject_id,
        field: "observations",
        value: {
          kind: "text",
          text: `Fictional ${slot} own report ${randomUUID()}`,
        },
        supersedes_id: null,
        effective_at: new Date().toISOString(),
      },
    );
    await actor.page.reload({ waitUntil: "domcontentloaded" });
    await actor.current();
    const saved = await actor.ok(
      `/v1/sessions/${text(ownSession, "id")}/own-reports`,
    );
    expect(Array.isArray(saved.items)).toBe(true);
    const items = (saved.items as unknown[]).map(row);
    expect(
      items.some(
        (f) =>
          f.id === assertion.id &&
          f.author_id === actor.issued.accountId &&
          f.subject_id === ownSession.subject_id,
      ),
    ).toBe(true);
    await denied(pid, `/v1/sessions/${text(ownSession, "id")}/own-reports`);
    observations.push({
      case: "Q05/A01",
      slot,
      status: "passed",
      session_id: ownSession.id,
      report_id: assertion.id,
      restored_committed_report_after_reload: true,
      cross_author_denied: true,
    });
    workflowProgress(
      slot === "carer"
        ? "normal_carer_report_complete"
        : "normal_professional_report_complete",
    );
  }
  workflowProgress("normal_visible_grant_start");
  for (const slot of ["carer", "professional", "pid-other"] as const)
    await actors[slot].park();
  workflowProgress("normal_unused_actor_contexts_closed");
  const visible = await visibleGrant(
    pid,
    actors.worker1,
    {
      session: text(own, "id"),
      plan: planId,
    },
    observations,
  );
  workflowProgress("normal_visible_grant_complete");
  const state = {
    session: text(own, "id"),
    subject: text(own, "subject_id"),
    plan: planId,
    proof: visible.proof,
    grant: text(visible.grant, "id"),
  };
  writeFileSync(
    resolve(evidenceDirectory(), "normal-checkpoint.json"),
    JSON.stringify(
      {
        ...state,
        at: new Date().toISOString(),
        stage: "visible_grant_created",
      },
      null,
      2,
    ),
    { mode: 0o600 },
  );
  const shared = await actors.worker1.ok(`/v1/plans/${planId}`);
  workflowProgress("normal_shared_projection_complete");
  expect(fields(shared).map((f) => f.field)).toEqual(["plan.strategies"]);
  await denied(actors.worker1, `/v1/sessions/${state.session}/own-reports`);
  const unassignedAppend = await actors.worker1.api(
    `/v1/plans/${planId}/fields`,
    {
      expected_revision: shared.revision,
      field: "plan.strategies",
      value: { kind: "text", text: "Fictional unassigned write must fail" },
      source: null,
      safety_relevant: true,
    },
  );
  expect([403, 404]).toContain(unassignedAppend.status);
  observations.push({
    case: "Q04/A01",
    status: "passed",
    grant_id: state.grant,
    ceremony_verified: true,
    visible_exact_preview_confirmed: true,
    disclosed_fields: ["plan.strategies"],
    medication_absent: true,
    unassigned_worker_append_denied: true,
  });
  const sessionBeforeAssignment = await pid.ok(`/v1/sessions/${state.session}`);
  workflowProgress("normal_assignment_start");
  const queued = await pid.ok(`/v1/sessions/${state.session}/human-request`, {
    expected_revision: sessionBeforeAssignment.revision,
    reason: "user_requested",
  });
  const reserved = await actors.worker1.ok(
    `/v1/sessions/${state.session}/workforce/reserve`,
    {
      expected_revision: queued.revision,
      worker_id: actors.worker1.issued.accountId,
    },
  );
  const accepted = await actors.worker1.ok(
    `/v1/sessions/${state.session}/workforce/accept`,
    {
      expected_revision: reserved.revision,
    },
  );
  expect(accepted.state).toBe("accepted");
  workflowProgress("normal_assignment_complete");
  const latestShared = await actors.worker1.ok(`/v1/plans/${planId}`);
  const conflict = await actors.worker1.ok(`/v1/plans/${planId}/fields`, {
    expected_revision: latestShared.revision,
    field: "plan.strategies",
    value: {
      kind: "text",
      text: `Fictional conflicting safety report ${randomUUID()}`,
    },
    source: null,
    safety_relevant: true,
  });
  workflowProgress("normal_conflict_append_complete");
  const strategies = fields(conflict).filter(
    (field) => field.field === "plan.strategies",
  );
  expect(strategies.length).toBe(2);
  expect(new Set(strategies.map((field) => field.author_id))).toEqual(
    new Set([pid.issued.accountId, actors.worker1.issued.accountId]),
  );
  expect(strategies.every((field) => field.verification === "disputed")).toBe(
    true,
  );
  observations.push({
    case: "Q03-worker-conflict",
    status: "passed",
    plan_id: planId,
    assignment_id: accepted.id,
    plan_revision: conflict.revision,
    exact_assignment_required: true,
    two_authors_retained: true,
    strategies_disputed: true,
    pending_human_review_db_count: "coordinator_read_only_check_required",
  });
  await pid.ok(`/v1/consents/${state.grant}/revoke`, {
    expected_revision: visible.grant.revision,
  });
  workflowProgress("normal_grant_revoked");
  await denied(actors.worker1, `/v1/plans/${planId}`);
  const revoked = await pid.ok(`/v1/consents/${state.grant}`);
  expect(typeof revoked.revoked_at).toBe("string");
  observations.push({
    case: "A02-revocation",
    status: "passed",
    grant_id: state.grant,
    revoked_at: revoked.revoked_at,
    later_disclosure_denied: true,
  });

  workflowProgress("normal_expiry_reload_start");
  const completed = await expiryAndReload(actors, observations, state);
  workflowProgress("normal_complete");
  return completed;
}
export async function normalContinue(
  actors: Actors,
  observations: Observations,
  previous: PlanState,
): Promise<PlanState> {
  const pid = actors.pid;
  const currentPlan = await pid.ok(`/v1/plans/${previous.plan}`);
  expect(currentPlan.id).toBe(previous.plan);
  expect(currentPlan.subject_id).toBe(previous.subject);
  const original = await pid.ok(`/v1/consents/${previous.grant}`);
  expect(
    typeof original.revoked_at,
    "Checkpoint resumes only after the original visible grant was revoked",
  ).toBe("string");
  const state = {
    ...previous,
    proof: await pid.verifySubject(previous.subject),
  };
  observations.push({
    case: "normal-continue",
    status: "passed",
    prior_plan_id: state.plan,
    prior_session_id: state.session,
    no_prior_plan_report_assignment_mutations_replayed: true,
    fresh_actual_subject_mfa_ceremony: true,
  });
  return expiryAndReload(actors, observations, state);
}
export async function reloadOnly(
  actors: Actors,
  observations: Observations,
  state: PlanState,
): Promise<PlanState> {
  const pid = actors.pid;
  const committed = await pid.ok(`/v1/plans/${state.plan}`);
  expect(committed.id).toBe(state.plan);
  expect(committed.subject_id).toBe(state.subject);
  expect(
    fields(committed).some((field) => field.author_id === pid.issued.accountId),
  ).toBe(true);
  const reports = await pid.ok(`/v1/sessions/${state.session}/own-reports`);
  expect(Array.isArray(reports.items)).toBe(true);
  await pid.ensureMain(true);
  await pid.page.reload({ waitUntil: "domcontentloaded" });
  await loadVisiblePlan(pid, state);
  const after = await pid.ok(`/v1/plans/${state.plan}`);
  expect(
    after.id === committed.id && after.revision === committed.revision,
  ).toBe(true);
  observations.push({
    case: "Q09-reload-only",
    status: "passed",
    plan_id: state.plan,
    session_id: state.session,
    committed_plan_revision: after.revision,
    current_own_report_endpoint_validated: true,
    native_visible_load_after_reload: true,
    no_new_grants_or_business_mutations: true,
    pending_intent_persistence: "not_claimed",
  });
  return state;
}
async function expiryAndReload(
  actors: Actors,
  observations: Observations,
  state: PlanState,
): Promise<PlanState> {
  const pid = actors.pid,
    planId = state.plan;
  const narrow = await grant(
    pid,
    actors.worker2,
    state,
    ["plan.strategies"],
    240,
  );
  const broad = await grant(
    pid,
    actors.worker2,
    state,
    ["plan.strategies", "plan.medication_report"],
    12,
  );
  writeFileSync(
    resolve(evidenceDirectory(), "normal-expiry-checkpoint.json"),
    JSON.stringify(
      {
        ...state,
        narrow_grant_id: narrow.id,
        narrow_grant_revision: narrow.revision,
        broad_grant_id: broad.id,
        broad_grant_expires_at: broad.expires_at,
        at: new Date().toISOString(),
        stage: "narrow_and_broad_grants_created",
      },
      null,
      2,
    ),
    { mode: 0o600 },
  );
  const before = await actors.worker2.ok(`/v1/plans/${planId}`);
  expect(fieldKeys(before)).toEqual([
    "plan.medication_report",
    "plan.strategies",
  ]);
  await expect
    .poll(() => Date.now() > Date.parse(text(broad, "expires_at")), {
      timeout: 16_000,
      intervals: [250, 500],
    })
    .toBe(true);
  const after = await actors.worker2.ok(`/v1/plans/${planId}`);
  expect(fieldKeys(after)).toEqual(["plan.strategies"]);
  await pid.ok(`/v1/consents/${text(narrow, "id")}/revoke`, {
    expected_revision: narrow.revision,
  });
  await denied(actors.worker2, `/v1/plans/${planId}`);
  observations.push({
    case: "A02-real-expiry",
    status: "passed",
    broad_grant_id: broad.id,
    broad_expires_at: broad.expires_at,
    observed_after: new Date().toISOString(),
    narrower_surviving_fields: ["plan.strategies"],
    final_narrow_revocation_denied: true,
    wall_clock_unchanged: true,
  });
  await pid.page.reload({ waitUntil: "domcontentloaded" });
  await loadVisiblePlan(pid, state);
  observations.push({
    case: "Q09",
    status: "passed",
    committed_work_reloaded_by_manual_ids: true,
    full_reload_pending_intent_persistence: "not_claimed",
  });
  return state;
}
export async function lifecycle(
  actors: Actors,
  observations: Observations,
): Promise<Row> {
  const owner = actors["pid-other"];
  const own = await session(owner);
  let plan = await owner.ok("/v1/plans", {
    subject_id: own.subject_id,
    expected_revision: own.revision,
  });
  plan = await owner.ok(`/v1/plans/${text(plan, "id")}/fields`, {
    expected_revision: plan.revision,
    field: "plan.strategies",
    value: {
      kind: "text",
      text: "Fictional independent lifecycle qualification",
    },
    source: null,
    safety_relevant: false,
  });
  const current = await owner.ok(`/v1/sessions/${text(own, "id")}`);
  await owner.ok(`/v1/sessions/${text(own, "id")}/end`, {
    expected_revision: current.revision,
    reason: "user_choice",
  });
  const afterClosure = await owner.ok(`/v1/plans/${text(plan, "id")}`);
  expect(afterClosure.state).toBe("active");
  expect(fieldKeys(afterClosure)).toEqual(["plan.strategies"]);
  const retired = await owner.ok(`/v1/plans/${text(plan, "id")}/retire`, {
    expected_revision: afterClosure.revision,
  });
  expect(retired.state).toBe("retired");
  expect(typeof retired.retired_at).toBe("string");
  observations.push({
    case: "Q07",
    status: "passed",
    session_id: own.id,
    subject_id: own.subject_id,
    plan_id: plan.id,
    retired_at: retired.retired_at,
    active_plan_retained_after_support_closed: true,
    retirement_plus_30_day_copy_anchor:
      "coordinator_read_only_metadata_check_required",
    purge_backup_completion: "not_claimed",
  });
  return {
    session: own.id,
    subject: own.subject_id,
    plan: plan.id,
    retired_at: retired.retired_at,
  };
}
export async function races(
  actors: Actors,
  observations: Observations,
): Promise<void> {
  // A genuine new subject-bound provider ceremony is required on this current
  // browser session; never reuse an injected proof/cookie or change the clock.
  const state = await createRaceScope(actors.pid, observations, "A03");
  const recipient = actors.worker2;
  const currentGrant = await grant(
    actors.pid,
    recipient,
    state,
    ["plan.strategies"],
    240,
  );
  await recipient.ensureMain();
  await actors.pid.ensureMain();
  const beforeRestriction = await recipient.ok(`/v1/plans/${state.plan}`);
  expect(fieldKeys(beforeRestriction)).toEqual(["plan.strategies"]);
  writeFileSync(
    resolve(evidenceDirectory(), "race-grants.json"),
    JSON.stringify({ state, current_grant: currentGrant }, null, 2),
    { mode: 0o600 },
  );
  const revokeKey = randomUUID();
  const csrfPrepared = await actors.pid.page.evaluate(
    async ({ path, revision, key }) => {
      const memory = window as unknown as {
        imp04PreparedRevoke?: {
          path: string;
          revision: unknown;
          key: string;
          csrf: string;
        };
      };
      delete memory.imp04PreparedRevoke;
      const response = await fetch("/v1/auth/csrf", {
        cache: "no-store",
        credentials: "same-origin",
        signal: AbortSignal.timeout(15000),
      });
      if (!response.ok) return response.status;
      const proof = (await response.json()) as { csrf_token?: unknown };
      if (typeof proof.csrf_token !== "string")
        throw new Error("Actual CSRF bootstrap required");
      memory.imp04PreparedRevoke = {
        path,
        revision,
        key,
        csrf: proof.csrf_token,
      };
      return response.status;
    },
    {
      path: `/v1/consents/${text(currentGrant, "id")}/revoke`,
      revision: currentGrant.revision,
      key: revokeKey,
    },
  );
  expect(
    csrfPrepared,
    "Actual CSRF proof is obtained before the timed hold",
  ).toBe(200);
  const bridge = await BarrierBridge.open();
  const control = async (
    action: BarrierRequest["action"],
    phase: BarrierRequest["phase"],
    nonce: string,
  ): Promise<Row> => {
    try {
      return await bridge.request({
        action,
        phase,
        operation: "plan_read",
        actor: recipient.issued.accountId,
        nonce,
      });
    } catch (error) {
      observations.push({
        case: "A03-control-failure",
        status: "failed",
        action,
        phase,
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
    const nonce = randomUUID();
    await control("arm", "before_policy", nonce);
    const readStarted = recipient.page.waitForRequest(
      (request) =>
        request.url() ===
          recipient.config.mainOrigin + `/v1/plans/${state.plan}` &&
        request.method() === "GET",
    );
    const pending = recipient.api(`/v1/plans/${state.plan}`);
    await readStarted;
    const pendingHttpObservedAt = new Date().toISOString();
    // Overlap the two genuine Core preflights; ordering is proven from the
    // eventual DB revocation timestamp, never assumed from dispatch order.
    const revokeStartedAt = new Date().toISOString();
    const revokeRequest = actors.pid.page.evaluate(async () => {
      const memory = window as unknown as {
        imp04PreparedRevoke?: {
          path: string;
          revision: unknown;
          key: string;
          csrf: string;
        };
      };
      const prepared = memory.imp04PreparedRevoke;
      delete memory.imp04PreparedRevoke;
      if (!prepared)
        throw new Error("Missing exact pre-held native CSRF command");
      const requestStartedAt = new Date().toISOString();
      const response = await fetch(prepared.path, {
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": prepared.csrf,
          "Idempotency-Key": prepared.key,
        },
        body: JSON.stringify({ expected_revision: prepared.revision }),
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
    let revoked: Row = {};
    let revokeTiming: Row = {};
    let entered = false;
    try {
      const [entry, actualRevoke] = await Promise.all([
        control("wait", "before_policy", nonce).then((value) => {
          ready = value;
          entered = true;
          return value;
        }),
        revokeRequest,
      ]);
      ready = entry;
      expect(
        actualRevoke.status,
        "Genuine same-cookie current revoke succeeds during hold",
      ).toBe(200);
      revoked = row(actualRevoke.value);
      revokeTiming = {
        request_started_at: actualRevoke.request_started_at,
        response_observed_at: actualRevoke.response_observed_at,
      };
    } finally {
      if (entered) await control("release", "before_policy", nonce);
    }
    const result = await pending;
    const finished = await control("finished", "before_policy", nonce);
    const errorKey =
      result.value &&
      typeof result.value === "object" &&
      "message_key" in result.value &&
      typeof result.value.message_key === "string" &&
      /^(manual|identity)\.[a-z_]+$/.test(result.value.message_key)
        ? result.value.message_key
        : null;
    const timing: Row = {
      case: "A03-revoke-timing",
      status: "observed",
      nonce,
      ready,
      finished,
      pending_status: result.status,
      pending_message_key: errorKey,
      actual_csrf_prefetched_before_hold: true,
      revoke_idempotency_key: revokeKey,
      pending_http_observed_at: pendingHttpObservedAt,
      revoke_invoked_at: revokeStartedAt,
      revoke_timing: revokeTiming,
      coordination:
        "Native preflights overlap; recorded revocation follows hold entry and genuine HTTP200 commit acknowledgement precedes release",
    };
    observations.push(timing);
    const revokedGrant = await actors.pid.ok(
      `/v1/consents/${text(currentGrant, "id")}`,
    );
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
      "Pending request denied after current journalled revocation",
    ).toContain(result.status);
    expect(row(result.value).fields === undefined).toBe(true);
    await denied(recipient, `/v1/plans/${state.plan}`);
    observations.push({
      case: "A03-revoke-before-policy",
      status: "passed",
      nonce,
      ready,
      revoke_result: revoked,
      revoked_at: revokedAt,
      finished,
      pending_status: result.status,
      zero_plan_fields_after_restriction: true,
      actor_id: recipient.issued.accountId,
      exact_phase:
        "after metadata locks released; before genuine live policy and locked final validation",
    });

    const expiring = await grant(
      actors.pid,
      recipient,
      state,
      ["plan.strategies"],
      1.3,
    );
    const expiryNonce = randomUUID();
    await control("arm", "before_final_output", expiryNonce);
    const expiryReadStarted = recipient.page.waitForRequest(
      (request) =>
        request.url() ===
          recipient.config.mainOrigin + `/v1/plans/${state.plan}` &&
        request.method() === "GET",
    );
    const expiringRequest = recipient.api(`/v1/plans/${state.plan}`);
    await expiryReadStarted;
    let expiryReady: Row = {};
    try {
      expiryReady = await control("wait", "before_final_output", expiryNonce);
      await expect
        .poll(() => Date.now() > Date.parse(text(expiring, "expires_at")), {
          timeout: 1500,
          intervals: [10, 20],
        })
        .toBe(true);
    } finally {
      await control("release", "before_final_output", expiryNonce);
    }
    const expired = await expiringRequest;
    const expiryFinished = await control(
      "finished",
      "before_final_output",
      expiryNonce,
    );
    const expiryErrorKey =
      expired.value &&
      typeof expired.value === "object" &&
      "message_key" in expired.value &&
      typeof expired.value.message_key === "string" &&
      /^(manual|identity)\.[a-z_]+$/.test(expired.value.message_key)
        ? expired.value.message_key
        : null;
    observations.push({
      case: "A03-expire-timing",
      status: "observed",
      nonce: expiryNonce,
      ready: expiryReady,
      finished: expiryFinished,
      pending_status: expired.status,
      pending_message_key: expiryErrorKey,
      grant_expires_at: expiring.expires_at,
    });
    expect(
      instantNanos(text(expiryReady, "entered_at")),
      "Grant remains current when final output hold begins",
    ).toBeLessThan(instantNanos(text(expiring, "expires_at")));
    expect(
      instantNanos(text(expiring, "expires_at")),
      "Actual expiry occurs before final output release",
    ).toBeLessThanOrEqual(instantNanos(text(expiryFinished, "released_at")));
    expect(
      Date.parse(text(expiryFinished, "released_at")) -
        Date.parse(text(expiryFinished, "entered_at")),
    ).toBeLessThan(800);
    expect(
      [403, 404, 409],
      "Projection rechecks actual wall-clock expiry",
    ).toContain(expired.status);
    expect(row(expired.value).fields === undefined).toBe(true);
    observations.push({
      case: "A03-expire-before-final-output",
      status: "passed",
      nonce: expiryNonce,
      ready: expiryReady,
      finished: expiryFinished,
      grant_id: expiring.id,
      expires_at: expiring.expires_at,
      observed_after: new Date().toISOString(),
      pending_status: expired.status,
      zero_plan_fields_after_expiry: true,
      clock_injection: false,
    });
  } finally {
    await bridge.close();
  }
}
export async function directory(
  actors: Actors,
  observations: Observations,
): Promise<void> {
  const fixture = row(
    JSON.parse(
      readFileSync(
        resolve("config/demo/imp04/directory-fixtures.json"),
        "utf8",
      ),
    ) as unknown,
  );
  if (!Array.isArray(fixture.feeds))
    throw new Error("Expected exact signed fixture feeds");
  const feeds = fixture.feeds.map(row);
  const revisions = new Map<string, string>();
  const admissions = new Map<string, "stale" | "suspended">();
  for (const feed of feeds) {
    const id = text(feed, "service_id");
    const existing = await actors.pid.api(`/v1/directory/${id}`);
    if (existing.status === 200) {
      const view = row(existing.value);
      revisions.set(id, text(view, "revision"));
      expect(
        ["stale", "suspended"],
        "Retained fixed source admission",
      ).toContain(view.state);
      admissions.set(id, view.state === "suspended" ? "suspended" : "stale");
      continue;
    }
    expect(
      [403, 404],
      "Fresh source absence is concealed by gateway authorization",
    ).toContain(existing.status);
    observations.push({
      case: "Q06-pre-ingest",
      service_id: id,
      actual_http_status: existing.status,
      status: "passed",
      no_serving_projection: true,
    });
    const ingested = await actors.operator.ok("/v1/directory/ingest", feed);
    revisions.set(id, text(ingested, "revision"));
    expect(ingested.state).toBe("stale");
    admissions.set(id, "stale");
  }
  for (const locale of ["en-CA", "fr-CA"]) {
    const page = await actors.pid.ok("/v1/directory/search", {
      jurisdiction: "CA-XX",
      locale,
      need: "client_support",
      limit: 50,
    });
    if (!Array.isArray(page.items))
      throw new Error("Missing directory projection");
    const items = page.items.map(row);
    expect(items.length, "All seven exact fixtures are returned").toBe(7);
    const states: Row[] = [];
    for (const feed of feeds) {
      const view = items.find((item) => item.id === feed.service_id);
      if (!view) throw new Error("Missing admitted service");
      const facts = row(view.facts),
        input = row(feed.facts);
      expect(facts.operating_state).toBe(input.operating_state);
      expect(facts.police_involvement).toBe("unknown");
      expect(facts.alternative_service_id).toBeNull();
      expect(facts.availability).toBe(
        ["temporary_closure", "regional_outage"].includes(
          text(input, "operating_state"),
        )
          ? "unavailable"
          : "unknown",
      );
      expect(
        view.state,
        "Fixed observation and retained negative admission are preserved",
      ).toBe(admissions.get(text(feed, "service_id")));
      expect(view.sources).toEqual(feed.sources);
      const direct = await actors.pid.ok(
        `/v1/directory/${text(feed, "service_id")}`,
      );
      expect(
        direct.id === view.id &&
          direct.revision === view.revision &&
          direct.state === view.state,
      ).toBe(true);
      states.push({
        service_id: view.id,
        revision: view.revision,
        operating_state: facts.operating_state,
        admission: view.state,
        availability: facts.availability,
        expires_at: view.expires_at,
      });
    }
    observations.push({
      case: "Q06",
      locale,
      status: "passed",
      states,
      fixed_source_observation_preserved: true,
      no_fresh_availability_claim: true,
    });
  }
  const first = feeds[0];
  if (!first) throw new Error("Missing first directory fixture");
  const bad = structuredClone(first);
  bad.expected_revision = revisions.get(text(first, "service_id"));
  bad.feed_artifact_digest = "f".repeat(64);
  const quarantined = await actors.operator.ok("/v1/directory/ingest", bad);
  expect(quarantined.state).toBe("quarantined");
  const unchanged = await actors.pid.ok(
    `/v1/directory/${text(first, "service_id")}`,
  );
  expect(unchanged.revision).toBe(revisions.get(text(first, "service_id")));
  expect(unchanged.state).toBe(admissions.get(text(first, "service_id")));
  await denied(actors.pid, "/v1/directory/ingest", bad);
  await denied(
    actors.pid,
    `/v1/directory/${text(first, "service_id")}/suspend`,
    {
      expected_revision: unchanged.revision,
      reason: "security",
    },
  );
  const preexistingSuspension = unchanged.state === "suspended";
  if (!preexistingSuspension)
    await actors.security.ok(
      `/v1/directory/${text(first, "service_id")}/suspend`,
      {
        expected_revision: unchanged.revision,
        reason: "security",
      },
    );
  const suspended = await actors.pid.ok(
    `/v1/directory/${text(first, "service_id")}`,
  );
  expect(suspended.state).toBe("suspended");
  const replayFeed = structuredClone(first);
  replayFeed.expected_revision = suspended.revision;
  const reingested = await actors.operator.ok(
    "/v1/directory/ingest",
    replayFeed,
  );
  expect(reingested.state).toBe("suspended");
  observations.push({
    case: "A06",
    status: "passed",
    service_id: first.service_id,
    rejected_digest_quarantined: true,
    serving_revision_unchanged_by_quarantine: true,
    participant_admin_denied: true,
    preexisting_suspension_preserved: preexistingSuspension,
    suspension_persisted_across_admitted_ingest: true,
  });
}
export async function accessibility(
  actors: Actors,
  observations: Observations,
): Promise<void> {
  const checkpoint = (
    slot: string,
    locale: string | null,
    stage: string,
    extra: Row = {},
  ): void => {
    writeFileSync(
      resolve(evidenceDirectory(), "accessibility-progress.json"),
      JSON.stringify(
        {
          case: "Q08",
          slot,
          locale,
          stage,
          at: new Date().toISOString(),
          completed_scans: observations.filter((item) => item.case === "Q08")
            .length,
          ...extra,
        },
        null,
        2,
      ),
      { mode: 0o600 },
    );
  };
  for (const slot of ["pid", "carer", "professional", "worker1"] as const) {
    const actor = actors[slot];
    checkpoint(slot, null, "actor_ui_start");
    await actor.ensureMain(true);
    const safeNetwork: Row[] = [];
    const errorReads: Promise<void>[] = [];
    let lastStage = "actor_ui_start",
      lastLocale: string | null = null;
    const allowed = (raw: string): string | null => {
      try {
        const url = new URL(raw);
        return url.origin === actor.config.mainOrigin &&
          [
            "/v1/auth/session",
            "/v1/auth/csrf",
            "/v1/directory/search",
          ].includes(url.pathname)
          ? url.pathname
          : null;
      } catch {
        return null;
      }
    };
    const request = (request: Request): void => {
      const path = allowed(request.url());
      if (path)
        safeNetwork.push({ event: "request", path, method: request.method() });
    };
    const response = (response: Response): void => {
      const path = allowed(response.url());
      if (path) {
        safeNetwork.push({
          event: "response",
          path,
          status: response.status(),
        });
        if (response.status() >= 400)
          errorReads.push(
            response
              .json()
              .then((raw: unknown) => {
                const value = row(raw);
                const messageKey =
                  typeof value.message_key === "string" &&
                  /^(manual|identity)\.[a-z_]+$/.test(value.message_key)
                    ? value.message_key
                    : null;
                const code =
                  typeof value.code === "string" &&
                  /^[A-Z_]{1,64}$/.test(value.code)
                    ? value.code
                    : null;
                safeNetwork.push({
                  event: "safe_error",
                  path,
                  status: response.status(),
                  message_key: messageKey,
                  code,
                });
              })
              .catch(() => {
                /* Never retain an error body or parsing exception. */
              }),
          );
      }
    };
    const failed = (request: Request): void => {
      const path = allowed(request.url());
      if (path) safeNetwork.push({ event: "requestfailed", path });
    };
    actor.page.on("request", request);
    actor.page.on("response", response);
    actor.page.on("requestfailed", failed);
    try {
      for (const locale of ["en-CA", "fr-CA"] as const) {
        lastLocale = locale;
        lastStage = "locale_start";
        checkpoint(slot, locale, "locale_start");
        await actor.page.locator("#language").selectOption(locale);
        await expect(actor.page.locator("html")).toHaveAttribute(
          "lang",
          locale,
        );
        await expect(
          actor.page.getByRole("heading", {
            name: textFor(locale).title,
            exact: true,
          }),
        ).toBeVisible();
        const workspace = actor.page.locator(
          'section[aria-labelledby="plans-title"]',
        );
        const check = workspace.getByRole("button", {
          name: textFor(locale).check,
          exact: true,
        });
        await expect(check).toBeEnabled();
        const identityResponse = actor.page.waitForResponse(
          (response) =>
            response.url() === actor.config.mainOrigin + "/v1/auth/session" &&
            response.request().method() === "GET",
          { timeout: 20_000 },
        );
        lastStage = "access_check_activation";
        checkpoint(slot, locale, lastStage);
        await check.press("Enter");
        const identity = await identityResponse;
        expect(
          identity.status(),
          "Actual UI current-access request succeeds",
        ).toBe(200);
        await expect(check).toBeEnabled();
        await expect(
          workspace
            .locator(':scope > [role="status"], :scope > [role="alert"]')
            .first(),
        ).toHaveText(textFor(locale).ready);
        checkpoint(slot, locale, "actual_access_checked", {
          http_status: identity.status(),
        });
        lastStage = "actual_access_checked";
        const search = actor.page.getByRole("button", {
          name: textFor(locale).search,
          exact: true,
        });
        await expect(search).toBeEnabled();
        const searchResponse = actor.page.waitForResponse(
          (response) =>
            response.url() ===
              actor.config.mainOrigin + "/v1/directory/search" &&
            response.request().method() === "POST",
          { timeout: 20_000 },
        );
        lastStage = "directory_search_activation";
        checkpoint(slot, locale, lastStage);
        await search.press("Enter");
        const searched = await searchResponse;
        expect(
          searched.status(),
          "Actual localized directory search succeeds",
        ).toBe(200);
        await expect(check).toBeEnabled();
        const status = workspace
          .locator(':scope > [role="status"], :scope > [role="alert"]')
          .first();
        await expect
          .poll(
            async () => {
              const message = await status.textContent();
              return [
                textFor(locale).committed,
                textFor(locale).ready,
              ].includes(message ?? "");
            },
            { timeout: 20_000 },
          )
          .toBe(true);
        checkpoint(slot, locale, "actual_directory_loaded", {
          http_status: searched.status(),
        });
        lastStage = "actual_directory_loaded";
        const options = actor.page.locator(
          'section[aria-labelledby="directory-title"]',
        );
        for (const label of Object.values(stateLabels[locale]))
          await expect(options.getByText(label, { exact: true })).toBeVisible();
        await actor.page.locator("#plans-id").focus();
        await actor.page.keyboard.press("Tab");
        expect(
          await actor.page.evaluate(() => document.activeElement?.tagName),
        ).toBe("BUTTON");
        checkpoint(slot, locale, "axe_scan_started", {
          keyboard_focus_checked: true,
        });
        lastStage = "axe_scan_started";
        const result = await new AxeBuilder({ page: actor.page })
          .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
          .analyze();
        checkpoint(slot, locale, "axe_scan_finished", {
          status: result.violations.length ? "failed" : "passed",
          violation_rule_count: result.violations.length,
          passed_rule_count: result.passes.length,
          incomplete_rule_count: result.incomplete.length,
        });
        lastStage = "axe_scan_finished";
        observations.push({
          case: "Q08",
          slot,
          locale,
          status: result.violations.length ? "failed" : "passed",
          violations: result.violations.map((v) => ({
            rule: v.id,
            impact: v.impact,
            affected_nodes: v.nodes.length,
          })),
          passed_rule_count: result.passes.length,
          incomplete_rule_count: result.incomplete.length,
          keyboard_input_to_submit_focus: true,
          manual_screen_reader: "not_run",
        });
        expect(result.passes.length).toBeGreaterThan(0);
        expect(
          result.violations.map((v) => v.id),
          "Native page WCAG scan",
        ).toEqual([]);
        await nativeZoom(actor, locale, observations);
      }
    } catch (error) {
      const errorBodiesComplete = await settleErrorReads(errorReads);
      const locale = lastLocale === "fr-CA" ? "fr-CA" : "en-CA";
      const workspace = actor.page.locator(
        'section[aria-labelledby="plans-title"]',
      );
      const actualNotice = await workspace
        .locator(':scope > [role="status"], :scope > [role="alert"]')
        .first()
        .textContent()
        .catch(() => null);
      const known = [
        "ready",
        "pending",
        "committed",
        "rejected",
        "unavailable",
        "signed_out",
        "invalid",
        "operationUnknown",
      ] as const;
      const failure = {
        stage: lastStage,
        error_bodies_complete: errorBodiesComplete,
        network: safeNetwork.slice(-30),
        network_first: safeNetwork.slice(0, 20),
        error_responses: safeNetwork
          .filter((entry) => Number(entry.status) >= 400)
          .slice(0, 20),
        notice:
          known.find((key) => actualNotice === textFor(locale)[key]) ??
          "other_or_unavailable",
        error_category:
          error instanceof Error && error.name === "TimeoutError"
            ? "driver_response_or_navigation_timeout"
            : "ui_or_scan_expectation_failed",
      };
      checkpoint(slot, locale, "failed", failure);
      writeFileSync(
        resolve(evidenceDirectory(), `accessibility-${slot}-diagnostic.json`),
        JSON.stringify(failure, null, 2),
        { mode: 0o600 },
      );
      // eslint-disable-next-line preserve-caught-error -- Driver errors may expose private browser data; retain only whitelisted metadata.
      throw new Error(
        `Accessibility actual UI/scan failed; safe diagnostic=${JSON.stringify(failure)}`,
      );
    } finally {
      // Each completed actor's UI is unloaded before the next actor starts;
      // this stops its real five-second refreshes without changing authority.
      await actor.page.goto("about:blank", { waitUntil: "domcontentloaded" });
      checkpoint(slot, lastLocale, "actor_ui_parked", {
        last_completed_or_failed_stage: lastStage,
      });
      actor.page.off("request", request);
      actor.page.off("response", response);
      actor.page.off("requestfailed", failed);
    }
  }
}
