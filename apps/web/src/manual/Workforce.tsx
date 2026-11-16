import { useEffect, useState } from "react";
import { RequestFailure } from "../trust/api";
import {
  assignment,
  preparation,
  type Assignment,
  type QueueItem,
} from "./api";
import { type Text } from "./messages";
import { type ManualChannel } from "./useManual";
export function Workforce({
  channel,
  text,
}: {
  channel: ManualChannel;
  text: Text;
}) {
  const [reserved, setReserved] = useState<Assignment | null>(null);
  const [selected, setSelected] = useState<QueueItem | null>(null);
  const [interruption, setInterruption] = useState<QueueItem | null>(null);
  const [interruptChoice, setInterruptChoice] = useState(false);
  const [interruptGrant, setInterruptGrant] = useState<{
    sessionId: string;
    expiresAt: string;
  } | null>(null);
  const view = channel.view;
  const supervisor = channel.identity?.role === "supervisor";
  const disabled = channel.busy || channel.pending !== null;
  useEffect(() => {
    setReserved(null);
    setSelected(null);
    setInterruption(null);
    setInterruptChoice(false);
    setInterruptGrant(null);
  }, [channel.identity?.account_id, channel.identity?.role]);
  useEffect(() => {
    if (!interruptGrant) return;
    const timer = window.setTimeout(
      () => setInterruptGrant(null),
      Math.max(0, Date.parse(interruptGrant.expiresAt) - Date.now()),
    );
    return () => window.clearTimeout(timer);
  }, [interruptGrant]);
  return (
    <section aria-labelledby="manual-workforce-title">
      <h3 id="manual-workforce-title">
        {supervisor ? text.supervisor : text.worker}
      </h3>
      <h4>{text.queue}</h4>
      <button
        type="button"
        disabled={disabled}
        onClick={() => {
          void channel.loadQueue();
        }}
      >
        {text.loadQueue}
      </button>
      {channel.queue.length === 0 ? (
        <p>{text.noQueue}</p>
      ) : (
        <ul className="manual-queue">
          {channel.queue.map((item) => (
            <li key={item.ticket_id}>
              <p>
                <code>{item.session_id}</code> · {item.mode} · {item.state}
              </p>
              <p>
                {item.connection_confirmed ? text.connected : text.waiting}{" "}
                {item.wait_estimate_seconds === null ? text.eta : ""}
              </p>
              <div className="actions">
                <button
                  type="button"
                  disabled={disabled || item.state !== "pending"}
                  onClick={() => {
                    setSelected(item);
                    void channel.perform(
                      `/v1/sessions/${item.session_id}/workforce/reserve`,
                      "AssignmentCommand",
                      {
                        expected_revision: item.revision,
                        worker_id: channel.identity?.account_id,
                      },
                      "AssignmentView",
                      (value) => {
                        if (!assignment(value))
                          throw new RequestFailure("invalid");
                        setReserved(value);
                      },
                    );
                  }}
                >
                  {text.reserve}
                </button>
                {supervisor && (
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => {
                      setSelected(item);
                      void channel.perform(
                        `/v1/sessions/${item.session_id}/workforce/observe`,
                        "ObserveCommand",
                        {
                          expected_revision: item.revision,
                          scope: "observe",
                          expires_at: new Date(
                            Date.now() + 300000,
                          ).toISOString(),
                        },
                        "CommandResult",
                        () => {},
                      );
                    }}
                  >
                    {text.observe}
                  </button>
                )}
                {supervisor && (
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => {
                      setInterruption(item);
                      setInterruptChoice(false);
                    }}
                  >
                    {text.prepareInterrupt}
                  </button>
                )}
                {supervisor && (
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => {
                      void channel.refresh(item.session_id);
                    }}
                  >
                    {text.open}
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {supervisor && interruption && (
        <div className="manual-interruption">
          <p>
            {text.session}: <code>{interruption.session_id}</code>
          </p>
          <label className="manual-choice">
            <input
              type="checkbox"
              checked={interruptChoice}
              onChange={(event) => setInterruptChoice(event.target.checked)}
            />
            {text.interruptChoice}
          </label>
          <button
            type="button"
            disabled={disabled || !interruptChoice}
            onClick={() => {
              const expiresAt = new Date(Date.now() + 300000).toISOString();
              void channel.perform(
                `/v1/sessions/${interruption.session_id}/workforce/observe`,
                "ObserveCommand",
                {
                  expected_revision: interruption.revision,
                  scope: "interrupt",
                  expires_at: expiresAt,
                },
                "CommandResult",
                () => {
                  setInterruptGrant({
                    sessionId: interruption.session_id,
                    expiresAt,
                  });
                  setInterruption(null);
                  setInterruptChoice(false);
                },
              );
            }}
          >
            {text.confirmInterrupt}
          </button>
        </div>
      )}
      {supervisor && interruptGrant && (
        <p role="status">{text.interruptReady}</p>
      )}
      {channel.nextQueue && (
        <button
          type="button"
          disabled={disabled}
          onClick={() => {
            void channel.loadQueue(channel.nextQueue);
          }}
        >
          {text.next}
        </button>
      )}
      {reserved && (
        <div>
          <p>
            <code>{reserved.session_id}</code> · {reserved.state}
          </p>
          {reserved.state === "reserved" && (
            <button
              type="button"
              disabled={disabled}
              onClick={() => {
                void channel.perform(
                  `/v1/sessions/${reserved.session_id}/workforce/accept`,
                  "RevisionCommand",
                  { expected_revision: reserved.revision },
                  "AssignmentView",
                  (value) => {
                    if (!assignment(value)) throw new RequestFailure("invalid");
                    setReserved(value);
                  },
                );
              }}
            >
              {text.accept}
            </button>
          )}
          {(reserved.state === "accepted" ||
            reserved.state === "connected") && (
            <>
              <p>{text.accepted}</p>
              <button
                type="button"
                disabled={disabled}
                onClick={() => {
                  void channel.refresh(reserved.session_id);
                }}
              >
                {text.open}
              </button>
              <button
                type="button"
                disabled={disabled}
                onClick={() => {
                  void channel.perform(
                    `/v1/sessions/${reserved.session_id}/workforce/prepare-transfer`,
                    "RevisionCommand",
                    { expected_revision: reserved.revision },
                    "TransferPreparation",
                    (value) => {
                      if (!preparation(value))
                        throw new RequestFailure("invalid");
                      setReserved(value.assignment);
                    },
                  );
                }}
              >
                {text.prepare}
              </button>
            </>
          )}
        </div>
      )}
      {view && (
        <div>
          {supervisor &&
            view.owner_id === channel.identity?.account_id &&
            !reserved &&
            view.service_phase === "worker_assigned" && (
              <button
                type="button"
                disabled={disabled}
                onClick={() => {
                  void channel.perform(
                    `/v1/sessions/${view.id}/workforce/prepare-transfer`,
                    "RevisionCommand",
                    { expected_revision: view.revision },
                    "TransferPreparation",
                    (value) => {
                      if (!preparation(value))
                        throw new RequestFailure("invalid");
                      setReserved(value.assignment);
                    },
                  );
                }}
              >
                {text.prepare}
              </button>
            )}
          {supervisor && (
            <>
              <p>{text.takeoverHint}</p>
              <button
                type="button"
                disabled={
                  disabled ||
                  view.service_phase === "ended" ||
                  interruptGrant?.sessionId !== view.id ||
                  Date.parse(interruptGrant.expiresAt) <= Date.now()
                }
                onClick={() => {
                  void channel.perform(
                    `/v1/sessions/${view.id}/workforce/takeover`,
                    "AssignmentCommand",
                    {
                      expected_revision: view.revision,
                      worker_id: channel.identity?.account_id,
                    },
                    "SessionView",
                    (value) => {
                      channel.receiveView(value);
                      setInterruptGrant(null);
                    },
                  );
                }}
              >
                {text.takeover}
              </button>
            </>
          )}
          <button
            type="button"
            disabled={
              disabled ||
              view.service_phase === "ended" ||
              (!reserved && !selected)
            }
            onClick={() => {
              void channel.perform(
                `/v1/sessions/${view.id}/workforce/transfer-failed`,
                "ReasonCommand",
                {
                  expected_revision: view.revision,
                  reason: "technical_failure",
                },
                "QueueView",
                () => setReserved(null),
              );
            }}
          >
            {text.transferFailed}
          </button>
        </div>
      )}
    </section>
  );
}
