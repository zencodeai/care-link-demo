import { useEffect, useState } from "react";
import { read, identifierPattern } from "./api";
import { DeliveryState, Payload } from "./Payload";
import { useCommand } from "./useCommand";
import type { Actions } from "./useActions";
import { label, type Text } from "./messages";
import type { Inbox, ReceiverDetail } from "./types";
export function Receiver({ actions, text }: { actions: Actions; text: Text }) {
  const [inbox, setInbox] = useState<Inbox | null>(null);
  const [id, setId] = useState("");
  const [detail, setDetail] = useState<ReceiverDetail | null>(null);
  const [decision, setDecision] = useState<
    "accept" | "partial" | "reject" | "clarify"
  >("accept");
  const [reason, setReason] = useState("accepted");
  const [fields, setFields] = useState<string[]>([]);
  const commands = useCommand(actions);
  useEffect(() => {
    setDetail(null);
    setInbox(null);
  }, [actions.failureEpoch]);
  const disabled = actions.busy || !actions.session;
  const visible = actions.notice === "done" && !actions.busy;
  async function load(id: string, signal: AbortSignal) {
    const result = await read(
      `/v1/receiver/packages/${id}/detail`,
      "ReceiverDetail",
      signal,
    );
    setDetail(result);
    setId(id);
    setFields([]);
    commands.clear();
  }
  return (
    <>
      <section aria-labelledby="receiver-title">
        <h2 id="receiver-title">{text.inbox}</h2>
        <p>{text.receiverHint}</p>
        <div className="actions">
          <button
            disabled={disabled}
            onClick={() =>
              void actions.run(async (signal) => {
                setInbox(
                  await read(
                    "/v1/receiver/inbox",
                    "ReceiverPackagePage",
                    signal,
                  ),
                );
              })
            }
          >
            {text.loadInbox}
          </button>
          {visible && inbox?.next_cursor && (
            <button
              disabled={disabled}
              onClick={() =>
                void actions.run(async (signal) => {
                  setInbox(
                    await read(
                      `/v1/receiver/inbox?cursor=${encodeURIComponent(inbox.next_cursor ?? "")}`,
                      "ReceiverPackagePage",
                      signal,
                    ),
                  );
                })
              }
            >
              {text.next}
            </button>
          )}
        </div>
        {visible &&
          inbox &&
          (inbox.dispatch_ids.length ? (
            <ul>
              {inbox.dispatch_ids.map((dispatchId) => (
                <li key={dispatchId}>
                  <button
                    disabled={disabled}
                    onClick={() =>
                      void actions.run((signal) => load(dispatchId, signal))
                    }
                  >
                    {dispatchId}
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p>{text.noPackages}</p>
          ))}
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void actions.run((signal) => load(id, signal));
          }}
        >
          <label htmlFor="receiver-dispatch">{text.dispatch}</label>
          <input
            id="receiver-dispatch"
            value={id}
            required
            pattern={identifierPattern}
            onChange={(event) => setId(event.target.value)}
            disabled={disabled}
          />
          <button disabled={disabled}>{text.currentReceipt}</button>
        </form>
      </section>
      {visible && detail && (
        <section aria-labelledby="receiver-package-title">
          <h2 id="receiver-package-title">{text.package}</h2>
          <Payload payload={detail.payload} text={text} />
          <p>
            {text.revision}: {detail.revision}
          </p>
          <p className="referral-digest">
            {text.digest}: {detail.receipt.payload_digest}
          </p>
          <p>
            {text.state}: {label(detail.receipt.status, text)}
          </p>
          <DeliveryState state={detail.receipt.status} text={text} />
          <form
            onSubmit={(event) => {
              event.preventDefault();
              commands.send(
                {
                  path: `/v1/receiver/packages/${detail.receipt.dispatch_id}/decision`,
                  input: "ReceiverDecision",
                  output: "ReceiptView",
                  body: {
                    expected_revision: detail.revision,
                    dispatch_id: detail.receipt.dispatch_id,
                    payload_digest: detail.receipt.payload_digest,
                    decision,
                    accepted_fields: fields,
                    reason,
                  },
                },
                async (_result, signal) => {
                  await load(detail.receipt.dispatch_id, signal);
                },
              );
            }}
          >
            <h3>{text.decision}</h3>
            <label htmlFor="receiver-decision">{text.decision}</label>
            <select
              id="receiver-decision"
              value={decision}
              disabled={disabled}
              onChange={(event) => {
                const value = event.target.value;
                if (
                  value === "accept" ||
                  value === "partial" ||
                  value === "reject" ||
                  value === "clarify"
                ) {
                  setDecision(value);
                  setFields([]);
                  setReason(
                    value === "accept"
                      ? "accepted"
                      : value === "clarify"
                        ? "missing_fields"
                        : "scope",
                  );
                }
              }}
            >
              <option value="accept">{text.accept}</option>
              <option value="partial">{text.partial}</option>
              <option value="reject">{text.decline}</option>
              <option value="clarify">{text.clarify}</option>
            </select>
            <fieldset
              disabled={
                disabled || decision === "reject" || decision === "clarify"
              }
            >
              <legend>{text.acceptedFields}</legend>
              {[
                ...new Set(detail.payload.fields.map((field) => field.field)),
              ].map((field) => (
                <label key={field}>
                  <input
                    type="checkbox"
                    checked={fields.includes(field)}
                    onChange={(event) =>
                      setFields((old) =>
                        event.target.checked
                          ? [...old, field]
                          : old.filter((value) => value !== field),
                      )
                    }
                  />
                  {label(field, text)}
                </label>
              ))}
            </fieldset>
            <label htmlFor="receiver-reason">{text.reason}</label>
            <select
              id="receiver-reason"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              disabled={disabled}
            >
              {[
                "capacity",
                "scope",
                "missing_fields",
                "invalid_schema",
                "accepted",
              ].map((item) => (
                <option key={item} value={item}>
                  {label(item, text)}
                </option>
              ))}
            </select>
            <button
              disabled={
                disabled ||
                !!commands.pending ||
                ((decision === "accept" || decision === "partial") &&
                  !fields.length)
              }
            >
              {text.submitDecision}
            </button>
          </form>
          <p className="notice">{text.support}</p>
        </section>
      )}
      {commands.pending && !actions.busy && (
        <p role="status" className="referral-digest">
          {text.unknown} {commands.pending.key}
          <button disabled={disabled} onClick={commands.retry}>
            {text.resume}
          </button>
        </p>
      )}
    </>
  );
}
