import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { RecoveryApp } from "./RecoveryApp";
import { targetEvidence } from "./api";
import { messages } from "./messages";
import { webcrypto } from "node:crypto";
import {
  binding,
  exactDigest,
  ids,
  RecoveryFixture,
} from "../../../../../tests/e2e/recovery/fixtures";
const text = messages["en-CA"];
function fixture(role = "operator") {
  vi.stubGlobal("crypto", webcrypto);
  const f = new RecoveryFixture();
  f.role = role;
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      const value = f.reply(
        url,
        init?.method ?? "GET",
        typeof init?.body === "string"
          ? (JSON.parse(init.body) as unknown)
          : null,
        new Headers(init?.headers).get("Idempotency-Key"),
      );
      return Promise.resolve(
        new Response(JSON.stringify(value.body), {
          status: value.status,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }),
  );
  return f;
}
async function open(role = "operator") {
  const f = fixture(role);
  render(<RecoveryApp />);
  fireEvent.click(screen.getByRole("button", { name: text.check }));
  await screen.findByText(text.ready);
  return f;
}
async function loadProposal() {
  fireEvent.change(screen.getByLabelText(text.proposalId), {
    target: { value: ids.proposal },
  });
  fireEvent.click(screen.getByRole("button", { name: text.loadProposal }));
  await screen.findByText(binding.artifact_digest);
}
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
describe("current-authority recovery", () => {
  it("proposes only exact server evidence and clears target projection after the command", async () => {
    const f = await open();
    fireEvent.change(screen.getByLabelText(text.targetId), {
      target: { value: ids.target },
    });
    fireEvent.click(screen.getByRole("button", { name: text.loadTarget }));
    await screen.findByText(binding.artifact_digest);
    fireEvent.click(screen.getByRole("button", { name: text.propose }));
    await waitFor(() => expect(f.commands).toHaveLength(1));
    expect(f.commands[0]?.body).toEqual({
      target_id: ids.target,
      expected_revision: "5",
      backup_digest: binding.backup_digest,
      head_digest: binding.head_digest,
      restriction_barrier: "9",
      validation_digest: binding.validation_digest,
      serving_generation: "2",
      binding,
    });
    await screen.findByText(text.committed, { exact: false });
    expect(screen.queryByText(binding.artifact_digest)).not.toBeInTheDocument();
  });
  it("governance reviews sealed evidence and submits exact ceremony-bound approval", async () => {
    const f = await open("governance");
    expect(
      screen.queryByRole("button", { name: text.capture }),
    ).not.toBeInTheDocument();
    await loadProposal();
    fireEvent.change(screen.getByLabelText(text.ceremony), {
      target: { value: ids.ceremony },
    });
    fireEvent.click(screen.getByRole("button", { name: text.approve }));
    await waitFor(() => expect(f.commands).toHaveLength(1));
    expect(f.commands[0]?.body).toMatchObject({
      proposal_id: ids.proposal,
      ceremony_id: ids.ceremony,
      exact_binding_digest: exactDigest,
    });
    const submitted = f.commands[0]?.body as { expires_at: string };
    expect(Date.parse(submitted.expires_at) - Date.now()).toBeGreaterThan(
      290000,
    );
    expect(Date.parse(submitted.expires_at) - Date.now()).toBeLessThanOrEqual(
      300000,
    );
  });
  it("executes approved exact binding using prior generation and never labels receipt as serving", async () => {
    const f = await open();
    f.proposalState = "approved";
    await loadProposal();
    fireEvent.click(screen.getByRole("button", { name: text.execute }));
    await waitFor(() => expect(f.commands).toHaveLength(1));
    expect(f.commands[0]?.body).toEqual({
      proposal_id: ids.proposal,
      approval_id: ids.approval,
      exact_binding_digest: exactDigest,
      expected_serving_generation: "1",
    });
    await screen.findByText(text.committed, { exact: false });
    expect(
      screen.queryByText(text.serving, { exact: true }),
    ).not.toBeInTheDocument();
  });
  it("expired approval disables execution", async () => {
    const f = await open();
    f.proposalState = "approved";
    f.expired = true;
    await loadProposal();
    expect(screen.getByRole("button", { name: text.execute })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent(text.expired);
    expect(f.commands).toHaveLength(0);
  });
  it("unknown execution reconciles exact body and idempotency identity", async () => {
    const f = await open();
    f.proposalState = "approved";
    f.lost = true;
    await loadProposal();
    fireEvent.click(screen.getByRole("button", { name: text.execute }));
    await screen.findByRole("button", { name: text.retry });
    expect(screen.queryByText(binding.artifact_digest)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: text.retry }));
    await waitFor(() => expect(f.commands).toHaveLength(2));
    expect(f.commands[1]).toEqual(f.commands[0]);
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: text.retry }),
      ).not.toBeInTheDocument(),
    );
  });
  it("a pending command acknowledgement retains its exact reconciliation identity", async () => {
    const f = await open();
    f.proposalState = "approved";
    f.ackState = "pending";
    await loadProposal();
    fireEvent.click(screen.getByRole("button", { name: text.execute }));
    await screen.findByRole("button", { name: text.retry });
    expect(screen.queryByText(binding.artifact_digest)).not.toBeInTheDocument();
    f.ackState = "committed";
    fireEvent.click(screen.getByRole("button", { name: text.retry }));
    await waitFor(() => expect(f.commands).toHaveLength(2));
    expect(f.commands[1]).toEqual(f.commands[0]);
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: text.retry }),
      ).not.toBeInTheDocument(),
    );
  });
  it("rejects evidence that does not hash to the exact approval binding", async () => {
    const f = await open("security");
    f.mismatch = true;
    fireEvent.change(screen.getByLabelText(text.proposalId), {
      target: { value: ids.proposal },
    });
    fireEvent.click(screen.getByRole("button", { name: text.loadProposal }));
    await screen.findByText(text.invalid);
    expect(screen.queryByText(binding.artifact_digest)).not.toBeInTheDocument();
    expect(f.commands).toHaveLength(0);
  });
  it("rejects unrecognized evidence fields before disclosure", async () => {
    const f = await open("security");
    f.malformed = true;
    fireEvent.change(screen.getByLabelText(text.proposalId), {
      target: { value: ids.proposal },
    });
    fireEvent.click(screen.getByRole("button", { name: text.loadProposal }));
    await screen.findByText(text.invalid);
    expect(screen.queryByText(binding.artifact_digest)).not.toBeInTheDocument();
    expect(f.commands).toHaveLength(0);
  });
  it("removes sealed evidence when fresh authority signs out", async () => {
    const f = await open("security");
    await loadProposal();
    f.signedOut = true;
    fireEvent.click(screen.getByRole("button", { name: text.check }));
    await screen.findByText(text.signed_out);
    expect(screen.queryByText(binding.artifact_digest)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: text.approve }),
    ).not.toBeInTheDocument();
  });
  it("prevents a stale role from issuing an approval", async () => {
    const f = await open("security");
    await loadProposal();
    f.role = "operator";
    fireEvent.change(screen.getByLabelText(text.ceremony), {
      target: { value: ids.ceremony },
    });
    fireEvent.click(screen.getByRole("button", { name: text.approve }));
    await screen.findByText(text.rejected);
    expect(f.commands).toHaveLength(0);
    expect(screen.queryByText(binding.artifact_digest)).not.toBeInTheDocument();
  });
});

describe("serving target projection", () => {
  it("loads serving status without asking for a new promotion binding", async () => {
    fixture();
    const fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          id: ids.target,
          revision: "10",
          backup_id: ids.backup,
          state: "serving",
          head: {
            journal_id: binding.journal_id,
            generation: "1",
            tip: "20",
            tip_digest: binding.head_digest,
            restriction_barrier: "9",
            signature: "x",
            observed_at: "2026-11-21T12:00:00Z",
          },
          validation_digest: binding.validation_digest,
          serving_generation: "2",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetch);
    const result = await targetEvidence(
      ids.target,
      new AbortController().signal,
    );
    expect(result.target.state).toBe("serving");
    expect(result.binding).toBeNull();
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
