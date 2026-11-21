import { useEffect, useRef, useState } from "react";
import { parseCapability, parseContract } from "@care-link/contracts";
import { messages } from "./messages";
import { TrustAndHelp } from "./trust/TrustAndHelp";
import { ManualService } from "./manual/ManualService";
import { ReviewApp } from "./review/ReviewApp";
import { PlansReviewApp } from "./plans-review/PlansReviewApp";
import { ReferralApp } from "./referrals/ReferralApp";
import { AssistanceApp } from "./assistance/AssistanceApp";
import { PlansWorkspace } from "./plans/PlansWorkspace";
import { LifecycleApp } from "./lifecycle/LifecycleApp";

type Locale = keyof typeof messages;
type Connection = "loading" | "unavailable" | "invalid" | "connected";
type Role = "participant" | "worker" | "supervisor";
type DemoContract = "RevisionCommand" | "SessionCreate";
const examples = {
  RevisionCommand: '{\n  "expected_revision": "1"\n}',
  SessionCreate: JSON.stringify(
    {
      tags: { environment: "demo", population: "synthetic" },
      participant_kind: "pid",
      jurisdiction: null,
      locale: "en-CA",
      channel: "web",
      persona_id: null,
      fixture_id: null,
    },
    null,
    2,
  ),
} satisfies Record<DemoContract, string>;

function DeveloperApp() {
  const [locale, setLocale] = useState<Locale>("en-CA");
  const [role, setRole] = useState<Role>("participant");
  const [connection, setConnection] = useState<Connection>("loading");
  const [attempt, setAttempt] = useState(0);
  const [contract, setContract] = useState<DemoContract>("RevisionCommand");
  const [raw, setRaw] = useState(examples.RevisionCommand);
  const [result, setResult] = useState<"valid" | "rejected" | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const text = messages[locale];

  useEffect(() => {
    document.documentElement.lang = locale;
    document.title = text.title;
  }, [locale, text.title]);

  useEffect(() => {
    const controller = new AbortController();
    setConnection("loading");
    const timeout = window.setTimeout(() => {
      setConnection("unavailable");
      controller.abort();
    }, 5000);
    async function load() {
      try {
        const response = await fetch("/dev/health", {
          signal: controller.signal,
          cache: "no-store",
          credentials: "omit",
        });
        if (!response.ok) {
          if (!controller.signal.aborted) setConnection("unavailable");
          return;
        }
        const body = await response.text();
        if (controller.signal.aborted) return;
        try {
          parseCapability(body);
          setConnection("connected");
        } catch {
          setConnection("invalid");
        }
      } catch {
        if (!controller.signal.aborted) setConnection("unavailable");
      } finally {
        window.clearTimeout(timeout);
      }
    }
    void load();
    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [attempt]);

  const roleNotice = {
    participant: text.participantNotice,
    worker: text.workerNotice,
    supervisor: text.supervisorNotice,
  }[role];

  return (
    <main>
      <header>
        <p className="eyebrow">{text.eyebrow}</p>
        <label className="language" htmlFor="language">
          {text.language}
        </label>
        <select
          id="language"
          value={locale}
          onChange={(event) => {
            const value = event.target.value;
            if (value === "en-CA" || value === "fr-CA") setLocale(value);
          }}
        >
          <option value="en-CA">English</option>
          <option value="fr-CA">Français</option>
        </select>
        <h1>{text.title}</h1>
        <p className="intro">{text.intro}</p>
      </header>
      <section aria-labelledby="capabilities-title">
        <h2 id="capabilities-title">{text.capabilities}</h2>
        <p role="status" className={`connection ${connection}`}>
          {text[connection]}
        </p>
        {connection === "connected" && <p>{text.scope}</p>}
        <button
          type="button"
          onClick={() => setAttempt((value) => value + 1)}
          disabled={connection === "loading"}
        >
          {text.retry}
        </button>
      </section>
      <section aria-labelledby="preview-title">
        <h2 id="preview-title">{text.preview}</h2>
        <label htmlFor="role">{text.preview}</label>
        <select
          id="role"
          value={role}
          onChange={(event) => {
            const value = event.target.value;
            if (
              value === "participant" ||
              value === "worker" ||
              value === "supervisor"
            )
              setRole(value);
          }}
        >
          <option value="participant">{text.participant}</option>
          <option value="worker">{text.worker}</option>
          <option value="supervisor">{text.supervisor}</option>
        </select>
        <p>{text.previewNotice}</p>
        <p className="notice">{roleNotice}</p>
      </section>
      <TrustAndHelp
        locale={locale}
        helpOrigin={import.meta.env.VITE_HELP_ORIGIN ?? null}
        oidcOrigin={import.meta.env.VITE_OIDC_ORIGIN ?? null}
        staticOrigin={import.meta.env.VITE_STATIC_ORIGIN ?? null}
      />
      <ManualService locale={locale} />
      <PlansWorkspace locale={locale} />
      <section aria-labelledby="contracts-title">
        <h2 id="contracts-title">{text.contracts}</h2>
        <p>{text.privacy}</p>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            try {
              parseContract(contract, raw);
              setResult("valid");
            } catch {
              setResult("rejected");
              input.current?.focus();
            }
          }}
        >
          <label htmlFor="contract">{text.contract}</label>
          <select
            id="contract"
            value={contract}
            onChange={(event) => {
              const value = event.target.value;
              if (value === "RevisionCommand" || value === "SessionCreate") {
                setContract(value);
                setRaw(examples[value]);
                setResult(null);
              }
            }}
          >
            <option value="RevisionCommand">RevisionCommand</option>
            <option value="SessionCreate">SessionCreate</option>
          </select>
          <label htmlFor="contract-input">{text.input}</label>
          <textarea
            id="contract-input"
            ref={input}
            value={raw}
            rows={12}
            spellCheck={false}
            aria-describedby="contract-hint contract-result"
            aria-invalid={result === "rejected"}
            onChange={(event) => {
              setRaw(event.target.value);
              setResult(null);
            }}
          />
          <p id="contract-hint" className="hint">
            {text.hint}
          </p>
          <button type="submit">{text.validate}</button>
          <p
            id="contract-result"
            role={result === "rejected" ? "alert" : "status"}
          >
            {result === null ? "" : text[result]}
          </p>
        </form>
      </section>
    </main>
  );
}

export function App() {
  if (window.location.pathname === "/follow-up") return <LifecycleApp />;
  if (window.location.pathname === "/assistance") return <AssistanceApp />;
  if (
    window.location.pathname === "/referrals" ||
    window.location.pathname.startsWith("/referrals/")
  )
    return <ReferralApp />;
  if (
    window.location.pathname === "/plans-review" ||
    window.location.pathname.startsWith("/plans-review/")
  )
    return <PlansReviewApp />;
  return /^r[0-9a-f]{32}-(participant|worker1|worker2|supervisor)\./.test(
    window.location.hostname,
  ) ? (
    <ReviewApp />
  ) : (
    <DeveloperApp />
  );
}
