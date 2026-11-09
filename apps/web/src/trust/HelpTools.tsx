import { useEffect, useState } from "react";
import { decodeHelp, request, RequestFailure, type HelpView } from "./api";
import { type Channel } from "./channel";
import { type Locale, type Text } from "./messages";
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export function HelpTools({
  channel,
  text,
  locale,
}: {
  channel: Channel;
  text: Text;
  locale: Locale;
}) {
  const [helpId, setHelpId] = useState("");
  const [view, setView] = useState<HelpView | null>(null);
  const [badId, setBadId] = useState(false);
  const { session, busy, run, mutate, origin, prepareHelpCreate } = channel;
  // Reauthentication can change the actor. Never retain an earlier actor's view.
  useEffect(() => {
    setView(null);
  }, [session]);
  function helpAction(action: "status" | "accept" | "cancel") {
    if (!uuid.test(helpId)) {
      setBadId(true);
      return;
    }
    const revision = view?.revision;
    setView(null);
    void run(async (signal) => {
      const matchingView = (raw: string) => {
        const current = decodeHelp(raw);
        if (current.id !== helpId) throw new RequestFailure("invalid");
        return current;
      };
      const raw =
        action === "status"
          ? await request(origin, `/help/v1/requests/${helpId}`, signal)
          : null;
      const current =
        raw === null
          ? await mutate(
              `/help/v1/requests/${helpId}/${action}`,
              { expected_revision: revision },
              signal,
              matchingView,
            )
          : matchingView(raw);
      setView(current);
    });
  }
  const participant =
    session &&
    ["pid", "carer", "professional_participant"].includes(session.role);
  const workforce = session && ["worker", "supervisor"].includes(session.role);
  return (
    <div className="help-tools">
      <h4>{text.request}</h4>
      <p>{text.privacy}</p>
      {channel.notice === "rejected" && (
        <p role="alert">{text.retrySettings}</p>
      )}
      <button
        type="button"
        disabled={busy || !participant}
        onClick={() => {
          setView(null);
          void run(async (signal) => {
            const body = { locale, jurisdiction: null };
            const operationId = await prepareHelpCreate(body, signal);
            const current = await mutate(
              "/help/v1/requests",
              body,
              signal,
              decodeHelp,
              operationId,
            );
            setHelpId(current.id);
            setView(current);
          });
        }}
      >
        {text.create}
      </button>
      <label htmlFor="help-request-id">{text.helpId}</label>
      <input
        id="help-request-id"
        disabled={busy}
        value={helpId}
        autoComplete="off"
        spellCheck={false}
        aria-invalid={badId}
        onChange={(event) => {
          setHelpId(event.target.value);
          setView(null);
          setBadId(false);
        }}
      />
      {badId && <p role="alert">{text.invalidId}</p>}
      <div className="actions">
        <button
          type="button"
          disabled={busy || !session}
          onClick={() => helpAction("status")}
        >
          {text.status}
        </button>
        <button
          type="button"
          disabled={busy || !workforce || view?.state !== "recorded"}
          onClick={() => helpAction("accept")}
        >
          {text.accept}
        </button>
        <button
          type="button"
          disabled={busy || !participant || !view || view.state === "cancelled"}
          onClick={() => helpAction("cancel")}
        >
          {text.cancel}
        </button>
      </div>
      <p role="status">{view ? text[view.state] : text.noHelp}</p>
      {view && (
        <p>
          {text.revision}: {view.revision}
        </p>
      )}
    </div>
  );
}
