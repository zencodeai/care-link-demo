import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createInterface, type Interface } from "node:readline";
import { resolve } from "node:path";
import { row, type Row } from "./config";

/** A single fixed-case restriction command; no Node actor, proof or target input. */
export class AuthorityBridge {
  private readonly child: ChildProcessWithoutNullStreams;
  private readonly lines: Interface;
  private readonly reader: AsyncIterator<string>;
  private used = false;
  private closed = false;
  private unavailable = false;
  private constructor(private readonly account: string) {
    this.child = spawn(
      resolve(".venv/bin/python"),
      ["-m", "tools.imp04_deployment.authority_case", "channel"],
      { stdio: ["pipe", "pipe", "pipe"] },
    );
    this.child.stderr.resume();
    this.lines = createInterface({ input: this.child.stdout });
    this.reader = this.lines[Symbol.asyncIterator]();
    this.child.on("error", () => {
      this.unavailable = true;
      this.lines.close();
    });
    this.child.stdin.on("error", () => {
      this.unavailable = true;
    });
  }
  private async next(): Promise<Row> {
    if (this.unavailable)
      throw new Error("Fixed authority channel unavailable");
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const line = await Promise.race([
        this.reader.next(),
        new Promise<never>((_, reject) => {
          timer = setTimeout(
            () =>
              reject(new Error("Fixed authority channel deadline exceeded")),
            15000,
          );
        }),
      ]);
      if (line.done || line.value.length > 65536)
        throw new Error("Fixed authority channel closed or invalid");
      const value = row(JSON.parse(line.value) as unknown);
      if (
        value.target !== "care-link-imp04-002" ||
        value.account_id !== this.account
      )
        throw new Error("Fixed authority channel identity differs");
      return value;
    } catch {
      throw new Error(
        "Fixed authority channel unavailable; private details suppressed",
      );
    } finally {
      if (timer !== undefined) clearTimeout(timer);
    }
  }
  static async open(account: string): Promise<AuthorityBridge> {
    const channel = new AuthorityBridge(account);
    try {
      const ready = await channel.next();
      if (ready.ready !== true)
        throw new Error("Fixed authority channel not ready");
      return channel;
    } catch (error) {
      await channel.close();
      throw error;
    }
  }
  async restrict(): Promise<Row> {
    if (this.used) throw new Error("Fixed authority channel is one-use");
    this.used = true;
    this.child.stdin.write(JSON.stringify({ action: "restrict" }) + "\n");
    const response = await this.next();
    const publicFields = [
      "target",
      "phase",
      "account_id",
      "provider_subject",
      "subject_id",
      "delegation_id",
      "operation_id",
      "nonce",
      "state",
      "resource_id",
      "revision",
      "audit_ref",
      "principal_revoked",
      "revoked",
      "authority_loss",
    ];
    return Object.fromEntries(
      publicFields
        .filter((key) => key in response)
        .map((key) => [key, response[key]]),
    );
  }
  async close(): Promise<void> {
    if (this.closed) return;
    this.closed = true;
    this.child.stdin.end();
    if (this.child.exitCode === null && this.child.signalCode === null)
      await new Promise<void>((resolve) => {
        const timer = setTimeout(() => {
          this.child.kill("SIGTERM");
          resolve();
        }, 2000);
        this.child.once("exit", () => {
          clearTimeout(timer);
          resolve();
        });
      });
    this.lines.close();
  }
}
