import "@testing-library/jest-dom/vitest";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { KnowledgePanel } from "./KnowledgePanel";
import { messages } from "./messages";
import { source } from "./fixtures";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function setup() {
  let status = 200;
  const bodies: unknown[] = [];
  const fetcher = vi.fn(async (path: string, init?: RequestInit) => {
    await Promise.resolve();
    const response = (body: unknown, code = 200) =>
      new Response(JSON.stringify(body), {
        status: code,
        headers: { "Content-Type": "application/json" },
      });
    if (path === "/v1/auth/csrf")
      return response({ csrf_token: "x".repeat(40) });
    if (path !== "/v1/assistance/knowledge")
      throw new Error("Unexpected route");
    bodies.push(
      JSON.parse(typeof init?.body === "string" ? init.body : "null"),
    );
    if (status !== 200) return response({}, status);
    return response({
      catalog_digest: "d".repeat(64),
      entries: [
        {
          source: { ...source, kind: "protocol", verification: "verified" },
          title: "Synthetic handoff guidance",
          text: "Check the receiving service requirements before preparing a package.",
          source_url:
            "https://www.ontariohealth.ca/clinical/quality-standards/major-depression",
          source_title: "Ontario Health background standard",
          locale: "en-CA",
        },
      ],
      notice: "synthetic_demo_information",
    });
  });
  vi.stubGlobal("fetch", fetcher);
  return {
    bodies,
    fetcher,
    setStatus: (value: number) => {
      status = value;
    },
  };
}
for (const locale of ["en-CA", "fr-CA"] as const) {
  it(`${locale} retrieves only explicit queries and renders attributed demo guidance`, async () => {
    const { bodies } = setup();
    render(<KnowledgePanel locale={locale} />);
    const text = messages[locale];
    expect(bodies).toHaveLength(0);
    fireEvent.change(
      screen.getByRole("textbox", { name: text.knowledgeQuery }),
      { target: { value: "handoff" } },
    );
    fireEvent.click(screen.getByRole("button", { name: text.knowledgeSearch }));
    await screen.findByText("Synthetic handoff guidance");
    expect(bodies).toEqual([{ query: "handoff", locale }]);
    expect(screen.getByText(text.knowledgeScope)).toBeVisible();
    expect(
      screen.getByRole("link", { name: "Ontario Health background standard" }),
    ).toHaveAttribute("rel", "noopener noreferrer");
  });
}
for (const code of [401, 403, 503]) {
  it(`hides guidance after status ${code} while preserving the unsent query`, async () => {
    const fixture = setup();
    render(<KnowledgePanel locale="en-CA" />);
    const text = messages["en-CA"];
    const query = screen.getByRole("textbox", { name: text.knowledgeQuery });
    fireEvent.change(query, { target: { value: "handoff" } });
    fireEvent.click(screen.getByRole("button", { name: text.knowledgeSearch }));
    await screen.findByText("Synthetic handoff guidance");
    fixture.setStatus(code);
    fireEvent.click(screen.getByRole("button", { name: text.knowledgeSearch }));
    await screen.findByText(text.knowledgeFailed);
    expect(screen.queryByText("Synthetic handoff guidance")).toBeNull();
    expect(query).toHaveValue("handoff");
    expect(fixture.bodies).toHaveLength(2);
  });
}
