// @vitest-environment jsdom
// @vitest-environment-options {"url":"https://governance.qualification.localhost/governance"}
import "@testing-library/jest-dom/vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { GovernanceApp } from "./GovernanceApp";
import { messages } from "./messages";
import { utc } from "./api";
const ids = {
  account: "10000000-0000-4000-8000-000000000001",
  activation: "20000000-0000-4000-8000-000000000001",
  grant: "30000000-0000-4000-8000-000000000001",
  export: "40000000-0000-4000-8000-000000000001",
  incident: "50000000-0000-4000-8000-000000000001",
  event: "60000000-0000-4000-8000-000000000001",
};
const at = "2026-11-21T12:00:00Z",
  future = "2099-11-21T12:00:00Z",
  digest = "a".repeat(64);
type Role = "operator" | "security" | "governance" | "auditor" | "pid";
function fixture(
  options: {
    role?: Role;
    lostCommit?: boolean;
    malformedMetrics?: boolean;
    suppressed?: boolean;
    missing?: string[];
    exportPages?: boolean;
    expiresAt?: string;
    delayedExport?: boolean;
  } = {},
) {
  const commands: {
    path: string;
    body: Record<string, unknown>;
    key: string | undefined;
  }[] = [];
  let role = options.role ?? "operator",
    denied = false,
    lostCommit = options.lostCommit ?? false;
  let state = "ready",
    expiresAt = options.expiresAt ?? future;
  const releaseExport: (() => void)[] = [];
  const page = {
    items: [
      {
        id: ids.event,
        sequence: "1",
        operation_id: ids.event,
        action: "artifact_register",
        decision: "PERMIT",
        input_digest: digest,
        output_digest: digest,
        previous_hash: "0".repeat(64),
        hash: digest,
        created_at: at,
      },
    ],
    next_cursor: null,
  };
  const fetcher = vi.fn((raw: string | URL | Request, init?: RequestInit) => {
    const path =
      typeof raw === "string" ? raw : raw instanceof URL ? raw.href : raw.url;
    const json = (value: unknown, status = 200) =>
      new Response(JSON.stringify(value), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    if (path === "/v1/auth/session")
      return denied
        ? json({}, 401)
        : json({
            account_id: ids.account,
            role,
            assurance: "AL2",
            revision: "1",
            expires_at: expiresAt,
            auth_time: at,
          });
    if (path === "/v1/auth/csrf") return json({ csrf_token: "a".repeat(48) });
    if (init?.method === "POST")
      commands.push({
        path,
        body: JSON.parse(
          typeof init.body === "string" ? init.body : "{}",
        ) as Record<string, unknown>,
        key: (init.headers as Record<string, string>)["Idempotency-Key"],
      });
    if (path === `/v1/artifacts/${digest}/review-context`)
      return json({
        artifact: {
          digest,
          kind: "policy",
          version: "v1",
          state: "review_pending",
        },
        source_revision: "abcdef123456",
        change_class: "C2",
        governed_domains: ["policy"],
        changed_paths: ["config/demo/imp08/policy.json"],
        required_authorities: ["technical", "security"],
        missing_authorities: ["technical", "security"],
        evidence_digests: ["b".repeat(64)],
        previous_digest: "c".repeat(64),
        payload_digest: "d".repeat(64),
      });
    if (path === "/v1/operations/health")
      return json({
        capability: "manual",
        ready: true,
        reasons: [],
        epoch: "7",
        serving_generation: "3",
      });
    if (path === `/v1/activations/${ids.activation}/commit`) {
      state = "active";
      if (lostCommit) {
        lostCommit = false;
        throw new Error("lost after commit");
      }
    }
    if (path.startsWith("/v1/activations/"))
      return json({
        id: ids.activation,
        epoch: "8",
        bundle_digest: digest,
        state,
        missing_instances: options.missing ?? [],
        revision: "2",
      });
    if (path === "/v1/activations")
      return json({
        id: ids.activation,
        epoch: "8",
        bundle_digest: digest,
        state: "staged",
        missing_instances: ["data-1"],
        revision: "1",
      });
    if (path === "/v1/metrics/query") {
      const count = { numerator: 20, denominator: 35, unknown: 4 };
      return json(
        options.malformedMetrics
          ? { definition_version: "v1", police_avoidance: count }
          : options.suppressed
            ? {
                definition_version: "v1",
                cohort_size: null,
                suppressed: true,
                safety: null,
                access: null,
                equity: null,
                police_avoidance: null,
                exposure_aggregate: null,
              }
            : {
                definition_version: "v1",
                cohort_size: 35,
                suppressed: false,
                safety: count,
                access: count,
                equity: count,
                police_avoidance: count,
                exposure_aggregate: null,
              },
      );
    }
    if (
      options.delayedExport &&
      path.startsWith(`/v1/audit/exports/${ids.export}?`)
    )
      return new Promise<Response>((resolve) =>
        releaseExport.push(() =>
          resolve(
            json({
              ...page,
              items: [{ ...page.items[0], action: "late_export" }],
            }),
          ),
        ),
      );
    if (
      options.exportPages &&
      path.startsWith(`/v1/audit/exports/${ids.export}?`)
    )
      return json(
        path.includes("cursor=export-page-2")
          ? {
              items: [
                { ...page.items[0], sequence: "2", action: "artifact_review" },
              ],
              next_cursor: null,
            }
          : { ...page, next_cursor: "export-page-2" },
      );
    if (
      path === "/v1/audit/search" ||
      path.startsWith(`/v1/audit/exports/${ids.export}?`)
    )
      return json(page);
    if (path === "/v1/audit/exports")
      return json({
        operation_id: ids.event,
        state: "committed",
        resource_id: ids.export,
        revision: "1",
        audit_ref: ids.event,
      });
    if (path === "/v1/artifacts")
      return json({
        digest,
        kind: "policy",
        version: "v1",
        state: "review_pending",
      });
    if (path.startsWith("/v1/incidents"))
      return json({
        id: ids.incident,
        revision: "1",
        state: "contained",
        kind: "security",
        review_due_at: future,
      });
    if (
      path === "/v1/access/grants" ||
      path === "/v1/artifacts/reviews" ||
      path === "/v1/exceptions"
    )
      return json({
        operation_id: ids.event,
        state: "committed",
        resource_id: ids.grant,
        revision: "1",
        audit_ref: ids.event,
      });
    return json({}, 404);
  });
  vi.stubGlobal("fetch", fetcher);
  return {
    commands,
    fetcher,
    releaseExport: () => releaseExport.shift()?.(),
    renew: () => {
      expiresAt = future;
      denied = false;
    },
    deny: () => {
      denied = true;
    },
    allow: () => {
      denied = false;
    },
    switchRole: (value: Role) => {
      role = value;
    },
  };
}
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
async function open(locale: "en-CA" | "fr-CA" = "en-CA") {
  const text = messages[locale];
  render(<GovernanceApp />);
  fireEvent.change(screen.getByLabelText("Language"), {
    target: { value: locale },
  });
  fireEvent.click(screen.getByRole("button", { name: text.check }));
  await screen.findByText(text.ready);
  return text;
}
function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label, { exact: true }), {
    target: { value },
  });
}
async function loadActivation(text = messages["en-CA"]) {
  fill(text.knownActivation, ids.activation);
  fireEvent.click(screen.getByRole("button", { name: text.loadActivation }));
  await screen.findByText(digest);
}
function metricsForm(text = messages["en-CA"]) {
  fill(text.definition, "v1");
  fill(text.periodStart, "2026-11-01T00:00");
  fill(text.periodEnd, "2026-11-02T00:00");
}
it.each(["en-CA", "fr-CA"] as const)(
  "opens only the server role workspace in %s",
  async (locale) => {
    fixture({ role: "operator" });
    const text = await open(locale);
    expect(screen.getByRole("heading", { name: text.artifact })).toBeVisible();
    expect(
      screen.queryByRole("heading", { name: text.audit }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: text.review }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("combobox", { name: text.role }),
    ).not.toBeInTheDocument();
    expect(document.documentElement.lang).toBe(locale);
  },
);
it("keeps a lost activation commit unresolved and retries exact bytes and key", async () => {
  const network = fixture({ lostCommit: true });
  const text = await open();
  await loadActivation();
  fireEvent.click(screen.getByRole("button", { name: text.commit }));
  await screen.findByRole("button", { name: text.retry });
  expect(screen.queryByText("Active")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: text.retry }));
  await screen.findByText("Active");
  const commits = network.commands.filter((v) => v.path.endsWith("/commit"));
  expect(commits).toHaveLength(2);
  expect(commits[1]).toEqual(commits[0]);
  expect(commits[0]?.body).toEqual({ expected_revision: "2" });
});
it("does not enable commit while an instance lacks a current-boot acknowledgement", async () => {
  const network = fixture({ missing: ["data-1"] });
  const text = await open();
  await loadActivation();
  expect(screen.getByText("data-1")).toBeVisible();
  expect(screen.getByRole("button", { name: text.commit })).toBeDisabled();
  expect(network.commands).toHaveLength(0);
});
it("binds activation creation to the server epoch and invalidates it after proposal", async () => {
  const network = fixture();
  const text = await open();
  const region = within(screen.getByRole("region", { name: text.activation }));
  expect(region.getByRole("button", { name: text.propose })).toBeDisabled();
  fireEvent.click(region.getByRole("button", { name: text.health }));
  await screen.findByText("7");
  fireEvent.change(region.getByLabelText(text.digest), {
    target: { value: digest },
  });
  fill(text.effective, "2026-11-21T13:00");
  fill(text.instances, "data-1,core-1");
  fireEvent.submit(region.getByLabelText(text.effective).closest("form")!);
  await screen.findByText("Staged");
  expect(network.commands[0]?.body).toEqual({
    artifact_digest: digest,
    expected_epoch: "7",
    effective_at: "2026-11-21T13:00:00.000Z",
    required_instances: ["data-1", "core-1"],
  });
  expect(region.getByRole("button", { name: text.propose })).toBeDisabled();
});
it.each(["en-CA", "fr-CA"] as const)(
  "always presents all coupled aggregate measures in %s",
  async (locale) => {
    fixture({ role: "auditor" });
    const text = await open(locale);
    metricsForm(text);
    fireEvent.click(screen.getByRole("button", { name: text.queryMetrics }));
    await screen.findByRole("heading", { name: text.police_avoidance });
    for (const name of [
      "safety",
      "access",
      "equity",
      "police_avoidance",
      "exposure_aggregate",
    ] as const)
      expect(screen.getByRole("heading", { name: text[name] })).toBeVisible();
    expect(screen.getByText(text.notMeasured)).toBeVisible();
  },
);
it("withholds every comparable sensitive value for a suppressed cohort", async () => {
  fixture({ role: "auditor", suppressed: true });
  const text = await open();
  metricsForm();
  fireEvent.click(screen.getByRole("button", { name: text.queryMetrics }));
  await screen.findByText(text.suppressed);
  expect(
    screen.queryByRole("heading", { name: text.police_avoidance }),
  ).not.toBeInTheDocument();
  expect(screen.queryByText(/Cohort size:/)).not.toBeInTheDocument();
});
it("rejects an isolated police-avoidance response before rendering values", async () => {
  fixture({ role: "auditor", malformedMetrics: true });
  const text = await open();
  metricsForm();
  fireEvent.click(screen.getByRole("button", { name: text.queryMetrics }));
  await screen.findByText(text.invalid);
  expect(
    screen.queryByRole("heading", { name: text.police_avoidance }),
  ).not.toBeInTheDocument();
});
it("clears audit evidence on expired authority and retains unsent form values in memory", async () => {
  const network = fixture({ role: "auditor" });
  const text = await open();
  fill(text.grantId, ids.grant);
  fill(text.from, "2026-11-21T00:00");
  fill(text.to, "2026-11-22T00:00");
  fireEvent.click(screen.getByRole("button", { name: text.queryAudit }));
  await screen.findByText("artifact_register");
  network.deny();
  fireEvent.click(screen.getByRole("button", { name: text.check }));
  await screen.findByText(text.signed_out);
  expect(screen.queryByText("artifact_register")).not.toBeInTheDocument();
  network.allow();
  fireEvent.click(screen.getByRole("button", { name: text.check }));
  await screen.findByText(text.ready);
  expect(screen.getByLabelText(text.grantId)).toHaveValue(ids.grant);
  expect(screen.queryByText("artifact_register")).not.toBeInTheDocument();
});
it("discards old scoped work when the authenticated role changes", async () => {
  const network = fixture({ role: "auditor" });
  const text = await open();
  metricsForm();
  network.switchRole("operator");
  fireEvent.click(screen.getByRole("button", { name: text.queryMetrics }));
  await screen.findByText(text.rejected);
  expect(network.commands).toHaveLength(0);
  expect(
    screen.queryByRole("heading", { name: text.metrics }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: text.artifact })).toBeVisible();
});
it("uses the exact grant and query window for export preparation and authorized read", async () => {
  const network = fixture({ role: "auditor" });
  const text = await open();
  fill(text.grantId, ids.grant);
  fill(text.from, "2026-11-21T00:00");
  fill(text.to, "2026-11-22T00:00");
  fireEvent.click(screen.getByRole("button", { name: text.export }));
  await screen.findByText(ids.export);
  fireEvent.click(screen.getByRole("button", { name: text.readExport }));
  await screen.findByText("artifact_register");
  expect(network.commands[0]?.body).toEqual({
    purpose: "audit",
    grant_id: ids.grant,
    from: "2026-11-21T00:00:00.000Z",
    to: "2026-11-22T00:00:00.000Z",
    limit: 50,
  });
  expect(
    network.fetcher.mock.calls.some(([path]) =>
      (typeof path === "string"
        ? path
        : path instanceof URL
          ? path.href
          : path.url
      ).includes(
        `/v1/audit/exports/${ids.export}?purpose=audit&grant_id=${ids.grant}&from=`,
      ),
    ),
  ).toBe(true);
});
it("uses UTC field values independently of the workstation timezone", () => {
  expect(utc("2026-11-21T13:00")).toBe("2026-11-21T13:00:00.000Z");
});

