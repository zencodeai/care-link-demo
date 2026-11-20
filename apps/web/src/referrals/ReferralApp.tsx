import { useEffect, useState } from "react";
import { label, messages, type Locale } from "./messages";
import { Worker } from "./Worker";
import { Client } from "./Client";
import { Receiver } from "./Receiver";
import { useActions } from "./useActions";
import "./styles.css";
export function ReferralApp() {
  const [locale, setLocale] = useState<Locale>("en-CA");
  const [mode, setMode] = useState<"worker" | "receiver" | "client">(
    window.location.pathname.startsWith("/referrals/client")
      ? "client"
      : window.location.pathname.startsWith("/referrals/receiver")
        ? "receiver"
        : "worker",
  );
  const text = messages[locale];
  const actions = useActions(text);
  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);
  return (
    <main className="referrals">
      <header>
        <p className="eyebrow">CARE-Link</p>
        <h1>{text.title}</h1>
        <p>{text.scope}</p>
        <label htmlFor="referral-language">{text.language}</label>
        <select
          id="referral-language"
          value={locale}
          onChange={(event) =>
            setLocale(event.target.value === "fr-CA" ? "fr-CA" : "en-CA")
          }
        >
          <option value="en-CA">English</option>
          <option value="fr-CA">Français</option>
        </select>
      </header>
      <section aria-labelledby="referral-account">
        <h2 id="referral-account">{text.actor}</h2>
        <p role="status" aria-live="polite">
          {actions.status}
        </p>
        {actions.session && (
          <p>
            {label(actions.session.role, text)} · {actions.session.assurance} ·{" "}
            {text.expiry}: {actions.session.expires_at}
          </p>
        )}
        <button disabled={actions.busy} onClick={() => void actions.run()}>
          {text.check}
        </button>
      </section>
      <nav aria-label={text.title} className="actions">
        <button
          disabled={actions.busy}
          aria-pressed={mode === "client"}
          onClick={() => setMode("client")}
        >
          {text.client}
        </button>
        <button
          disabled={actions.busy}
          aria-pressed={mode === "worker"}
          onClick={() => setMode("worker")}
        >
          {text.worker}
        </button>
        <button
          disabled={actions.busy}
          aria-pressed={mode === "receiver"}
          onClick={() => setMode("receiver")}
        >
          {text.receiver}
        </button>
      </nav>
      <div key={actions.epoch}>
        {mode === "client" ? (
          <Client actions={actions} text={text} />
        ) : mode === "worker" ? (
          <Worker actions={actions} text={text} />
        ) : (
          <Receiver actions={actions} text={text} />
        )}
      </div>
    </main>
  );
}
