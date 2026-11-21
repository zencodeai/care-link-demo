import { useEffect, useState } from "react";
import { read } from "./api";
import type { Text } from "./messages";
import type { InboxMessage, Page } from "./types";
import type { Channel } from "./useLifecycle";
export function InboxPanel({
  channel,
  text,
}: {
  channel: Channel;
  text: Text;
}) {
  const [page, setPage] = useState<Page<InboxMessage> | null>(null);
  const [message, setMessage] = useState<InboxMessage | null>(null);
  useEffect(() => {
    setPage(null);
    setMessage(null);
  }, [channel.privateEpoch]);
  function load(cursor?: string | null) {
    setMessage(null);
    void channel.run(async (signal) =>
      setPage(
        await read(
          `/v1/inbox${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`,
          "InboxPage",
          signal,
        ),
      ),
    );
  }
  if (!channel.account) return null;
  return (
    <section aria-labelledby="inbox-title">
      <h2 id="inbox-title">{text.inbox}</h2>
      <button disabled={channel.busy} onClick={() => load()}>
        {text.openInbox}
      </button>
      {page &&
        (page.items.length ? (
          <ul>
            {page.items.map((item) => (
              <li key={item.id}>
                <time dateTime={item.created_at}>{item.created_at}</time> ·{" "}
                <button
                  disabled={channel.busy}
                  onClick={() =>
                    void channel.run(async (signal) =>
                      setMessage(
                        await read(
                          `/v1/inbox/${item.id}`,
                          "InboxMessageView",
                          signal,
                        ),
                      ),
                    )
                  }
                >
                  {text.openMessage}
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p>{text.noMessages}</p>
        ))}
      {page?.next_cursor && (
        <button disabled={channel.busy} onClick={() => load(page.next_cursor)}>
          {text.next}
        </button>
      )}
      {message && (
        <article>
          <p>{message.text}</p>
          <p>
            {text.expires}:{" "}
            <time dateTime={message.expires_at}>{message.expires_at}</time>
          </p>
          {message.read_at && (
            <p>
              {text.readAt}:{" "}
              <time dateTime={message.read_at}>{message.read_at}</time>
            </p>
          )}
        </article>
      )}
    </section>
  );
}
