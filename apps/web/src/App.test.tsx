// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

const capability = {
  contract_version: "dev-1",
  status: "developer_only",
  tags: { environment: "demo", population: "synthetic" },
  participant_admission: false,
  business_operations: "unavailable",
  contract_validation: true,
};
function mockResponse(body: unknown, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status })),
  );
}
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("developer shell", () => {
  it("shows a validated capability and truthful role previews", async () => {
    mockResponse(capability);
    render(<App />);
    expect(await screen.findByText("Development API connected")).toBeVisible();
    expect(
      screen.getByText(
        /Participant admission and business operations are unavailable/,
      ),
    ).toBeVisible();
    fireEvent.change(screen.getByRole("combobox", { name: "Role preview" }), {
      target: { value: "worker" },
    });
    expect(
      screen.getByText("Worker queues and assignments are unavailable."),
    ).toBeVisible();
    expect(screen.getByText(/does not sign in or grant access/)).toBeVisible();
  });
  it("keeps a failed connection visible and supports retry", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    render(<App />);
    expect(await screen.findByText(/API unconnected/)).toBeVisible();
    mockResponse(capability);
    fireEvent.click(screen.getByRole("button", { name: "Check API again" }));
    expect(await screen.findByText("Development API connected")).toBeVisible();
  });
  it("makes a stalled API request retryable after five seconds", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>(() => {})),
    );
    render(<App />);
    expect(screen.getByText("Checking the development API…")).toBeVisible();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(screen.getByText(/API unconnected/)).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Check API again" }),
    ).toBeEnabled();
  });
  it("rejects a capability that claims participant admission", async () => {
    mockResponse({ ...capability, participant_admission: true });
    render(<App />);
    expect(
      await screen.findByText(
        "The API returned an incompatible capability result.",
      ),
    ).toBeVisible();
    expect(
      screen.queryByText("Development API connected"),
    ).not.toBeInTheDocument();
  });
  it("switches EN/FR without discarding the unsent contract input", async () => {
    mockResponse(capability);
    render(<App />);
    await screen.findByText("Development API connected");
    fireEvent.change(screen.getByLabelText("JSON input"), {
      target: { value: '{"expected_revision":"7"}' },
    });
    fireEvent.change(screen.getByLabelText("Language"), {
      target: { value: "fr-CA" },
    });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Interface de développement CARE-Link",
    );
    expect(screen.getByLabelText("Saisie JSON")).toHaveValue(
      '{"expected_revision":"7"}',
    );
    await waitFor(() => expect(document.documentElement.lang).toBe("fr-CA"));
  });
  it("rejects revision overflow, focuses the input, and reports only validation success", async () => {
    mockResponse(capability);
    render(<App />);
    await screen.findByText("Development API connected");
    const input = screen.getByLabelText("JSON input");
    fireEvent.change(input, {
      target: { value: '{"expected_revision":"9223372036854775808"}' },
    });
    fireEvent.click(screen.getByRole("button", { name: "Validate locally" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Input rejected.");
    expect(input).toHaveFocus();
    expect(input).toHaveAttribute("aria-invalid", "true");
    fireEvent.change(input, {
      target: { value: '{"expected_revision":"9223372036854775807"}' },
    });
    fireEvent.click(screen.getByRole("button", { name: "Validate locally" }));
    expect(
      screen.getByText("Valid contract input. No operation was performed."),
    ).toBeVisible();
  });
  it("rejects an unknown nested session key", async () => {
    mockResponse(capability);
    render(<App />);
    await screen.findByText("Development API connected");
    fireEvent.change(screen.getByLabelText("Contract", { exact: true }), {
      target: { value: "SessionCreate" },
    });
    const input = screen.getByLabelText("JSON input");
    fireEvent.change(input, {
      target: {
        value:
          '{"tags":{"environment":"demo","population":"synthetic","authority":true},"participant_kind":"pid","jurisdiction":null,"locale":"en-CA","channel":"web","persona_id":null,"fixture_id":null}',
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Validate locally" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Input rejected.");
  });
});
