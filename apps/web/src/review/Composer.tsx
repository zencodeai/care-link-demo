import { useState } from "react";
import { headers, json } from "./api";
import type { Labels } from "./labels";
import { useDraft } from "./useDraft";
import type { ReviewChannel } from "./useReview";
import type { Conversation, Draft, Intent, Locale } from "./types";
export function Composer({
  channel,
  conversation,
  kind,
  locale,
  text,
}: {
  channel: ReviewChannel;
  conversation: Conversation;
  kind: Draft["kind"];
  locale: Locale;
  text: Labels;
}) {
  const draft = useDraft(channel, conversation.id, kind);
  const [submitting, setSubmitting] = useState(false);
  const isIntake = kind === "intake";
  const permitted =
    channel.enabled &&
    (!isIntake || channel.workspace?.disclosure_acknowledged) &&
    (!isIntake
      ? channel.session?.role === "pid" ||
        conversation.owner_id === channel.session?.account_id
      : true);
  const submit = async () => {
    setSubmitting(true);
    try {
      const saved = await draft.flush();
      if (!saved || !saved.text.trim()) return;
      const current = await json<Conversation>(
        `/v1/sessions/${conversation.id}`,
        "SessionView",
        headers(channel.view?.view_id ?? null),
      );
      const intent = await channel.write<Intent>(
        `/v1/review/sessions/${conversation.id}/intent`,
        {
          kind,
          draft_revision: saved.revision,
          expected_revision: current.revision,
          expected_control_epoch: current.control_epoch,
          locale,
        },
        "ReviewIntentView",
      );
      if (
        intent?.payload &&
        !["committed", "rejected", "cancelled"].includes(intent.state)
      )
        await channel.write(
          `/v1/sessions/${conversation.id}/${isIntake ? "turns" : "messages"}`,
          intent.payload,
          isIntake ? "AssessmentView" : "MessageView",
          intent.operation_id,
        );
    } catch (error) {
      channel.fail(error);
    } finally {
      setSubmitting(false);
    }
  };
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <label htmlFor={`review-${kind}`}>
        {isIntake ? text.story : text.message}
      </label>
      <textarea
        id={`review-${kind}`}
        value={draft.text}
        maxLength={8000}
        rows={4}
        disabled={!channel.enabled || submitting}
        onChange={(event) => draft.edit(event.target.value)}
        onBlur={() => {
          if (channel.enabled) void draft.flush();
        }}
        aria-describedby={`review-${kind}-saved`}
      />
      <p id={`review-${kind}-saved`} role="status">
        {text[draft.state]}
      </p>
      {draft.state === "draftError" && (
        <button
          type="button"
          disabled={!channel.enabled}
          onClick={() => {
            void draft.flush();
          }}
        >
          {text.retryDraft}
        </button>
      )}
      <button
        type="submit"
        disabled={!permitted || submitting || !draft.text.trim()}
      >
        {isIntake ? text.turn : text.send}
      </button>
    </form>
  );
}
