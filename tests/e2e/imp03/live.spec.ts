import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { providerLogin } from "../imp02/browser";
import { browserRequest, prepareBarrierMutation } from "./request";
import {
  evidenceDirectory,
  readConfig,
  privateFile,
  type Role,
} from "./config";

const lab = readConfig();
const output = evidenceDirectory();
function checkpoint(stage: string) {
  writeFileSync(resolve(output, "progress.json"), JSON.stringify({ stage }), {
    mode: 0o600,
  });
}
type Row = Record<string, unknown>;
function row(value: unknown): Row {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Invalid live server projection; private body suppressed");
  return value as Row;
}
function field(value: Row, name: string): string {
  if (typeof value[name] !== "string")
    throw new Error("Missing live projection field: " + name);
  return value[name];
}
// Responses stay inside browser memory. Assertion output never includes bodies,
// cookies, authorization URLs, continuation tokens or private message text.
async function request(
  page: Page,
  path: string,
  body?: Row,
  key?: string,
  preparedMutation = false,
) {
  return page.evaluate(browserRequest, {
    path,
    body,
    key,
    preparedMutation,
  });
}
async function ok(
  page: Page,
  path: string,
  body?: Row,
  key?: string,
): Promise<Row> {
  const response = await request(page, path, body, key);
  const failure = row(response.value ?? {});
  const reason =
    typeof failure.message_key === "string" &&
    /^manual\.[a-z_]+$/.test(failure.message_key)
      ? failure.message_key
      : "private_body_suppressed";
  expect(
    response.status,
    `Actual protected request must succeed: ${path.split("?")[0]} (${reason})`,
  ).toBe(200);
  return row(response.value);
}
async function login(page: Page, role: Role) {
  checkpoint(role + "_shell");
  await page.goto(lab.mainOrigin);
  checkpoint(role + "_login_intent");
  const intent = await ok(page, "/v1/auth/login", {
    role,
    return_route: role === "pid" ? "participant" : "workforce",
    locale: "en-CA",
  });
  const url = field(intent, "authorization_url");
  if (new URL(url).origin !== lab.oidcOrigin)
    throw new Error("Unexpected provider origin");
  await providerNavigate(page, url);
  checkpoint(role + "_provider_challenge");
  await providerLogin(
    page,
    lab,
    role === "pid"
      ? lab.participant
      : role === "worker"
        ? lab.worker
        : lab.supervisor,
    lab.mainOrigin,
  );
  const actor = await ok(page, "/v1/auth/session");
  checkpoint(role + "_current_session");
  expect(
    actor.account_id === lab.accounts[role] && actor.role === role,
    "Provider must resolve exact separately issued account and role",
  ).toBe(true);
  await page
    .getByRole("button", { name: "Check manual access", exact: true })
    .click();
  await expect(
    page.getByText(`Current signed-in role: ${role}`, { exact: true }),
  ).toBeVisible();
  return actor;
}
async function providerNavigate(page: Page, url: string) {
  if (new URL(url).origin !== lab.oidcOrigin)
    throw new Error("Unexpected provider origin");
  try {
    await page.goto(url);
  } catch {
    throw new Error("Provider navigation failed; authorization URL suppressed");
  }
}
async function stream(page: Page, sid: string) {
  await page.evaluate(async (sid) => {
    const container = window as unknown as { g03Stream?: EventSource };
    container.g03Stream?.close();
    await new Promise<void>((resolve, reject) => {
      const source = new EventSource(`/v1/sessions/${sid}/events`);
      container.g03Stream = source;
      const deadline = setTimeout(() => {
        source.close();
        reject(new Error("Live SSE did not open"));
      }, 15_000);
      source.onopen = () => {
        clearTimeout(deadline);
        resolve();
      };
      source.onerror = () => {
        clearTimeout(deadline);
        source.close();
        reject(new Error("Live SSE denied"));
      };
    });
  }, sid);
}
async function closeStream(page: Page) {
  await page.evaluate(() =>
    (window as unknown as { g03Stream?: EventSource }).g03Stream?.close(),
  );
}
async function create(page: Page) {
  checkpoint("ui_create");
  const response = page.waitForResponse(
    (reply) =>
      reply.url() === lab.mainOrigin + "/v1/sessions" &&
      reply.request().method() === "POST",
  );
  await page
    .getByRole("button", {
      name: "Start a fictional conversation",
      exact: true,
    })
    .click();
  const reply = await response;
  const result = row((await reply.json()) as unknown);
  const reason =
    typeof result.message_key === "string" &&
    /^manual\.[a-z_]+$/.test(result.message_key)
      ? result.message_key
      : "private_body_suppressed";
  expect(
    reply.status(),
    `Actual UI conversation creation succeeds (${reason})`,
  ).toBe(200);
  // Reload the real shell with its client bundle blocked before opening
  // controlled SSE endpoints. The server's shell CSP permits same-origin
  // fetches; its JSON responses deliberately do not. No API is intercepted.
  await page.route("**/assets/*.js", (route) => route.abort("blockedbyclient"));
  await page.goto(lab.mainOrigin);
  checkpoint("controlled_shell");
  return result;
}

