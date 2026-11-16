import { defineConfig } from "@playwright/test";
import { resolve } from "node:path";
import { evidenceDirectory, readConfig } from "./config";
const config = readConfig();
const output = evidenceDirectory();
export default defineConfig({
  testDir: ".",
  testMatch: "live.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 240_000,
  expect: { timeout: 15_000 },
  outputDir: resolve(output, "artifacts"),
  reporter: [
    ["line"],
    ["json", { outputFile: resolve(output, "results.json") }],
  ],
  use: {
    browserName: "chromium",
    ignoreHTTPSErrors: config.ignoreHTTPSErrors,
    launchOptions: {
      args: ["--host-resolver-rules=MAP *.localhost 127.0.0.1"],
    },
    trace: "off",
    screenshot: "off",
    video: "off",
  },
});
