import { useEffect } from "react";
import type { ViewLease } from "./types";

export function useConnection(
  view: ViewLease | null,
  epoch: number,
  ready: (id: string) => void,
  changed: () => void,
  lost: (id: string) => void,
) {
  useEffect(() => {
    if (!view || view.state !== "active") return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const connect = async () => {
      let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
      try {
        const response = await fetch("/v1/review/events", {
          credentials: "include",
          cache: "no-store",
          redirect: "error",
          signal: controller.signal,
          headers: { "X-Review-View": view.view_id },
        });
        if (
          !response.ok ||
          !response.body ||
          !response.headers.get("content-type")?.startsWith("text/event-stream")
        )
          throw new Error("Review connection unavailable");
        reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (!controller.signal.aborted) {
          const chunk = await reader.read();
          if (chunk.done) break;
          buffer += decoder.decode(chunk.value, { stream: true });
          let boundary = buffer.indexOf("\n\n");
          while (boundary >= 0) {
            const event = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            if (/^event:\s*ready\s*$/m.test(event)) ready(view.view_id);
            if (
              /^event:\s*(lost|resync_required|rights_changed)\s*$/m.test(event)
            ) {
              lost(view.view_id);
              throw new Error("Current review channel lost");
            } else if (/^event:\s*changed\s*$/m.test(event)) changed();
            boundary = buffer.indexOf("\n\n");
          }
          if (buffer.length > 65536) throw new Error("Invalid review event");
        }
      } catch {
        /* Parent revalidates all current authority before effects. */
      } finally {
        void reader?.cancel().catch(() => {});
      }
      if (!controller.signal.aborted) {
        lost(view.view_id);
        timer = setTimeout(() => {
          void connect();
        }, 1500);
      }
    };
    void connect();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [view?.view_id, view?.state, epoch, ready, changed, lost]);
}
