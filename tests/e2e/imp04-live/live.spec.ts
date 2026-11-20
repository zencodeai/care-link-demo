import { test, expect, type BrowserContext } from "@playwright/test";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { resolve } from "node:path";
import { Actor } from "./browser";
import {
  accessibility,
  directory,
  lifecycle,
  normal,
  normalContinue,
  reloadOnly,
  races,
  type Actors,
  type Observations,
  type PlanState,
} from "./cases";
import { evidenceDirectory, privateFile, readConfig, slots } from "./config";
import { absentGrantRace, delegation, dependencies } from "./adverse";
import { manualRegression } from "./manual";
import { reportUi } from "./report_ui";
import { pendingUi } from "./pending_ui";
import { phaseCoverage } from "./coverage";
import { authorityLoss } from "./authority_loss";

test("IMP04 genuine provider, isolated actors, plans/consent/directory and native page qualification", async ({
  browser,
}) => {
  const config = readConfig(),
    output = evidenceDirectory();
  const observations: Observations = [];
  const actors = {} as Actors;
  const contexts: BrowserContext[] = [];
  type StorageState = Awaited<ReturnType<BrowserContext["storageState"]>>;
  const actualStates = new Map<string, StorageState>();
  let maximumInitialContexts = 0;
  const phase = process.env.CARE_LINK_IMP04_E2E_PHASE ?? "all";
  const stateRoot = process.env.CARE_LINK_IMP04_E2E_STATE ?? output;
  if (
    ![
      "all",
      "normal",
      "normal-continue",
      "reload-only",
      "manual-regression",
      "report-ui",
      "pending-ui",
      "directory",
      "accessibility",
      "signin",
      "lifecycle",
      "race",
      "dependency",
      "absent-race",
      "authority-loss",
      "delegation",
      "delegation-expired",
    ].includes(phase)
  )
    throw new Error("Explicit known IMP04 live qualification phase required");
  const requestedSlots = process.env.CARE_LINK_IMP04_E2E_SLOTS;
  const selectedSlots = requestedSlots ? requestedSlots.split(",") : [...slots];
  if (
    requestedSlots &&
    (phase !== "signin" ||
      !selectedSlots.length ||
      selectedSlots.some(
        (slot) => !slots.includes(slot as (typeof slots)[number]),
      ) ||
      new Set(selectedSlots).size !== selectedSlots.length)
  )
    throw new Error(
      "Actor subset is allowed only for signin, with unique exact slot names",
    );
  const selected = selectedSlots as (typeof slots)[number][];
  const phaseActors: Record<string, (typeof slots)[number][]> = {
    normal: ["pid", "pid-other", "carer", "professional", "worker1", "worker2"],
    "normal-continue": ["pid", "worker2"],
    "reload-only": ["pid"],
    "manual-regression": ["pid", "worker2"],
    "report-ui": ["carer", "professional"],
    "pending-ui": ["pid"],
    directory: ["pid", "operator", "security"],
    lifecycle: ["pid-other"],
    accessibility: ["pid", "carer", "professional", "worker1"],
    race: ["pid", "worker2"],
    dependency: ["pid"],
    "absent-race": ["pid", "worker2"],
    "authority-loss": ["pid", "carer", "worker2"],
    delegation: ["pid", "carer", "worker2"],
    "delegation-expired": ["pid", "carer", "worker2"],
    all: [
      "pid",
      "pid-other",
      "carer",
      "professional",
      "worker1",
      "worker2",
      "operator",
      "security",
    ],
    signin: [],
  };
  const restoredSlots = selected.filter((slot) =>
    phaseActors[phase]?.includes(slot),
  );
  const progress = (stage: string, slot: string | null): void => {
    writeFileSync(
      resolve(output, "progress.json"),
      JSON.stringify(
        {
          phase,
          stage,
          slot,
          at: new Date().toISOString(),
          completed_actor_checks: observations.filter(
            (item) => item.case === "Q02",
          ),
        },
        null,
        2,
      ),
      { mode: 0o600 },
    );
  };
  let status = "failed";
  const sessionDirectory = resolve(output, "sessions");
  mkdirSync(sessionDirectory, { recursive: true, mode: 0o700 });
  try {
    for (const slot of selected) {
      progress("actor_signin_started", slot);
      const sessionFile = resolve(stateRoot, "sessions", slot + ".json");
      const resumed =
        process.env.CARE_LINK_IMP04_E2E_RESUME === "1" &&
        existsSync(sessionFile);
      if (resumed) privateFile(sessionFile);
      const context = await browser.newContext({
        ignoreHTTPSErrors: false,
        locale: "en-CA",
        viewport: { width: 1440, height: 1100 },
        ...(resumed
          ? {
              storageState: JSON.parse(readFileSync(sessionFile, "utf8")) as {
                cookies: [];
                origins: [];
              },
            }
          : {}),
      });
      context.setDefaultTimeout(20_000);
      context.setDefaultNavigationTimeout(30_000);
      contexts.push(context);
      maximumInitialContexts = Math.max(
        maximumInitialContexts,
        browser.contexts().length,
      );
      const page = await context.newPage();
      const actor = new Actor(page, slot, config.actors[slot], config);
      actors[slot] = actor;
      if (resumed) {
        await page.goto(config.mainOrigin, { waitUntil: "domcontentloaded" });
        try {
          const actual = await actor.current();
          if (actual.assurance !== "AL2") await actor.signIn(false);
        } catch {
          await actor.signIn(false);
        }
      } else await actor.signIn();
      const current = await actor.current();
      expect(current.assurance, "Actual password+OTP yields AL2").toBe("AL2");
      observations.push({
        case: "Q02",
        slot,
        status: "passed",
        account_id: current.account_id,
        role: current.role,
        assurance: current.assurance,
        auth_time: current.auth_time,
        separate_browser_context: true,
        native_tls: true,
        resumed_private_session: resumed,
      });
      progress("actor_signin_verified", slot);
      const issuedState = await context.storageState();
      actualStates.set(slot, issuedState);
      writeFileSync(
        resolve(sessionDirectory, slot + ".json"),
        JSON.stringify(issuedState),
        { mode: 0o600 },
      );
      // Free each real authenticator document before opening the next actor.
      // Only its actual same-actor browser state is later restored; no cookie,
      // token, role or proof is manufactured or edited.
      await context.close();
    }
    progress("initial_actors_verified", null);
    if (phase !== "signin") {
      for (const slot of restoredSlots) {
        const storageState = actualStates.get(slot);
        if (!storageState)
          throw new Error("Missing actual verified actor browser state");
        const context = await browser.newContext({
          ignoreHTTPSErrors: false,
          locale: "en-CA",
          viewport: { width: 1440, height: 1100 },
          storageState,
        });
        context.setDefaultTimeout(20_000);
        context.setDefaultNavigationTimeout(30_000);
        contexts.push(context);
        actors[slot] = new Actor(
          await context.newPage(),
          slot,
          config.actors[slot],
          config,
        );
      }
    }
    observations.push({
      case: "Q01-browser",
      status: "passed",
      browser_version: browser.version(),
      ignore_https_errors: false,
      actual_provider_login_required_for_fresh_session:
        process.env.CARE_LINK_IMP04_E2E_RESUME !== "1",
      restored_genuine_same_actor_browser_state: phase !== "signin",
      phase_actor_slots_restored: restoredSlots,
      unused_verified_actor_contexts_kept_closed: true,
      maximum_simultaneous_initial_authenticator_contexts:
        maximumInitialContexts,
      api_driver_shell:
        "Actual main HTML/CSP; only app JavaScript assets aborted; no API interception",
      visible_ui_driver:
        "Real application bundle loaded on demand with ensureMain(true)",
      origin: config.mainOrigin,
      provider_origin: config.oidcOrigin,
      main_transport: process.env.CARE_LINK_IMP04_E2E_MAIN_ROUTE ?? "broker",
    });
    if (["all", "normal"].includes(phase)) {
      const state = await normal(actors, observations);
      writeFileSync(
        resolve(output, "live-state.json"),
        JSON.stringify(state, null, 2),
        { mode: 0o600 },
      );
    }
    if (phase === "normal-continue") {
      const file = resolve(stateRoot, "normal-checkpoint.json");
      privateFile(file);
      const previous = JSON.parse(readFileSync(file, "utf8")) as PlanState;
      const state = await normalContinue(actors, observations, previous);
      writeFileSync(
        resolve(output, "live-state.json"),
        JSON.stringify(state, null, 2),
        { mode: 0o600 },
      );
    }
    if (phase === "reload-only") {
      const file = resolve(stateRoot, "normal-checkpoint.json");
      privateFile(file);
      const previous = JSON.parse(readFileSync(file, "utf8")) as PlanState;
      const state = await reloadOnly(actors, observations, previous);
      writeFileSync(
        resolve(output, "live-state.json"),
        JSON.stringify(state, null, 2),
        { mode: 0o600 },
      );
    }
    if (phase === "manual-regression") {
      const state = await manualRegression(actors, observations);
      writeFileSync(
        resolve(output, "manual-regression-state.json"),
        JSON.stringify(state, null, 2),
        { mode: 0o600 },
      );
    }
    if (phase === "report-ui") await reportUi(actors, observations, stateRoot);
    if (phase === "pending-ui") {
      const file = resolve(stateRoot, "live-state.json");
      privateFile(file);
      const state = JSON.parse(readFileSync(file, "utf8")) as PlanState;
      const result = await pendingUi(actors, observations, state);
      writeFileSync(
        resolve(output, "pending-ui-state.json"),
        JSON.stringify(result, null, 2),
        { mode: 0o600 },
      );
    }
    if (["all", "directory"].includes(phase))
      await directory(actors, observations);
    if (["all", "lifecycle"].includes(phase)) {
      const state = await lifecycle(actors, observations);
      writeFileSync(
        resolve(output, "lifecycle-state.json"),
        JSON.stringify(state, null, 2),
        { mode: 0o600 },
      );
    }
    if (["all", "accessibility"].includes(phase))
      await accessibility(actors, observations);
    if (phase === "race") {
      await races(actors, observations);
    }
    if (phase === "absent-race") {
      const result = await absentGrantRace(actors, observations);
      writeFileSync(
        resolve(output, "absent-race-state.json"),
        JSON.stringify(result, null, 2),
        { mode: 0o600 },
      );
    }
    if (phase === "authority-loss") await authorityLoss(actors, observations);
    if (["dependency", "delegation", "delegation-expired"].includes(phase)) {
      const file = resolve(stateRoot, "live-state.json");
      privateFile(file);
      const previous = JSON.parse(readFileSync(file, "utf8")) as PlanState;
      if (phase === "dependency")
        await dependencies(actors, observations, previous);
      else {
        const result = await delegation(
          actors,
          observations,
          previous,
          phase === "delegation-expired",
        );
        writeFileSync(
          resolve(output, phase + "-state.json"),
          JSON.stringify(result, null, 2),
          { mode: 0o600 },
        );
      }
    }
    expect(
      phaseCoverage(phase, observations, selected.length).checks.every(
        (item) => item.completed,
      ),
      "All planned browser checks for the selected phase have actual passing observations",
    ).toBe(true);
    status = "passed";
  } finally {
    const sessions = resolve(output, "sessions");
    mkdirSync(sessions, { recursive: true, mode: 0o700 });
    for (const slot of slots) {
      const actor = actors[slot];
      if (!actor) continue;
      try {
        const path = resolve(sessions, slot + ".json");
        if (actor.page.isClosed()) {
          const saved = actor.parkedState ?? actualStates.get(slot);
          if (saved)
            writeFileSync(path, JSON.stringify(saved), { mode: 0o600 });
        } else await actor.page.context().storageState({ path });
        chmodSync(path, 0o600);
      } catch {
        /* Original failure remains authoritative. */
      }
    }
    writeFileSync(
      resolve(output, "observations.json"),
      JSON.stringify(
        {
          phase,
          selected_slots: selected,
          status,
          at: new Date().toISOString(),
          observations,
          not_run: phaseCoverage(phase, observations, selected.length).notRun,
          phase_coverage: phaseCoverage(phase, observations, selected.length),
          gate_decision: "G04 pending; automated run is not human acceptance",
        },
        null,
        2,
      ),
      { mode: 0o600 },
    );
    for (const context of contexts) await context.close().catch(() => {});
  }
});
