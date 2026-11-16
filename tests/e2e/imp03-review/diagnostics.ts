import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { ActorPage } from "./browser";
import { slots, type Slot } from "./config";

interface ResponseObservation {
  path: string;
  status: number;
  error_code: string | null;
}

export function observeResponses(actors: Record<Slot, ActorPage>) {
  const observations = {} as Record<Slot, ResponseObservation[]>;
  for (const slot of slots) {
    observations[slot] = [];
    const actor = actors[slot];
    actor.page.on("response", (response) => {
      const url = new URL(response.url());
      if (
        url.origin !== actor.actor.origin ||
        !url.pathname.startsWith("/v1/") ||
        url.pathname === "/v1/auth/callback"
      )
        return;
      const observation: ResponseObservation = {
        path: url.pathname,
        status: response.status(),
        error_code: null,
      };
      const recent = observations[slot];
      recent.push(observation);
      if (recent.length > 50) recent.shift();
      if (
        response.status() >= 400 &&
        response.headers()["content-type"]?.includes("application/json")
      )
        void response
          .json()
          .then((value: unknown) => {
            if (value && typeof value === "object" && "code" in value) {
              const code: unknown = value.code;
              if (
                typeof code === "string" &&
                /^[A-Z][A-Z0-9_]{0,79}$/.test(code)
              )
                observation.error_code = code;
            }
          })
          .catch(() => {
            // Unavailable bodies remain unknown; never store a raw response.
          });
    });
  }
  return observations;
}

export async function captureFailurePages(
  output: string,
  phase: string,
  actors: Record<Slot, ActorPage>,
  responses: Record<Slot, ResponseObservation[]>,
) {
  const pages = await Promise.all(
    slots.map(async (slot) => {
      const actor = actors[slot];
      const url = new URL(actor.page.url());
      const sameOrigin = url.origin === actor.actor.origin;
      return {
        slot,
        same_origin: sameOrigin,
        path: sameOrigin ? url.pathname : null,
        closed: actor.page.isClosed(),
        visible_body:
          sameOrigin && !actor.page.isClosed()
            ? await actor.page
                .locator("body")
                .innerText({ timeout: 2000 })
                .then((body) => body.slice(0, 20000))
                .catch(() => null)
            : null,
        recent_same_origin_api_responses: responses[slot],
      };
    }),
  );
  writeFileSync(
    resolve(output, "failure-pages.json"),
    JSON.stringify({ phase, pages }, null, 2),
    { mode: 0o600, flag: "wx" },
  );
}
