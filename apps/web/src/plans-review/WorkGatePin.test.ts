import { expect, it } from "vitest";
import { WorkGate, withinSignal } from "./WorkGate";
it("an aborted caller cannot unlock a cookie rotation that has not settled", async () => {
  const gate = new WorkGate(),
    signal = new AbortController();
  const owner = await gate.acquire(signal.signal, () => "current-view");
  let settle!: () => void;
  const rotation = new Promise<void>((resolve) => {
    settle = resolve;
  });
  gate.hold(owner, rotation);
  const joined = withinSignal(rotation, signal.signal);
  const rejected = expect(joined).rejects.toThrow("unavailable");
  signal.abort();
  await rejected;
  owner.release();
  let entered = false;
  const next = gate
    .acquire(new AbortController().signal, () => "next-view")
    .then((lease) => {
      entered = true;
      return lease;
    });
  await Promise.resolve();
  expect(entered).toBe(false);
  expect(gate.owns(owner)).toBe(true);
  settle();
  const lease = await next;
  expect(gate.owns(owner)).toBe(false);
  expect(gate.owns(lease)).toBe(true);
  lease.release();
});
