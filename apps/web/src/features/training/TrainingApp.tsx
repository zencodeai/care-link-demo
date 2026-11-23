import { useEffect, useState } from "react";
import type { Locale } from "./api";
import { messages } from "./messages";
import { ReplayPanel } from "./ReplayPanel";
import { ScenarioPanel } from "./ScenarioPanel";
import { useTraining } from "./useTraining";
import { AccountPanel } from "../../trust/IdentityPanel";
import { useChannel } from "../../trust/channel";
import { configuredOrigin } from "../../trust/api";
import { trustMessages } from "../../trust/messages";
import "./styles.css";

export function TrainingApp() {
  const [locale, setLocale] = useState<Locale>("en-CA");
  const text = messages[locale];
  const workspace = useTraining();
  const channel = useChannel("");
  const oidc = configuredOrigin(import.meta.env.VITE_OIDC_ORIGIN);
  const { account, notice, pending, busy } = workspace;
  const blocked = busy || pending !== null;

  useEffect(() => {
    document.documentElement.lang = locale;
    document.title = text.title;
  }, [locale, text.title]);

  return (
    <main className="training-app">
      <header>
        <h1>{text.title}</h1>
        <p className="intro">{text.scope}</p>
        <label htmlFor="training-language">{text.language}</label>
        <select
          id="training-language"
          value={locale}
          onChange={(event) =>
            setLocale(event.target.value === "fr-CA" ? "fr-CA" : "en-CA")
          }
        >
          <option value="en-CA" lang="en">
            English
          </option>
          <option value="fr-CA" lang="fr">
            Français
          </option>
        </select>
      </header>
      <section aria-labelledby="training-access">
        <h2 id="training-access">{text.account}</h2>
        {oidc ? (
          <AccountPanel
            id="training-sign-in"
            training
            channel={channel}
            locale={locale}
            title={text.signIn}
            text={trustMessages[locale]}
            oidcOrigin={oidc}
            navigate={(url) => window.location.assign(url)}
          />
        ) : (
          <p>
            <a href="/">{text.signIn}</a>
          </p>
        )}
        <p role="status">
          {notice === "unchecked" || notice === "checking" || notice === "ready"
            ? text[notice]
            : ""}
        </p>
        {notice !== "unchecked" &&
          notice !== "checking" &&
          notice !== "ready" && <p role="alert">{text[notice]}</p>}
        {workspace.workspace && (
          <p>{account?.role === "trainer" ? text.trainer : text.governance}</p>
        )}
        {account && !workspace.workspace && <p>{text.unsupported}</p>}
        <button type="button" disabled={busy} onClick={workspace.check}>
          {text.check}
        </button>
      </section>
      {pending && (
        <section aria-labelledby="training-pending">
          <h2 id="training-pending">{text.pending}</h2>
          <p>
            <code>{pending.key}</code>
          </p>
          <button
            type="button"
            disabled={busy || !workspace.workspace}
            onClick={workspace.retry}
          >
            {text.retry}
          </button>
          {!workspace.workspace && <p>{text.retryHint}</p>}
        </section>
      )}
      {workspace.previousRole && (
        <div key={workspace.epoch}>
          {workspace.previousRole === "trainer" && (
            <ScenarioPanel
              workspace={workspace}
              locale={locale}
              text={text}
              blocked={blocked}
              available={workspace.workspace}
            />
          )}
          <ReplayPanel
            workspace={workspace}
            text={text}
            blocked={blocked}
            available={workspace.workspace}
          />
        </div>
      )}
    </main>
  );
}