it("requires exact current signed artifact context before recording a review", async () => {
  const network = fixture({ role: "governance" });
  const text = await open();
  const region = within(screen.getByRole("region", { name: text.review }));
  expect(
    region.getByRole("button", { name: text.submitReview }),
  ).toBeDisabled();
  fireEvent.change(region.getByLabelText(text.digest), {
    target: { value: digest },
  });
  fireEvent.click(region.getByRole("button", { name: text.loadContext }));
  await region.findByText("config/demo/imp08/policy.json");
  expect(region.getByText("abcdef123456")).toBeVisible();
  fireEvent.change(region.getByLabelText(text.evidence), {
    target: { value: "b".repeat(64) },
  });
  fireEvent.change(region.getByLabelText(text.reviewExpiry), {
    target: { value: "2099-11-21T12:00" },
  });
  fireEvent.click(region.getByRole("button", { name: text.submitReview }));
  await region.findByText(ids.grant);
  expect(network.commands[0]?.body).toMatchObject({
    artifact_digest: digest,
    change_class: "C2",
    evidence_digest: "b".repeat(64),
  });
  fireEvent.change(region.getByLabelText(text.digest), {
    target: { value: "e".repeat(64) },
  });
  expect(
    region.getByRole("button", { name: text.submitReview }),
  ).toBeDisabled();
  expect(
    region.queryByText("config/demo/imp08/policy.json"),
  ).not.toBeInTheDocument();
});

