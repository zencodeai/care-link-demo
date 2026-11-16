import { useState } from "react";
import { disclosures } from "./disclosures";
import { type ManualChannel } from "./useManual";
import { type Locale, type Text } from "./messages";
export function Participant({
  channel,
  locale,
  text,
}: {
  channel: ManualChannel;
  locale: Locale;
  text: Text;
}) {
  const [story, setStory] = useState("");
  const [acknowledged, setAcknowledged] = useState<string | null>(null);
  const [endChoice, setEndChoice] = useState(false);
  const view = channel.view;
  const disclosure = disclosures[locale];
  const disabled = channel.busy || channel.pending !== null;
  const active = !!view && view.service_phase !== "ended";
  return (
    <section aria-labelledby="manual-participant-title">
      <h3 id="manual-participant-title">{text.participant}</h3>
      {!view && (
        <button
          type="button"
          disabled={disabled}
          onClick={() => {
            const kind = channel.identity?.role;
            if (
              kind !== "pid" &&
              kind !== "carer" &&
              kind !== "professional_participant"
            )
              return;
            void channel.perform(
              "/v1/sessions",
              "SessionCreate",
              {
                tags: { environment: "demo", population: "synthetic" },
                participant_kind: kind,
                jurisdiction: null,
                locale,
                channel: "web",
                persona_id: null,
                fixture_id: null,
              },
              "SessionView",
              channel.receiveView,
            );
          }}
        >
          {text.create}
        </button>
      )}
      {active && (
        <>
          <h4>{text.disclosure}</h4>
          <p>{disclosure.text}</p>
          <button
            type="button"
            disabled={disabled || acknowledged === view.id}
            onClick={() => {
              void channel.perform(
                `/v1/sessions/${view.id}/disclosure`,
                "DisclosureAck",
                {
                  expected_revision: view.revision,
                  template_id: disclosure.id,
                  template_digest: disclosure.digest,
                  locale,
                  acknowledged: true,
                },
                "CommandResult",
                () => setAcknowledged(view.id),
              );
            }}
          >
            {text.acknowledge}
          </button>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (!story.trim() || disabled || acknowledged !== view.id) return;
              void channel.perform(
                `/v1/sessions/${view.id}/turns`,
                "TurnSubmit",
                {
                  expected_revision: view.revision,
                  client_turn_id: crypto.randomUUID(),
                  text: story,
                  locale,
                },
                "AssessmentView",
                () => setStory(""),
              );
            }}
          >
            <label htmlFor="manual-story">{text.story}</label>
            <textarea
              id="manual-story"
              value={story}
              maxLength={8000}
              rows={5}
              onChange={(event) => setStory(event.target.value)}
              aria-describedby="manual-scope"
            />
            <button
              type="submit"
              disabled={disabled || !story.trim() || acknowledged !== view.id}
            >
              {text.turn}
            </button>
          </form>
          <div className="actions">
            <button
              type="button"
              disabled={disabled}
              onClick={() => {
                void channel.perform(
                  `/v1/sessions/${view.id}/human-request`,
                  "HumanRequest",
                  {
                    expected_revision: view.revision,
                    reason: "user_requested",
                  },
                  "QueueView",
                );
              }}
            >
              {text.human}
            </button>
          </div>
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
            disabled={disabled || !endChoice}
            onClick={() => {
              void channel.perform(
                `/v1/sessions/${view.id}/end`,
                "ReasonCommand",
                { expected_revision: view.revision, reason: "user_choice" },
                "CommandResult",
                () => setEndChoice(false),
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
