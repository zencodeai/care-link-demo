import { expect, test } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  evidenceDirectory,
  readConfig,
  slots,
  type Row,
  type Slot,
} from "./config";
import { Toolkit } from "./toolkit";
import { ActorPage } from "./browser";
import { ensureFreshMfa, signIn } from "./auth";
import {
  createConversation,
  disclosureAndIntake,
  handshake,
  reserveAndAccept,
  sendMessage,
  supervisorTakeover,
} from "./journey";
import { draftRecovery, duplicateTab, unknownReply } from "./recovery";
import { closedRun, crossRun, type PreviousRun } from "./isolation";
import { reviewPageAccessibility } from "./accessibility";
import { captureFailurePages, observeResponses } from "./diagnostics";

const config = readConfig();
const output = evidenceDirectory();
test("three fresh visible review runs share one genuine Chrome profile", async ({
  browser,
}) => {
  expect(
    browser.version(),
    "The connected browser is the exact accepted Chrome for Testing version",
  ).toBe(config.expectedBrowserVersion);
  const toolkit = new Toolkit(config);
  const context = await browser.newContext({ ignoreHTTPSErrors: false });
  const completed: Row[] = [];
  const reviewPageChecks: Row[] = [];
  let phase = "initial",
    activeRun: string | null = null;
  let previous: PreviousRun | null = null;
  const checkpoint = (value: string) => {
    phase = value;
    process.stdout.write("Review checkpoint: " + value + "\n");
  };
  try {
    for (let repetition = 1; repetition <= 3; repetition += 1) {
      checkpoint(`run_${repetition}_create`);
      const run = await toolkit.create();
      activeRun = run.id;
      const actors = {} as Record<Slot, ActorPage>;
      for (const slot of slots)
        actors[slot] = new ActorPage(
          await context.newPage(),
          run.actors[slot],
          run.id,
        );
      const participant = actors.participant,
        worker = actors.worker1,
        secondWorker = actors.worker2,
        supervisor = actors.supervisor;
      const responses = observeResponses(actors);
      try {
        for (const slot of slots) {
          checkpoint(`run_${repetition}_login_${slot}`);
          await signIn(actors[slot], toolkit);
        }
        if (repetition === 1)
          await reviewPageAccessibility(actors, reviewPageChecks, checkpoint);
        if (previous) {
          checkpoint(`run_${repetition}_cross_run_denial`);
          await crossRun(participant, previous);
          await secondWorker.button("Refresh queue").click();
          await expect(
            secondWorker.page
              .locator(".manual-queue")
              .getByText(previous.sessionId, { exact: true }),
          ).toHaveCount(0);
        }
        checkpoint(`run_${repetition}_create_conversation`);
        const id = await createConversation(participant);
        checkpoint(`run_${repetition}_draft_reload_reauth`);
        await draftRecovery(
          participant,
          [worker, secondWorker, supervisor],
          toolkit,
        );
        checkpoint(`run_${repetition}_duplicate_observer_claim`);
        await duplicateTab(participant);
        checkpoint(`run_${repetition}_disclosure_request_intake`);
        await disclosureAndIntake(participant, id);
        checkpoint(`run_${repetition}_assignment_reload`);
        const freshMfa: string[] = [];
        if (await ensureFreshMfa(worker, toolkit))
          freshMfa.push("worker1_before_assignment");
        await reserveAndAccept(worker, id);
        checkpoint(`run_${repetition}_real_expiry_and_two_party_confirmation`);
        if (await ensureFreshMfa(worker, toolkit))
          freshMfa.push("worker1_before_confirmation");
        await handshake(participant, worker, id, true);
        checkpoint(`run_${repetition}_visible_manual_exchange`);
        const first = await sendMessage(
          participant,
          worker,
          id,
          "participant manual message",
        );
        const second = await sendMessage(
          worker,
          participant,
          id,
          "assigned worker manual message",
        );
        checkpoint(`run_${repetition}_unknown_commit_reply_reload`);
        const unknown = await unknownReply(participant, worker, id);
        checkpoint(`run_${repetition}_observe_interrupt_takeover`);
        if (await ensureFreshMfa(supervisor, toolkit))
          freshMfa.push("supervisor_before_interrupt");
        await supervisorTakeover(supervisor, worker, participant, id);
        checkpoint(`run_${repetition}_close`);
        await toolkit.close(run);
        checkpoint(`run_${repetition}_closed_status_recovery`);
        await closedRun(participant, toolkit, unknown.operation_id);
        completed.push({
          repetition,
          run_id: run.id,
          session_id: id,
          actual_slots: [...slots],
          browser_context_reused: true,
          message_ids: [first.messageId, second.messageId, unknown.message_id],
          unknown_reply: unknown,
          explicit_fresh_mfa_ceremonies: freshMfa,
          observations: [
            "four_visible_password_mfa_logins",
            "server_draft_reload_and_reauthentication",
            "slot_signout_preserves_other_actors",
            "duplicate_tab_observer_explicit_claim",
            "visible_exact_disclosure_and_human_request",
            "visible_fictional_intake",
            "reserved_and_accepted_assignment_recovered",
            "actual_30_second_expiry_and_fresh_preparation",
            "visible_two_party_channel_confirmation",
            "visible_attributed_manual_exchange",
            "dropped_committed_http_reply_recovered_by_original_key_once",
            "supervisor_observe_then_explicit_interrupt_reload_and_takeover",
            "old_owner_blocked",
            "closed_run_status_only_reauthentication",
            ...(previous ? ["previous_run_record_and_operation_denied"] : []),
          ],
        });
        previous = {
          runId: run.id,
          sessionId: id,
          operationId: unknown.operation_id,
        };
        activeRun = null;
      } catch (error) {
        try {
          await captureFailurePages(output, phase, actors, responses);
        } catch {
          // Diagnostics must preserve the original failure.
        }
        throw error;
      } finally {
        await Promise.all(slots.map((slot) => actors[slot].page.close()));
      }
    }
    checkpoint("completed");
    writeFileSync(
      resolve(output, "observations.json"),
      JSON.stringify(
        {
          suite: "ordinary-tab-review-recovery",
          status: "passed",
          browser: "Google Chrome for Testing",
          browser_version: browser.version(),
          browser_tls_verification: true,
          shared_browser_contexts: 1,
          fresh_runs_completed: completed.length,
          cookie_or_cache_clearing: false,
          retries: 0,
          runs: completed,
          review_page_accessibility_and_locale: reviewPageChecks,
          human_acceptance: false,
          scope:
            "Three successive CLI-created runs in one ordinary-tab browser context. Business actions through visible UI; supplemental real API negative/status assertions. Durable database counts supplied separately by coordinator.",
        },
        null,
        2,
      ),
      { mode: 0o600, flag: "wx" },
    );
  } catch (error) {
    writeFileSync(
      resolve(output, "failure.txt"),
      error instanceof Error
        ? (error.stack ?? error.message)
        : "Non-Error failure; no private value rendered",
      { mode: 0o600, flag: "wx" },
    );
    writeFileSync(
      resolve(output, "observations.json"),
      JSON.stringify(
        {
          suite: "ordinary-tab-review-recovery",
          status: "failed",
          phase,
          browser_version: browser.version(),
          fresh_runs_completed: completed.length,
          run_under_test_preserved: activeRun,
          completed_runs: completed,
          review_page_accessibility_and_locale: reviewPageChecks,
          cookie_or_cache_clearing: false,
          retries: 0,
          human_acceptance: false,
        },
        null,
        2,
      ),
      { mode: 0o600, flag: "wx" },
    );
    // eslint-disable-next-line preserve-caught-error -- Raw stack stays only in owner-only failure.txt.
    throw new Error(
      `Actual ordinary-tab review run failed at ${phase}; private details suppressed; inspect retained private results and exact active run`,
    );
  } finally {
    await context.close();
  }
});
