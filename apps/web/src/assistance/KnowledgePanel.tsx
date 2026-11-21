import { useEffect, useId, useRef, useState } from "react";
import { write } from "./api";
import { messages } from "./messages";
import { referenceUrl } from "./reference";
import type { KnowledgeResults, Locale } from "./types";

export function KnowledgePanel({ locale }: { locale: Locale }) {
  const text = messages[locale],
    id = useId();
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<KnowledgeResults | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "failed" | "ready">(
    "idle",
  );
  const active = useRef<AbortController | null>(null);
  useEffect(() => {
    active.current?.abort();
    setResult(null);
    setState("idle");
    return () => {
      active.current?.abort();
      active.current = null;
    };
  }, [locale]);
  async function search() {
    if (!query.trim() || query.length > 500 || state === "loading") return;
    active.current?.abort();
    const current = new AbortController();
    active.current = current;
    setResult(null);
    setState("loading");
    const timeout = window.setTimeout(() => {
      if (active.current !== current) return;
      current.abort();
      setResult(null);
      setState("failed");
    }, 5000);
    try {
      const found = await write(
        {
          key: crypto.randomUUID(),
          path: "/v1/assistance/knowledge",
          input: "KnowledgeQuery",
          output: "KnowledgeResults",
          body: { query: query.trim(), locale },
        },
        current.signal,
      );
      if (current.signal.aborted) return;
      setResult(found);
      setState("ready");
    } catch {
      if (current.signal.aborted) return;
      setResult(null);
      setState("failed");
    } finally {
      window.clearTimeout(timeout);
    }
  }
  return (
    <section
      className="assistance assistance-knowledge"
      aria-labelledby={`${id}-title`}
    >
      <h2 id={`${id}-title`}>{text.knowledgeTitle}</h2>
      <p>{text.knowledgeScope}</p>
      <p>{text.sourceIntegrity}</p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void search();
        }}
      >
        <label htmlFor={`${id}-query`}>{text.knowledgeQuery}</label>
        <input
          id={`${id}-query`}
          value={query}
          maxLength={500}
          autoComplete="off"
          onChange={(event) => setQuery(event.target.value)}
        />
        <button type="submit" disabled={state === "loading" || !query.trim()}>
          {text.knowledgeSearch}
        </button>
      </form>
      {state !== "idle" && (
        <p role={state === "failed" ? "alert" : "status"}>
          {state === "loading"
            ? text.knowledgeLoading
            : state === "failed"
              ? text.knowledgeFailed
              : text.knowledgeReady}
        </p>
      )}
      {result &&
        (result.entries.length ? (
          <ul>
            {result.entries.map((entry) => {
              const url = referenceUrl(entry.source_url);
              return (
                <li key={`${entry.source.id}:${entry.source.revision}`}>
                  <h3>{entry.title}</h3>
                  <p className="assistance-copy">{entry.text}</p>
                  <p>
                    {text.knowledgeSource}:{" "}
                    {url ? (
                      <a href={url} target="_blank" rel="noopener noreferrer">
                        {entry.source_title}
                      </a>
                    ) : (
                      entry.source_title
                    )}
                  </p>
                  <p>
                    {text.knowledgeRevision}: {entry.source.revision} ·{" "}
                    {text.observed}:{" "}
                    <time dateTime={entry.source.observed_at}>
                      {entry.source.observed_at}
                    </time>
                  </p>
                </li>
              );
            })}
          </ul>
        ) : (
          <p>{text.knowledgeEmpty}</p>
        ))}
    </section>
  );
}
