import "@testing-library/jest-dom/vitest";
import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { AssistancePanel } from "./AssistancePanel";
import { messages } from "./messages";
import {
  draftContext,
  draftId,
  review,
  sessionId,
  subjectId,
  task,
  taskId,
} from "./fixtures";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
interface Mutation {
  path: string;
  body: Record<string, unknown>;
  key: string | null;
}
function setup({
  available = true,
  state = "review_pending",
  expiry,
  unknown = false,
  signedOut = false,
  processingReads = 0,
  unknownCreate = false,
  protocol = false,
  taskDeadline,
}: {
  available?: boolean;
  state?: string;
  expiry?: string;
  unknown?: boolean;
  signedOut?: boolean;
  processingReads?: number;
  unknownCreate?: boolean;
  protocol?: boolean;
  taskDeadline?: string;
} = {}) {
  const mutations: Mutation[] = [];
  let statusCode = 200;
  let edited: string | undefined,
    revision = "1",
    unknownOnce = unknown,
    unknownCreateOnce = unknownCreate,
    contextReads = 0;
  const fetcher = vi.fn(async (input: string, init?: RequestInit) => {
    await Promise.resolve();
    const path = input;
    const body = init?.body
      ? (JSON.parse(
          typeof init.body === "string" ? init.body : "null",
        ) as Record<string, unknown>)
      : {};
    if (init?.method === "POST")
      mutations.push({
        path,
        body,
        key: new Headers(init.headers).get("Idempotency-Key"),
      });
    const result = (value: unknown, status = 200) =>
      new Response(JSON.stringify(value), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    if (path === "/v1/auth/csrf") return result({ csrf_token: "x".repeat(40) });
    if (path === "/v1/assistance") {
      if (statusCode !== 200) return result({}, statusCode);
      return result({
        available,
        reason: available ? null : "assistance.function_disabled",
        functions: available ? ["worker_summary"] : [],
      });
    }
    if (path === "/v1/tasks") {
      if (unknownCreateOnce) {
        unknownCreateOnce = false;
        throw new Error("synthetic unknown task creation");
      }
      const value = task(processingReads ? "running" : "awaiting_human");
      if (taskDeadline) value.deadline = taskDeadline;
      return result(value);
    }
    if (path === `/v1/tasks/${taskId}/context`) {
      contextReads += 1;
      const value = task(
        contextReads <= processingReads ? "running" : "awaiting_human",
      );
      if (taskDeadline) value.deadline = taskDeadline;
      return result({
        task: value,
        draft_id: contextReads <= processingReads ? null : draftId,
        available,
        reason: null,
      });
    }
    if (path === `/v1/drafts/${draftId}/context`) {
      const context = draftContext(edited, revision, state);
      if (expiry) context.expires_at = expiry;
      if (protocol)
        context.sources.push({
          ref: {
            ...context.sources[0]!.ref,
            id: "50000000-0000-4000-8000-000000000002",
            kind: "protocol",
            verification: "verified",
          },
          text: "Synthetic guidance: verify the receiving service requirements.",
        });
      return result(context);
    }
    if (path === `/v1/tasks/${taskId}/cancel`)
      return result(task("cancelled", "2"));
    if (path === `/v1/drafts/${draftId}/review`) {
      if (unknownOnce) {
        unknownOnce = false;
        throw new Error("synthetic lost reply");
      }
      if (signedOut) return result({}, 401);
      if (body.decision === "edit") {
        edited = String(body.edited_text);
        revision = "2";
      }
      return result(review(String(body.decision)));
    }
    throw new Error("Unexpected fixture route " + path);
  });
  vi.stubGlobal("fetch", fetcher);
  return {
    mutations,
    fetcher,
    setStatusCode: (value: number) => {
      statusCode = value;
    },
    setAvailable: (value: boolean) => {
      available = value;
    },
  };
}
function panel(locale: "en-CA" | "fr-CA" = "en-CA") {
  return render(
    <AssistancePanel
      locale={locale}
      allowAutomatic
      session={{ id: sessionId, revision: "1", subject_id: subjectId }}
    />,
  );
}
async function open(locale: "en-CA" | "fr-CA" = "en-CA") {
  panel(locale);
  const button = await screen.findByRole("button", {
    name: messages[locale].start,
  });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  await screen.findByRole("textbox", { name: messages[locale].edit });
}
for (const locale of ["en-CA", "fr-CA"] as const) {
  it(`${locale} renders current source facts, uncertainty and exact unsent review`, async () => {
    const { mutations } = setup();
    await open(locale);
    const text = messages[locale];
    expect(screen.getByText(text.noRecipient)).toBeVisible();
    expect(screen.getByText(text.effect)).toBeVisible();
    expect(screen.getByText(text.disputed, { exact: false })).toBeVisible();
    expect(
      screen.getByText(
        "Synthetic report: navigation requested; service capacity is unknown.",
      ),
    ).toBeVisible();
    expect(
      screen.getByRole("heading", { name: text.proposed, level: 3 }),
    ).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: text.reject }));
    await screen.findByText(text.rejected);
    expect(mutations.at(-1)?.body).toMatchObject({
      decision: "reject",
      expected_revision: "1",
      exact_digest: "a".repeat(64),
      edited_text: null,
    });
    expect(
      mutations.some((entry) => /dispatch|consent|messages/.test(entry.path)),
    ).toBe(false);
  });
}
it("fails closed when model function is unavailable", async () => {
  const { mutations } = setup({ available: false });
  panel();
  await screen.findByText(messages["en-CA"].unavailable);
  expect(
    screen.getByRole("button", { name: messages["en-CA"].start }),
  ).toBeDisabled();
  expect(mutations).toHaveLength(0);
});
it("edits create a new revision requiring a separate exact review", async () => {
  const { mutations } = setup();
  await open();
  const text = messages["en-CA"];
  fireEvent.change(screen.getByRole("textbox", { name: text.edit }), {
    target: { value: "Human corrected synthetic draft." },
  });
  expect(screen.getByRole("button", { name: text.accept })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: text.save }));
  await screen.findByText(text.edited);
  expect(screen.getByRole("textbox", { name: text.edit })).toHaveValue(
    "Human corrected synthetic draft.",
  );
  expect(mutations.at(-1)?.body.decision).toBe("edit");
  fireEvent.click(screen.getByRole("button", { name: text.accept }));
  await screen.findByText(text.accepted);
  expect(mutations.at(-1)?.body).toMatchObject({
    decision: "accept",
    expected_revision: "2",
    exact_digest: "c".repeat(64),
    edited_text: null,
  });
});
it("expired and stale drafts cannot be accepted", async () => {
  setup({ expiry: "2020-01-01T00:00:00Z", state: "stale" });
  await open();
  const text = messages["en-CA"];
  expect(screen.getByRole("button", { name: text.accept })).toBeDisabled();
  expect(screen.getByRole("button", { name: text.reject })).toBeDisabled();
  expect(screen.getByText(text.expired)).toBeVisible();
  expect(screen.getByText(text.stale)).toBeVisible();
});
it("cancel reports output suppression without asserting compute stopped", async () => {
  const { mutations } = setup();
  await open();
  const text = messages["en-CA"];
  fireEvent.click(screen.getByRole("button", { name: text.cancel }));
  await screen.findByText(text.cancelled);
  expect(screen.queryByRole("textbox", { name: text.edit })).toBeNull();
  expect(mutations.at(-1)?.body).toEqual({ expected_revision: "1" });
});
it("unknown command retries preserve idempotency and exact payload", async () => {
  const { mutations } = setup({ unknown: true });
  await open();
  const text = messages["en-CA"];
  fireEvent.click(screen.getByRole("button", { name: text.accept }));
  await screen.findByText(text.unknown);
  expect(screen.getByRole("button", { name: text.start })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: text.retry }));
  await screen.findByText(text.accepted);
  const entries = mutations.filter((entry) => entry.path.endsWith("/review"));
  expect(entries).toHaveLength(2);
  expect(entries[0]).toEqual(entries[1]);
});
it("reauthentication preserves unsent edits and disables review until refreshed", async () => {
  setup({ signedOut: true });
  await open();
  const text = messages["en-CA"];
  const editor = screen.getByRole("textbox", { name: text.edit });
  fireEvent.change(editor, { target: { value: "Unsent human edit" } });
  fireEvent.click(screen.getByRole("button", { name: text.save }));
  await screen.findByText(text.signedOut);
  expect(editor).toHaveValue("Unsent human edit");
  expect(screen.queryByRole("button", { name: text.save })).toBeNull();
  expect(
    screen.queryByText(
      "Synthetic report: navigation requested; service capacity is unknown.",
    ),
  ).toBeNull();
});
it("changing sessions fences late responses and clears the previous draft", async () => {
  setup();
  const view = panel();
  const button = await screen.findByRole("button", {
    name: messages["en-CA"].start,
  });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  await screen.findByRole("textbox", { name: messages["en-CA"].edit });
  view.rerender(
    <AssistancePanel
      locale="en-CA"
      session={{
        id: "10000000-0000-4000-8000-000000000002",
        revision: "1",
        subject_id: subjectId,
      }}
    />,
  );
  await waitFor(() =>
    expect(
      screen.queryByRole("textbox", { name: messages["en-CA"].edit }),
    ).toBeNull(),
  );
});

