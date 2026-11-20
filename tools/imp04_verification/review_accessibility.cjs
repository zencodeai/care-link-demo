/* Automated-only qualification of the approved synthetic review build.
 * Execute from the repository with: node tools/imp04_verification/review_accessibility.cjs
 *   /absolute/new/private-output.json
 * Reuses the existing owned browser container; never connects to or closes its
 * shared browser. Every row owns a separate ephemeral Chromium profile/session.
 */
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { createRequire } = require("node:module");
const { spawnSync } = require("node:child_process");
process.umask(0o077);

async function browserRun() {
  const fs = require("node:fs");
  const crypto = require("node:crypto");
  const { chromium } = require("/opt/playwright-core");
  const input = JSON.parse(fs.readFileSync(0, "utf8"));
  const rows = [];
  function check(value, category) {
    if (!value) {
      const error = new Error(category);
      error.name = "QualificationAssertion";
      throw error;
    }
  }
  const metrics = (page) =>
    page.evaluate(() => ({
      dpr: devicePixelRatio,
      width: innerWidth,
      outer: outerWidth,
      pinch: visualViewport.scale,
    }));
  const labels = {
    "en-CA": {
      title: "Plans and sharing review",
      ready: "Your review is ready.",
      search: "Refresh sourced options",
      plan: "Active plan",
      own: "My saved reports",
      conflict: "Disputed report — human review required",
      strategies: "Strategies",
      medication: "Medication report",
      stale: "Stale source — current availability is unknown",
      suspended: "Suspended — this option is blocked",
      unknown: "Unknown — verify current facts before choosing",
      unavailable: "Unavailable",
    },
    "fr-CA": {
      title: "Examen du plan et du partage",
      ready: "Votre examen est prêt.",
      search: "Actualiser les options sourcées",
      plan: "Plan actif",
      own: "Mes rapports enregistrés",
      conflict: "Rapport contesté — examen humain requis",
      strategies: "Stratégies",
      medication: "Médicaments rapportés",
      stale: "Source périmée — disponibilité actuelle inconnue",
      suspended: "Suspendu — option bloquée",
      unknown: "Inconnue — vérifier les faits actuels avant de choisir",
      unavailable: "Indisponible",
    },
  };
  check(
    crypto.createHash("sha256").update(input.axe_source).digest("hex") ===
      input.axe_sha256,
    "scanner_digest",
  );
  let current;
  const deadline = setTimeout(() => {
    if (current) void current.close();
  }, 480000);
  try {
    for (const actor of input.actors)
      for (const locale of ["en-CA", "fr-CA"]) {
        const row = {
          slot: actor.slot,
          locale,
          status: "failed",
          checks: {},
          cleanup: {},
          forbidden_write_attempts: 0,
        };
        rows.push(row);
        const profile = fs.mkdtempSync("/tmp/imp04-review-accessibility-");
        fs.chmodSync(profile, 0o700);
        let context,
          page,
          settings,
          stage = "launch";
        try {
          context = current = await chromium.launchPersistentContext(profile, {
            executablePath: "/opt/chrome-for-testing/chrome",
            headless: true,
            ignoreHTTPSErrors: false,
            viewport: { width: 1440, height: 1100 },
            timeout: 45000,
            args: [
              "--host-resolver-rules=" +
                input.actors
                  .map(
                    (a) =>
                      "MAP " +
                      new URL(a.origin).hostname +
                      " " +
                      input.address_pin,
                  )
                  .join(","),
            ],
          });
          context.setDefaultTimeout(45000);
          context.setDefaultNavigationTimeout(45000);
          check((await context.cookies()).length === 0, "fresh_cookie_context");
          row.checks.isolated_empty_cookie_context = true;
          // Read-only business scope is enforced before the first navigation.
          await context.route("**/v1/**", async (route) => {
            const request = route.request(),
              name = new URL(request.url()).pathname;
            const allowed =
              ["GET", "HEAD"].includes(request.method()) ||
              [
                "/v1/auth/review/login",
                "/v1/auth/logout",
                "/v1/review/view",
                "/v1/review/view/claim",
                "/v1/directory/search",
              ].includes(name);
            if (!allowed) {
              row.forbidden_write_attempts++;
              await route.abort("blockedbyclient");
            } else await route.continue();
          });
          stage = "browser_settings";
          settings = await context.newPage();
          await settings.goto("chrome://settings/appearance");
          const zoom = settings.locator("#zoomLevel");
          await zoom.selectOption("1");
          page = await context.newPage();
          let plan, reports, directory, identity, projectionRequest;
          const pending = new Set();
          page.on("response", (response) => {
            const name = new URL(response.url()).pathname;
            if (
              response.status() !== 200 ||
              !(
                /^\/v1\/plans\/[^/]+$/.test(name) ||
                name.endsWith("/own-reports") ||
                name === "/v1/directory/search" ||
                name === "/v1/auth/session"
              )
            )
              return;
            const task = response
              .json()
              .then((value) => {
                if (name === "/v1/auth/session") identity = value;
                else if (name === "/v1/directory/search") directory = value;
                else if (name.endsWith("/own-reports")) {
                  reports = value;
                  projectionRequest = {
                    path: name,
                    view: response.request().headers()["x-review-view"],
                  };
                } else {
                  plan = value;
                  projectionRequest = {
                    path: name,
                    view: response.request().headers()["x-review-view"],
                  };
                }
              })
              .catch(() => {});
            pending.add(task);
            void task.finally(() => pending.delete(task));
          });
          stage = "automatic_sign_in";
          const response = await page.goto(
            actor.origin + "/plans-review?locale=" + locale,
          );
          check(response?.status() === 200, "https_document");
          const security = await response.securityDetails();
          check(
            security && security.protocol.startsWith("TLS"),
            "verified_tls",
          );
          row.checks.verified_https = true;
          stage = "review_ready";
          await page
            .getByRole("heading", { name: labels[locale].title, exact: true })
            .waitFor({ timeout: 45000 });
          await page
            .getByText(labels[locale].ready, { exact: true })
            .waitFor({ timeout: 45000 });
          check(
            (await page.evaluate(() => document.documentElement.lang)) ===
              locale,
            "document_language",
          );
          stage = "workspace_ready";
          await page.waitForFunction(
            () => {
              const node = document.querySelector(
                'section[aria-labelledby="plans-title"] > [role="status"]',
              );
              return (
                node &&
                /Current information loaded|informations actuelles sont chargées/.test(
                  node.textContent,
                )
              );
            },
            undefined,
            { timeout: 45000 },
          );
          await Promise.all([...pending]);
          check(
            identity?.role === actor.role &&
              identity.assurance === "AL2" &&
              /^[0-9a-f-]{36}$/.test(identity.account_id),
            "actor_identity",
          );
          row.account_id = identity.account_id;
          row.checks.automatic_role_sign_in = true;
          stage = "populated_projection";
          const workspace = page.locator(
            'section[aria-labelledby="plans-title"]',
          );
          if (["pid", "worker1"].includes(actor.slot)) {
            await workspace
              .getByRole("heading", { name: labels[locale].plan, exact: true })
              .waitFor();
            check(plan?.fields?.length >= 2, "populated_plan");
            const names = [
              ...new Set(plan.fields.map((field) => field.field)),
            ].sort();
            check(
              JSON.stringify(names) ===
                JSON.stringify(
                  actor.slot === "pid"
                    ? ["plan.medication_report", "plan.strategies"]
                    : ["plan.strategies"],
                ),
              "exact_field_scope",
            );
            const strategies = plan.fields.filter(
              (field) => field.field === "plan.strategies",
            );
            check(
              strategies.length === 2 &&
                strategies.every((field) => field.verification === "disputed"),
              "disputed_reports_preserved",
            );
            check(
              (await workspace
                .getByRole("alert")
                .filter({ hasText: labels[locale].conflict })
                .count()) === 2,
              "conflict_live_regions",
            );
            row.projection = {
              kind: "plan",
              field_count: plan.fields.length,
              field_scope: names,
              disputed_count: strategies.length,
              revision: plan.revision,
            };
            if (actor.slot === "pid")
              check(
                plan.fields.some(
                  (field) =>
                    field.field === "plan.medication_report" &&
                    field.verification === "unverified",
                ),
                "medication_unverified",
              );
          } else {
            await workspace
              .getByRole("heading", { name: labels[locale].own, exact: true })
              .waitFor();
            check(
              reports?.items?.length >= 1 &&
                reports.items.every(
                  (report) =>
                    report.author_id === identity.account_id &&
                    report.verification === "unverified",
                ),
              "own_attributed_reports",
            );
            check(
              !plan &&
                (await workspace
                  .getByRole("heading", {
                    name: labels[locale].plan,
                    exact: true,
                  })
                  .count()) === 0,
              "no_pid_plan",
            );
            check(
              (await workspace
                .locator("#plan-words,#consent-recipient")
                .count()) === 0,
              "no_pid_authority_controls",
            );
            row.projection = {
              kind: "own_reports",
              count: reports.items.length,
              attributed_to_current_actor: true,
              unverified: true,
            };
          }
          row.checks.populated_authorized_projection = true;
          const initialProjection = crypto
            .createHash("sha256")
            .update(JSON.stringify(plan ?? reports))
            .digest("hex");
          stage = "populated_directory";
          const search = workspace.getByRole("button", {
            name: labels[locale].search,
            exact: true,
          });
          const searched = page.waitForResponse(
            (reply) =>
              new URL(reply.url()).pathname === "/v1/directory/search" &&
              reply.status() === 200,
          );
          await search.click();
          await searched;
          await workspace.locator("#directory-title").waitFor();
          await page.waitForFunction(
            () =>
              document.querySelectorAll(
                'section[aria-labelledby="directory-title"] h4',
              ).length === 4,
          );
          await Promise.all([...pending]);
          check(directory?.items?.length === 4, "four_directory_cases");
          check(
            directory.items
              .map((item) => item.id)
              .sort()
              .join(",") === input.directory_ids.sort().join(","),
            "exact_directory_fixture_set",
          );
          const directoryText = await workspace
            .locator('section[aria-labelledby="directory-title"]')
            .innerText();
          check(
            directoryText.includes(labels[locale].stale) &&
              directoryText.includes(labels[locale].suspended),
            "stale_suspended_wording",
          );
          // TTLs remain intact; availability must reflect the facts at test time.
          check(
            directory.items.filter((item) => item.state === "suspended")
              .length === 1,
            "suspended_case",
          );
          let unknownCount = 0,
            unavailableCount = 0;
          for (const item of directory.items) {
            const unavailable =
              item.state === "suspended" ||
              ["temporary_closure", "regional_outage"].includes(
                item.facts.operating_state,
              );
            const unknown =
              !unavailable &&
              (item.state !== "verified" ||
                Date.parse(item.expires_at) <= Date.now() ||
                item.facts.operating_state !== "normal_operations");
            check(unavailable || unknown, "expected_conservative_availability");
            const option = workspace
              .locator('section[aria-labelledby="directory-title"] > ul > li')
              .filter({
                has: page.getByRole("heading", {
                  name: item.facts.name,
                  exact: true,
                }),
              });
            check(
              (await option.locator(":scope > p > strong").innerText()) ===
                (unavailable
                  ? labels[locale].unavailable
                  : labels[locale].unknown),
              "availability_wording",
            );
            if (unavailable) unavailableCount++;
            else unknownCount++;
          }
          row.directory = {
            count: 4,
            states: directory.items.map((item) => ({
              state: item.state,
              expired: Date.parse(item.expires_at) <= Date.now(),
            })),
            ttl_preserved: true,
            unknown_availability: unknownCount,
            unavailable: unavailableCount,
          };
          row.checks.populated_directory = true;
          stage = "native_zoom";
          const baseline = await metrics(page);
          await zoom.selectOption("2");
          await page.waitForFunction(
            (dpr) => Math.abs(devicePixelRatio / dpr - 2) < 0.02,
            baseline.dpr,
          );
          const enlarged = await metrics(page);
          check(
            Math.abs(enlarged.width * 2 - baseline.width) <= 2 &&
              Math.abs(enlarged.outer - baseline.outer) <= 1 &&
              Math.abs(enlarged.pinch - baseline.pinch) < 0.01,
            "native_200_percent",
          );
          row.zoom = {
            baseline,
            enlarged,
            native_ratio: enlarged.dpr / baseline.dpr,
          };
          row.checks.native_browser_200_percent = true;
          stage = "layout";
          row.layout = await page.evaluate(() => {
            const visible = (node) =>
              !!(
                node.getClientRects().length &&
                !node.closest("[hidden],[inert]")
              );
            const controls = [
              ...document.querySelectorAll(
                "button,input,select,textarea,summary,a[href]",
              ),
            ].filter(visible);
            const clipped = controls.filter((node) => {
              const r = node.getBoundingClientRect();
              return (
                r.left < -1 ||
                r.right > innerWidth + 1 ||
                r.width < 1 ||
                r.height < 1
              );
            });
            return {
              viewport_width: innerWidth,
              document_width: document.documentElement.scrollWidth,
              visible_controls: controls.length,
              clipped_controls: clipped.map((node) => ({
                tag: node.tagName,
                id: node.id,
              })),
            };
          });
          check(
            row.layout.document_width <= row.layout.viewport_width + 1 &&
              !row.layout.clipped_controls.length,
            "no_horizontal_clipping",
          );
          row.checks.layout_at_200_percent = true;
          stage = "keyboard";
          const focusable = await page.evaluate(
            () =>
              [
                ...document.querySelectorAll(
                  "button,input,select,textarea,summary,a[href]",
                ),
              ].filter(
                (node) =>
                  !node.disabled &&
                  node.tabIndex >= 0 &&
                  node.getClientRects().length &&
                  !node.closest("[hidden],[inert]"),
              ).length,
          );
          await page.locator("#review-language").focus();
          const visited = new Set();
          let invalidFocus = 0;
          // Native datetime-local controls contain several internal Tab stops
          // sharing one DOM activeElement. Bound traversal without treating those
          // standard browser stops as an application focus trap.
          for (let i = 0; i < focusable * 6 + 5; i++) {
            await page.keyboard.press("Tab");
            const state = await page.evaluate(() => {
              const node = document.activeElement;
              if (!node || node === document.body) return { body: true };
              const r = node.getBoundingClientRect();
              const label = node.labels?.length
                ? [...node.labels].map((item) => item.textContent).join(" ")
                : "";
              const name =
                node.getAttribute("aria-label") ||
                label ||
                node.textContent ||
                "";
              const candidates = [
                ...document.querySelectorAll(
                  "button,input,select,textarea,summary,a[href]",
                ),
              ];
              return {
                index: candidates.indexOf(node),
                named: !!name.trim(),
                visible:
                  r.width > 0 &&
                  r.height > 0 &&
                  r.left >= -1 &&
                  r.right <= innerWidth + 1 &&
                  r.bottom > 0 &&
                  r.top < innerHeight,
              };
            });
            if (!state.body) {
              visited.add(state.index);
              if (!state.named || !state.visible) invalidFocus++;
            }
            if (visited.size === focusable) break;
          }
          row.keyboard = {
            focusable_controls: focusable,
            distinct_controls_reached: visited.size,
            unnamed_or_offscreen_focus: invalidFocus,
            reverse_tab_exercised: true,
          };
          check(
            visited.size === focusable && invalidFocus === 0,
            "keyboard_reachable_named_visible",
          );
          await page.keyboard.press("Shift+Tab");
          row.checks.keyboard_at_200_percent = true;
          stage = "axe";
          await page.evaluate(input.axe_source);
          check(
            (await page.evaluate(() => window.axe.version)) === "4.14.0",
            "scanner_version",
          );
          const axe = await page.evaluate(async () => {
            const result = await window.axe.run(document, {
              runOnly: {
                type: "tag",
                values: ["wcag2a", "wcag2aa", "wcag21aa"],
              },
            });
            return {
              violations: result.violations.map((item) => ({
                id: item.id,
                impact: item.impact,
                nodes: item.nodes.length,
              })),
              passed: result.passes.length,
              incomplete: result.incomplete.map((item) => ({
                id: item.id,
                nodes: item.nodes.length,
              })),
            };
          });
          row.axe = axe;
          check(!axe.violations.length, "axe_no_violations");
          row.checks.axe_at_200_percent = true;
          stage = "durable_projection_unchanged";
          await Promise.all([...pending]);
          const reread = await page.evaluate(async (request) => {
            const reply = await fetch(request.path, {
              credentials: "include",
              cache: "no-store",
              redirect: "error",
              headers: { "X-Review-View": request.view },
              signal: AbortSignal.timeout(10000),
            });
            return { status: reply.status, body: await reply.json() };
          }, projectionRequest);
          check(
            reread.status === 200 &&
              initialProjection ===
                crypto
                  .createHash("sha256")
                  .update(JSON.stringify(reread.body))
                  .digest("hex"),
            "projection_unchanged",
          );
          check(
            row.forbidden_write_attempts === 0,
            "no_business_write_attempts",
          );
          row.checks.no_business_writes = true;
          row.status = "passed";
        } catch (error) {
          row.stage = stage;
          row.error_category =
            error.name === "QualificationAssertion"
              ? error.message
              : error.name === "TimeoutError"
                ? "driver_timeout"
                : "driver_error";
        } finally {
          if (page)
            try {
              // Delete only this isolated context's session, never a shared actor session.
              // Unload React first, so its recovery loop cannot create another session.
              await page.route("**/*.js", (route) =>
                route.abort("blockedbyclient"),
              );
              await page.goto(actor.origin + "/plans-review");
              const logout = await page.evaluate(async () => {
                const proof = await fetch("/v1/auth/csrf", {
                  credentials: "include",
                  signal: AbortSignal.timeout(5000),
                });
                if (!proof.ok)
                  return { passed: false, csrf_status: proof.status };
                const csrf = await proof.json();
                const reply = await fetch("/v1/auth/logout", {
                  method: "POST",
                  credentials: "include",
                  headers: {
                    "Content-Type": "application/json",
                    "X-CSRF-Token": csrf.csrf_token,
                    "Idempotency-Key": crypto.randomUUID(),
                  },
                  body: "{}",
                  signal: AbortSignal.timeout(5000),
                });
                if (!reply.ok)
                  return {
                    passed: false,
                    csrf_status: proof.status,
                    logout_status: reply.status,
                  };
                const current = await fetch("/v1/auth/session", {
                  credentials: "include",
                  cache: "no-store",
                  signal: AbortSignal.timeout(5000),
                });
                return {
                  passed: current.status === 401,
                  csrf_status: proof.status,
                  logout_status: reply.status,
                  session_after_logout: current.status,
                };
              });
              row.cleanup_http = logout;
              row.cleanup.logout = logout.passed;
            } catch {
              row.cleanup.logout = false;
            }
          if (settings)
            try {
              await settings.locator("#zoomLevel").selectOption("1");
              row.cleanup.zoom_restored = true;
            } catch {
              row.cleanup.zoom_restored = false;
            }
          if (context)
            try {
              await context.close();
              row.cleanup.context_closed = true;
              current = undefined;
            } catch {
              row.cleanup.context_closed = false;
            }
          if (!context || row.cleanup.context_closed) {
            fs.rmSync(profile, { recursive: true, force: true });
            row.cleanup.profile_removed = true;
          }
          if (Object.values(row.cleanup).some((value) => value !== true))
            row.status = "failed";
        }
        if (current) throw new Error("owned_context_cleanup_failed");
      }
    process.stdout.write(
      JSON.stringify({ version: input.version, observations: rows }),
    );
  } finally {
    clearTimeout(deadline);
  }
}

