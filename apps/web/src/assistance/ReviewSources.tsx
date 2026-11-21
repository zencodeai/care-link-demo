import { referenceUrl } from "./reference";
import type { Text } from "./messages";
import type { DraftContext } from "./types";

export function ReviewSources({
  sources,
  text,
  empty,
}: {
  sources: DraftContext["sources"];
  text: Text;
  empty: string;
}) {
  if (!sources.length) return <p>{empty}</p>;
  return (
    <ul>
      {sources.map(({ ref, text: fact, title, source_url, source_title }) => {
        const url = source_url ? referenceUrl(source_url) : null;
        return (
          <li key={`${ref.kind}:${ref.id}:${ref.revision}`}>
            {title && <h5>{title}</h5>}
            <p className="assistance-copy">{fact}</p>
            {source_title && (
              <p>
                {text.knowledgeSource}:{" "}
                {url ? (
                  <a href={url} target="_blank" rel="noopener noreferrer">
                    {source_title}
                  </a>
                ) : (
                  source_title
                )}
              </p>
            )}
            <p>
              {text.source}: <code>{ref.id}</code> · {text.revision}:{" "}
              {ref.revision}
            </p>
            <p>
              {text.observed}:{" "}
              <time dateTime={ref.observed_at}>{ref.observed_at}</time> ·{" "}
              {text.verification}:{" "}
              {ref.verification === "unknown"
                ? text.unknownValue
                : text[ref.verification]}
            </p>
          </li>
        );
      })}
    </ul>
  );
}
