import { useEffect, useState } from "react";
import { Field } from "./Fields";
import { ContactConsent } from "./ContactConsent";
import { read, utc } from "./api";
import type { Text } from "./messages";
import type { Anchor, FollowUp, SessionContext } from "./types";
import type { Channel } from "./useLifecycle";
export function FollowUpPanel({
  channel,
  text,
  session,
}: {
  channel: Channel;
  text: Text;
  session: SessionContext;
}) {
  const [source, setSource] = useState("");
  const [occurred, setOccurred] = useState("");
  const [anchor, setAnchor] = useState<Anchor | null>(null);
  const [grant, setGrant] = useState("");
  const [recipient, setRecipient] = useState(channel.account?.account_id ?? "");
  const [pendingAnchor, setPendingAnchor] = useState(true);
  const [due, setDue] = useState("");
  const [knownId, setKnownId] = useState("");
  const [followup, setFollowup] = useState<FollowUp | null>(null);
  useEffect(() => {
    setAnchor(null);
    setFollowup(null);
  }, [channel.privateEpoch]);
  const disabled = channel.disabled;
  function receive(value: FollowUp) {
    setFollowup(value);
    setKnownId(value.id);
  }
  if (!channel.account) return null;
  return (
    <section aria-labelledby="followup-title">
      <h2 id="followup-title">{text.followup}</h2>
      <p>{text.window}</p>
      <ContactConsent
        channel={channel}
        text={text}
        session={session}
        onGrant={(id, account) => {
          setGrant(id);
          setRecipient(account);
        }}
      />
      <form
        onSubmit={(e) => {
          e.preventDefault();
          channel.command(
            {
              path: `/v1/sessions/${session.id}/post-crisis`,
              input: "PostCrisisRecord",
              output: "PostCrisisView",
              body: {
                expected_revision: session.revision,
                occurred_at: utc(occurred),
                source_event_id: source,
              },
            },
            (value) => {
              setAnchor(value);
            },
          );
        }}
      >
        <h3>{text.anchor}</h3>
        <p>{text.anchorHint}</p>
        <Field
          id="crisis-source"
          label={text.sourceEvent}
          value={source}
          onChange={setSource}
          identifier
        />
        <Field
          id="crisis-time"
          label={text.occurred}
          value={occurred}
          onChange={setOccurred}
          type="datetime-local"
        />
        <button disabled={disabled}>{text.recordAnchor}</button>
      </form>
      {anchor && (
        <p>
          {text.anchor}: {anchor.id} ·{" "}
          <time dateTime={anchor.occurred_at}>{anchor.occurred_at}</time>
        </p>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!session.subject_id) return;
          channel.command(
            {
              path: `/v1/sessions/${session.id}/follow-ups`,
              input: "FollowUpCreate",
              output: "FollowUpView",
              body: {
                expected_revision: session.revision,
                subject_id: session.subject_id,
                recipient_account_id: recipient,
                contact_grant_id: grant,
                ...(pendingAnchor
                  ? { kind: "pending_anchor" }
                  : {
                      kind: "scheduled",
                      post_crisis_event_id: anchor?.id,
                      due_at: utc(due),
                    }),
              },
            },
            receive,
          );
        }}
      >
        <Field
          id="followup-recipient"
          label={text.recipient}
          value={recipient}
          onChange={setRecipient}
          identifier
        />
        <Field
          id="followup-grant"
          label={text.grant}
          value={grant}
          onChange={setGrant}
          identifier
        />
        <label>
          <input
            type="checkbox"
            checked={pendingAnchor}
            onChange={(e) => setPendingAnchor(e.target.checked)}
          />
          {text.pendingAnchor}
        </label>
        <Field
          id="followup-due"
          label={text.due}
          value={due}
          onChange={setDue}
          type="datetime-local"
          required={!pendingAnchor || followup?.state === "anchor_pending"}
        />
        <button
          disabled={
            disabled || !session.subject_id || (!pendingAnchor && !anchor)
          }
        >
          {text.schedule}
        </button>
      </form>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void channel.run(async (signal) =>
            receive(
              await read(`/v1/follow-ups/${knownId}`, "FollowUpView", signal),
            ),
          );
        }}
      >
        <Field
          id="known-followup"
          label={text.knownFollowup}
          value={knownId}
          onChange={setKnownId}
          identifier
        />
        <button disabled={channel.busy}>{text.refresh}</button>
      </form>
      {followup && (
        <div aria-live="polite">
          <p>
            {text.state}: {text.states[followup.state]}
          </p>
          <p>
            {text.reference}: {followup.id}
          </p>
          {followup.due_at && (
            <p>
              {text.due}:{" "}
              <time dateTime={followup.due_at}>{followup.due_at}</time>
            </p>
          )}
          {followup.state === "anchor_pending" && (
            <button
              disabled={disabled || !anchor || !due || !grant}
              onClick={() => {
                if (!anchor) return;
                channel.command(
                  {
                    path: `/v1/follow-ups/${followup.id}/anchor`,
                    input: "FollowUpBindAnchor",
                    output: "FollowUpView",
                    body: {
                      expected_revision: followup.revision,
                      post_crisis_event_id: anchor.id,
                      contact_grant_id: grant,
                      due_at: utc(due),
                    },
                  },
                  receive,
                );
              }}
            >
              {text.bind}
            </button>
          )}
          <p>{text.cancellation}</p>
          {["unknown", "reconciliation_needed"].includes(followup.state) && (
            <p>{text.unknownDelivery}</p>
          )}
          <button
            disabled={
              disabled ||
              ["sent", "cancelled", "expired"].includes(followup.state)
            }
            onClick={() =>
              channel.command(
                {
                  path: `/v1/follow-ups/${followup.id}/cancel`,
                  input: "RevisionCommand",
                  output: "FollowUpView",
                  body: { expected_revision: followup.revision },
                },
                receive,
              )
            }
          >
            {text.cancel}
          </button>
        </div>
      )}
    </section>
  );
}