function main() {
  const output = process.argv[2];
  if (
    !output ||
    !path.isAbsolute(output) ||
    fs.existsSync(output) ||
    path.dirname(output) !==
      "/private/tmp/imp04-closure-pr-20261120/accessibility"
  )
    throw Error("new_private_output_required");
  fs.mkdirSync(path.dirname(output), { recursive: true, mode: 0o700 });
  const info = fs.lstatSync(path.dirname(output));
  if (
    !info.isDirectory() ||
    info.isSymbolicLink() ||
    info.mode & 0o077 ||
    info.uid !== process.getuid()
  )
    throw Error("owner_only_evidence_directory_required");
  const privateRoot = "/private/tmp/care-link-imp04-002";
  const configPath = path.join(privateRoot, "browser.json");
  const configInfo = fs.lstatSync(configPath);
  if (
    !configInfo.isFile() ||
    configInfo.isSymbolicLink() ||
    configInfo.mode & 0o077 ||
    configInfo.uid !== process.getuid()
  )
    throw Error("owner_only_browser_capability_required");
  const browser = JSON.parse(fs.readFileSync(configPath, "utf8"));
  if (browser.ignoreHTTPSErrors === true)
    throw Error("verified_https_required");
  const fixtures = JSON.parse(
    fs.readFileSync(
      "/private/tmp/imp04-review-restart-20261120/activation-fixtures.json",
      "utf8",
    ),
  );
  if (
    fixtures.target_id !== "care-link-imp04-002" ||
    fixtures.state !== "ready" ||
    Date.parse(fixtures.expires_at) <= Date.now()
  )
    throw Error("active_exact_synthetic_run_required");
  const route = spawnSync(
    ".venv/bin/python",
    ["-m", "tools.imp04_verification.browser_route"],
    { encoding: "utf8", timeout: 20000 },
  );
  if (route.status !== 0) throw Error("owned_browser_route_unavailable");
  const binding = JSON.parse(route.stdout);
  const axeRequire = createRequire(require.resolve("@axe-core/playwright"));
  const axeFile = fs.realpathSync(axeRequire.resolve("axe-core/axe.min.js"));
  if (
    axeRequire("axe-core/package.json").version !== "4.14.0" ||
    !axeFile.startsWith(fs.realpathSync("node_modules") + path.sep)
  )
    throw Error("locked_scanner_required");
  const axe = fs.readFileSync(axeFile, "utf8");
  const input = {
    version: "imp04.review-accessibility.v1",
    address_pin: binding.address,
    actors: Object.entries(fixtures.actors).map(([slot, actor]) => ({
      slot,
      origin: actor.origin,
      role: actor.role,
    })),
    directory_ids: Object.values(fixtures.directory_service_ids),
    axe_source: axe,
    axe_sha256: crypto.createHash("sha256").update(axe).digest("hex"),
  };
  for (const actor of input.actors) {
    const url = new URL(actor.origin);
    if (
      url.protocol !== "https:" ||
      url.port !== "30443" ||
      url.hostname !==
        "r" +
          fixtures.run_id.replaceAll("-", "") +
          "-" +
          actor.slot +
          ".plans.localhost"
    )
      throw Error("exact_run_origin_required");
  }
  if (
    input.actors
      .map((actor) => actor.slot)
      .sort()
      .join(",") !== "carer,pid,professional,worker1"
  )
    throw Error("four_actor_matrix_required");
  const result = spawnSync(
    "docker",
    [
      "exec",
      "--interactive",
      binding.browser_id,
      "node",
      "-e",
      "(" +
        browserRun.toString() +
        ')().catch(()=>{process.stdout.write(JSON.stringify({error:"runner_failed"}));process.exitCode=1;})',
    ],
    {
      input: JSON.stringify(input),
      encoding: "utf8",
      timeout: 520000,
      maxBuffer: 4 * 1024 * 1024,
    },
  );
  if (result.status !== 0) throw Error("isolated_browser_runner_failed");
  const evidence = JSON.parse(result.stdout);
  if (evidence.version !== input.version || evidence.observations?.length !== 8)
    throw Error("eight_observations_required");
  evidence.generated_at = new Date().toISOString();
  evidence.run_id = fixtures.run_id;
  evidence.axe_version = "4.14.0";
  evidence.axe_sha256 = input.axe_sha256;
  evidence.harness_sha256 = crypto
    .createHash("sha256")
    .update(fs.readFileSync(__filename))
    .digest("hex");
  evidence.human_review = false;
  evidence.status = evidence.observations.every(
    (row) => row.status === "passed",
  )
    ? "passed"
    : "failed";
  fs.writeFileSync(output, JSON.stringify(evidence, null, 2) + "\n", {
    mode: 0o600,
    flag: "wx",
  });
  console.log(
    JSON.stringify({
      status: evidence.status,
      rows: evidence.observations.length,
      passed: evidence.observations.filter((row) => row.status === "passed")
        .length,
      evidence: output,
    }),
  );
  process.exitCode = evidence.status === "passed" ? 0 : 1;
}
try {
  main();
} catch (error) {
  console.error(
    error.message.match(/^[a-z_]+$/)
      ? error.message
      : "qualification_runner_failed",
  );
  process.exitCode = 1;
}
