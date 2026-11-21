import { defineConfig } from "@playwright/test";
import { resolve } from "node:path";
const output =
  process.env.IMP08_BROWSER_OUTPUT ?? "/private/tmp/care-link-imp08-browser";
export default defineConfig({
  testDir: ".",
  testMatch: "governance.spec.ts",
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
      "pnpm --filter @care-link/web exec vite --host 127.0.0.1 --port 4188 --strictPort --force",
    url: "http://127.0.0.1:4188",
    reuseExistingServer: false,
    timeout: 30000,
  },
  use: {
    baseURL: "http://127.0.0.1:4188",
    browserName: "chromium",
    connectOptions: {
      wsEndpoint:
        process.env.PLAYWRIGHT_WS_ENDPOINT ?? "ws://127.0.0.1:30908/imp08-001",
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
