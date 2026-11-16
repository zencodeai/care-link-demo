import { useState } from "react";
import { disclosures } from "../manual/disclosures";
import { Composer } from "./Composer";
import { Handshake } from "./Handshake";
import type { Labels } from "./labels";
import type { Conversation as ConversationView, Locale } from "./types";
import type { ReviewChannel } from "./useReview";
export function Conversation({
  channel,
  conversation,
  locale,
  text,
}: {
  channel: ReviewChannel;
  conversation: ConversationView;
  locale: Locale;
  text: Labels;
}) {
  const [endChoice, setEndChoice] = useState(false);
  const participant = channel.context?.role === "pid";
  const disclosure = disclosures[locale];
  const acknowledge = () =>
    channel.write(
      `/v1/sessions/${conversation.id}/disclosure`,
      {
        expected_revision: conversation.revision,
        template_id: disclosure.id,
        template_digest: disclosure.digest,
        locale,
        acknowledged: true,
      },
      "CommandResult",
    );
  return (
    <section aria-labelledby="review-conversation-title">
      <h2 id="review-conversation-title">{text.conversation}</h2>
      {channel.workspace && (
        <>
          <p>
            {text.session}: <code>{conversation.id}</code>
          </p>
          <dl className="manual-state">
            <dt>{text.phase}</dt>
            <dd>
              {conversation.service_phase === "ended"
                ? text.endedPhase
                : text[conversation.service_phase]}
            </dd>
            <dt>{text.owner}</dt>
            <dd>{conversation.owner_id ?? text.none}</dd>
          </dl>
          <p role="status">
            {conversation.service_phase === "human_controlled" &&
            conversation.transport === "connected"
              ? text.connected
              : text.unconnected}
          </p>
          {conversation.unresolved && <p>{text.unresolved}</p>}
        </>
      )}
      {participant && conversation.service_phase !== "ended" && (
        <>
          <h3>{text.disclosure}</h3>
          <p>{disclosure.text}</p>
          {channel.workspace?.disclosure_acknowledged ? (
            <p>{text.acknowledged}</p>
          ) : (
            <button
              type="button"
              disabled={!channel.enabled}
              onClick={() => {
                void acknowledge();
              }}
            >
              {text.acknowledge}
            </button>
          )}
          {channel.workspace?.intake_submitted ? (
            <p>{text.submitted}</p>
          ) : (
            <Composer
              channel={channel}
              conversation={conversation}
              kind="intake"
              locale={locale}
              text={text}
            />
          )}
          <button
            type="button"
            disabled={
              !channel.enabled ||
              !["active", "human_requested"].includes(
                conversation.service_phase,
              )
            }
            onClick={() => {
              void channel.write(
                `/v1/sessions/${conversation.id}/human-request`,
                {
                  expected_revision: conversation.revision,
                  reason: "user_requested",
                },
                "QueueView",
              );
            }}
          >
            {text.human}
          </button>
        </>
      )}
      <Handshake channel={channel} conversation={conversation} text={text} />
      <div aria-live="polite" aria-relevant="additions text">
        {channel.messages.length ? (
          <ol className="manual-messages">
            {channel.messages.map((item) => (
              <li key={item.id}>
                <p>
                  {text.author}: {item.sender_id} · {text.source}: {item.kind}
                </p>
                <p className="manual-message-text">{item.text}</p>
              </li>
            ))}
          </ol>
        ) : (
          <p>{text.noMessages}</p>
        )}
      </div>
      {conversation.service_phase !== "ended" && (
        <Composer
          channel={channel}
          conversation={conversation}
          kind="message"
          locale={locale}
          text={text}
        />
      )}
      {participant && conversation.service_phase !== "ended" && (
        <>
          <label className="manual-choice">
            <input
              type="checkbox"
              checked={endChoice}
              onChange={(event) => setEndChoice(event.target.checked)}
            />
            {text.endConfirm}
          </label>
          <button
            type="button"
            disabled={!channel.enabled || !endChoice}
            onClick={() => {
              void channel.write(
                `/v1/sessions/${conversation.id}/end`,
                {
                  expected_revision: conversation.revision,
                  reason: "user_choice",
                },
                "CommandResult",
              );
            }}
          >
            {text.end}
          </button>
        </>
      )}
    </section>
  );
}
