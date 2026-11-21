import { useEffect, useState } from "react";
import "./styles.css";
import { ActivationPanel } from "./ActivationPanel";
import { Artifacts } from "./Artifacts";
import { EvidencePanel } from "./EvidencePanel";
import { GrantPanel, ExceptionPanel } from "./GrantPanel";
import { IncidentPanel } from "./IncidentPanel";
import { MetricsPanel } from "./MetricsPanel";
import { State } from "./Labels";
import { messages } from "./messages";
import type { Locale } from "./types";
import { useGovernance } from "./useGovernance";
export function GovernanceApp() {
  const [locale, setLocale] = useState<Locale>("en-CA"),
    channel = useGovernance(),
    text = messages[locale];
  const role = channel.role;
  useEffect(() => {
    document.documentElement.lang = locale;
    document.title = text.title;
  }, [locale, text.title]);
  const controls =
    role !== null && ["operator", "security", "governance"].includes(role);
  const grants = role !== null && ["security", "governance"].includes(role);
  return (
    <main className="governance-app">
      <header>
        <p className="eyebrow">CARE-Link</p>
        <h1>{text.title}</h1>
        <p>{text.scope}</p>
        <label htmlFor="governance-language">{text.language}</label>
        <select
          id="governance-language"
          value={locale}
          onChange={(e) =>
            setLocale(e.target.value === "fr-CA" ? "fr-CA" : "en-CA")
          }
        >
          <option value="en-CA">English</option>
          <option value="fr-CA">Français</option>
        </select>
      </header>
      <section aria-labelledby="governance-account">
        <h2 id="governance-account">{text.account}</h2>
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
            {channel.account.account_id} · {text.role}:{" "}
            <State value={channel.account.role} text={text} /> ·{" "}
            {channel.account.assurance} · {text.expires}:{" "}
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
            {text.pending}: <code>{channel.pending.command.key}</code>
          </p>
          <p>{text.unknown}</p>
          <button
            disabled={channel.busy || !channel.account}
            onClick={channel.retry}
          >
            {text.retry}
          </button>
        </section>
      )}
      <div key={channel.epoch} hidden={!channel.account}>
        {controls && (
          <>
            <Artifacts channel={channel} text={text} />
            <ActivationPanel channel={channel} text={text} />
            <IncidentPanel channel={channel} text={text} />
          </>
        )}
        {grants && <GrantPanel channel={channel} text={text} />}
        {role === "governance" && (
          <ExceptionPanel channel={channel} text={text} />
        )}
        {role === "auditor" && <EvidencePanel channel={channel} text={text} />}
        {role !== null &&
          ["auditor", "governance", "supervisor"].includes(role) && (
            <MetricsPanel channel={channel} text={text} />
          )}
        {role !== null &&
          ![
            "operator",
            "security",
            "governance",
            "auditor",
            "supervisor",
          ].includes(role) && <p>{text.unsupported}</p>}
      </div>
    </main>
  );
}
