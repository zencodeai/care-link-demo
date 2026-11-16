import { useEffect, useState } from "react";
import type { ViewLease } from "./types";
export function useEvents(
  view: ViewLease | null,
  onUpdate: () => void,
  onLost: () => void,
) {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    setReady(false);
    if (!view || view.state !== "active") return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const run = async () => {
      try {
        const response = await fetch("/v1/review/events", {
          credentials: "include",
          cache: "no-store",
          redirect: "error",
          headers: { "X-Review-View": view.view_id },
          signal: controller.signal,
        });
        if (!response.ok || !response.body)
          throw new Error("stream unavailable");
        const reader = response.body.getReader();
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
            if (/^event:\s*ready\s*$/m.test(event)) setReady(true);
            if (
              /^event:\s*(lost|resync_required|rights_changed)\s*$/m.test(event)
            ) {
              setReady(false);
              onLost();
            } else if (/^event:\s*changed\s*$/m.test(event)) onUpdate();
            boundary = buffer.indexOf("\n\n");
          }
          if (buffer.length > 65536) throw new Error("invalid stream");
        }
      } catch {
        /* current workspace reads provide the safe recovery status */
      }
      if (!controller.signal.aborted) {
        setReady(false);
        onLost();
        timer = setTimeout(() => {
          void run();
        }, 1500);
      }
    };
    void run();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [view?.view_id, view?.state, onUpdate, onLost]);
  return ready;
}
