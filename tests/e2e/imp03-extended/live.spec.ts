import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { evidenceDirectory } from "../imp03/config";
import {
  object,
  readExtendedConfig,
  readLocale,
  type ActorName,
} from "./config";
import {
  checkpoint,
  closeStream,
  login,
  observeSignals,
  ok,
  park,
} from "./helpers";
import { intake } from "./intake";
import { connect, reserveRace, type Worker } from "./ownership";
import { bufferedReply } from "./buffered";
import { revokeAcl } from "./revocation";

const lab = readExtendedConfig();
const output = evidenceDirectory();
const locale = readLocale();
test("G-03 extended current-authority scenarios", async ({ browser }) => {
  const mode = process.env.CARE_LINK_IMP03_EXTENDED_CASE ?? "all";
  if (!["all", "ui", "race", "buffered", "revocation"].includes(mode))
    throw new Error("Unknown exact extended case");
  const names: ActorName[] = ["pid"];
  if (["all", "race", "buffered"].includes(mode))
    names.push("worker", "worker2", "supervisor");
  const contexts = await Promise.all(
    names.map(() => browser.newContext({ ignoreHTTPSErrors: false })),
  );
  try {
    const pages = await Promise.all(
      contexts.map((context) => context.newPage()),
    );
    for (let index = 0; index < names.length; index += 1) {
      await observeSignals(pages[index]!);
      await login(pages[index]!, lab, names[index]!, output);
    }
    const participant = pages[0]!;
    const { path } = await intake(participant, lab, locale, output);
    const observations: string[] = [
      "exact_" + locale + "_disclosure_ui",
      "server_intake_gate",
      "fictional_ui_intake_with_participant_attribution",
    ];
    const details: Record<string, unknown> = {};
    await park(participant, lab.mainOrigin);
    if (["all", "race", "buffered"].includes(mode)) {
      checkpoint(output, "concurrent_worker_reservation");
      const workers: [Worker, Worker] = [
        { page: pages[1]!, account: lab.accounts.worker, name: "worker" },
        { page: pages[2]!, account: lab.accounts.worker2, name: "worker2" },
      ];
      const result = await reserveRace(participant, workers, path);
      const connected = await connect(
        participant,
        result.winner,
        result.assignment,
        path,
      );
      details.reservation_statuses = result.reservationStatuses;
      const marker = `Fictional buffered qualification response ${randomUUID()}.`;
      const message = await ok(result.winner.page, path + "/messages", {
        expected_revision: connected.revision,
        expected_control_epoch: connected.control_epoch,
        text: marker,
        accepted_draft_id: null,
      });
      const messages = await ok(participant, path + "/messages");
      expect(
        Array.isArray(messages.items) &&
          messages.items.some((item: unknown) => {
            const value = object(item);
            return (
              value.id === message.id &&
              value.kind === "human_authored" &&
              value.sender_id === result.winner.account
            );
          }),
        "Participant receives the attributed message from the sole confirmed worker",
      ).toBe(true);
      writeFileSync(
        resolve(output, "case-binding.json"),
        JSON.stringify({
          session_id: path.split("/").at(-1),
          participant_id: lab.accounts.pid,
          winner_id: result.winner.account,
          message_id: message.id,
        }),
        { mode: 0o600, flag: "wx" },
      );
      observations.push(
        "two_distinct_issued_workers_race",
        "exactly_one_accepted_assignment",
        "one_confirmed_accountable_owner",
      );
      if (["all", "buffered"].includes(mode)) {
        checkpoint(output, "hold_actual_old_owner_reply");
        details.buffered = await bufferedReply(
          result.winner,
          pages[3]!,
          lab,
          path,
          message,
          marker,
        );
        observations.push(
          "held_real_old_owner_reply_discarded_after_observed_authority_loss",
        );
      }
      await Promise.all([
        closeStream(participant),
        closeStream(result.winner.page),
      ]);
    }
    if (["all", "revocation"].includes(mode)) {
      checkpoint(output, "await_current_acl_restriction");
      details.revocation = await revokeAcl(participant, lab, path, output);
      observations.push(
        "current_acl_revocation_denies_actual_read_and_post",
        "existing_channel_and_fresh_page_revalidate",
      );
    }
    checkpoint(output, "passed");
    writeFileSync(
      resolve(output, "observations.json"),
      JSON.stringify(
        {
          session: "imp03-002",
          suite: "extended",
          mode,
          locale,
          status: "passed",
          actual_provider_actors: names,
          browser_tls_verification: true,
          observations,
          details,
          human_acceptance: false,
          limits: [
            "Selected automated UI actions and exact recorded races; human language/accessibility review absent.",
            "Browser-transport held reply does not cover every serving/OS buffered-output interleaving.",
            "Durable row/effect counts and audit-chain evidence require the separate operator observations.",
          ],
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
