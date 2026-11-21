import { useEffect, useState } from "react";
import { Field } from "./Fields";
import { read } from "./api";
import { FollowUpPanel } from "./FollowUpPanel";
import { InboxPanel } from "./InboxPanel";
import { OutcomePanel } from "./OutcomePanel";
import { RightsPanel } from "./RightsPanel";
import { messages } from "./messages";
import type { Locale, SessionContext } from "./types";
import { useLifecycle } from "./useLifecycle";
function Workspace({
  channel,
  text,
}: {
  channel: ReturnType<typeof useLifecycle>;
  text: (typeof messages)[Locale];
}) {
  const [id, setId] = useState("");
  const [session, setSession] = useState<SessionContext | null>(null);
  useEffect(() => {
    if (session) load();
  }, [channel.sessionEpoch]);
  function load() {
    void channel.run(async (signal) =>
      setSession(await read(`/v1/sessions/${id}`, "SessionView", signal)),
    );
  }
  return (
    <>
      <InboxPanel channel={channel} text={text} />
      {channel.account && (
        <section aria-labelledby="session-title">
          <h2 id="session-title">{text.currentSession}</h2>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              load();
            }}
          >
            <Field
              id="lifecycle-session"
              label={text.session}
              value={id}
              onChange={setId}
              identifier
            />
            <button disabled={channel.busy}>{text.load}</button>
          </form>
          {session && (
            <p>
              {text.reference}: {session.id} · {text.revision}:{" "}
              {session.revision}
            </p>
          )}
        </section>
      )}
      {session && (
        <div key={session.id}>
          <FollowUpPanel channel={channel} text={text} session={session} />
          <OutcomePanel channel={channel} text={text} session={session} />
        </div>
      )}
      <RightsPanel channel={channel} text={text} session={session} />
    </>
  );
}
export function LifecycleApp() {
  const [locale, setLocale] = useState<Locale>("en-CA");
  const channel = useLifecycle();
  const text = messages[locale];
  useEffect(() => {
    document.documentElement.lang = locale;
    document.title = text.title;
  }, [locale, text.title]);
  return (
    <main>
      <header>
        <p className="eyebrow">CARE-Link</p>
        <h1>{text.title}</h1>
        <p>{text.scope}</p>
        <label htmlFor="lifecycle-language">{text.language}</label>
        <select
          id="lifecycle-language"
          value={locale}
          onChange={(e) =>
            setLocale(e.target.value === "fr-CA" ? "fr-CA" : "en-CA")
          }
        >
          <option value="en-CA">English</option>
          <option value="fr-CA">Français</option>
        </select>
      </header>
      <section aria-labelledby="lifecycle-account">
        <h2 id="lifecycle-account">{text.account}</h2>
        <p>
          <a href="/">{text.signIn}</a>
        </p>
        <p
          role={
            [
              "rejected",
              "invalid",
              "unknown",
              "signed_out",
              "unavailable",
            ].includes(channel.notice)
              ? "alert"
              : "status"
          }
          aria-live="polite"
        >
          {text[channel.notice]}
        </p>
        {channel.account && (
          <p>
            {channel.account.account_id} · {channel.account.assurance} ·{" "}
            {text.expires}:{" "}
            <time dateTime={channel.account.expires_at}>
              {channel.account.expires_at}
            </time>
          </p>
        )}
        <button disabled={channel.busy} onClick={() => void channel.run()}>
          {text.check}
        </button>
      </section>
      {channel.pending && (
        <section aria-label={text.pending}>
          <p>
            {text.pending}: {channel.pending.command.key}
          </p>
          <p>{text.unknown}</p>
          <button disabled={channel.busy} onClick={channel.retry}>
            {text.retry}
          </button>
        </section>
      )}
      <Workspace key={channel.epoch} channel={channel} text={text} />
    </main>
  );
}