it("disabling a function blocks a previously displayed draft", async () => {
  const fixture = setup();
  await open();
  fixture.setAvailable(false);
  fireEvent.click(
    screen.getByRole("button", { name: messages["en-CA"].check }),
  );
  await screen.findByText(messages["en-CA"].unavailable);
  expect(
    screen.queryByRole("button", { name: messages["en-CA"].accept }),
  ).toBeNull();
  expect(
    fixture.mutations.filter((entry) => entry.path.endsWith("/review")),
  ).toHaveLength(0);
});

for (const statusCode of [401, 403, 503]) {
  it(`status ${statusCode} hides an already visible private draft and retains only unsent edits`, async () => {
    const fixture = setup();
    await open();
    const text = messages["en-CA"];
    const editor = screen.getByRole("textbox", { name: text.edit });
    fireEvent.change(editor, { target: { value: "Unsent human correction" } });
    fixture.setStatusCode(statusCode);
    fireEvent.click(screen.getByRole("button", { name: text.check }));
    await screen.findByText(statusCode === 401 ? text.signedOut : text.failed);
    expect(screen.getByRole("textbox", { name: text.edit })).toHaveValue(
      "Unsent human correction",
    );
    expect(
      screen.queryByText(
        "Synthetic report: navigation requested; service capacity is unknown.",
      ),
    ).toBeNull();
    expect(
      screen.queryByText(
        "Synthetic original: navigation requested; capacity unknown.",
      ),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: text.accept })).toBeNull();
    fixture.setStatusCode(200);
    fireEvent.click(screen.getByRole("button", { name: text.check }));
    // Status success alone cannot revive old private facts; a fresh authorized context read follows.
    await screen.findByText(
      "Synthetic report: navigation requested; service capacity is unknown.",
    );
    expect(screen.getByRole("textbox", { name: text.edit })).toHaveValue(
      "Unsent human correction",
    );
  });
}

