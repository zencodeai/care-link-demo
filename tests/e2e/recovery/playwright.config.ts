import { defineConfig } from "@playwright/test";
import { resolve } from "node:path";
const output =
  process.env.IMP09_BROWSER_OUTPUT ?? "/private/tmp/care-link-imp09-browser";
export default defineConfig({
  testDir: ".",
  testMatch: "recovery.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60000,
  expect: { timeout: 10000 },
  outputDir: resolve(output, "artifacts"),
  reporter: [
    ["line"],
    ["json", { outputFile: resolve(output, "playwright-results.json") }],
  ],
  webServer: {
    command:
      "pnpm --filter @care-link/web exec vite --host 127.0.0.1 --port 4199 --strictPort --force",
    url: "http://127.0.0.1:4199",
    reuseExistingServer: false,
    timeout: 30000,
  },
  use: {
    baseURL: "http://127.0.0.1:4199",
    browserName: "chromium",
    connectOptions: {
      wsEndpoint:
        process.env.PLAYWRIGHT_WS_ENDPOINT ?? "ws://127.0.0.1:31909/imp09-001",
      exposeNetwork: "<loopback>",
      headers: {
        "x-playwright-launch-options": JSON.stringify({
          executablePath: "/opt/chrome-for-testing/chrome",
          headless: true,
        }),
      },
    },
    actionTimeout: 15000,
    navigationTimeout: 30000,
    trace: "off",
    screenshot: "off",
    video: "off",
  },
});