test("G-03 live protected service and adverse barriers", async ({
  browser,
}) => {
  const phase = process.env.CARE_LINK_IMP03_PHASE ?? "normal";
  const phases = [
    "normal",
    "identity-loss",
    "pdp-loss",
    "journal-loss",
    "audit-loss",
    "fenced",
  ];
  if (!phases.includes(phase)) throw new Error("Unknown live phase");
  const contexts = await Promise.all([
    browser.newContext({ ignoreHTTPSErrors: lab.ignoreHTTPSErrors }),
    browser.newContext({ ignoreHTTPSErrors: lab.ignoreHTTPSErrors }),
    browser.newContext({ ignoreHTTPSErrors: lab.ignoreHTTPSErrors }),
  ]);
  try {
    const pages = await Promise.all(
      contexts.map((context) => context.newPage()),
    );
    const participant = pages[0]!,
      worker = pages[1]!,
      supervisor = pages[2]!;
    await login(participant, "pid");
    await login(worker, "worker");
    await login(supervisor, "supervisor");
    const session = await create(participant);
    const sid = field(session, "id");
    const sessionPath = `/v1/sessions/${sid}`;
    const observations: string[] = [
      "three_current_provider_accounts",
      "signed_remote_session_create",
    ];
    const barrierRequests: {
      method: string;
      path: string;
      status: number;
    }[] = [];
    if (phase !== "normal") {
      // Operator pauses/restricts the exact leased dependency only after all
      // actors sign in and protected success is established. No mock response.
      const mutationPath = sessionPath + "/human-request";
      expect(
        await participant.evaluate(prepareBarrierMutation, mutationPath),
        "Valid CSRF proof is obtained before any dependency fault",
      ).toBe(200);
      const nonce = randomUUID();
      writeFileSync(
        resolve(output, "barrier-ready.json"),
        JSON.stringify({ session: "imp03-002", phase, nonce }),
        { mode: 0o600, flag: "wx" },
      );
      const applied = resolve(output, "barrier-applied.json");
      await expect
        .poll(
          () => {
            if (!existsSync(applied)) return false;
            privateFile(applied);
            const value = row(
              JSON.parse(readFileSync(applied, "utf8")) as unknown,
            );
            return value.nonce === nonce && value.phase === phase;
          },
          {
            timeout: 120_000,
            message: "Waiting for actual operator dependency barrier receipt",
          },
        )
        .toBe(true);
      const denied = await request(participant, sessionPath);
      expect(
        [401, 403, 503].includes(denied.status),
        "Protected read must fail closed behind the actual barrier",
      ).toBe(true);
      const mutationKey = randomUUID();
      const actualPost = participant.waitForRequest(
        (sent) =>
          sent.method() === "POST" &&
          sent.url() === lab.mainOrigin + mutationPath &&
          sent.headers()["idempotency-key"] === mutationKey,
      );
      const [command] = await Promise.all([
        request(
          participant,
          mutationPath,
          { expected_revision: session.revision, reason: "user_requested" },
          mutationKey,
          true,
        ),
        actualPost,
      ]);
      expect(
        command.attempted?.method === "POST" &&
          command.attempted.path === mutationPath,
        "Barrier result belongs to the intended mutation, not CSRF bootstrap",
      ).toBe(true);
      expect(
        [401, 403, 503].includes(command.status),
        "Protected mutation must fail closed behind the actual barrier",
      ).toBe(true);
      barrierRequests.push(
        { method: "GET", path: sessionPath, status: denied.status },
        { method: "POST", path: mutationPath, status: command.status },
      );
      const staticResponse = await participant.request.get(
        lab.staticOrigin + "/fallback",
      );
      expect(
        staticResponse.status(),
        "Independent static fallback remains available",
      ).toBe(200);
      const helpResponse = await participant.request.get(
        lab.helpOrigin + "/private-help",
      );
      expect(
        helpResponse.status(),
        "Independent help UI shell remains available; no authenticated help or connection claim",
      ).toBe(200);
      observations.push(
        phase + "_denies_protected_read_and_mutation",
        "independent_static_and_help_shell_available",
      );
    } else {
      const stranger = await browser.newContext({
        ignoreHTTPSErrors: lab.ignoreHTTPSErrors,
      });
      try {
        const denied = await stranger.request.get(lab.mainOrigin + sessionPath);
        expect(denied.status()).toBe(401);
      } finally {
        await stranger.close();
      }
      const queue = await ok(participant, sessionPath + "/human-request", {
        expected_revision: session.revision,
        reason: "user_requested",
      });
      const reservation = await ok(worker, sessionPath + "/workforce/reserve", {
        expected_revision: queue.revision,
        worker_id: lab.accounts.worker,
      });
      const assignment = await ok(worker, sessionPath + "/workforce/accept", {
        expected_revision: reservation.revision,
      });
      expect(
        assignment.state === "accepted" &&
          (await ok(worker, sessionPath)).service_phase === "worker_assigned",
        "Queue acceptance never implies connection",
      ).toBe(true);
      await ok(worker, sessionPath + "/workforce/prepare-transfer", {
        expected_revision: assignment.revision,
      });
      await stream(participant, sid);
      await stream(worker, sid);
      const acks: Record<string, { body: Row; key: string }> = {};
      for (const [name, page] of [
        ["worker", worker],
        ["participant", participant],
      ] as const) {
        const challenge = await ok(page, sessionPath + "/workforce/challenge");
        const current = await ok(page, sessionPath);
        const body = {
          expected_revision: current.revision,
          challenge_id: challenge.challenge_id,
          nonce: challenge.nonce,
          transport_generation: challenge.transport_generation,
          expected_control_epoch: challenge.control_epoch,
        };
        const key = randomUUID();
        const ack = await ok(
          page,
          sessionPath + "/workforce/channel-acks",
          body,
          key,
        );
        if (name === "worker") expect(ack.state).toBe("one_party_acknowledged");
        acks[name] = { body, key };
      }
      const ack = await ok(
        worker,
        sessionPath + "/workforce/channel-acks",
        acks.worker!.body,
        acks.worker!.key,
      );
      expect(ack.state).toBe("two_party_confirmed");
      const pending = await ok(worker, sessionPath);
      const connected = await ok(
        worker,
        sessionPath + "/workforce/confirm-transfer",
        {
          expected_revision: pending.revision,
          assignment_id: assignment.id,
          channel_evidence_id: ack.evidence_id,
          worker_ack_id: ack.ack_id,
          expected_control_epoch: pending.control_epoch,
        },
      );
      expect(connected.transport).toBe("connected");
      const message = await ok(worker, sessionPath + "/messages", {
        expected_revision: connected.revision,
        expected_control_epoch: connected.control_epoch,
        text: "Fictional G-03 manual response.",
        accepted_draft_id: null,
      });
      expect(message.kind).toBe("human_authored");
      const messages = await ok(participant, sessionPath + "/messages");
      expect(
        Array.isArray(messages.items) &&
          messages.items.some((item: unknown) => row(item).id === message.id),
        "Participant receives the actual attributed message",
      ).toBe(true);
      await closeStream(participant);
      await expect
        .poll(async () => (await ok(worker, sessionPath)).transport)
        .toBe("disconnected");
      const queuePage = await ok(supervisor, "/v1/workforce/queue");
      if (!Array.isArray(queuePage.items))
        throw new Error("Invalid actual queue page");
      const before = row(
        queuePage.items.find((item: unknown) => row(item).session_id === sid),
      );
      await ok(supervisor, sessionPath + "/workforce/observe", {
        expected_revision: before.revision,
        scope: "interrupt",
        expires_at: new Date(Date.now() + 60_000).toISOString(),
      });
      const observed = await ok(supervisor, sessionPath);
      const taken = await ok(supervisor, sessionPath + "/workforce/takeover", {
        expected_revision: observed.revision,
        worker_id: lab.accounts.supervisor,
      });
      expect(
        BigInt(field(taken, "control_epoch")) >
          BigInt(field(connected, "control_epoch")) &&
          taken.service_phase === "worker_assigned",
        "Takeover fences old epoch and requires new handshake",
      ).toBe(true);
      const stale = await request(worker, sessionPath + "/messages", {
        expected_revision: taken.revision,
        expected_control_epoch: connected.control_epoch,
        text: "Fictional stale response.",
        accepted_draft_id: null,
      });
      expect(
        [403, 404, 409].includes(stale.status),
        "Old worker cannot send after takeover",
      ).toBe(true);
      await closeStream(worker);
      observations.push(
        "two_party_real_sse_handshake",
        "manual_message",
        "disconnect_truth",
        "takeover_fences_previous_owner",
      );

      const current = await ok(participant, sessionPath);
      const family = await ok(participant, sessionPath + "/continuations", {
        expected_revision: current.revision,
      });
      const rotation = {
        session_id: sid,
        family_id: family.family_id,
        token: family.token,
        channel: "web",
        expected_revision: "1",
      };
      const rotationKey = randomUUID();
      await participant.route("**/v1/continuations/rotate", async (route) => {
        let committed;
        try {
          committed = await route.fetch();
        } catch {
          throw new Error(
            "Live commit request failed; private call details suppressed",
          );
        }
        expect(
          committed.status(),
          "Server commits before transport acknowledgement is dropped",
        ).toBe(200);
        await route.abort("failed");
      });
      expect(
        (
          await request(
            participant,
            "/v1/continuations/rotate",
            rotation,
            rotationKey,
          )
        ).status,
      ).toBe(0);
      await participant.unroute("**/v1/continuations/rotate");
      const status = await ok(participant, "/v1/operations/" + rotationKey);
      expect(
        ["committed", "replacement_unavailable"].includes(
          field(status, "state"),
        ),
      ).toBe(true);
      expect(
        (
          await request(
            participant,
            "/v1/continuations/rotate",
            rotation,
            rotationKey,
          )
        ).status,
      ).toBe(409);
      const identity = await ok(participant, "/v1/auth/session");
      const ceremony = await ok(participant, "/v1/auth/continuation-recovery", {
        session_id: sid,
        family_id: family.family_id,
        expected_revision: identity.revision,
      });
      await providerNavigate(participant, field(ceremony, "authorization_url"));
      await providerLogin(participant, lab, lab.participant, lab.mainOrigin);
      const proof = await ok(
        participant,
        "/v1/auth/step-up/proof?ceremony_id=" + field(ceremony, "ceremony_id"),
      );
      await ok(participant, "/v1/auth/step-up/confirm", {
        ceremony_id: ceremony.ceremony_id,
        proof_intent_id: proof.proof_intent_id,
        expected_revision: identity.revision,
      });
      const recovered = await ok(participant, "/v1/continuations/recover", {
        session_id: sid,
        family_id: family.family_id,
        ceremony_id: ceremony.ceremony_id,
        channel: "web",
        expected_revision: "1",
      });
      expect(
        recovered.assurance === "AL0" &&
          recovered.family_id !== family.family_id,
        "Fresh exact provider ceremony replaces the lost family without assurance upgrade",
      ).toBe(true);
      observations.push(
        "committed_rotation_ack_dropped",
        "original_key_reconciliation",
        "fresh_provider_recovery",
      );
    }
    writeFileSync(
      resolve(output, "observations.json"),
      JSON.stringify(
        {
          session: "imp03-002",
          phase,
          status: "passed",
          observations,
          barrier_requests: barrierRequests,
          human_acceptance: false,
        },
        null,
        2,
      ),
      { mode: 0o600, flag: "wx" },
    );
  } finally {
    await Promise.all(contexts.map((context) => context.close()));
  }
});