for (const locale of ["en-CA", "fr-CA"] as const) {
  it(`${locale} automatic preparation requires explicit opt-in and creates once per revision`, async () => {
    const { mutations } = setup();
    const view = panel(locale);
    const text = messages[locale];
    await waitFor(() =>
      expect(screen.getByRole("button", { name: text.start })).toBeEnabled(),
    );
    const automatic = screen.getByRole("checkbox", { name: text.automatic });
    expect(automatic).not.toBeChecked();
    expect(mutations).toHaveLength(0);
    fireEvent.click(automatic);
    await screen.findByRole("textbox", { name: text.edit });
    expect(mutations.filter(({ path }) => path === "/v1/tasks")).toHaveLength(
      1,
    );
    view.rerender(
      <AssistancePanel
        locale={locale}
        session={{ id: sessionId, revision: "1", subject_id: subjectId }}
      />,
    );
    fireEvent.click(automatic);
    fireEvent.click(automatic);
    expect(mutations.filter(({ path }) => path === "/v1/tasks")).toHaveLength(
      1,
    );
    expect(
      mutations.some(({ path }) => /dispatch|consent|messages/.test(path)),
    ).toBe(false);
  });
}

it("polls only reads of the authorized task until a draft is ready", async () => {
  const { mutations, fetcher } = setup({ processingReads: 1 });
  panel();
  const text = messages["en-CA"];
  await waitFor(() =>
    expect(screen.getByRole("button", { name: text.start })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: text.start }));
  await screen.findByText(text.working);
  await screen.findByRole("textbox", { name: text.edit }, { timeout: 4000 });
  expect(mutations.filter(({ path }) => path === "/v1/tasks")).toHaveLength(1);
  expect(
    fetcher.mock.calls.filter(
      ([path]) => path === `/v1/tasks/${taskId}/context`,
    ),
  ).toHaveLength(2);
});

