import { useEffect, useRef, useState } from "react";
import { get } from "../manual/api";
import { KnowledgePanel } from "./KnowledgePanel";
import { AssistancePanel } from "./AssistancePanel";
import { messages } from "./messages";
import type { Locale, SessionContext } from "./types";
function sessionContext(value: unknown): value is SessionContext {
  return (
    typeof value === "object" &&
    value !== null &&
    "id" in value &&
    typeof value.id === "string" &&
    "revision" in value &&
    typeof value.revision === "string" &&
    "subject_id" in value &&
    (value.subject_id === null || typeof value.subject_id === "string")
  );
}
export function AssistanceApp() {
  const [locale, setLocale] = useState<Locale>("en-CA");
  const [identifier, setIdentifier] = useState("");
  const [session, setSession] = useState<SessionContext | null>(null);
  const [status, setStatus] = useState<
    "invalid" | "unavailable" | "loading" | null
  >(null);
  const active = useRef<AbortController | null>(null);
  const text = messages[locale];
  useEffect(() => {
    document.documentElement.lang = locale;
    document.title = text.pageTitle;
  }, [locale, text.pageTitle]);
  useEffect(() => () => active.current?.abort(), []);
  async function load() {
    if (
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
        identifier,
      )
    ) {
      setStatus("invalid");
      return;
    }
    active.current?.abort();
    const current = new AbortController();
    active.current = current;
    setStatus("loading");
    setSession(null);
    try {
      const result = await get(
        `/v1/sessions/${identifier}`,
        "SessionView",
        sessionContext,
        current.signal,
      );
      if (!current.signal.aborted) {
        setSession(result);
        setStatus(null);
      }
    } catch {
      if (!current.signal.aborted) setStatus("unavailable");
    }
  }
  return (
    <main>
      <header>
        <p className="eyebrow">CARE-Link · {text.synthetic}</p>
        <h1>{text.pageTitle}</h1>
        <label htmlFor="assistance-language">{text.language}</label>
        <select
          id="assistance-language"
          value={locale}
          onChange={(event) =>
            setLocale(event.target.value === "fr-CA" ? "fr-CA" : "en-CA")
          }
        >
          <option value="en-CA">English</option>
          <option value="fr-CA">Français</option>
        </select>
      </header>
      <p>
        <a href="/">{text.manual}</a>
      </p>
      <KnowledgePanel locale={locale} />
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void load();
        }}
      >
        <label htmlFor="assistance-session">{text.session}</label>
        <input
          id="assistance-session"
          value={identifier}
          onChange={(event) => setIdentifier(event.target.value)}
          autoComplete="off"
          required
        />
        <button type="submit" disabled={status === "loading"}>
          {text.load}
        </button>
      </form>
      {status && (
        <p role={status === "loading" ? "status" : "alert"}>{text[status]}</p>
      )}
      {session && (
        <AssistancePanel key={session.id} locale={locale} session={session} />
      )}
    </main>
  );
}
