import { spawn } from "node:child_process";
import { resolve } from "node:path";
import {
  origin,
  row,
  slots,
  text,
  uuid,
  type ReviewConfig,
  type Row,
  type Slot,
} from "./config";
export interface ActorBinding {
  slot: Slot;
  account: string;
  role: string;
  username: string;
  origin: string;
  url: string;
}
export interface Run {
  id: string;
  actors: Record<Slot, ActorBinding>;
}
export class Toolkit {
  constructor(readonly config: ReviewConfig) {}
  private async execute(args: string[]): Promise<string> {
    const settings = [
      "-m",
      "tools.demo",
      "--state-root",
      this.config.stateRoot,
    ];
    if (this.config.vaultKeyFile)
      settings.push("--vault-key-file", this.config.vaultKeyFile);
    return new Promise((resolveResult, reject) => {
      const child = spawn(resolve(".venv/bin/python"), [...settings, ...args], {
        stdio: ["ignore", "pipe", "pipe"],
      });
      let stdout = "",
        stderr = "",
        settled = false;
      const finish = (error?: string) => {
        if (settled) return;
        settled = true;
        clearTimeout(timeout);
        if (error) reject(new Error(error));
        else
          resolveResult(stdout.endsWith("\n") ? stdout.slice(0, -1) : stdout);
      };
      const timeout = setTimeout(() => {
        child.kill("SIGTERM");
        finish("Toolkit command timed out; private output suppressed");
      }, 65_000);
      child.stdout.setEncoding("utf8");
      child.stderr.setEncoding("utf8");
      child.stdout.on("data", (part: string) => {
        stdout += part;
        if (stdout.length > 1048576) {
          child.kill("SIGTERM");
          finish("Toolkit output bound exceeded");
        }
      });
      child.stderr.on("data", (part: string) => {
        stderr += part;
        if (stderr.length > 8192) {
          child.kill("SIGTERM");
          finish("Toolkit diagnostic bound exceeded");
        }
      });
      child.on("error", () =>
        finish("Toolkit unavailable; private output suppressed"),
      );
      child.on("close", (code) => {
        if (code === 0) finish();
        else {
          let canonical = "unavailable";
          try {
            const value = row(JSON.parse(stderr) as unknown);
            if (
              typeof value.error === "string" &&
              /^[a-z0-9_]+$/.test(value.error)
            )
              canonical = value.error;
          } catch {
            /* no raw diagnostics */
          }
          finish("Toolkit command failed: " + canonical);
        }
      });
    });
  }
  async json(args: string[]): Promise<Row> {
    return row(JSON.parse(await this.execute(args)) as unknown);
  }
  async create(): Promise<Run> {
    const result = await this.json([
      "run",
      "create",
      "--environment",
      this.config.environmentId,
      "--scenario",
      "manual-service",
    ]);
    const id = uuid(text(result, "run_id"));
    if (
      result.environment_id !== this.config.environmentId ||
      result.state !== "active"
    )
      throw new Error("Actual toolkit run creation unconfirmed");
    const listed = await this.json(["actors", "list", "--run", id]);
    if (listed.run_id !== id || listed.state !== "active")
      throw new Error("Actor listing belongs to another run");
    const values = row(listed.actors);
    const actors = {} as Record<Slot, ActorBinding>;
    for (const slot of slots) {
      const value = row(values[slot]);
      const opened = await this.json([
        "run",
        "open",
        "--run",
        id,
        "--actor",
        slot,
        "--print-only",
      ]);
      const actorOrigin = origin(text(value, "origin"));
      const url = text(opened, "url");
      if (url !== actorOrigin + "/" || opened.opened !== false)
        throw new Error("Toolkit returned an unexpected ordinary-tab URL");
      actors[slot] = {
        slot,
        account: uuid(text(value, "account_id")),
        role: text(value, "role"),
        username: text(value, "username"),
        origin: actorOrigin,
        url,
      };
    }
    if (
      new Set(slots.map((slot) => actors[slot].account)).size !== 4 ||
      new Set(slots.map((slot) => actors[slot].origin)).size !== 4
    )
      throw new Error("Four distinct actors/origins required");
    return { id, actors };
  }
  async password(slot: Slot): Promise<string> {
    const result = await this.execute([
      "credentials",
      "reveal",
      "--environment",
      this.config.environmentId,
      "--actor",
      slot,
      "--reveal-password",
    ]);
    if (!result || result.length > 1024)
      throw new Error("Issued password unavailable");
    return result;
  }
  async otp(slot: Slot): Promise<string> {
    const value = await this.json([
      "credentials",
      "otp",
      "--environment",
      this.config.environmentId,
      "--actor",
      slot,
      "--fresh",
    ]);
    const code = text(value, "code");
    if (
      !/^[0-9]{6}$/.test(code) ||
      value.slot !== slot ||
      value.fresh_window !== true
    )
      throw new Error("Fresh issued OTP unavailable");
    return code;
  }
  async close(run: Run) {
    const value = await this.json(["run", "close", "--run", run.id]);
    if (
      value.run_id !== run.id ||
      value.environment_id !== this.config.environmentId ||
      value.state !== "closed"
    )
      throw new Error("Toolkit run closure not confirmed");
  }
}
