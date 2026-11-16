import { useEffect, useState } from "react";
import type { Challenge } from "../manual/api";
import { headers, json } from "./api";
import type { Labels } from "./labels";
import type { ReviewChannel } from "./useReview";
import type { Conversation } from "./types";
export function Handshake({
  channel,
  conversation,
  text,
}: {
  channel: ReviewChannel;
  conversation: Conversation;
  text: Labels;
}) {
  const [challenge, setChallenge] = useState<Challenge | null>(null);
  const [clock, setClock] = useState(Date.now());
  const [reading, setReading] = useState(false);
  const handshake = channel.workspace?.handshake;
  const worker = channel.session?.role !== "pid";
  useEffect(() => {
    setChallenge(null);
  }, [
    handshake?.challenge_id,
    conversation.control_epoch,
    channel.view?.view_id,
  ]);
  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const seconds = handshake
    ? Math.max(0, Math.ceil((Date.parse(handshake.expires_at) - clock) / 1000))
    : 0;
  const ownAck = worker
    ? handshake?.worker_acknowledged
    : handshake?.participant_acknowledged;
  const ownAssignment = channel.workspace?.assignment;
  const prepare = async () => {
    if (ownAssignment)
      await channel.write(
        `/v1/sessions/${conversation.id}/workforce/prepare-transfer`,
        { expected_revision: ownAssignment.revision },
        "TransferPreparation",
      );
  };
  const acknowledge = async () => {
    setReading(true);
    try {
      const value =
        challenge ??
        (await json<Challenge>(
          `/v1/sessions/${conversation.id}/workforce/challenge`,
          "ChannelChallengeView",
          headers(channel.view?.view_id ?? null),
        ));
      setChallenge(value);
      const current = await json<Conversation>(
        `/v1/sessions/${conversation.id}`,
        "SessionView",
        headers(channel.view?.view_id ?? null),
      );
      const result = await channel.write(
        `/v1/sessions/${conversation.id}/workforce/channel-acks`,
        {
          expected_revision: current.revision,
          challenge_id: value.challenge_id,
          nonce: value.nonce,
          transport_generation: value.transport_generation,
          expected_control_epoch: value.control_epoch,
        },
        "ChannelAckView",
      );
      if (result) setChallenge(null);
    } catch (error) {
      channel.fail(error);
    } finally {
      setReading(false);
    }
  };
  const confirm = async () => {
    if (!handshake?.evidence_id || !handshake.worker_ack_id) return;
    const current = await json<Conversation>(
      `/v1/sessions/${conversation.id}`,
      "SessionView",
      headers(channel.view?.view_id ?? null),
    );
    await channel.write(
      `/v1/sessions/${conversation.id}/workforce/confirm-transfer`,
      {
        expected_revision: current.revision,
        assignment_id: handshake.assignment_id,
        channel_evidence_id: handshake.evidence_id,
        worker_ack_id: handshake.worker_ack_id,
        expected_control_epoch: current.control_epoch,
      },
      "SessionView",
    );
  };
  if (
    !["worker_assigned", "handoff_pending"].includes(
      conversation.service_phase,
    ) &&
    !(
      conversation.service_phase === "human_controlled" &&
      conversation.transport !== "connected"
    )
  )
    return null;
  return (
    <section aria-label={text.challenge}>
      {worker &&
        ownAssignment &&
        ["accepted", "connected"].includes(ownAssignment.state) && (
          <button
            type="button"
            disabled={!channel.enabled}
            onClick={() => {
              void prepare();
            }}
          >
            {text.prepare}
          </button>
        )}
      {handshake && (
        <>
          <p role="status">
            {seconds
              ? `${text.expires} ${seconds} ${text.seconds}.`
              : text.expired}
          </p>
          {ownAck ? (
            <p>
              {handshake.participant_acknowledged &&
              handshake.worker_acknowledged
                ? text.twoParty
                : `${text.ownAck} ${text.waitOther}`}
            </p>
          ) : (
            <button
              type="button"
              disabled={!channel.enabled || !seconds || reading}
              onClick={() => {
                void acknowledge();
              }}
            >
              {text.challenge}
            </button>
          )}
          {worker && handshake.evidence_id && (
            <button
              type="button"
              disabled={!channel.enabled || !seconds}
              onClick={() => {
                void confirm().catch(channel.fail);
              }}
            >
              {text.confirm}
            </button>
          )}
        </>
      )}
    </section>
  );
}
