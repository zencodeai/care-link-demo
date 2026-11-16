import { useState } from "react";
import { headers, json } from "./api";
import type { Labels } from "./labels";
import type { Intent } from "./types";
import type { ReviewChannel } from "./useReview";
function Operation({
  intent,
  channel,
  text,
  closed,
}: {
  intent: Intent;
  channel: ReviewChannel;
  text: Labels;
  closed: boolean;
}) {
  const [state, setState] = useState(intent.state);
  return (
    <section className="manual-reconciliation">
      <p>{closed ? text.closed : text.pending}</p>
      <p>
        {text.operation}: <code>{intent.operation_id}</code>
      </p>
      <p role="status">{state}</p>
      <button
        type="button"
        disabled={channel.busy}
        onClick={() => {
          void json<{ state: string }>(
            `/v1/operations/${intent.operation_id}`,
            "OperationStatus",
            headers(channel.view?.view_id ?? null),
          )
            .then(async (result) => {
              setState(result.state);
              await channel.refresh();
            })
            .catch(channel.fail);
        }}
      >
        {text.reconcile}
      </button>
      {!closed && (
        <>
          <button
            type="button"
            disabled={!channel.enabled || !intent.payload}
            onClick={() => {
              void channel.write(
                `/v1/sessions/${intent.session_id}/${intent.kind === "intake" ? "turns" : "messages"}`,
                intent.payload,
                intent.kind === "intake" ? "AssessmentView" : "MessageView",
                intent.operation_id,
              );
            }}
          >
            {text.resend}
          </button>
          {intent.state === "prepared" && (
            <button
              type="button"
              disabled={!channel.enabled}
              onClick={() => {
                void channel.write(
                  `/v1/review/sessions/${intent.session_id}/intent/cancel`,
                  { operation_id: intent.operation_id },
                  "ReviewIntentView",
                );
              }}
            >
              {text.cancel}
            </button>
          )}
        </>
      )}
    </section>
  );
}
export function PendingOperations({
  channel,
  text,
}: {
  channel: ReviewChannel;
  text: Labels;
}) {
  const closed = channel.workspace?.run_state !== "active";
  return (
    <>
      {channel.workspace?.pending_intents
        .filter(
          (intent) =>
            closed ||
            !["committed", "rejected", "cancelled"].includes(intent.state),
        )
        .map((intent) => (
          <Operation
            key={intent.operation_id}
            intent={intent}
            channel={channel}
            text={text}
            closed={closed}
          />
        ))}
    </>
  );
}
