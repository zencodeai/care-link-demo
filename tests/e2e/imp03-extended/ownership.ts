import { expect, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { object, text, type ExtendedConfig } from "./config";
import { ok, request, stream, type Row } from "./helpers";

export interface Worker {
  page: Page;
  account: string;
  name: "worker" | "worker2";
}
export async function reserveRace(
  participant: Page,
  workers: [Worker, Worker],
  path: string,
) {
  const current = await ok(participant, path);
  const queue = await ok(participant, path + "/human-request", {
    expected_revision: current.revision,
    reason: "user_requested",
  });
  const reservations = await Promise.all(
    workers.map(async (worker) => ({
      worker,
      response: await request(worker.page, path + "/workforce/reserve", {
        expected_revision: queue.revision,
        worker_id: worker.account,
      }),
    })),
  );
  const successes = reservations.filter(
    (entry) => entry.response.status === 200,
  );
  expect(
    successes.length,
    "Exactly one real concurrent reservation succeeds",
  ).toBe(1);
  const winner = successes[0]!;
  const loser = reservations.find((entry) => entry !== winner)!;
  expect(
    [403, 409].includes(loser.response.status),
    "The competing issued worker receives a real authority/conflict denial",
  ).toBe(true);
  const reservation = object(winner.response.value);
  const deniedAccept = await request(
    loser.worker.page,
    path + "/workforce/accept",
    {
      expected_revision: reservation.revision,
    },
  );
  expect(
    [403, 404, 409].includes(deniedAccept.status),
    "Loser cannot accept winner's assignment",
  ).toBe(true);
  const assignment = await ok(winner.worker.page, path + "/workforce/accept", {
    expected_revision: reservation.revision,
  });
  expect(
    assignment.state === "accepted" &&
      assignment.worker_id === winner.worker.account,
    "Accepted assignment belongs to the sole winning worker",
  ).toBe(true);
  const assigned = await ok(winner.worker.page, path);
  expect(
    assigned.service_phase,
    "Acceptance still requires channel confirmation",
  ).toBe("worker_assigned");
  return {
    winner: winner.worker,
    loser: loser.worker,
    assignment,
    reservationStatuses: reservations.map((entry) => ({
      actor: entry.worker.name,
      status: entry.response.status,
    })),
  };
}
export async function connect(
  participant: Page,
  winner: Worker,
  assignment: Row,
  path: string,
) {
  const sid = path.split("/").at(-1)!;
  await ok(winner.page, path + "/workforce/prepare-transfer", {
    expected_revision: assignment.revision,
  });
  await stream(participant, sid);
  await stream(winner.page, sid);
  let workerAck: { body: Row; key: string } | undefined;
  for (const page of [winner.page, participant]) {
    const challenge = await ok(page, path + "/workforce/challenge");
    const current = await ok(page, path);
    const body = {
      expected_revision: current.revision,
      challenge_id: challenge.challenge_id,
      nonce: challenge.nonce,
      transport_generation: challenge.transport_generation,
      expected_control_epoch: challenge.control_epoch,
    };
    const key = randomUUID();
    const ack = await ok(page, path + "/workforce/channel-acks", body, key);
    if (page === winner.page) {
      expect(ack.state).toBe("one_party_acknowledged");
      workerAck = { body, key };
    }
  }
  if (!workerAck) throw new Error("Missing actual worker acknowledgement");
  const ack = await ok(
    winner.page,
    path + "/workforce/channel-acks",
    workerAck.body,
    workerAck.key,
  );
  expect(ack.state).toBe("two_party_confirmed");
  const pending = await ok(winner.page, path);
  const connected = await ok(
    winner.page,
    path + "/workforce/confirm-transfer",
    {
      expected_revision: pending.revision,
      assignment_id: assignment.id,
      channel_evidence_id: ack.evidence_id,
      worker_ack_id: ack.ack_id,
      expected_control_epoch: pending.control_epoch,
    },
  );
  expect(
    connected.service_phase === "human_controlled" &&
      connected.transport === "connected" &&
      connected.owner_id === winner.account,
    "Real two-party handoff yields exactly the winning accountable owner",
  ).toBe(true);
  return connected;
}
export async function takeover(
  supervisor: Page,
  lab: ExtendedConfig,
  path: string,
) {
  const queue = await ok(supervisor, "/v1/workforce/queue");
  if (!Array.isArray(queue.items))
    throw new Error("Invalid actual queue projection");
  const entry = object(
    queue.items.find(
      (item: unknown) => object(item).session_id === path.split("/").at(-1),
    ),
  );
  await ok(supervisor, path + "/workforce/observe", {
    expected_revision: entry.revision,
    scope: "interrupt",
    expires_at: new Date(Date.now() + 60_000).toISOString(),
  });
  const current = await ok(supervisor, path);
  const taken = await ok(supervisor, path + "/workforce/takeover", {
    expected_revision: current.revision,
    worker_id: lab.accounts.supervisor,
  });
  expect(
    BigInt(text(taken, "control_epoch")) >
      BigInt(text(current, "control_epoch")) &&
      taken.owner_id === lab.accounts.supervisor &&
      taken.service_phase === "worker_assigned",
    "Actual takeover advances ownership generation and requires a new handshake",
  ).toBe(true);
  return taken;
}
