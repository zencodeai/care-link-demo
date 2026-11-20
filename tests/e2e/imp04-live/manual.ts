import { expect } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { type Actor } from "./browser";
import { type Actors, type Observations } from "./cases";
import { row, text, type Row } from "./config";

async function fresh(actor: Actor): Promise<void> {
  const current = await actor.current();
  const age = Date.now() - Date.parse(text(current, "auth_time"));
  if (!Number.isFinite(age) || age >= 210_000) await actor.signIn(false);
}
async function openStream(actor: Actor, session: string): Promise<void> {
  await actor.ensureMain();
  await actor.page.evaluate(async (session) => {
    const memory = window as unknown as { imp04ManualStream?: EventSource };
    memory.imp04ManualStream?.close();
    await new Promise<void>((resolve, reject) => {
      const source = new EventSource(`/v1/sessions/${session}/events`);
      memory.imp04ManualStream = source;
      const deadline = setTimeout(() => {
        source.close();
        reject(new Error("Real manual EventSource failed to open"));
      }, 15000);
      source.onopen = () => {
        clearTimeout(deadline);
        resolve();
      };
      source.onerror = () => {
        clearTimeout(deadline);
        source.close();
        reject(new Error("Real manual EventSource unavailable"));
      };
    });
  }, session);
}
async function streamOpen(actor: Actor): Promise<boolean> {
  return actor.page.evaluate(() => {
    const memory = window as unknown as { imp04ManualStream?: EventSource };
    return memory.imp04ManualStream?.readyState === EventSource.OPEN;
  });
}
async function closeStream(actor: Actor): Promise<void> {
  await actor.page.evaluate(() => {
    const memory = window as unknown as { imp04ManualStream?: EventSource };
    memory.imp04ManualStream?.close();
    delete memory.imp04ManualStream;
  });
}
function messageItems(page: Row): Row[] {
  if (!Array.isArray(page.items))
    throw new Error("Actual manual message page missing");
  return page.items.map(row);
}

