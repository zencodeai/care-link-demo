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
  timeout: 1_200_000,
  expect: { timeout: 20_000 },
  outputDir: resolve(output, "artifacts"),
  reporter: [
    ["line"],
    ["json", { outputFile: resolve(output, "results.json") }],
  ],
  use: {
    browserName: "chromium",
    ignoreHTTPSErrors: false,
    connectOptions: {
      wsEndpoint: config.wsEndpoint,
      exposeNetwork: "<loopback>",
      headers: {
        "x-playwright-launch-options": JSON.stringify({
          executablePath: "/opt/chrome-for-testing/chrome",
          headless: true,
        }),
      },
    },
    actionTimeout: 20_000,
    navigationTimeout: 30_000,
    trace: "off",
    screenshot: "off",
    video: "off",
  },
});
