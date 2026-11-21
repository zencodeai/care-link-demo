import { useEffect, useState } from "react";
import { KnowledgePanel } from "../assistance/KnowledgePanel";
import { AssistancePanel } from "../assistance/AssistancePanel";
import { Connection } from "./Connection";
import { manualMessages, type Locale } from "./messages";
import { Participant } from "./Participant";
import { useManual } from "./useManual";
import { Workforce } from "./Workforce";
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export function ManualService({ locale }: { locale: Locale }) {
  const channel = useManual();
  const text = manualMessages[locale];
  const [sessionId, setSessionId] = useState("");
  const [badId, setBadId] = useState(false);
  const [draft, setDraft] = useState("");
  const [workspace, setWorkspace] = useState({ account: "", role: "" });
  const identity = channel.identity;
  const view = channel.view;
  const disabled = channel.busy || channel.pending !== null;
  const role = identity?.role ?? workspace.role;
  const workspaceAccount = identity?.account_id ?? workspace.account;
  const participant = ["pid", "carer", "professional_participant"].includes(
    role,
  );
  const workforce = role === "worker" || role === "supervisor";
  useEffect(() => {
    if (identity) {
      setWorkspace((previous) => {
        if (
          previous.account &&
          (previous.account !== identity.account_id ||
            previous.role !== identity.role)
        ) {
          setDraft("");
          setSessionId("");
        }
        return { account: identity.account_id, role: identity.role };
      });
    }
  }, [identity]);
  return (
    <section aria-labelledby="manual-title">
      <h2 id="manual-title">{text.title}</h2>
      <p id="manual-scope" className="notice">
        {text.scope}
      </p>
      <p className="notice">{text.recoveryUnproven}</p>
      <p role="status">{text[channel.notice]}</p>
      <button
        type="button"
        disabled={channel.busy}
        onClick={() => {
          void channel.check();
        }}
      >
        {text.check}
      </button>
      {channel.pending && (
        <div className="manual-reconciliation">
          <p>
            {text.operation}: <code>{channel.pending.command.key}</code>
          </p>
          <div className="actions">
            <button
              type="button"
              disabled={channel.busy}
              onClick={() => {
                void channel.reconcile();
              }}
            >
              {text.reconcile}
            </button>
            <button
              type="button"
              disabled={channel.busy}
              onClick={() => {
                void channel.retry();
              }}
            >
              {text.retry}
            </button>
          </div>
          {channel.status && (
            <p role="status">
              {text.resolved}: {channel.status.state}
            </p>
          )}
        </div>
      )}
      {identity && (
        <p>
          {text.role}: {identity.role}
        </p>
      )}
      <div
        hidden={!identity || !participant}
        key={`participant-${workspaceAccount}-${role}`}
      >
        <Participant channel={channel} locale={locale} text={text} />
      </div>
      <div
        hidden={!identity || !workforce}
        key={`workforce-${workspaceAccount}-${role}`}
      >
        <Workforce channel={channel} text={text} />
      </div>
      {identity && !participant && !workforce && <p>{text.unsupported}</p>}
      {identity &&
        [
          "pid",
          "carer",
          "professional_participant",
          "worker",
          "supervisor",
          "receiver",
        ].includes(identity.role) && (
          <KnowledgePanel
            key={`knowledge-${identity.account_id}:${identity.role}`}
            locale={locale}
          />
        )}
      {identity && (participant || workforce) && (
        <>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (!uuid.test(sessionId)) {
                setBadId(true);
                return;
              }
              setBadId(false);
              void channel.refresh(sessionId);
            }}
          >
            <label htmlFor="manual-session-id">{text.session}</label>
            <input
              id="manual-session-id"
              value={sessionId}
              autoComplete="off"
              spellCheck={false}
              onChange={(event) => {
                setSessionId(event.target.value);
                setBadId(false);
              }}
              aria-invalid={badId}
              aria-describedby={badId ? "manual-session-error" : undefined}
            />
            {badId && (
              <p id="manual-session-error" role="alert">
                {text.invalidId}
              </p>
            )}
            <button type="submit" disabled={disabled}>
              {text.open}
            </button>
          </form>
          {view && (
            <section aria-labelledby="manual-current-title">
              <h3 id="manual-current-title">{text.conversation}</h3>
              <p>
                {text.session}: <code>{view.id}</code>
              </p>
              <dl className="manual-state">
                <dt>{text.phase}</dt>
                <dd>
                  {view.service_phase === "ended"
                    ? text.endedPhase
                    : text[view.service_phase]}
                </dd>
                <dt>{text.owner}</dt>
                <dd>{view.owner_id ?? text.none}</dd>
                <dt>{text.epoch}</dt>
                <dd>{view.control_epoch}</dd>
              </dl>
              <p role="status">
                {view.service_phase === "human_controlled" &&
                view.transport === "connected"
                  ? text.connected
                  : text.unconnected}
              </p>
              {view.transport === "disconnected" && <p>{text.disconnected}</p>}
              {view.unresolved && <p>{text.unresolved}</p>}
              {view.service_phase === "ended" && <p>{text.ended}</p>}
              {view.degraded_reasons.length > 0 && (
                <p>{view.degraded_reasons.join(" · ")}</p>
              )}
              <button
                type="button"
                disabled={disabled}
                onClick={() => {
                  void channel.refresh();
                }}
              >
                {text.refresh}
              </button>
              <Connection channel={channel} text={text} />
              {workforce && view.owner_id === identity.account_id && (
                <AssistancePanel
                  key={`${identity.account_id}:${view.id}`}
                  locale={locale}
                  allowAutomatic
                  session={{
                    id: view.id,
                    revision: view.revision,
                    subject_id: null,
                  }}
                />
              )}
              <div aria-live="polite" aria-relevant="additions text">
                {channel.messages.length === 0 ? (
                  <p>{text.noMessages}</p>
                ) : (
                  <ol className="manual-messages">
                    {channel.messages.map((item) => (
                      <li key={item.id}>
                        <p className="hint">
                          {text.author}: {item.sender_id} · {text.source}:{" "}
                          {item.kind}
                        </p>
                        <p className="manual-message-text">{item.text}</p>
                        <time dateTime={item.created_at}>
                          {new Intl.DateTimeFormat(locale, {
                            dateStyle: "short",
                            timeStyle: "short",
                            timeZone: "America/Toronto",
                          }).format(new Date(item.created_at))}{" "}
                          (America/Toronto)
                        </time>
                      </li>
                    ))}
                  </ol>
                )}
              </div>
              {channel.nextMessages && (
                <>
                  <p>{text.more}</p>
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => {
                      void channel.loadMessages();
                    }}
                  >
                    {text.next}
                  </button>
                </>
              )}
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  if (
                    !draft.trim() ||
                    disabled ||
                    view.service_phase === "ended"
                  )
                    return;
                  void channel.perform(
                    `/v1/sessions/${view.id}/messages`,
                    "MessageSubmit",
                    {
                      expected_revision: view.revision,
                      expected_control_epoch: view.control_epoch,
                      text: draft,
                      accepted_draft_id: null,
                    },
                    "MessageView",
                    () => setDraft(""),
                  );
                }}
              >
                <label htmlFor="manual-message">{text.message}</label>
                <textarea
                  id="manual-message"
                  rows={4}
                  maxLength={8000}
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                />
                <button
                  type="submit"
                  disabled={
                    disabled ||
                    !draft.trim() ||
                    view.service_phase === "ended" ||
                    (workforce && view.owner_id !== identity.account_id)
                  }
                >
                  {text.send}
                </button>
              </form>
            </section>
          )}
        </>
      )}
    </section>
  );
}