export async function manualRegression(
  actors: Actors,
  observations: Observations,
): Promise<Row> {
  const participant = actors.pid,
    worker = actors.worker2;
  await fresh(participant);
  await fresh(worker);
  const session = await participant.ok("/v1/sessions", {
    tags: { environment: "demo", population: "synthetic" },
    participant_kind: "pid",
    jurisdiction: null,
    locale: "en-CA",
    channel: "web",
    persona_id: null,
    fixture_id: null,
  });
  const sessionId = text(session, "id"),
    path = `/v1/sessions/${sessionId}`;
  const disclosure = row(
    row(
      JSON.parse(
        readFileSync(resolve("config/demo/imp03/disclosures.json"), "utf8"),
      ) as unknown,
    )["en-CA"],
  );
  await participant.ok(path + "/disclosure", {
    expected_revision: session.revision,
    template_id: disclosure.id,
    template_digest: disclosure.digest,
    locale: "en-CA",
    acknowledged: true,
  });
  const current = await participant.ok(path);
  const queued = await participant.ok(path + "/human-request", {
    expected_revision: current.revision,
    reason: "user_requested",
  });
  const reserved = await worker.ok(path + "/workforce/reserve", {
    expected_revision: queued.revision,
    worker_id: worker.issued.accountId,
  });
  const assignment = await worker.ok(path + "/workforce/accept", {
    expected_revision: reserved.revision,
  });
  expect(assignment.state).toBe("accepted");
  const assigned = await worker.ok(path);
  expect(assigned.service_phase).toBe("worker_assigned");
  expect(
    assigned.owner_id,
    "Accepted assignment alone does not install a human conversation owner",
  ).toBeNull();
  expect(
    assigned.service_phase,
    "Assignment alone is not the two-party human-controlled phase",
  ).not.toBe("human_controlled");
  observations.push({
    case: "Q09-manual-created",
    status: "passed",
    session_id: sessionId,
    subject_id: session.subject_id,
    assignment_id: assignment.id,
    worker_id: worker.issued.accountId,
    accepted_without_connection_claim: true,
    participant_transport_before_handoff: assigned.transport,
  });
  let participantStream = false,
    workerStream = false;
  let result: Row;
  let cleanupFailed: boolean;
  try {
    await openStream(participant, sessionId);
    participantStream = true;
    await openStream(worker, sessionId);
    workerStream = true;
    expect(await streamOpen(participant)).toBe(true);
    expect(await streamOpen(worker)).toBe(true);
    const prepared = await worker.ok(path + "/workforce/prepare-transfer", {
      expected_revision: assignment.revision,
    });
    const workerChallenge = await worker.ok(path + "/workforce/challenge");
    expect(workerChallenge.party).toBe("worker");
    expect(workerChallenge.challenge_id).toBe(prepared.challenge_id);
    const workerCurrent = await worker.ok(path);
    const workerAckBody = {
      expected_revision: workerCurrent.revision,
      challenge_id: workerChallenge.challenge_id,
      nonce: workerChallenge.nonce,
      transport_generation: workerChallenge.transport_generation,
      expected_control_epoch: workerChallenge.control_epoch,
    };
    const workerAckKey = randomUUID();
    const firstAck = await worker.ok(
      path + "/workforce/channel-acks",
      workerAckBody,
      workerAckKey,
    );
    expect(firstAck.state).toBe("one_party_acknowledged");
    const participantChallenge = await participant.ok(
      path + "/workforce/challenge",
    );
    expect(participantChallenge.party).toBe("participant");
    expect(participantChallenge.challenge_id).toBe(prepared.challenge_id);
    const participantCurrent = await participant.ok(path);
    const secondAck = await participant.ok(path + "/workforce/channel-acks", {
      expected_revision: participantCurrent.revision,
      challenge_id: participantChallenge.challenge_id,
      nonce: participantChallenge.nonce,
      transport_generation: participantChallenge.transport_generation,
      expected_control_epoch: participantChallenge.control_epoch,
    });
    expect(secondAck.state).toBe("two_party_confirmed");
    const workerAck = await worker.ok(
      path + "/workforce/channel-acks",
      workerAckBody,
      workerAckKey,
    );
    expect(workerAck.state).toBe("two_party_confirmed");
    const pending = await worker.ok(path);
    const connected = await worker.ok(path + "/workforce/confirm-transfer", {
      expected_revision: pending.revision,
      assignment_id: assignment.id,
      channel_evidence_id: workerAck.evidence_id,
      worker_ack_id: workerAck.ack_id,
      expected_control_epoch: pending.control_epoch,
    });
    expect(connected.transport).toBe("connected");
    expect(connected.service_phase).toBe("human_controlled");
    expect(connected.owner_id).toBe(worker.issued.accountId);
    expect(await streamOpen(participant)).toBe(true);
    expect(await streamOpen(worker)).toBe(true);
    const workerText = `Fictional IMP04 manual worker response ${randomUUID()}.`;
    const sendKey = randomUUID();
    const sendBody = {
      expected_revision: connected.revision,
      expected_control_epoch: connected.control_epoch,
      text: workerText,
      accepted_draft_id: null,
    };
    const sent = await worker.ok(path + "/messages", sendBody, sendKey);
    expect(sent.kind).toBe("human_authored");
    expect(sent.sender_id).toBe(worker.issued.accountId);
    const duplicate = await worker.ok(path + "/messages", sendBody, sendKey);
    expect(
      duplicate.id,
      "Same logical message command returns original durable message",
    ).toBe(sent.id);
    const participantReady = await participant.ok(path);
    const replyText = `Fictional IMP04 participant reply ${randomUUID()}.`;
    const reply = await participant.ok(path + "/messages", {
      expected_revision: participantReady.revision,
      expected_control_epoch: participantReady.control_epoch,
      text: replyText,
      accepted_draft_id: null,
    });
    expect(reply.sender_id).toBe(participant.issued.accountId);
    expect(reply.kind).toBe("participant");
    for (const actor of [participant, worker]) {
      const messages = messageItems(await actor.ok(path + "/messages"));
      expect(messages.filter((item) => item.id === sent.id).length).toBe(1);
      expect(messages.filter((item) => item.id === reply.id).length).toBe(1);
      expect(
        messages.some(
          (item) => item.id === sent.id && item.text === workerText,
        ),
      ).toBe(true);
      expect(
        messages.some(
          (item) => item.id === reply.id && item.text === replyText,
        ),
      ).toBe(true);
    }
    result = {
      case: "Q09-manual-regression",
      status: "passed",
      session_id: sessionId,
      subject_id: session.subject_id,
      assignment_id: assignment.id,
      worker_id: worker.issued.accountId,
      challenge_id: prepared.challenge_id,
      actual_participant_event_source_open: true,
      actual_worker_event_source_open: true,
      both_real_channel_acks: true,
      actual_connection_confirmed: true,
      worker_message_id: sent.id,
      participant_message_id: reply.id,
      duplicate_message_key: sendKey,
      original_message_once_in_both_actual_reads: true,
      fictional_reply_read_by_both: true,
      manual_channels_not_fabricated: true,
      prior_plan_assignment_untouched: true,
    };
  } finally {
    const cleanup = await Promise.allSettled([
      ...(participantStream ? [closeStream(participant)] : []),
      ...(workerStream ? [closeStream(worker)] : []),
    ]);
    cleanupFailed = cleanup.some((item) => item.status === "rejected");
  }
  if (cleanupFailed)
    throw new Error(
      "Manual regression stream cleanup failed; remaining contexts require ordinary close",
    );
  observations.push(result);
  return result;
}
