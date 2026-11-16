import { useEffect, useRef, useState } from "react";
import {
  authorizationUrl,
  configuredOrigin,
  type LoginIntent,
} from "../trust/api";
import { Conversation } from "./Conversation";
import { Workforce } from "./Workforce";
import { PendingOperations } from "./PendingOperations";
import { labels } from "./labels";
import { useReview } from "./useReview";
import type { Conversation as ConversationView, Locale } from "./types";
export function ReviewApp() {
  const [locale, setLocale] = useState<Locale>(() =>
    new URL(window.location.href).searchParams.get("locale") === "fr-CA"
      ? "fr-CA"
      : "en-CA",
  );
  const channel = useReview();
  const text = labels(locale);
  useEffect(() => {
    document.documentElement.lang = locale;
    document.title =
      text.title + (channel.context ? " · " + channel.context.slot_id : "");
  }, [locale, text.title, channel.context?.slot_id]);
  const cached = useRef<ConversationView | null>(null);
  if (channel.workspace) cached.current = channel.workspace.conversation;
  if (channel.notice === "wrongActor") cached.current = null;
  const current = channel.workspace?.conversation ?? cached.current;
  const participant = channel.context?.role === "pid";
  const oidc = configuredOrigin(import.meta.env.VITE_OIDC_ORIGIN);
  const help = configuredOrigin(import.meta.env.VITE_HELP_ORIGIN);
  const fallback = configuredOrigin(import.meta.env.VITE_STATIC_ORIGIN);
  const signIn = async () => {
    const context = channel.context;
    if (!context || !oidc) {
      channel.fail(new Error("unconfigured provider"));
      return;
    }
    const intent = await channel.write<LoginIntent>(
      "/v1/auth/login",
      {
        role: context.role,
        return_route: context.role === "pid" ? "participant" : "workforce",
        locale,
      },
      "LoginIntent",
    );
    if (intent)
      window.location.assign(authorizationUrl(intent.authorization_url, oidc));
  };
  const create = async () => {
    const result = await channel.write<ConversationView>(
      "/v1/sessions",
      {
        tags: { environment: "demo", population: "synthetic" },
        participant_kind: "pid",
        jurisdiction: null,
        locale,
        channel: "web",
        persona_id: null,
        fixture_id: null,
      },
      "SessionView",
    );
    if (result) channel.select(result.id);
  };
  return (
    <main className="review-app">
      <header>
        {new URL(window.location.href).searchParams.get("auth_error") ===
          "sign_in_interrupted" && <p role="alert">{text.authError}</p>}
        <label htmlFor="review-language">{text.language}</label>
        <select
          id="review-language"
          value={locale}
          onChange={(event) => {
            const value = event.target.value === "fr-CA" ? "fr-CA" : "en-CA";
            setLocale(value);
            document.documentElement.lang = value;
            const url = new URL(window.location.href);
            url.searchParams.set("locale", value);
            window.history.replaceState(null, "", url);
          }}
        >
          <option value="en-CA">English</option>
          <option value="fr-CA">Français</option>
        </select>
        <h1>{text.title}</h1>
        <p className="notice">{text.scope}</p>
        {channel.context && (
          <p>
            {text.slot}: <strong>{channel.context.slot_id}</strong> · {text.run}
            : <code>{channel.context.run_id}</code>
          </p>
        )}
        {channel.session && (
          <p>
            {text.actor}: {channel.session.role} ·{" "}
            <code>{channel.session.account_id}</code>
          </p>
        )}
        <p
          role={
            channel.notice === "wrongActor" || channel.notice === "rejected"
              ? "alert"
              : "status"
          }
        >
          {channel.notice
            ? text[channel.notice]
            : channel.view?.state === "observer"
              ? text.observer
              : !channel.ready
                ? text.connecting
                : ""}
        </p>
        <div className="actions">
          <button
            type="button"
            disabled={channel.busy || !channel.context || !oidc}
            onClick={() => {
              void signIn().catch(channel.fail);
            }}
          >
            {text.signIn}
          </button>
          {channel.session && (
            <button
              type="button"
              disabled={channel.busy}
              onClick={() => {
                void channel.write("/v1/auth/logout", {}, "CommandResult");
              }}
            >
              {text.signOut}
            </button>
          )}
          <button
            type="button"
            disabled={channel.busy}
            onClick={() => {
              void channel.refresh();
            }}
          >
            {text.retry}
          </button>
          <button
            type="button"
            disabled={channel.busy}
            onClick={() => {
              channel.select("");
              void channel.refresh();
            }}
          >
            {text.returnWorkspace}
          </button>
          {channel.view?.state === "observer" && (
            <button
              type="button"
              disabled={channel.busy}
              onClick={() => {
                void channel.claim();
              }}
            >
              {text.claim}
            </button>
          )}
        </div>
      </header>
      {channel.workspace?.run_state !== "active" && channel.workspace && (
        <p role="status">{text.closed}</p>
      )}
      <div
        hidden={
          !channel.session ||
          !channel.workspace ||
          channel.notice === "wrongActor"
        }
      >
        <PendingOperations channel={channel} text={text} />
        <div hidden={channel.workspace?.run_state !== "active"}>
          {!participant && <Workforce channel={channel} text={text} />}
          {!!channel.workspace?.conversations.length && (
            <section>
              <label htmlFor="review-conversation-select">{text.choose}</label>
              <select
                id="review-conversation-select"
                value={channel.selected}
                onChange={(event) => channel.select(event.target.value)}
              >
                <option value="">{text.choose}</option>
                {channel.workspace.conversations.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.id}
                  </option>
                ))}
              </select>
            </section>
          )}
          {participant && !current && (
            <button
              type="button"
              disabled={!channel.enabled}
              onClick={() => {
                void create();
              }}
            >
              {text.create}
            </button>
          )}
          {current && (
            <Conversation
              key={`${channel.context?.account_id}:${current.id}`}
              channel={channel}
              conversation={current}
              locale={locale}
              text={text}
            />
          )}
        </div>
      </div>
      <footer className="actions">
        {help && help !== window.location.origin && (
          <a href={help + "/private-help"}>{text.help}</a>
        )}
        {fallback &&
          fallback !== window.location.origin &&
          fallback !== help && (
            <a href={fallback + "/fallback?locale=" + locale}>
              {text.fallback}
            </a>
          )}
      </footer>
    </main>
  );
}
