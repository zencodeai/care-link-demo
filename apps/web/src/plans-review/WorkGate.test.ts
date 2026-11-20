import { expect, it } from "vitest";
import { WorkGate } from "./WorkGate";

it("holds later work until its owner finishes and releases each lease once", async () => {
  const gate = new WorkGate();
  const signal = new AbortController().signal;
  const first = await gate.acquire(signal, () => "view-one");
  const order: string[] = [];
  const secondRequest = gate
    .acquire(signal, () => "view-two")
    .then((lease) => {
      order.push("second");
      return lease;
    });
  const thirdRequest = gate
    .acquire(signal, () => "view-three")
    .then((lease) => {
      order.push("third");
      return lease;
    });
  await Promise.resolve();
  expect(order).toEqual([]);
  expect(gate.owns(first)).toBe(true);
  first.release();
  const second = await secondRequest;
  expect(order).toEqual(["second"]);
  expect(gate.owns(first)).toBe(false);
  expect(gate.owns(second)).toBe(true);
  first.release();
  await Promise.resolve();
  expect(order).toEqual(["second"]);
  second.release();
  const third = await thirdRequest;
  expect(order).toEqual(["second", "third"]);
  expect(third.view_id).toBe("view-three");
  third.release();
  expect(gate.owns(third)).toBe(false);
});

it("cancels queued work without running its view lookup or blocking later work", async () => {
  const gate = new WorkGate();
  const signal = new AbortController().signal;
  const owner = await gate.acquire(signal, () => "active");
  const controller = new AbortController();
  let lookedUp = false;
  const cancelled = gate.acquire(controller.signal, () => {
    lookedUp = true;
    return "cancelled";
  });
  const rejected = expect(cancelled).rejects.toThrow();
  const nextRequest = gate.acquire(signal, () => "next");
  controller.abort();
  await rejected;
  expect(lookedUp).toBe(false);
  expect(gate.owns(owner)).toBe(true);
  owner.release();
  const next = await nextRequest;
  expect(next.view_id).toBe("next");
  next.release();
});

it("checks the current view when work starts and refuses stale ownership", async () => {
  const gate = new WorkGate();
  const signal = new AbortController().signal;
  const owner = await gate.acquire(signal, () => "initial");
  let active = true;
  const stale = gate.acquire(signal, () => {
    if (!active) throw new Error("Control was lost");
    return "old-view";
  });
  const rejected = expect(stale).rejects.toThrow("Control was lost");
  const fresh = gate.acquire(signal, () => "fresh-view");
  active = false;
  owner.release();
  await rejected;
  const next = await fresh;
  expect(gate.owns(next)).toBe(true);
  next.release();
});

it("refuses work whose deadline already expired", async () => {
  const gate = new WorkGate();
  const controller = new AbortController();
  controller.abort();
  await expect(
    gate.acquire(controller.signal, () => "expired"),
  ).rejects.toThrow();
  const next = await gate.acquire(
    new AbortController().signal,
    () => "current",
  );
  expect(gate.owns(next)).toBe(true);
  next.release();
});
