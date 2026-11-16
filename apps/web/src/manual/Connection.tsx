import { useEffect, useState } from "react";
import { RequestFailure } from "../trust/api";
import {
  acknowledgement,
  challenge,
  type Acknowledgement,
  type Challenge,
} from "./api";
import { type Text } from "./messages";
import { type ManualChannel } from "./useManual";
export function Connection({
  channel,
  text,
}: {
  channel: ManualChannel;
  text: Text;
}) {
  const [ownChallenge, setChallenge] = useState<Challenge | null>(null);
  const [ack, setAck] = useState<Acknowledgement | null>(null);
  const [assignmentId, setAssignmentId] = useState<string | null>(null);
  const view = channel.view;
  useEffect(() => {
    setChallenge(null);
    setAck(null);
    setAssignmentId(null);
  }, [view?.id, view?.control_epoch]);
  if (!view || view.service_phase !== "handoff_pending") return null;
  const worker =
    channel.identity?.role === "worker" ||
    channel.identity?.role === "supervisor";
  const disabled = channel.busy || channel.pending !== null;
  return (
    <section className="manual-connection" aria-label={text.challenge}>
      <p>{text.confirmHint}</p>
      <button
        type="button"
        disabled={disabled || !!ack}
        onClick={() => {
          // GET consumes the one-time nonce response. It is kept only in component
          // memory until ACK; loss requires a new prepare-transfer, never nonce reuse.
          void (async () => {
            const value =
              ownChallenge ??
              (await channel.read(
                `/v1/sessions/${view.id}/workforce/challenge`,
                "ChannelChallengeView",
                challenge,
              ));
            if (!value) return;
            setChallenge(value);
            setAssignmentId(value.assignment_id);
            await channel.perform(
              `/v1/sessions/${view.id}/workforce/channel-acks`,
              "ChannelAckSubmit",
              {
                expected_revision: view.revision,
                challenge_id: value.challenge_id,
                nonce: value.nonce,
                transport_generation: value.transport_generation,
                expected_control_epoch: value.control_epoch,
              },
              "ChannelAckView",
              (result) => {
                if (!acknowledgement(result))
                  throw new RequestFailure("invalid");
                setAck(result);
                setChallenge(null);
              },
            );
          })();
        }}
      >
        {text.challenge}
      </button>
      {ack && (
        <p role="status">
          {ack.state === "two_party_confirmed" ? text.twoParty : text.oneParty}
        </p>
      )}
      {worker && ack && !ack.evidence_id && (
        <button
          type="button"
          disabled={disabled}
          onClick={() => {
            void channel.repeatAck();
          }}
        >
          {text.refreshAck}
        </button>
      )}
      {worker && ack?.evidence_id && assignmentId && (
        <button
          type="button"
          disabled={disabled}
          onClick={() => {
            void channel.perform(
              `/v1/sessions/${view.id}/workforce/confirm-transfer`,
              "TransferConfirm",
              {
                expected_revision: view.revision,
                assignment_id: assignmentId,
                channel_evidence_id: ack.evidence_id,
                worker_ack_id: ack.ack_id,
                expected_control_epoch: view.control_epoch,
              },
              "SessionView",
              channel.receiveView,
            );
          }}
        >
          {text.confirm}
        </button>
      )}
    </section>
  );
}
