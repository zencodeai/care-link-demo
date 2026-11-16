import { defineConfig } from "@playwright/test";
import { resolve } from "node:path";
import { evidenceDirectory } from "../imp03/config";
import { readExtendedConfig } from "./config";
readExtendedConfig();
const output = evidenceDirectory();
const resolver = process.env.CARE_LINK_IMP03_BROWSER_RESOLVER;
export default defineConfig({
  testDir: ".",
  testMatch:
    process.env.CARE_LINK_IMP03_EXTENDED_CASE === "handoff-ui"
      ? "handoff-ui.spec.ts"
      : process.env.CARE_LINK_IMP03_EXTENDED_CASE === "stability"
        ? "stability.spec.ts"
        : process.env.CARE_LINK_IMP03_EXTENDED_CASE === "operations"
          ? "operations.spec.ts"
          : process.env.CARE_LINK_IMP03_EXTENDED_CASE === "commit-ack"
            ? "commit.spec.ts"
            : "live.spec.ts",
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
    ignoreHTTPSErrors: false,
    actionTimeout: 15_000,
    navigationTimeout: 20_000,
    launchOptions: {
      args: [
        "--host-resolver-rules=" + (resolver ?? "MAP *.localhost 127.0.0.1"),
      ],
    },
    trace: "off",
    screenshot: "off",
    video: "off",
  },
});