it("reads subsequent export pages from the same export under the exact current grant", async () => {
  const network = fixture({ role: "auditor", exportPages: true });
  const text = await open();
  fill(text.grantId, ids.grant);
  fill(text.from, "2026-11-21T00:00");
  fill(text.to, "2026-11-22T00:00");
  fill(text.exportId, ids.export);
  fireEvent.click(screen.getByRole("button", { name: text.readExport }));
  await screen.findByText("artifact_register");
  fireEvent.click(screen.getByRole("button", { name: text.next }));
  await screen.findByText("artifact_review");
  expect(
    screen.queryByRole("button", { name: text.next }),
  ).not.toBeInTheDocument();
  const reads = network.fetcher.mock.calls
    .map(([path]) =>
      typeof path === "string"
        ? path
        : path instanceof URL
          ? path.href
          : path.url,
    )
    .filter((path) => path.startsWith(`/v1/audit/exports/${ids.export}?`));
  expect(reads).toHaveLength(2);
  expect(reads[1]).toContain("cursor=export-page-2");
  expect(reads[1]).toContain(`grant_id=${ids.grant}`);
  expect(network.commands).toHaveLength(0);
});

it("keeps expired evidence absent when a delayed export response arrives after revocation", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const network = fixture({
    role: "auditor",
    expiresAt: new Date(Date.now() + 5000).toISOString(),
    delayedExport: true,
  });
  const text = await open();
  fill(text.grantId, ids.grant);
  fill(text.from, "2026-11-21T00:00");
  fill(text.to, "2026-11-22T00:00");
  fill(text.exportId, ids.export);
  fireEvent.click(screen.getByRole("button", { name: text.readExport }));
  await act(async () => {
    await Promise.resolve();
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5001);
  });
  expect(screen.getByText(text.signed_out)).toBeInTheDocument();
  await act(async () => {
    network.releaseExport();
    await Promise.resolve();
  });
  expect(screen.getByText(text.signed_out)).toBeInTheDocument();
  expect(screen.queryByText("late_export")).not.toBeInTheDocument();
  network.renew();
  fireEvent.click(screen.getByRole("button", { name: text.check }));
  await screen.findByText(text.ready);
  expect(screen.queryByText("late_export")).not.toBeInTheDocument();
  expect(screen.getByLabelText(text.grantId)).toHaveValue(ids.grant);
});
