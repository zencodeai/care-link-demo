import { useState } from "react";
import type { Labels } from "./labels";
import type { ReviewChannel } from "./useReview";
import type { Assignment, QueueItem } from "./types";
export function Workforce({
  channel,
  text,
}: {
  channel: ReviewChannel;
  text: Labels;
}) {
  const [interrupt, setInterrupt] = useState("");
  const [choice, setChoice] = useState(false);
  const [observed, setObserved] = useState(false);
  const supervisor = channel.context?.role === "supervisor";
  const assignment = channel.workspace?.assignment;
  const grant = channel.workspace?.interrupt_expires_at;
  const canTakeOver = Boolean(
    grant && Date.parse(grant) > Date.now() && channel.workspace?.conversation,
  );
  const observe = async (item: QueueItem, scope: "observe" | "interrupt") => {
    const result = await channel.write(
      `/v1/sessions/${item.session_id}/workforce/observe`,
      {
        expected_revision: item.revision,
        scope,
        expires_at: new Date(Date.now() + 300000).toISOString(),
      },
      "CommandResult",
    );
    if (result) {
      channel.select(item.session_id);
      setObserved(true);
      setInterrupt("");
      setChoice(false);
    }
  };
  return (
    <section aria-labelledby="review-workforce-title">
      <h2 id="review-workforce-title">
        {supervisor ? text.supervisor : text.worker}
      </h2>
      <h3>{text.queue}</h3>
      <button
        type="button"
        disabled={channel.busy}
        onClick={() => {
          void channel.refresh();
        }}
      >
        {text.loadQueue}
      </button>
      {channel.queue.length ? (
        <ul className="manual-queue">
          {channel.queue.map((item) => (
            <li key={item.ticket_id}>
              <p>
                <code>{item.session_id}</code> · {item.state}
              </p>
              <p>{item.connection_confirmed ? text.connected : text.waiting}</p>
              {!supervisor && (
                <button
                  type="button"
                  disabled={!channel.enabled || item.state !== "pending"}
                  onClick={() => {
                    void channel.write<Assignment>(
                      `/v1/sessions/${item.session_id}/workforce/reserve`,
                      {
                        expected_revision: item.revision,
                        worker_id: channel.session?.account_id,
                      },
                      "AssignmentView",
                    );
                  }}
                >
                  {text.reserve}
                </button>
              )}
              {supervisor && (
                <div className="actions">
                  <button
                    type="button"
                    disabled={!channel.enabled}
                    onClick={() => {
                      void observe(item, "observe");
                    }}
                  >
                    {text.observe}
                  </button>
                  <button
                    type="button"
                    disabled={!channel.enabled}
                    onClick={() => {
                      setInterrupt(item.session_id);
                      setChoice(false);
                    }}
                  >
                    {text.prepareInterrupt}
                  </button>
                  {interrupt === item.session_id && (
                    <>
                      <label className="manual-choice">
                        <input
                          type="checkbox"
                          checked={choice}
                          onChange={(event) => setChoice(event.target.checked)}
                        />
                        {text.interrupt}
                      </label>
                      <button
                        type="button"
                        disabled={!channel.enabled || !choice}
                        onClick={() => {
                          void observe(item, "interrupt");
                        }}
                      >
                        {text.confirmInterrupt}
                      </button>
                    </>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p>{text.noQueue}</p>
      )}
      {assignment && (
        <section aria-label={text.accept}>
          <p>
            <code>{assignment.session_id}</code> · {assignment.state}
          </p>
          {assignment.state === "reserved" ? (
            <button
              type="button"
              disabled={!channel.enabled}
              onClick={() => {
                void (async () => {
                  const accepted = await channel.write<Assignment>(
                    `/v1/sessions/${assignment.session_id}/workforce/accept`,
                    { expected_revision: assignment.revision },
                    "AssignmentView",
                  );
                  if (accepted) channel.select(accepted.session_id);
                })();
              }}
            >
              {text.accept}
            </button>
          ) : (
            <>
              <p>{text.accepted}</p>
              <button
                type="button"
                disabled={channel.busy}
                onClick={() => channel.select(assignment.session_id)}
              >
                {text.open}
              </button>
            </>
          )}
        </section>
      )}
      {observed && <p role="status">{text.observed}</p>}
      {supervisor && canTakeOver && (
        <button
          type="button"
          disabled={!channel.enabled}
          onClick={() => {
            void channel.write(
              `/v1/sessions/${channel.workspace?.conversation?.id}/workforce/takeover`,
              {
                expected_revision: channel.workspace?.conversation?.revision,
                worker_id: channel.session?.account_id,
              },
              "SessionView",
            );
          }}
        >
          {text.takeover}
        </button>
      )}
    </section>
  );
}
