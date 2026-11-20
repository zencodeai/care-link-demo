import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createInterface, type Interface } from "node:readline";
import { resolve } from "node:path";
import { row, type Row } from "./config";

export interface BarrierRequest {
  action: "arm" | "wait" | "release" | "finished";
  phase: "before_policy" | "before_final_output";
  operation: "plan_read" | "consent_grant";
  actor: string;
  nonce: string;
}
const target = "care-link-imp04-002";
/** One host control process and one receipt-bound docker exec per case group.
 * Timing control never changes policy, authorization, time or serving inputs.
 */
export class BarrierBridge {
  private readonly child: ChildProcessWithoutNullStreams;
  private readonly lines: Interface;
  private readonly buffered: Row[] = [];
  private waiter: {
    resolve: (value: Row) => void;
    reject: (error: Error) => void;
  } | null = null;
  private failure: Error | null = null;
  private closed = false;
  private busy = false;

  private constructor() {
    this.child = spawn(
      resolve(".venv/bin/python"),
      ["-m", "tools.imp04_deployment.barrier_bridge"],
      { stdio: ["pipe", "pipe", "pipe"] },
    );
    this.child.stderr.resume(); // Raw control diagnostics remain unprinted.
    this.lines = createInterface({ input: this.child.stdout });
    this.lines.on("line", (line) => {
      try {
        if (line.length > 65536) throw new Error("oversize");
        const value = row(JSON.parse(line) as unknown);
        if (this.waiter) {
          const waiting = this.waiter;
          this.waiter = null;
          waiting.resolve(value);
        } else this.buffered.push(value);
      } catch {
        this.fail(
          "Invalid structured barrier bridge response; contents suppressed",
        );
      }
    });
    this.child.on("error", () =>
      this.fail("New-target barrier bridge process unavailable"),
    );
    this.child.on("exit", () => {
      if (!this.closed)
        this.fail("New-target barrier bridge exited unexpectedly");
    });
  }
  private fail(message: string): void {
    this.failure = new Error(message);
    if (this.waiter) {
      const waiting = this.waiter;
      this.waiter = null;
      waiting.reject(this.failure);
    }
  }
  private async next(): Promise<Row> {
    if (this.failure) throw this.failure;
    const available = this.buffered.shift();
    if (available) return available;
    if (this.waiter)
      throw new Error("Barrier protocol requires one serial control request");
    return new Promise<Row>((resolve, reject) => {
      const timeout = setTimeout(
        () =>
          this.fail("New-target barrier control response deadline exceeded"),
        15000,
      );
      this.waiter = {
        resolve: (value) => {
          clearTimeout(timeout);
          resolve(value);
        },
        reject: (error) => {
          clearTimeout(timeout);
          reject(error);
        },
      };
    });
  }
  static async open(): Promise<BarrierBridge> {
    const bridge = new BarrierBridge();
    try {
      const welcome = await bridge.next();
      if (welcome.ready !== true || welcome.target !== target)
        throw new Error(
          "Exact new-target receipt-bound bridge readiness required",
        );
      return bridge;
    } catch (error) {
      await bridge.close();
      throw error;
    }
  }
  async request(value: BarrierRequest): Promise<Row> {
    if (this.closed || this.busy)
      throw new Error("Serial live barrier bridge lease required");
    for (const id of [value.actor, value.nonce])
      if (
        !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
          id,
        )
      )
        throw new Error("Canonical barrier actor/nonce binding required");
    this.busy = true;
    try {
      const reply = this.next();
      this.child.stdin.write(JSON.stringify(value) + "\n", (error) => {
        if (error) this.fail("Barrier bridge control write failed");
      });
      const result = await reply;
      if (result.error === true) {
        const categories = [
          "FileExistsError",
          "FileNotFoundError",
          "TimeoutError",
          "JSONDecodeError",
          "ValueError",
          "TypeError",
          "PermissionError",
          "RuntimeError",
          "OSError",
        ];
        const category =
          typeof result.category === "string" &&
          categories.includes(result.category)
            ? result.category
            : "unspecified";
        throw new Error(
          `Receipt-bound barrier operation failed; action=${value.action}; phase=${value.phase}; operation=${value.operation}; category=${category}`,
        );
      }
      if (
        (value.action === "wait" || value.action === "finished") &&
        (result.target !== target ||
          result.nonce !== value.nonce ||
          result.actor_id !== value.actor)
      )
        throw new Error("Barrier receipt target/nonce/actor mismatch");
      if (value.action === "arm" && result.armed !== true)
        throw new Error("Barrier arm not confirmed");
      if (value.action === "release" && result.released !== true)
        throw new Error("Barrier release not confirmed");
      return result;
    } finally {
      this.busy = false;
    }
  }
  async close(): Promise<void> {
    if (this.closed) return;
    this.closed = true;
    this.child.stdin.end();
    if (this.child.exitCode === null && this.child.signalCode === null) {
      await new Promise<void>((resolve) => {
        const timeout = setTimeout(() => {
          this.child.kill("SIGTERM");
          resolve();
        }, 2000);
        this.child.once("exit", () => {
          clearTimeout(timeout);
          resolve();
        });
      });
    }
    this.lines.close();
  }
}
