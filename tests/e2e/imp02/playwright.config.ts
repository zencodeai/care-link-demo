import { defineConfig } from "@playwright/test";
import { resolve } from "node:path";
import { lstatSync, mkdirSync } from "node:fs";
import { readLabConfig } from "./lab";
const lab = readLabConfig();
const phase = process.env.CARE_LINK_IMP02_E2E_PHASE ?? "normal";
if (!["normal", "outage", "cooling"].includes(phase))
  throw new Error("Unknown IMP-02 browser qualification phase");
const browserArgs = ["--host-resolver-rules=MAP *.localhost 127.0.0.1"];
const output =
  process.env.CARE_LINK_IMP02_E2E_OUTPUT ??
  "/private/tmp/care-link-imp02-browser-results";
mkdirSync(output, { recursive: true, mode: 0o700 });
const outputMetadata = lstatSync(output);
if (!outputMetadata.isDirectory() || (outputMetadata.mode & 0o077) !== 0)
  throw new Error("IMP-02 browser evidence directory must be owner-only");
export default defineConfig({
  testDir: ".",
  testMatch:
    phase === "outage"
      ? "outage.spec.ts"
      : phase === "cooling"
        ? "cooling.spec.ts"
        : ["journeys.spec.ts", "unknown.spec.ts", "accessibility.spec.ts"],
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  outputDir: resolve(output, "artifacts"),
  reporter: [
    ["line"],
    ["json", { outputFile: resolve(output, "results.json") }],
  ],
  use: {
    browserName: "chromium",
    ...(process.env.CARE_LINK_IMP02_BROWSER_PATH
      ? {
          launchOptions: {
            executablePath: process.env.CARE_LINK_IMP02_BROWSER_PATH,
            args: browserArgs,
          },
        }
      : {
          channel:
            process.env.CARE_LINK_IMP02_BROWSER_CHANNEL === "chrome"
              ? "chrome"
              : "chromium",
          launchOptions: { args: browserArgs },
        }),
    ignoreHTTPSErrors: lab.ignoreHTTPSErrors,
    trace: "off",
    screenshot: "off",
    video: "off",
    viewport: { width: 1280, height: 960 },
  },
});