it("automatic preparation preserves an unknown creation key across retries", async () => {
  const { mutations } = setup({ unknownCreate: true });
  panel();
  const text = messages["en-CA"];
  await waitFor(() =>
    expect(screen.getByRole("button", { name: text.start })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("checkbox", { name: text.automatic }));
  await screen.findByText(text.unknown);
  fireEvent.click(screen.getByRole("checkbox", { name: text.automatic }));
  fireEvent.click(screen.getByRole("checkbox", { name: text.automatic }));
  expect(mutations).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: text.retry }));
  await screen.findByRole("textbox", { name: text.edit });
  expect(mutations).toHaveLength(2);
  expect(mutations[0]).toEqual(mutations[1]);
});

it("separates general guidance from patient reports without inventing missing facts", async () => {
  setup({ protocol: true });
  await open();
  const text = messages["en-CA"];
  expect(
    screen.getByRole("heading", { name: text.clinicalSources }),
  ).toBeVisible();
  expect(
    screen.getByText(
      "Synthetic guidance: verify the receiving service requirements.",
    ),
  ).toBeVisible();
  expect(screen.getByText(text.clinicalSourceHint)).toBeVisible();
  expect(screen.getByText(text.missingnessHint)).toBeVisible();
});

it("standalone assistance has no automatic preparation choice", async () => {
  const { mutations } = setup();
  render(
    <AssistancePanel
      locale="en-CA"
      session={{ id: sessionId, revision: "1", subject_id: subjectId }}
    />,
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: messages["en-CA"].start }),
    ).toBeEnabled(),
  );
  expect(
    screen.queryByRole("checkbox", { name: messages["en-CA"].automatic }),
  ).toBeNull();
  expect(mutations).toHaveLength(0);
});

it("an unavailable function stays manual after automatic preparation is selected", async () => {
  const { mutations } = setup({ available: false });
  panel();
  const text = messages["en-CA"];
  await screen.findByText(text.unavailable);
  fireEvent.click(screen.getByRole("checkbox", { name: text.automatic }));
  expect(screen.getByRole("button", { name: text.start })).toBeDisabled();
  expect(mutations).toHaveLength(0);
});

it("stops automatic status polling at the server task deadline without claiming compute stopped", async () => {
  const { mutations, fetcher } = setup({
    processingReads: 10,
    taskDeadline: "2020-01-01T00:00:00Z",
  });
  panel();
  const text = messages["en-CA"];
  await waitFor(() =>
    expect(screen.getByRole("button", { name: text.start })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("checkbox", { name: text.automatic }));
  await screen.findByText(text.timedOut);
  expect(
    fetcher.mock.calls.filter(
      ([path]) => path === `/v1/tasks/${taskId}/context`,
    ),
  ).toHaveLength(1);
  expect(mutations.filter(({ path }) => path === "/v1/tasks")).toHaveLength(1);
});
